#!/usr/bin/env python3
"""
Fauxnos Client - Client-side audio source manager

Manages local audio sources with smart volume routing
"""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

# Import our modules
from modules.config_manager import ConfigManager
from modules import logger as logger_module
from modules.eq_controller import EqController
from modules.go_librespot import GoLibrespotController
from modules.source_manager import SourceManager
from modules.mqtt_client import MQTTClient
from modules.ir_listener import IRListener, COMMAND_IDS as IR_COMMAND_IDS
from modules.gpio_buttons import GPIOButtonHandler


class FauxnosClient:
    """Main Fauxnos client application"""

    def __init__(self, config_file: str = None):
        """
        Initialize Fauxnos client

        Args:
            config_file: Path to config file (default: ~/.config/fauxnos/client_config.yaml)
        """
        # Load configuration
        self.config_manager = ConfigManager(config_file)

        # Setup logging
        logger_module.setup_logging(
            self.config_manager.logging_config.file,
            self.config_manager.logging_config.level
        )
        self.logger = logging.getLogger(__name__)

        self.logger.info(f"Fauxnos Client starting for device: {self.config_manager.device_config.display_name}")

        # Construct the go-librespot controller if any source on this
        # client uses `volume_controller: go_librespot`. The wrapper
        # is cheap (one requests session + dormant WS thread until
        # start()), so we always build it when it's relevant rather
        # than lazy-creating it. Host/port come from config_manager —
        # derived from fauxnos<NNN> + server_host by default, with
        # YAML overrides supported. See brief_spotify_volume_sync.md.
        self.go_librespot = None
        if any(
            src.volume_controller == 'go_librespot'
            for src in self.config_manager.get_internal_sources().values()
        ):
            self.go_librespot = GoLibrespotController(
                host=self.config_manager.go_librespot_host,
                port=self.config_manager.go_librespot_port,
                on_volume=self._on_spotify_external_volume,
                on_active=self._on_spotify_active,
                on_inactive=None,
                on_playing=self._on_spotify_playing,
                on_paused=None,
            )
            self.logger.info(
                f"go-librespot controller: "
                f"{self.config_manager.go_librespot_host}:"
                f"{self.config_manager.go_librespot_port}"
            )

        # Initialize source manager. The on_external_volume_change
        # callback is the bridge that lets a Spotify-mobile-app slider
        # nudge propagate to MQTT (web UI) — source_manager owns the
        # state save; we own the publish.
        self.source_manager = SourceManager(
            self.config_manager,
            go_librespot=self.go_librespot,
            on_external_volume_change=self._on_source_external_volume,
        )

        # NOTE: AirPlay has NO fauxnos-side volume mirror. shairport-sync
        # owns the volume entirely (iPhone slider drives its software
        # attenuation on the PCM stream). We surface that in the UI by
        # locking the slider and hiding the percentage — see GroupCard.
        # No metadata-pipe reader, no MQTT volume status for the airplay
        # source. The `volume_controller: external` branch in
        # source_manager._set_source_volume still applies so any
        # fauxnos-side write (UI, IR remote) is a no-op on audio.

        # IR listener (hardware-remote support). Constructed BEFORE the
        # MQTT client so we can hand its enable/clear/state-getter to
        # the MQTT layer's IR callbacks. The on_learn_event hook fires
        # when learning mode transitions; we forward those to MQTT so
        # the server can mirror state to any open browser tab. (Learn
        # itself is triggered via phase 4's set/clients/<id>/ir/learn
        # topic family.)
        self.ir_listener = IRListener(
            state_manager=self.source_manager.state_manager,
            command_handlers=self._build_ir_handlers(),
            on_learn_event=self._on_ir_learn_event,
        )

        # GPIO push-button handler (optional hardware buttons soldered
        # to the Pi header). Reuses the IR handler dispatch table — same
        # callbacks, same feedback sounds, same MQTT publishes — so a
        # button press is indistinguishable from a remote press downstream.
        # See modules/gpio_buttons.py for the wiring (default GPIO 5/6/26).
        # Soft-fails on missing gpiozero or already-claimed pins; the
        # daemon comes up without buttons rather than crashing.
        self.gpio_buttons = GPIOButtonHandler(
            buttons_config=self.config_manager.buttons,
            command_handlers=self._build_ir_handlers(),
        )

        # EQ controller — rewrites ~/.config/pulse/default.pa's
        # module-ladspa-sink control= line and runs a pactl unload/load
        # dance so the new gains land live. Source of truth is the
        # sidecar at ~/.config/fauxnos/eq_state.json. No MQTT awareness
        # here; the MQTTClient below ferries set/get commands to it.
        self.eq_controller = EqController()

        # Initialize MQTT client (connects to broker, routes commands through SourceManager)
        self.mqtt_client = MQTTClient(
            config_manager=self.config_manager,
            volume_callback=self.source_manager.set_volume,
            mode_callback=self.source_manager.switch_source,
            source_volume_getter=self.source_manager.get_source_volume,
            calibration_callback=self.source_manager.set_calibration,
            calibration_getter=self.source_manager.get_calibration,
            ir_enable_callback=self.ir_listener.set_enabled,
            ir_clear_callback=self.ir_listener.clear_command,
            ir_state_getter=self.ir_listener.state_manager.get_ir,
            ir_learn_start_callback=self.ir_listener.start_learning,
            ir_learn_cancel_callback=self.ir_listener.cancel_learning,
            ir_feedback_volume_callback=self._set_ir_feedback_volume,
            eq_callback=self.eq_controller.set_state,
            eq_getter=self.eq_controller.get_state,
            # External volume controller: server publishes the device's EVC
            # state on a retained config topic; we forward the `enabled`
            # bool to source_manager so it knows whether to pin the local
            # audio chain at unity (and skip go-librespot phone pushes /
            # snapcast attenuation) versus business-as-usual.
            evc_state_callback=self.source_manager.set_external_volume_state,
            # External-volume authoritative-value mirror: server publishes
            # whenever the external authority reports a new value (knob
            # turn, UI-slider round-trip echo). source_manager pushes
            # that value to go-librespot so Spotify phone slider tracks.
            evc_mirror_callback=self.source_manager.apply_external_mirror,
        )

        # Flag for graceful shutdown
        self.running = True

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {sig}, shutting down...")
        self.running = False
        self.ir_listener.stop()
        self.gpio_buttons.stop()
        if self.go_librespot:
            self.go_librespot.stop()
        self.mqtt_client.stop()
        sys.exit(0)

    # ---- go-librespot WS callbacks ----
    #
    # These fire from the GoLibrespotController's reader thread. They
    # bridge daemon-detected Spotify events into the same code paths
    # an IR or web-UI change takes, so all surfaces stay in lockstep.
    # Echo prevention is handled inside the controller, not here.

    def _on_spotify_external_volume(self, volume: int):
        """
        Spotify mobile app moved the volume slider. Find the
        go-librespot-controlled source and route through
        SourceManager.on_external_volume_change so state persists and
        MQTT publishes.
        """
        spotify_source_id = self._go_librespot_source_id()
        if spotify_source_id is None:
            return
        self.source_manager.on_external_volume_change(spotify_source_id, volume)

    def _on_spotify_active(self):
        """
        Spotify Connect session became active on go-librespot, i.e. the
        user selected this device in the Spotify app. We do two things:

        1. Re-push our stored volume so the audio (and the phone's
           slider, which go-librespot will sync to whatever value it's
           at) matches what the user last set in fauxnos. Without this
           the phone slider snaps to go-librespot's `initial_volume: 50`
           regardless of what fauxnos says it should be.
        2. Auto-switch the device's source to Spotify. Selecting a
           device in the Spotify app is itself enough intent to claim
           it for Spotify — we no longer wait for the `playing` event
           (FX-84). The `playing` handler still fires the same switch
           so resume-after-pause from another source also works.
        """
        self.source_manager.resync_go_librespot_volume()
        self._auto_switch_to_spotify("Spotify Connect active")

    def _on_spotify_playing(self):
        """
        Spotify audio started playing on go-librespot. The user's intent
        is unambiguous: they pressed play (or resumed) on the Spotify
        mobile app, so they want audio from this device — auto-switch.
        """
        self._auto_switch_to_spotify("Spotify playing detected")

    def _auto_switch_to_spotify(self, reason: str):
        """
        Ensure the device's active source is its go-librespot (Spotify)
        source. Shared by the `active` (device selected in the Spotify app)
        and `playing` (audio started) go-librespot events.

        Crucially this does NOT skip when fauxnos already believes it's on
        spotify. The cached current_source can disagree with the real PA
        routing — restored stale from disk on boot, or left muted by a
        sibling source's switch — which produced the "UI shows Spotify but
        no audio until I re-pick it" bug. ensure_source_routed re-asserts
        the live route in that case (idempotent: mutes siblings + re-applies
        volume, no audible glitch) instead of trusting state and no-op'ing.

        Goes through MQTTClient.update_mode so the web UI tracks the change
        just like a manual switch, and republishes the per-source volume
        (matching the path an MQTT mode command takes, see mqtt_client.py
        phase 4) so the UI shows the right source's level. Both are
        idempotent and only fire on these (low-frequency) session events,
        so re-publishing when nothing changed is harmless.
        """
        spotify_source_id = self._go_librespot_source_id()
        if spotify_source_id is None:
            return
        already = self.source_manager.get_current_source() == spotify_source_id
        self.logger.info(
            f"{reason} — ensuring source is {spotify_source_id} "
            f"({'re-assert' if already else 'switch'})"
        )
        if self.source_manager.ensure_source_routed(spotify_source_id):
            self.mqtt_client.update_mode(spotify_source_id)
            new_vol = self.source_manager.get_source_volume(spotify_source_id)
            if new_vol is not None:
                self.mqtt_client.update_volume(new_vol)

    def _on_source_external_volume(self, source_id: str, volume: int):
        """
        SourceManager → MQTT publish bridge for externally-driven
        volume changes. Routed back through `update_volume` so the
        de-dup + publish path is identical to a web-UI or IR-driven
        change.
        """
        self.mqtt_client.update_volume(volume)

    def _go_librespot_source_id(self):
        """First (and conventionally only) source whose
        volume_controller is go_librespot. Returns None if none."""
        for sid, src in self.config_manager.get_internal_sources().items():
            if src.volume_controller == 'go_librespot':
                return sid
        return None


    # ---- IR command handlers ----
    #
    # Each handler is a no-arg callable invoked by IRListener when a
    # learned scancode matches. They route through the same code paths
    # the MQTT and Web UI use, so the remote and the UI stay in lockstep
    # (e.g. a remote-driven volume change still publishes status updates).

    # Volume-step granularity for the IR remote. 5% gives a 20-step
    # range from 0 to 100, which feels natural on a button press.
    IR_VOLUME_STEP = 5

    # Path where per-notch feedback WAVs live. Files are named
    # `volume-NNN.wav` where NNN is the volume percentage zero-padded
    # to 3 digits (e.g. volume-005.wav, volume-100.wav). Generated by
    # scripts/generate-volume-feedback-placeholders.py at install time
    # — meant to be overwritten with the user's real sounds.
    IR_SOUNDS_DIR = Path(__file__).parent / 'sounds'

    def _play_feedback_sound(self, filename: str):
        """
        Play a feedback sound file from IR_SOUNDS_DIR, scaled by the
        user-configured ir.feedback_volume (0-100, default 30). Used by
        all IR-handler feedback paths: per-notch volume sounds, mute/
        unmute toggle, etc.

        Missing files are a soft failure — the handler still applies
        the volume change, we just skip the sound. This is intentional
        so the user can ship partial sound sets during iteration.
        """
        path = self.IR_SOUNDS_DIR / filename
        feedback_vol = self.source_manager.state_manager.get_ir().get(
            'feedback_volume',
            self.source_manager.state_manager.IR_FEEDBACK_VOLUME_DEFAULT,
        )
        self.source_manager.pulse.play_sound(path, volume_pct=feedback_vol)

    def _play_volume_feedback(self, volume_pct: int):
        """
        Play the per-notch feedback sound for an IR Vol+/Vol- press.
        Snaps to the nearest IR_VOLUME_STEP-aligned notch so a 73%
        level from the web UI followed by an IR vol+ still resolves
        to a real notch file. The 0% and 100% positions are caps —
        their `volume-000.wav` / `volume-100.wav` are distinct sounds
        that play whenever you ARRIVE at the cap.
        """
        step = self.IR_VOLUME_STEP
        notch = max(0, min(100, round(volume_pct / step) * step))
        self._play_feedback_sound(f'volume-{notch:03d}.wav')

    def _build_ir_handlers(self):
        """Construct the {command_id: callable} map passed to IRListener."""
        return {
            'volume_up':    self._ir_volume_up,
            'volume_down':  self._ir_volume_down,
            'mute':         self._ir_mute_toggle,
            'source_cycle': self._ir_source_cycle,
            'source_analog': self._ir_source_analog,
            # Transport controls are stubbed for phase 2. Phase 3 will
            # wire these to playerctl (Spotify), no-op for analog/vinyl/aux.
            'play_pause':   lambda: self.logger.info("IR play_pause (stub — phase 3)"),
            'next':         lambda: self.logger.info("IR next (stub — phase 3)"),
            'previous':     lambda: self.logger.info("IR previous (stub — phase 3)"),
        }

    def _ir_volume_up(self):
        cur = self.source_manager.get_current_source()
        if not cur:
            return
        vol = self.source_manager.get_source_volume(cur) or 0
        new_vol = min(100, vol + self.IR_VOLUME_STEP)
        # Feedback FIRST — paplay is non-blocking, so the user hears
        # the notch tone within ~100ms instead of waiting for the pactl
        # subprocess + MQTT publish chain below to finish.
        self._play_volume_feedback(new_vol)
        if self.source_manager.set_volume(new_vol):
            self.mqtt_client.update_volume(new_vol)

    def _ir_volume_down(self):
        cur = self.source_manager.get_current_source()
        if not cur:
            return
        vol = self.source_manager.get_source_volume(cur) or 0
        new_vol = max(0, vol - self.IR_VOLUME_STEP)
        self._play_volume_feedback(new_vol)
        if self.source_manager.set_volume(new_vol):
            self.mqtt_client.update_volume(new_vol)

    def _ir_mute_toggle(self):
        """
        Mute toggle: if current volume > 0, save it and set to 0; if
        already 0, restore the last non-zero value (default 30% if we
        have no memory).

        Sound feedback is dedicated mute.wav / unmute.wav rather than
        a notch sound — distinguishes "user explicitly muted" from
        "user stepped Vol- down to 0" (which plays volume-000.wav).
        """
        cur = self.source_manager.get_current_source()
        if not cur:
            return
        vol = self.source_manager.get_source_volume(cur) or 0
        muting = vol > 0
        if muting:
            self._ir_pre_mute_volume = vol
            target = 0
        else:
            target = getattr(self, '_ir_pre_mute_volume', 30)
        # Sound first; volume change second. Same latency rationale as
        # the volume up/down handlers above.
        self._play_feedback_sound('mute.wav' if muting else 'unmute.wav')
        if self.source_manager.set_volume(target):
            self.mqtt_client.update_volume(target)

    def _ir_source_cycle(self):
        """Cycle through this client's internal sources in config order."""
        sources = list(self.config_manager.get_internal_sources().keys())
        if not sources:
            return
        cur = self.source_manager.get_current_source()
        try:
            idx = sources.index(cur)
        except ValueError:
            idx = -1
        nxt = sources[(idx + 1) % len(sources)]
        # Sound BEFORE the switch — switch_source() is now near-
        # instant (the old blocking fade was removed), but keeping
        # the sound-first ordering preserves the rule from the IR
        # latency fix and stays robust against future regressions.
        # Single tone for any source change, distinct from per-notch
        # volume + mute/unmute sounds. IR-only by design; web/MQTT
        # source switches go through SourceManager.switch_source()
        # directly and stay silent.
        self._play_feedback_sound('source_switch.wav')
        if self.source_manager.switch_source(nxt):
            self.mqtt_client.update_mode(nxt)

    # Built-in source id for the analog input. Matches the `analog`
    # id in client_config.yaml.template and the server's default
    # source catalog — every device with ADC hardware uses it.
    ANALOG_SOURCE_ID = 'analog'

    def _ir_source_analog(self):
        """Jump straight to the analog source, regardless of current source.

        Discrete sibling of _ir_source_cycle: one press always lands on
        analog in (e.g. flipping on a turntable), no cycling. No-op with
        no feedback tone on devices that have no analog source configured
        (same silent-ignore posture as the stubbed transport handlers) —
        we guard here rather than letting switch_source log an error.
        """
        if self.config_manager.get_source(self.ANALOG_SOURCE_ID) is None:
            self.logger.info(
                "IR source_analog: no analog source on this device, ignoring"
            )
            return
        # Same feedback tone + sound-first ordering as source_cycle.
        self._play_feedback_sound('source_switch.wav')
        if self.source_manager.switch_source(self.ANALOG_SOURCE_ID):
            self.mqtt_client.update_mode(self.ANALOG_SOURCE_ID)

    def _set_ir_feedback_volume(self, volume_pct: int):
        """
        Persist the user-tuned feedback playback volume and immediately
        play a sample (volume-050.wav, a mid-range notch) at the new
        level so they can hear what they're tuning.

        Called from MQTTClient when a set/.../ir/feedback_volume command
        arrives. The UI uses a debounced PUT so the slider drag doesn't
        spam previews — only the post-debounce settled value triggers
        this method.
        """
        self.source_manager.state_manager.set_ir_feedback_volume(volume_pct)
        # Sample sound at the new level — gives immediate auditory feedback
        # without the user needing to grab the remote.
        sample = self.IR_SOUNDS_DIR / 'volume-050.wav'
        self.source_manager.pulse.play_sound(sample, volume_pct=volume_pct)

    def _on_ir_learn_event(self, event: str, payload: dict):
        """
        Bridge IRListener lifecycle events to MQTT so the server can
        mirror state to any open browser tab. Events: started / captured
        / timeout / cancelled. See modules/ir_listener.py for payload shapes.
        On 'captured' we also republish the full state since the mapping
        changed; the others are just lifecycle telemetry.
        """
        try:
            topic = f"status/clients/{self.config_manager.device_config.name}/ir/learn_event"
            self.mqtt_client.client.publish(
                topic,
                json.dumps({'event': event, **payload}),
            )
        except Exception as e:
            self.logger.error(f"Failed to publish ir learn event {event}: {e}")
        if event == 'captured':
            # The mapping just changed — make the new state visible.
            self.mqtt_client.publish_ir_state()

    def run_daemon(self):
        """Run in daemon mode (background service)"""
        self.logger.info("Running in daemon mode")

        # Initialize audio system (also kicks the initial resync of
        # go-librespot's volume to our stored value, if applicable).
        self.source_manager.initialize_audio_system()

        # Start MQTT client (subscribes to control topics, publishes status)
        self.mqtt_client.start()

        # Start IR listener if the feature is enabled in saved state.
        # No-op + warning if disabled, so the daemon comes up cleanly
        # on devices without IR configured.
        self.ir_listener.start()

        # Start GPIO button handler if buttons.enabled=true in config.
        # Same no-op-when-disabled pattern as IR; per-pin failures are
        # logged but don't take down the daemon.
        self.gpio_buttons.start()

        # Start the go-librespot WebSocket reader. The HTTP side
        # works whether or not this starts — but without WS we miss
        # Spotify-mobile-app slider changes. Soft-fails if the
        # daemon isn't reachable yet (reconnect loop handles it).
        if self.go_librespot:
            self.go_librespot.start()

        # Publish initial state
        current = self.source_manager.get_current_source()
        if current:
            self.mqtt_client.update_mode(current)
            vol = self.source_manager.get_source_volume(current)
            if vol is not None:
                self.mqtt_client.update_volume(vol)

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        self.ir_listener.stop()
        self.gpio_buttons.stop()
        if self.go_librespot:
            self.go_librespot.stop()
        self.mqtt_client.stop()
        self.logger.info("Daemon shutting down")

    def run_interactive(self):
        """Run in interactive CLI mode"""
        self.logger.info("Running in interactive mode")

        # Initialize audio system
        self.source_manager.initialize_audio_system()

        print(f"\nFauxnos Client - {self.config_manager.device_config.display_name}")
        print("=" * 60)
        print("Type 'help' for available commands\n")

        try:
            while self.running:
                try:
                    command_str = input("> ").strip()
                    if not command_str:
                        continue

                    self._handle_command(command_str)

                except EOFError:
                    print("\nExiting...")
                    break

        except KeyboardInterrupt:
            print("\nExiting...")

        self.logger.info("Interactive session ended")

    def _handle_command(self, command_str: str):
        """
        Handle a user command

        Args:
            command_str: Command string from user
        """
        parts = command_str.split()
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        if command == 'help':
            self._cmd_help()

        elif command == 'source':
            if not args:
                print("Error: source ID required")
                print(f"Available sources: {', '.join(self.config_manager.sources.keys())}")
            else:
                source_id = args[0]
                if self.source_manager.switch_source(source_id):
                    print(f"Switched to {source_id}")
                else:
                    print(f"Failed to switch to {source_id}")

        elif command == 'volume':
            if not args:
                print("Error: volume level required (0-100)")
            else:
                try:
                    volume = int(args[0])
                    if self.source_manager.set_volume(volume):
                        print(f"Volume set to {volume}%")
                    else:
                        print("Failed to set volume")
                except ValueError:
                    print("Error: volume must be a number (0-100)")

        elif command == 'status':
            self._cmd_status()

        elif command == 'list-sources':
            self._cmd_list_sources()

        elif command == 'quit' or command == 'exit':
            print("Exiting...")
            self.running = False
            sys.exit(0)

        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands")

    def _cmd_help(self):
        """Show help message"""
        print("\nAvailable commands:")
        print("  help                  Show this help message")
        print("  source <id>           Switch to source")
        print("  volume <0-100>        Set volume for active source")
        print("  status                Show current status")
        print("  list-sources          List all configured sources")
        print("  quit/exit             Exit the client")
        print()

    def _cmd_status(self):
        """Show current status"""
        current = self.source_manager.get_current_source()

        print("\nCurrent Status:")
        print("=" * 60)

        if current:
            source = self.config_manager.get_source(current)
            if source:
                print(f"Active Source: {source.label} ({current})")
                volume = self.source_manager.get_source_volume(current)
                print(f"Volume: {volume}%")
                print(f"Type: {source.type}")
                if source.type == 'internal':
                    print(f"Sink: {source.sink}")
                    print(f"Volume Controller: {source.volume_controller}")
        else:
            print("Active Source: None")

        print("\nAll Sources:")
        for source_id, source in self.config_manager.sources.items():
            volume = self.source_manager.get_source_volume(source_id)
            active = " (active)" if source_id == current else ""
            print(f"  - {source.label} ({source_id}): {volume}%{active}")

        print()

    def _cmd_list_sources(self):
        """List all configured sources"""
        print("\nConfigured Sources:")
        print("=" * 60)

        for source_id, source in self.config_manager.sources.items():
            print(f"\n{source.label} ({source_id})")
            print(f"  Type: {source.type}")
            if source.type == 'internal':
                print(f"  Sink: {source.sink}")
                print(f"  Volume Controller: {source.volume_controller}")
            volume = self.source_manager.get_source_volume(source_id)
            print(f"  Volume: {volume}%")

        print()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Fauxnos Client - Audio source manager',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--config',
        help='Path to config file (default: ~/.config/fauxnos/client_config.yaml)'
    )

    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run in daemon mode (no interactive CLI)'
    )

    args = parser.parse_args()

    try:
        # Create client
        client = FauxnosClient(args.config)

        # Run in appropriate mode
        if args.daemon:
            client.run_daemon()
        else:
            client.run_interactive()

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("\nPlease create a configuration file first.")
        print("See client_config.yaml.template for an example")
        sys.exit(1)

    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
