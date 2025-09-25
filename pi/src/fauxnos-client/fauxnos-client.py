#!/usr/bin/env python3
"""
Fauxnos Client - Main client application for multiroom audio

This is the main client daemon that runs on each Fauxnos device.
It handles:
- Volume monitoring from go-librespot
- Local audio source management
- MQTT communication with server
- PulseAudio control

TODO: Full implementation pending - this is a placeholder for service deployment
"""

import json
import sys
import time
import signal
from pathlib import Path

class FauxnosClient:
    def __init__(self):
        self.running = True
        self.config_file = Path.home() / "src" / "fauxnos-client" / "config.json"
        self.config = self.load_config()

    def load_config(self):
        """Load client configuration"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            else:
                print(f"Config file not found: {self.config_file}")
                return {}
        except Exception as e:
            print(f"Failed to load config: {e}")
            return {}

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\nReceived signal {signum}, shutting down...")
        self.running = False

    def run(self):
        """Main client loop"""
        print("Fauxnos Client starting...")
        print(f"Client ID: {self.config.get('client_id', 'Unknown')}")
        print(f"Display Name: {self.config.get('display_name', 'Unknown')}")

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Main loop
        while self.running:
            try:
                # TODO: Implement actual client functionality
                # - Volume monitoring
                # - MQTT communication
                # - Source switching
                # - PulseAudio management

                print("Client running... (placeholder)")
                time.sleep(30)

            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(5)

        print("Fauxnos Client stopped")

if __name__ == '__main__':
    client = FauxnosClient()
    client.run()