#!/usr/bin/env python3
"""
Source Manager

Handles audio source switching with smart volume control routing
"""

import logging
import requests
from typing import Callable, Dict, Optional
from .config_manager import ConfigManager, SourceConfig
from .go_librespot import GoLibrespotController
from .pulse_controller import PulseAudioController
from .snapcast_controller import SnapcastController
from .state_manager import StateManager


class SourceManager:
    """Manages audio source switching and volume control"""

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

        # Track current source and volumes
        self.current_source: Optional[str] = None
        self.source_volumes: Dict[str, int] = {}

        # Initialize volumes from config
        for source_id, source in config_manager.sources.items():
            self.source_volumes[source_id] = source.starting_volume

        # Try to load previous state
        self._load_state()

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

    def switch_source(self, source_id: str) -> bool:
        """
        Switch to a different audio source

        Args:
            source_id: ID of source to switch to

        Returns:
            True if successful, False otherwise
        """
        # Validate source exists
        source = self.config_manager.get_source(source_id)
        if not source:
            self.logger.error(f"Source not found: {source_id}")
            return False

        # Check if already on this source
        if self.current_source == source_id:
            self.logger.debug(f"Already on source {source_id}, skipping switch")
            return True

        # Leaving a go_librespot-controlled source? Pause it so the
        # daemon doesn't keep streaming Spotify audio into the now-
        # unselected snapcast stream (which would also keep the
        # Spotify "Now Playing" running on the user's phone). Idempotent:
        # pause when already paused is a soft no-op inside the controller.
        if self.current_source is not None:
            prev_source = self.config_manager.get_source(self.current_source)
            if (
                prev_source is not None
                and prev_source.volume_controller == 'go_librespot'
                and self.go_librespot is not None
            ):
                self.go_librespot.pause()

        self.logger.info(f"Switching to source: {source.label} ({source_id})")

        # Handle external sources differently
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
        # Step 1: Mute all other internal sources
        self.logger.debug("Muting other sources...")
        for other_id, other_source in self.config_manager.get_internal_sources().items():
            if other_id != source.id:
                self.pulse.mute_sink(other_source.sink)

        # Step 2: Apply the new source's stored volume via its
        # configured controller (self/snapcast/go_librespot). Direct
        # set, no fade — the fade ramp was a step-loop that blocked
        # this thread for ~1s on every switch, making the UI lag
        # behind every action with no audible benefit.
        target_volume = self.source_volumes[source.id]
        self._set_source_volume(source, target_volume)

        # Step 3: Trigger external switch if configured
        if source.external_switch and source.external_switch.enabled:
            self._trigger_external_switch(source.external_switch.url, source.external_switch.payload, source.external_switch.content_type)

        # Update current source and save state
        self.current_source = source.id
        self._save_state()

        self.logger.info(f"Switched to {source.label}")
        return True

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

    def _set_source_volume(self, source: SourceConfig, volume: int):
        """
        Set volume for a source using appropriate controller

        Args:
            source: Source configuration
            volume: Target volume (0-100)
        """
        if source.type != 'internal':
            self.logger.warning(f"Cannot set volume for external source {source.id}")
            return

        volume_controller = source.volume_controller
        sink_name = source.sink

        if volume_controller == 'self':
            # Use PulseAudio sink for volume control
            self.pulse.set_sink_volume(sink_name, volume)
            self.logger.debug(f"Set {source.label} volume to {volume}% (PA sink control)")

        elif volume_controller == 'snapcast':
            # Keep PA sink at 100%, control via snapcast
            self.pulse.set_sink_volume(sink_name, 100)

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
            client_id = self.config_manager.device_config.name
            self.pulse.set_sink_volume(sink_name, 100)

            if not self.snapcast.set_volume(volume, client_id):
                self.logger.debug(
                    f"snapcast set_volume({volume}%) failed for '{client_id}' "
                    f"(client may not be connected yet)"
                )

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
        # active — if the user is on AirPlay and the Spotify phone
        # slider moves, we want to remember the new level for next
        # time we switch back to spotify, but we must NOT clobber
        # AirPlay's snapcast attenuation while it's playing.
        source = self.config_manager.get_source(source_id)
        if (
            source is not None
            and source.volume_controller == 'go_librespot'
            and self.current_source == source_id
        ):
            client_id = self.config_manager.device_config.name
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
        what we calibrate. Multiple sources may share a sink (e.g.
        spotify and airplay both target snapsink), so they share the
        same calibration loopback.
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
        if not (0 <= value <= 100):
            self.logger.error(f"set_calibration: value {value} out of range 0-100")
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

        # Mute all internal sources
        for source_id, source in self.config_manager.get_internal_sources().items():
            self.pulse.mute_sink(source.sink)

        # Apply per-source PA loopback calibration ceilings (e.g. Spotify cap
        # at 50%, Analog at 100%) so volume normalization is in place before
        # we restore any source/volume state.
        self.apply_calibrations()

        # Try to restore previous source or use first source
        saved_source = self.state_manager.get_current_source()

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
