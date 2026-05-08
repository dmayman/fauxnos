#!/usr/bin/env python3
"""
Fauxnos Client - Client-side audio source manager

Manages local audio sources with smart volume routing
"""

import argparse
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

        # Initialize MQTT client (connects to broker, routes commands through SourceManager)
        self.mqtt_client = MQTTClient(
            config_manager=self.config_manager,
            volume_callback=self.source_manager.set_volume,
            mode_callback=self.source_manager.switch_source,
            calibration_callback=self.source_manager.set_calibration,
            calibration_getter=self.source_manager.get_calibration,
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
        self.mqtt_client.stop()
        sys.exit(0)

    def run_daemon(self):
        """Run in daemon mode (background service)"""
        self.logger.info("Running in daemon mode")

        # Initialize audio system
        self.source_manager.initialize_audio_system()

        # Start MQTT client (subscribes to control topics, publishes status)
        self.mqtt_client.start()

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
