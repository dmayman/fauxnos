#!/usr/bin/env python3
"""
Source Manager

Handles audio source switching with smart volume control routing
"""

import logging
import subprocess
import threading
import time
import requests
from typing import Callable, Dict, Optional
from .config_manager import ConfigManager, SourceConfig
from .go_librespot import GoLibrespotController
from .pulse_controller import PulseAudioController
from .snapcast_controller import SnapcastController
from .state_manager import StateManager


class SourceManager:
    """Manages audio source switching and volume control"""

    # Crossfade granularity: one pair of PA sink writes per step.
    FADE_STEP_MS = 100

    def __init__(
        self,
        config_manager: ConfigManager,
        go_librespot: Optional[GoLibrespotController] = None,
        on_external_volume_change: Optional[Callable[[str, int], None]] = None,
    ):
        """
        Initialize source manager

        Args:
            config_manager: ConfigManager instance
            go_librespot: Optional controller for sources whose
                `volume_controller == 'go_librespot'`. If None, those
                sources' volume changes are still tracked in fauxnos
                state but not pushed to the daemon (won't reach Spotify
                Connect). Required if any source uses that controller.
            on_external_volume_change: (source_id, volume) callback
                fired when something OUTSIDE fauxnos (e.g. the Spotify
                mobile app) changes the volume for a go_librespot-
                controlled source. The caller (fauxnos_client.py) is
                responsible for publishing the update over MQTT so the
                web UI tracks. Source-manager state is already saved
                before the callback fires.
        """
        self.logger = logging.getLogger(__name__)
        self.config_manager = config_manager

        # Initialize controllers
        self.pulse = PulseAudioController()
        self.snapcast = SnapcastController(host=config_manager.server_host)
        self.go_librespot = go_librespot
        self.state_manager = StateManager(config_manager.state_file)
        self._on_external_volume_change = on_external_volume_change
        # Keep-alive connection to the server API, so forwarding a volume
        # drag doesn't repeat the name lookup of the server for every step.
        self._server_http = requests.Session()

        # Track current source and volumes
        self.current_source: Optional[str] = None
        self.source_volumes: Dict[str, int] = {}

        # External volume controller state (per-device flag). When True,
        # this client's local audio chain is pinned at unity gain and
        # the actual attenuation happens OUTSIDE fauxnos (e.g. a
        # Particle Photon receiving setVolume commands). The mqtt_client
        # keeps this in sync by subscribing to the retained
        # `config/clients/<id>/external_volume_controller` topic the
        # server publishes. When the flag is True:
        #   - _set_source_volume forces snapcast=100 (not attenuating)
        #     and skips the go-librespot phone-slider push
        #   - on_external_volume_change (phone slider WS event) skips
        #     the snapcast.set_volume(N) call AND POSTs the new value
        #     to the server's /external_volume endpoint so it routes
        #     out via the configured transport
        self.external_volume_enabled: bool = False

        # Companion to the flag above: how far to pad the DAC's own
        # output while external mode is on. See _apply_output_pad.
        # None = "we haven't applied anything yet", so the first retained
        # EVC message always writes the mixer even if the pad is 0.
        self.output_pad_db: Optional[int] = None

        # In-flight fade, stepped by a background thread so the command
        # that started it returns at once. `_fade` is one of:
        #   {"from": SourceConfig, "to": SourceConfig}  a crossfade, from
        #       switch_source(fade_ms=...)
        #   {"source": SourceConfig, "on_done": callable | None}  one
        #       source's own sink ramping, from fade_in_source /
        #       fade_out_source (library/play and library/stop with fade_ms)
        # Bumping `_fade_gen` (under `_fade_lock`) retires the running
        # thread; every step re-checks it under the same lock, so no stale
        # step can land after a newer command has taken over.
        self._fade_lock = threading.Lock()
        self._fade_gen = 0
        self._fade: Optional[Dict[str, SourceConfig]] = None

        # Initialize volumes from config
        for source_id, source in config_manager.sources.items():
            self.source_volumes[source_id] = source.starting_volume

        # Try to load previous state
        self._load_state()

    def apply_external_mirror(self, volume: int):
        """Apply an authoritative external-volume value to local mirrors.

        Called when the server publishes `set/clients/<id>/external_volume_mirror`,
        which happens whenever the actual volume authority (e.g. a Particle
        Photon's knob, or the round-trip echo after a UI slider move) reports
        a new value. In external mode the audio chain is already pinned at
        unity, so the only thing to "apply" locally is the Spotify phone-
        slider mirror: push the value to go-librespot's /player/volume so the
        Spotify Connect UI tracks the authoritative number.

        go-librespot fires a WS event on every /player/volume change. Its
        echo-suppression (ECHO_SUPPRESS_S in go_librespot.py) keeps that
        from feeding back into on_external_volume_change.

        Also: if the value matches what we last received-or-pushed to
        go-librespot, skip the round trip entirely. The mirror topic
        fires for EVERY external update — including the round-trip echo
        from a UI-slider-move (UI → /external_volume → Photon →
        vinyltable/volume → server → mirror → here). For those echoes
        we already pushed the same value through; re-pushing would just
        burn a WS event with no actual phone-slider movement to mirror.
        This dedup is what breaks the feedback loop when echo-suppression
        timing falls short (e.g. go-librespot WS arrives ~350ms after
        our POST, past the 300ms window).

        No-op if external is disabled (defensive).
        """
        if not self.external_volume_enabled:
            return
        if self.go_librespot is None:
            return
        volume = max(0, min(100, int(volume)))
        if getattr(self, "_last_mirror_pushed", None) == volume:
            self.logger.debug(f"EVC mirror: {volume}% already pushed, skipping")
            return
        self._last_mirror_pushed = volume
        self.logger.info(f"EVC mirror: pushing {volume}% to go-librespot")
        try:
            self.go_librespot.set_volume(volume)
        except Exception as e:
            self.logger.warning(f"go-librespot mirror push failed for v={volume}: {e}")

    def _forward_to_external_volume(self, volume: int):
        """POST a volume value to the server's external-volume dispatch endpoint.

        Used when the phone (Spotify Connect slider) moves the volume and
        external_volume_controller is enabled — instead of attenuating
        snapcast locally, we hand the value to the server which routes it
        out via the configured transport (HTTP or MQTT) to the actual
        volume authority. Fire-and-forget with a short timeout: we don't
        block the WS-event handler thread on a slow Particle round trip,
        and we don't surface failures audibly to the user (the snapcast
        pin already happened defensively before this call).
        """
        try:
            client_id = self.config_manager.device_config.name
            host = self.config_manager.server_host
            url = f"http://{host}:8080/api/clients/{client_id}/external_volume"
            self._server_http.post(url, json={"value": int(volume)}, timeout=2.0)
        except Exception as e:
            # Log but don't raise — phone WS handler must not crash.
            self.logger.warning(
                f"External volume forward failed (slider may not reach the external controller): {e}"
            )

    def _apply_output_pad(self, pad_db: int):
        """Attenuate the DAC's own output by `pad_db` dB (<= 0).

        In external mode the whole digital chain is pinned at 0 dBFS, so
        the DAC runs flat out — ~2.1 Vrms on a PCM512x — permanently. That
        overloads the input stage of whatever analog box is actually doing
        the attenuating (Kitchen: the VinylTable's TDA7468), which reads as
        distortion that only cleans up when you cut the digital level. The
        pad moves that headroom into the DAC's own 32-bit volume, where it
        costs no bits, instead of into PulseAudio's s16 chain, where -24 dB
        costs four.

        `Analogue` is pinned at 0 dB so `pad_db` alone fully describes the
        hardware state — no two-knob arithmetic to reason about later. The
        `--` is required: amixer's getopt would read `-24dB` as a flag.

        Cards with no mixer at all (PCM5102A / the `hifiberry-dac` overlay)
        have neither control; amixer exits non-zero and we log and move on.
        """
        for control, value in (("Analogue", "0dB"), ("Digital", f"{pad_db}dB")):
            r = subprocess.run(
                ["amixer", "-c", "0", "--", "set", control, value],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                self.logger.warning(
                    f"Output pad: no '{control}' mixer control on this card "
                    f"— skipping (amixer: {r.stderr.strip()})"
                )
                return
        # Persist so the pad survives a reboot without waiting for the
        # retained MQTT message to land (alsa-restore runs long before us).
        subprocess.run(["sudo", "-n", "alsactl", "store"],
                       capture_output=True, text=True, timeout=10)
        self.logger.info(f"Output pad applied: DAC Digital → {pad_db} dB")

    def set_external_volume_state(self, enabled: bool, output_pad_db: int = 0):
        """Update the external-volume-controller flag and DAC output pad.

        Called by mqtt_client when a `config/clients/<id>/external_volume_controller`
        retained message arrives. Idempotent — only acts on transitions
        so we don't spam at every reconnect (the retained payload fires
        on every subscribe).

        On the OFF→ON transition we proactively pin snapcast to 100 for
        every source's snapcast-controlled sink. Otherwise: if the user
        toggled external ON while audio was attenuated locally (say 30%),
        the local stage would stay at 30% until somebody called set_volume.
        Without this, the actual chain would be 30% (local) × N% (external)
        until the next slider move. Idempotent — set_volume(100) is a no-op
        if snapcast was already at 100.

        The pad is tracked separately from `enabled` because the user can
        retune it without toggling the flag — an `enabled`-only guard would
        swallow every pad edit after the first. It only applies while
        external is on; turning external off restores the DAC to 0 dB,
        since the chain goes back to attenuating locally and the pad would
        otherwise stack on top of it.
        """
        target_pad = min(0, int(output_pad_db)) if enabled else 0
        if target_pad != self.output_pad_db:
            self.output_pad_db = target_pad
            self._apply_output_pad(target_pad)

        if bool(enabled) == self.external_volume_enabled:
            return
        self.external_volume_enabled = bool(enabled)
        self.logger.info(
            f"External volume controller {'ENABLED' if enabled else 'disabled'} "
            f"— local audio chain will be {'pinned at unity' if enabled else 'used normally'}"
        )
        if self.external_volume_enabled:
            try:
                client_id = self.config_manager.device_config.name
                self.snapcast.set_volume(100, client_id)
                # Also pin every PA sink we manage. Mostly defensive — the
                # active source's sink already gets pinned on every
                # _set_source_volume call, but if no slider move happens
                # after the toggle we'd leave non-active sinks wherever.
                for source_id, source in self.config_manager.sources.items():
                    if source.type == 'internal' and source.sink:
                        try:
                            self.pulse.set_sink_volume(source.sink, 100)
                        except Exception:
                            pass
            except Exception as e:
                self.logger.warning(f"EVC enable: failed to pin local chain — {e}")

    def _load_state(self):
        """Load previous state from disk"""
        state = self.state_manager.load_state()

        # Restore source volumes
        saved_volumes = state.get('source_volumes', {})
        for source_id, volume in saved_volumes.items():
            if source_id in self.source_volumes:
                self.source_volumes[source_id] = volume

        # Note: Don't restore current_source yet - let initialization do that
        self.logger.info(f"Restored {len(saved_volumes)} source volumes from state")

    def _save_state(self):
        """Save current state to disk"""
        self.state_manager.save_state(self.current_source, self.source_volumes)

    def switch_source(self, source_id: str, fade_ms: int = 0) -> bool:
        """
        Switch to a different audio source

        Args:
            source_id: ID of source to switch to
            fade_ms: If > 0, crossfade from the current source over this
                many milliseconds instead of cutting over. The switch
                returns at once (current_source is already the new one);
                a background thread ramps the two PA sinks and runs the
                outgoing source's leave hooks when the ramp ends. Only
                applies between two internal sources on different sinks
                — anything else falls back to an instant switch. UI taps
                send no fade; routines (e.g. bedtime → sleep) do.

        Returns:
            True if successful, False otherwise
        """
        # Validate source exists
        source = self.config_manager.get_source(source_id)
        if not source:
            self.logger.error(f"Source not found: {source_id}")
            return False

        # A new switch always lands any fade still running first.
        self._settle_fade(next_source_id=source_id)

        # Check if already on this source
        if self.current_source == source_id:
            self.logger.debug(f"Already on source {source_id}, skipping switch")
            return True

        prev_source = (
            self.config_manager.get_source(self.current_source)
            if self.current_source is not None else None
        )

        if fade_ms > 0 and self._can_fade(prev_source, source):
            return self._start_fade(prev_source, source, fade_ms)

        if prev_source is not None:
            self._run_leave_hooks(prev_source)

        self.logger.info(f"Switching to source: {source.label} ({source_id})")

        # Handle external sources differently
        if source.type == 'external':
            return self._switch_to_external_source(source)
        else:
            return self._switch_to_internal_source(source)

    def ensure_source_routed(self, source_id: str) -> bool:
        """
        Make sure source_id is the live, correctly-routed active source —
        re-asserting the actual PA/snapcast routing even when we already
        believe we're on it.

        Why this exists: switch_source() early-returns True the moment
        self.current_source already equals the target, on the assumption
        that cached state matches reality. It often doesn't — current_source
        is restored from disk on boot and can also drift when a sink gets
        muted out from under us (e.g. another source's switch mutes every
        sibling sink). The symptom is silent audio while the UI correctly
        shows the source as already selected; re-selecting it by hand fixes
        it precisely because that re-runs the routing this method now runs.

        Behaviour:
          * Not currently on source_id → ordinary switch_source (which runs
            the outgoing source's pause / on_leave hooks).
          * Already on source_id → re-run ONLY the routing assertion
            (mute siblings + re-apply this source's volume, which re-pins
            the sink and re-sets snapcast attenuation). We deliberately do
            NOT run the leave/pause path here: pausing the very source we
            want audible would be wrong.

        Returns True on success.
        """
        source = self.config_manager.get_source(source_id)
        if not source:
            self.logger.error(f"Source not found: {source_id}")
            return False

        self._settle_fade(next_source_id=source_id)

        if self.current_source != source_id:
            # Coming from a different source — let switch_source own the
            # leave hooks and the pause of the outgoing go_librespot stream.
            return self.switch_source(source_id)

        # Already the active source on paper — re-assert the live route.
        self.logger.info(
            f"Re-asserting route for current source: {source.label} ({source_id})"
        )
        if source.type == 'external':
            return self._switch_to_external_source(source)
        else:
            return self._switch_to_internal_source(source)

    def _switch_to_internal_source(self, source: SourceConfig) -> bool:
        """
        Switch to internal source (PulseAudio-based)

        Args:
            source: Source configuration

        Returns:
            True if successful
        """
        # Steps 1-2: mute every other sink, apply this source's volume.
        self._assert_route(source)

        # Step 3: external switch + on_enter_command
        self._run_enter_hooks(source)

        # Update current source and save state
        self.current_source = source.id
        self._save_state()

        self.logger.info(f"Switched to {source.label}")
        return True

    def _assert_route(self, source: SourceConfig):
        """Make `source` the only audible internal sink, at its stored volume."""
        # Step 1: Mute all other internal sources
        self.logger.debug("Muting other sources...")
        for other_id, other_source in self.config_manager.get_internal_sources().items():
            if other_id != source.id:
                self.pulse.mute_sink(other_source.sink)

        # Step 2: Apply the new source's stored volume via its
        # configured controller (self/snapcast/go_librespot). Direct
        # set, no fade — the old always-on fade ramp was a step-loop
        # that blocked this thread for ~1s on every switch, making the
        # UI lag behind every action. Fades are now opt-in per switch
        # (switch_source fade_ms) and run on a background thread.
        target_volume = self.source_volumes[source.id]
        self._set_source_volume(source, target_volume)

    def _run_enter_hooks(self, source: SourceConfig):
        """Side effects of a source becoming active: external switch, on_enter_command."""
        if source.external_switch and source.external_switch.enabled:
            self._trigger_external_switch(source.external_switch.url, source.external_switch.payload, source.external_switch.content_type)
        if source.on_enter_command:
            self._spawn_hook(source.id, "on_enter_command", source.on_enter_command)

    def _run_leave_hooks(self, source: SourceConfig):
        """Side effects of a source going inactive."""
        # Leaving a go_librespot-controlled source? Pause it so the
        # daemon doesn't keep streaming Spotify audio into the now-
        # unselected snapcast stream (which would also keep the
        # Spotify "Now Playing" running on the user's phone). Idempotent:
        # pause when already paused is a soft no-op inside the controller.
        if source.volume_controller == 'go_librespot' and self.go_librespot is not None:
            self.go_librespot.pause()
        # Run the outgoing source's on_leave_command, if any. For
        # airplay this restarts shairport-sync, which drops the
        # iPhone's active RTSP session — otherwise the phone keeps
        # streaming audio into a muted void, indefinitely. For noise it
        # stops the generator; for library it stops MPD. Fire-and-forget;
        # output discarded.
        if source.on_leave_command:
            self._spawn_hook(source.id, "on_leave_command", source.on_leave_command)

    # ── Crossfade ─────────────────────────────────────────────────────────

    @staticmethod
    def _can_fade(prev: Optional[SourceConfig], new: SourceConfig) -> bool:
        """A fade needs two internal sources on separate PA sinks."""
        return (
            prev is not None
            and prev.type == 'internal' and new.type == 'internal'
            and bool(prev.sink) and bool(new.sink)
            and prev.sink != new.sink
        )

    def _active_pa_level(self, source: SourceConfig) -> int:
        """The PA sink level `source` sits at while it is the active source.

        Only 'self' attenuates at the sink; every other controller pins
        its sink at 100 and attenuates upstream (snapcast, go-librespot,
        shairport). See _set_source_volume.
        """
        if source.volume_controller == 'self':
            return self.source_volumes[source.id]
        return 100

    def _start_fade(self, prev: SourceConfig, new: SourceConfig, fade_ms: int) -> bool:
        self.logger.info(f"Fading {prev.label} → {new.label} over {fade_ms} ms")

        # Bring the incoming source up silent: its upstream stages
        # (snapcast / go-librespot) get their stored level now, its PA
        # sink starts at 0, and the ramp raises it. Enter hooks run first
        # so e.g. the noise generator is already producing by the time
        # the sink is audible.
        self._run_enter_hooks(new)
        self._set_source_volume(new, self.source_volumes[new.id], pa_volume=0)

        from_level = self.pulse.get_sink_volume(prev.sink)
        if from_level is None:
            from_level = self._active_pa_level(prev)
        to_level = self._active_pa_level(new)

        self.current_source = new.id
        self._save_state()

        def step(frac: float):
            self.pulse.set_sink_volume(prev.sink, round(from_level * (1 - frac)))
            self.pulse.set_sink_volume(new.sink, round(to_level * frac))

        with self._fade_lock:
            self._launch_fade_locked({"from": prev, "to": new}, step, fade_ms,
                                     f"Fade to {new.label} complete")
        return True

    def _launch_fade_locked(self, fade: Dict, step: Callable[[float], None],
                            fade_ms: int, done_message: str):
        """Make `fade` the running fade and step it on a thread. Caller holds _fade_lock."""
        self._fade_gen += 1
        self._fade = fade
        threading.Thread(
            target=self._run_fade,
            args=(self._fade_gen, step, fade_ms, done_message),
            name="source-fade",
            daemon=True,
        ).start()

    def _run_fade(self, gen: int, step: Callable[[float], None], fade_ms: int,
                  done_message: str):
        steps = max(1, fade_ms // self.FADE_STEP_MS)
        interval = fade_ms / steps / 1000.0
        # Step on a fixed schedule, not sleep-after-write: each step costs
        # two pactl calls, and sleeping a full interval after them would
        # stretch a 3 s fade to ~3.5 s (measured on PA).
        start = time.monotonic()
        for i in range(1, steps + 1):
            time.sleep(max(0.0, start + i * interval - time.monotonic()))
            with self._fade_lock:
                if gen != self._fade_gen:
                    return  # settled by a newer switch / volume change
                step(i / steps)
        with self._fade_lock:
            if gen != self._fade_gen:
                return
            self._finish_fade_locked()
        self.logger.info(done_message)

    # ── Fading one source in or out ───────────────────────────────────────
    #
    # A crossfade needs a second sink to fade from. These ramp the active
    # source's own sink instead, for "start this from silence" and "fade
    # this to silence, then stop it". They share the crossfade's thread,
    # generation counter and landing rules: a switch, a volume change or
    # another fade mid-ramp lands it first.

    def fade_out_source(self, source_id: str, fade_ms: int,
                        on_done: Optional[Callable[[], object]] = None) -> bool:
        """Ramp the active source's sink to silence, then call on_done.

        on_done stops the producer (for the library: MPD). Afterwards the
        sink goes back to the source's stored level with nothing playing
        into it, so the next play starts at the normal volume and the
        stored volume never changes. If a fade is landed early, on_done
        runs at that moment.

        Returns False and does nothing when source_id isn't the active
        internal source; the caller then stops it outright.
        """
        source = self.config_manager.get_source(source_id)
        if fade_ms <= 0 or source is None or source.type != 'internal' or not source.sink:
            return False
        with self._fade_lock:
            if self.current_source != source_id:
                return False
            from_level = self._take_over_locked(source)
            self.logger.info(f"Fading {source.label} out over {fade_ms} ms")
            self._launch_fade_locked(
                {"source": source, "on_done": on_done},
                self._level_step(source, from_level, 0), fade_ms,
                f"Fade-out of {source.label} complete",
            )
        return True

    def fade_in_source(self, source_id: str, fade_ms: int,
                       start: Callable[[], bool]) -> bool:
        """Start the active source from silence and ramp it up.

        Mutes the source's sink, calls start() (for the library: queue and
        play on MPD), then ramps the sink up to the stored level. For a
        source that's already active, where there's nothing to crossfade
        from. If start() fails, the sink goes straight back to its level.
        """
        source = self.config_manager.get_source(source_id)
        if source is None or source.type != 'internal' or not source.sink:
            return False
        with self._fade_lock:
            if self.current_source != source_id:
                return False
            self._take_over_locked(source)
            self.pulse.set_sink_volume(source.sink, 0)
            if not start():
                self._assert_route(source)
                return False
            if fade_ms <= 0:
                self._assert_route(source)
                return True
            self.logger.info(f"Fading {source.label} in over {fade_ms} ms")
            self._launch_fade_locked(
                {"source": source, "on_done": None},
                self._level_step(source, 0, self._active_pa_level(source)), fade_ms,
                f"Fade-in of {source.label} complete",
            )
        return True

    def _level_step(self, source: SourceConfig, from_level: int, to_level: int):
        def step(frac: float):
            self.pulse.set_sink_volume(source.sink, round(from_level + (to_level - from_level) * frac))
        return step

    def _take_over_locked(self, source: SourceConfig) -> int:
        """Clear the way for a new ramp on the active `source`'s sink.

        Returns the sink's level now, which the new ramp starts from. A
        ramp already running on this sink is retired where it stands
        (no on_done, no jump), so fade-in → fade-out turns around
        smoothly. A crossfade into this source is landed, and the sink is
        put back at the level it had reached. Caller holds _fade_lock.
        """
        level = self.pulse.get_sink_volume(source.sink)
        if level is None:
            level = self._active_pa_level(source)
        if self._fade is not None:
            if self._fade.get("source") is not None and self._fade["source"].id == source.id:
                self._fade = None
                self._fade_gen += 1
            else:
                self._finish_fade_locked()
                self.pulse.set_sink_volume(source.sink, level)
        return level

    @staticmethod
    def _fade_from_id(fade: Optional[Dict]) -> Optional[str]:
        """The source a crossfade is leaving; None for no fade or a one-sink ramp."""
        return fade["from"].id if fade is not None and "from" in fade else None

    def is_fading_from(self, source_id: str) -> bool:
        """True while a crossfade away from `source_id` is still running."""
        with self._fade_lock:
            return self._fade_from_id(self._fade) == source_id

    def settle_fade(self, next_source_id: Optional[str] = None):
        """Land any running fade now. See _settle_fade."""
        self._settle_fade(next_source_id=next_source_id)

    def _settle_fade(self, next_source_id: Optional[str] = None):
        """Jump any running fade to its end state before acting on the sinks.

        Called first by switch_source, ensure_source_routed and set_volume
        so they never race the fade thread. If the caller is heading back
        to the source we were fading away from, its leave hooks are
        skipped — pausing Spotify or stopping the noise generator you are
        returning to would be wrong.
        """
        with self._fade_lock:
            if self._fade is None:
                return
            skip_leave = next_source_id is not None and self._fade_from_id(self._fade) == next_source_id
            self._finish_fade_locked(skip_leave=skip_leave)

    def _finish_fade_locked(self, skip_leave: bool = False):
        """End state of a fade. Caller holds _fade_lock."""
        fade, self._fade = self._fade, None
        self._fade_gen += 1  # retire the fade thread, if it's still stepping
        if fade is None:
            return
        if "source" in fade:
            # A one-sink ramp. A fade-out ends silent with its producer
            # stopped; then (like a fade-in) the sink returns to the
            # source's normal route and stored level.
            source = fade["source"]
            if fade.get("on_done") is not None:
                self.pulse.mute_sink(source.sink)
                try:
                    fade["on_done"]()
                except Exception as e:
                    self.logger.error(f"Fade-out of {source.label}: stopping failed: {e}")
            self._assert_route(source)
            return
        prev, new = fade["from"], fade["to"]
        self.pulse.mute_sink(prev.sink)
        if not skip_leave:
            self._run_leave_hooks(prev)
        # Land exactly on the incoming source's normal route (re-mutes
        # every other sink, re-applies its volume through its controller
        # — including any slider change made mid-fade).
        self._assert_route(new)

    def _switch_to_external_source(self, source: SourceConfig) -> bool:
        """
        Switch to external source (no local PulseAudio control)

        Args:
            source: Source configuration

        Returns:
            True if successful
        """
        # Mute all internal sources
        self.logger.debug("Muting all internal sources...")
        for source_id, internal_source in self.config_manager.get_internal_sources().items():
            self.pulse.mute_sink(internal_source.sink)

        # Trigger external source control
        if source.control_url:
            success = self._trigger_external_switch(source.control_url, source.control_payload)
            if not success:
                self.logger.warning(f"Failed to trigger external source {source.label}")

        # Update current source and save state
        self.current_source = source.id
        self._save_state()

        self.logger.info(f"Switched to external source: {source.label}")
        return True

    def _set_source_volume(self, source: SourceConfig, volume: int,
                           pa_volume: Optional[int] = None):
        """
        Set volume for a source using appropriate controller

        Args:
            source: Source configuration
            volume: Target volume (0-100)
            pa_volume: If given, write this to the PA sink instead of the
                level the controller would normally put there. Used by
                the crossfade to set up a source's upstream stages while
                keeping its sink silent.
        """
        if source.type != 'internal':
            self.logger.warning(f"Cannot set volume for external source {source.id}")
            return

        volume_controller = source.volume_controller
        sink_name = source.sink

        def pa(level: int) -> int:
            return level if pa_volume is None else pa_volume

        if volume_controller == 'self':
            # Use PulseAudio sink for volume control
            self.pulse.set_sink_volume(sink_name, pa(volume))
            self.logger.debug(f"Set {source.label} volume to {volume}% (PA sink control)")

        elif volume_controller == 'snapcast':
            # Keep PA sink at 100%, control via snapcast
            self.pulse.set_sink_volume(sink_name, pa(100))

            # Use the device name as the snapcast client_id. We always launch
            # snapclient with `--hostID <device.name>` (e.g. fauxnos000), so
            # snapcast knows the client by that exact id. Looking up by MAC
            # was unreliable: install.sh records eth0's MAC in
            # server_config.json, but on a WiFi-attached Pi snapcast sees the
            # wlan0 MAC instead — and they differ on Pi 3B+/Zero 2 W.
            client_id = self.config_manager.device_config.name
            if self.snapcast.set_volume(volume, client_id):
                self.logger.debug(f"Set {source.label} volume to {volume}% (snapcast control, PA at 100%)")
            else:
                self.logger.warning(f"snapcast set_volume failed for client '{client_id}' — is it connected?")

        elif volume_controller == 'external':
            # Audio is attenuated UPSTREAM of the PA sink by an external
            # authority — for the airplay source that's shairport-sync,
            # which does software volume on the PCM stream based on the
            # iPhone's RAOP slider. So fauxnos has nothing to attenuate
            # here: pin the sink at 100 (transparent pass-through when
            # the source is active; mute_sink will still zero it when
            # inactive via the switch_source mute-all loop) and persist
            # the value below for the UI's display memory.
            #
            # We MUST set the PA volume to 100 here even though it looks
            # like a no-op — switch_source mutes every non-active sink
            # to 0, so without this the sink would stay at 0 forever and
            # the externally-attenuated audio would be silenced. The
            # 100 is intentional: any fauxnos-side attenuation would
            # double-attenuate against the iPhone's stage.
            self.pulse.set_sink_volume(sink_name, pa(100))
            self.logger.debug(
                f"Set {source.label} sink to 100% (external authority "
                f"owns attenuation); stored display value = {volume}%"
            )

        elif volume_controller == 'go_librespot':
            # Snapcast is the REAL attenuator here — go-librespot is
            # only a mirror for the Spotify mobile-app slider.
            #
            # Why not single-stage at go-librespot? Because we run
            # `external_volume: true` (so go-librespot does not
            # attenuate at all; it pipes audio at full level and
            # treats its own /player/volume value as a label that's
            # echoed to/from Spotify Connect). Flipping to
            # `external_volume: false` would let go-librespot
            # attenuate, but ONLY inside its decode-to-FIFO stage —
            # which means every volume change has to wait for the
            # ~1s snapcast buffer to drain before being audible. That
            # lag is unacceptable for a slider.
            #
            # So: snapcast attenuates (instant, client-side, after
            # the buffer), go-librespot HTTP push moves the phone
            # slider, WS events from the phone come back through
            # on_external_volume_change which applies the same dual
            # action. PA snapsink stays pinned at 100 (defensive —
            # idempotent set; same instruction cost as a no-op check).
            #
            # EXCEPTION — external_volume_enabled: when the device is
            # in external-volume-controller mode, the audio chain
            # is pinned at unity end-to-end. Snapcast goes to 100
            # (not `volume`) so the external controller owns
            # attenuation, and we skip the go-librespot push so the
            # phone slider doesn't snap to whatever value we got told
            # to "set" (the user set their phone slider; if we POST
            # back to go-librespot, it overwrites their gesture).
            client_id = self.config_manager.device_config.name
            self.pulse.set_sink_volume(sink_name, pa(100))
            snapcast_target = 100 if self.external_volume_enabled else volume

            if not self.snapcast.set_volume(snapcast_target, client_id):
                self.logger.debug(
                    f"snapcast set_volume({snapcast_target}%) failed for '{client_id}' "
                    f"(client may not be connected yet)"
                )
            if self.external_volume_enabled:
                # Skip the go-librespot push entirely — we don't want
                # the phone slider snapping. Persist the saved value
                # below (handled by caller) so the UI's per-source
                # memory still works for next-time-this-source-is-active.
                return

            if self.go_librespot is None:
                self.logger.warning(
                    f"Source {source.id} uses volume_controller=go_librespot "
                    f"but no GoLibrespotController is configured. Volume saved "
                    f"to fauxnos state only; phone-slider mirror NOT updated."
                )
            else:
                if self.go_librespot.set_volume(volume):
                    self.logger.debug(
                        f"Set {source.label} volume to {volume}% "
                        f"(snapcast=attenuator, go-librespot=phone-mirror)"
                    )
                else:
                    # Soft fail: snapcast already attenuated above, so
                    # audio is correct. Only the phone slider may lag
                    # the fauxnos UI until the next active/resync event.
                    self.logger.debug(
                        f"go-librespot mirror push failed for {volume}% — "
                        f"audio is correct (snapcast already set), phone "
                        f"slider may lag until next session/active event"
                    )

        # Update stored volume
        self.source_volumes[source.id] = volume

    def set_volume(self, volume: int) -> bool:
        """
        Set volume for currently active source

        Args:
            volume: Target volume (0-100)

        Returns:
            True if successful
        """
        if not self.current_source:
            self.logger.error("No active source to set volume for")
            return False

        # A slider move mid-fade ends the fade on the spot; the ramp
        # would otherwise keep overwriting the level the user just set.
        self._settle_fade()

        source = self.config_manager.get_source(self.current_source)
        if not source:
            self.logger.error(f"Current source not found: {self.current_source}")
            return False

        if source.type == 'external':
            self.logger.warning(f"Cannot control volume for external source {source.label}")
            return False

        self._set_source_volume(source, volume)

        # Save state
        self._save_state()

        self.logger.info(f"Set {source.label} volume to {volume}%")
        return True

    def on_external_volume_change(self, source_id: str, volume: int):
        """
        Apply a volume change that originated OUTSIDE fauxnos (e.g.
        the Spotify mobile-app slider, routed through the
        go-librespot WS).

        For a go_librespot-controlled source, snapcast is the real
        attenuator — so we must apply the new value to snapcast on
        this path too. Without it, the fauxnos UI slider would track
        the phone but audio would stay at the OLD level until the
        next UI drag (the server-side VolumeManager used to be the
        bridge that propagated phone → snapcast; we replaced it with
        this).

        We do NOT push the value back to go-librespot — that's where
        the change came from. Echo suppression in GoLibrespotController
        also prevents our OWN HTTP pushes from looping back through
        here.

        Per-source-volume rule: even if this isn't the currently
        active source, we still save it so the value is right next
        time we restore that source.
        """
        volume = max(0, min(100, int(volume)))
        if self.source_volumes.get(source_id) == volume:
            return  # No-op — avoids MQTT chatter on idempotent echoes.
        self.source_volumes[source_id] = volume

        # Apply snapcast attenuation if this source uses go_librespot
        # mirror mode. Only relevant when this source is currently
        # active — if the user has switched to another source and the
        # Spotify phone slider moves, we want to remember the new
        # level for next time we switch back to spotify, but we must
        # NOT clobber the active source's attenuation while it's playing.
        source = self.config_manager.get_source(source_id)
        if (
            source is not None
            and source.volume_controller == 'go_librespot'
            and self.current_source == source_id
        ):
            client_id = self.config_manager.device_config.name
            if self.external_volume_enabled:
                # External-volume mode: don't attenuate locally — keep
                # snapcast pinned at unity. Instead forward the new
                # value to the server's /external_volume endpoint so
                # the configured transport (HTTP or MQTT) carries it
                # to the actual volume authority (e.g. a Particle
                # Photon). The server's response also pins our local
                # chain to 100 as a belt-and-suspenders idempotent
                # write; we don't await that here — the slider should
                # feel instant from the user's perspective.
                self.snapcast.set_volume(100, client_id)  # defensive pin
                # Echo suppression: if this WS event is the confirmation
                # of a value we just pushed via apply_external_mirror,
                # don't forward it back through /external_volume — that
                # would dispatch another setVolume to the external
                # device, which would publish its (possibly rounded)
                # value, which would mirror back, … the cascade ends
                # at a Photon rounding fixed-point but it's still wrong.
                # Value-based echo suppression (vs the time-based one
                # in go_librespot.py) catches the case where the WS
                # event arrives past the time window but still matches.
                if getattr(self, "_last_mirror_pushed", None) == volume:
                    self.logger.debug(
                        f"on_external_volume_change({volume}): echo of mirror push, skip forward"
                    )
                else:
                    self._forward_to_external_volume(volume)
            else:
                if not self.snapcast.set_volume(volume, client_id):
                    self.logger.debug(
                        f"snapcast set_volume({volume}%) failed for '{client_id}' "
                        f"on external change — audio may lag phone slider"
                    )

        self._save_state()
        self.logger.info(
            f"External volume change: {source_id} → {volume}% (Spotify Connect)"
        )
        if self._on_external_volume_change is not None:
            try:
                self._on_external_volume_change(source_id, volume)
            except Exception as e:
                self.logger.error(f"on_external_volume_change callback raised: {e}")

    def resync_go_librespot_volume(self):
        """
        Push the stored spotify-source volume into go-librespot.
        Called on daemon startup and on every `active` WS event so
        fauxnos's stored value wins over go-librespot's
        `initial_volume` default (and over whatever it remembered
        before the last service restart). No-op if there's no
        go_librespot-controlled source configured.
        """
        if self.go_librespot is None:
            return
        for source_id, source in self.config_manager.get_internal_sources().items():
            if source.volume_controller != 'go_librespot':
                continue
            stored = self.source_volumes.get(source_id)
            if stored is None:
                continue
            if self.go_librespot.set_volume(stored):
                self.logger.info(
                    f"Resynced go-librespot volume → {stored}% (from stored {source_id})"
                )
            return  # Only one go_librespot-controlled source expected.

    def get_current_source(self) -> Optional[str]:
        """Get ID of currently active source"""
        return self.current_source

    def get_source_volume(self, source_id: str) -> Optional[int]:
        """Get stored volume for a source"""
        return self.source_volumes.get(source_id)

    def get_all_source_volumes(self) -> Dict[str, int]:
        """Get all source volumes"""
        return self.source_volumes.copy()

    @staticmethod
    def loopback_role_for_sink(sink_name: str) -> str:
        """
        Convention: each <sink>.monitor → alsa_output loopback gets a
        media.role of f'fauxnos-{sink_name}-out' in default.pa. This is
        what we calibrate. Multiple sources may share a sink, in which
        case they share the same calibration loopback.
        """
        return f"fauxnos-{sink_name}-out"

    def apply_calibrations(self):
        """
        Apply per-source PA loopback calibration for every internal source.
        Idempotent — safe to call on startup and on every change. State
        overrides take priority over the YAML default.
        """
        # Build a sink -> calibration map. If multiple sources target the
        # same sink, the LAST one wins (they share the loopback anyway).
        sink_calibrations: Dict[str, int] = {}
        for source_id, source in self.config_manager.get_internal_sources().items():
            if not source.sink:
                continue
            cal = self.state_manager.get_pa_calibration(source_id)
            if cal is None:
                cal = source.pa_calibration
            sink_calibrations[source.sink] = cal

        for sink_name, cal in sink_calibrations.items():
            role = self.loopback_role_for_sink(sink_name)
            ok = self.pulse.set_loopback_calibration(role, cal)
            if ok:
                self.logger.info(
                    f"Applied calibration for sink={sink_name} (role={role}) → {cal}%"
                )
            else:
                self.logger.warning(
                    f"Could not apply calibration for sink={sink_name} (role={role}) — "
                    f"loopback not loaded? PA may still be starting."
                )

    def set_calibration(self, source_id: str, value: int) -> bool:
        """
        Set the PA loopback calibration for a source. Persists the value
        to state, applies via PA, and returns True on success.
        Affects all sources that share the same sink (since they share
        the underlying loopback).
        """
        if not (0 <= value <= 200):
            self.logger.error(f"set_calibration: value {value} out of range 0-200")
            return False

        source = self.config_manager.get_source(source_id)
        if not source or source.type != 'internal' or not source.sink:
            self.logger.warning(f"set_calibration: source {source_id} not internal or no sink")
            return False

        role = self.loopback_role_for_sink(source.sink)
        if not self.pulse.set_loopback_calibration(role, value):
            return False

        # Persist for THIS source plus every other source sharing the sink
        for sid, src in self.config_manager.get_internal_sources().items():
            if src.sink == source.sink:
                self.state_manager.set_pa_calibration(sid, value)

        self.logger.info(f"Calibration saved: {source_id} (sink={source.sink}) → {value}%")
        return True

    def get_calibration(self, source_id: str) -> int:
        """Return effective calibration: state override else YAML default."""
        source = self.config_manager.get_source(source_id)
        if not source:
            return 100
        cal = self.state_manager.get_pa_calibration(source_id)
        if cal is None:
            cal = source.pa_calibration
        return cal

    def initialize_audio_system(self):
        """
        Initialize audio system on startup:
        - Mute all sinks
        - Apply per-source PA loopback calibrations (fixed pre-amp ceilings)
        - Load previous state or switch to first source
        """
        self.logger.info("Initializing audio system...")

        saved_source = self.state_manager.get_current_source()

        # Mute all internal sources — except the one we're about to
        # restore, which goes straight to its normal level instead. Its
        # producer (e.g. the noise generator, a separate systemd service)
        # may well still be playing through a daemon restart or update,
        # and a mute here would put a gap in overnight noise for nothing.
        # Setting it (rather than leaving it alone) still covers a fresh
        # boot, where PA brings every null sink up at 100%.
        restore = None
        if saved_source and saved_source in self.config_manager.sources:
            restore = self.config_manager.sources[saved_source]
        keep_sink = restore.sink if restore is not None and restore.type == 'internal' else None
        for source_id, source in self.config_manager.get_internal_sources().items():
            if source.sink != keep_sink:
                self.pulse.mute_sink(source.sink)
        if keep_sink:
            self.pulse.set_sink_volume(keep_sink, self._active_pa_level(restore))

        # Apply per-source PA loopback calibration ceilings (e.g. Spotify cap
        # at 50%, Analog at 100%) so volume normalization is in place before
        # we restore any source/volume state.
        self.apply_calibrations()

        # Restore previous source or use first source
        if saved_source and saved_source in self.config_manager.sources:
            self.logger.info(f"Restoring previous source: {saved_source}")
            self.switch_source(saved_source)
        else:
            # Use first source as default
            first_source = list(self.config_manager.sources.keys())[0]
            self.logger.info(f"No previous source, using default: {first_source}")
            self.switch_source(first_source)

        # Reconcile go-librespot to our stored spotify volume even if
        # spotify isn't the active source right now. go-librespot
        # started with `initial_volume: 50` regardless of what fauxnos
        # remembers; without this, a fresh `active` event before any
        # web-UI nudge would play at the daemon's 50% instead of the
        # user's saved level. Best-effort — silently skipped if
        # go-librespot isn't reachable yet (it'll resync on the next
        # `active` WS event).
        self.resync_go_librespot_volume()

    def _spawn_hook(self, source_id: str, hook: str, command: str):
        """
        Run a source's `on_enter_command` / `on_leave_command` asynchronously.

        Fire-and-forget by design: we never want a slow cleanup
        (e.g. shairport-sync's restart of ~1-2s) to gate the source
        switch — the user's main intent is "play audio from the new
        source NOW," not "wait for the previous source to wind down."
        Output is discarded; failures are logged at warning level.

        We use shell=True so the value in YAML can be a one-liner
        with pipes/redirects if needed (e.g. `dbus-send … | head -1`),
        not just an argv list. Trust boundary: the YAML is operator-
        owned config on the device, same trust level as the daemon
        itself, so command injection is not a vulnerability here.
        """
        try:
            subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,  # don't tie to our process group
            )
            self.logger.info(
                f"{hook} for {source_id}: spawned `{command}`"
            )
        except Exception as e:
            self.logger.warning(
                f"{hook} for {source_id} failed to spawn: {e}"
            )

    def _trigger_external_switch(self, url: str, payload: Dict, content_type: str = 'json') -> bool:
        """
        Trigger external source switch via HTTP POST

        Args:
            url: Webhook URL
            payload: Payload to send
            content_type: 'json' or 'form'

        Returns:
            True if successful
        """
        try:
            self.logger.debug(f"Triggering external switch: {url} ({content_type})")
            if content_type == 'form':
                response = requests.post(url, data=payload, timeout=5)
            else:
                response = requests.post(url, json=payload, timeout=5)

            if response.status_code == 200:
                self.logger.debug("External switch triggered successfully")
                return True
            else:
                self.logger.warning(f"External switch returned status {response.status_code}")
                return False

        except requests.exceptions.Timeout:
            self.logger.error(f"Timeout triggering external switch: {url}")
            return False
        except Exception as e:
            self.logger.error(f"Error triggering external switch: {e}")
            return False


# Standalone testing
if __name__ == '__main__':
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) < 2:
        print("Usage: python source_manager.py <config_file>")
        print("  Test source manager with a config file")
        sys.exit(1)

    config_file = sys.argv[1]

    try:
        # Load configuration
        cm = ConfigManager(config_file)
        print(f"✓ Configuration loaded")

        # Create source manager
        sm = SourceManager(cm)
        print(f"✓ Source manager initialized")

        # Initialize audio system
        sm.initialize_audio_system()
        print(f"✓ Audio system initialized")
        print(f"  Current source: {sm.current_source}")

        # Show available sources
        print("\nAvailable sources:")
        for source_id, source in cm.sources.items():
            vol = sm.get_source_volume(source_id)
            print(f"  - {source.label} ({source_id}): {vol}%")

        print("\nSource manager ready for testing")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
