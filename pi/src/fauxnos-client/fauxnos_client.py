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
from modules.source_manager import SourceManager
from modules.mqtt_client import MQTTClient
from modules.ir_listener import IRListener, COMMAND_IDS as IR_COMMAND_IDS


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

        # Initialize source manager
        self.source_manager = SourceManager(self.config_manager)

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

        # Initialize MQTT client (connects to broker, routes commands through SourceManager)
        self.mqtt_client = MQTTClient(
            config_manager=self.config_manager,
            volume_callback=self.source_manager.set_volume,
            mode_callback=self.source_manager.switch_source,
            calibration_callback=self.source_manager.set_calibration,
            calibration_getter=self.source_manager.get_calibration,
            ir_enable_callback=self.ir_listener.set_enabled,
            ir_clear_callback=self.ir_listener.clear_command,
            ir_state_getter=self.ir_listener.state_manager.get_ir,
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
        self.mqtt_client.stop()
        sys.exit(0)

    # ---- IR command handlers ----
    #
    # Each handler is a no-arg callable invoked by IRListener when a
    # learned scancode matches. They route through the same code paths
    # the MQTT and Web UI use, so the remote and the UI stay in lockstep
    # (e.g. a remote-driven volume change still publishes status updates).

    # Volume-step granularity for the IR remote. 5% gives a 20-step
    # range from 0 to 100, which feels natural on a button press.
    IR_VOLUME_STEP = 5

    def _build_ir_handlers(self):
        """Construct the {command_id: callable} map passed to IRListener."""
        return {
            'volume_up':    self._ir_volume_up,
            'volume_down':  self._ir_volume_down,
            'mute':         self._ir_mute_toggle,
            'source_cycle': self._ir_source_cycle,
            # Transport controls are stubbed for phase 2. Phase 3 will
            # wire these to playerctl (Spotify) and shairport DBUS
            # (AirPlay), no-op for analog/vinyl/aux.
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
        if self.source_manager.set_volume(new_vol):
            self.mqtt_client.update_volume(new_vol)

    def _ir_volume_down(self):
        cur = self.source_manager.get_current_source()
        if not cur:
            return
        vol = self.source_manager.get_source_volume(cur) or 0
        new_vol = max(0, vol - self.IR_VOLUME_STEP)
        if self.source_manager.set_volume(new_vol):
            self.mqtt_client.update_volume(new_vol)

    def _ir_mute_toggle(self):
        """
        Mute toggle: if current volume > 0, save it and set to 0; if
        already 0, restore the last non-zero value (default 30% if we
        have no memory).
        """
        cur = self.source_manager.get_current_source()
        if not cur:
            return
        vol = self.source_manager.get_source_volume(cur) or 0
        if vol > 0:
            self._ir_pre_mute_volume = vol
            target = 0
        else:
            target = getattr(self, '_ir_pre_mute_volume', 30)
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
        if self.source_manager.switch_source(nxt):
            self.mqtt_client.update_mode(nxt)

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

        # Initialize audio system
        self.source_manager.initialize_audio_system()

        # Start MQTT client (subscribes to control topics, publishes status)
        self.mqtt_client.start()

        # Start IR listener if the feature is enabled in saved state.
        # No-op + warning if disabled, so the daemon comes up cleanly
        # on devices without IR configured.
        self.ir_listener.start()

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
