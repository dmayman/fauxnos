#!/usr/bin/env python3
"""
Fauxnos Client - Main client application for multiroom audio

This is the main client daemon that runs on each Fauxnos device.
It handles:
- Volume monitoring from go-librespot
- Local audio source management
- MQTT communication with server
- PulseAudio control
- Service cleanup and management

Usage:
  python3 fauxnos-client.py run          # Run the client daemon
  python3 fauxnos-client.py cleanup      # Clean up old services
  python3 fauxnos-client.py status       # Show client status
  python3 fauxnos-client.py restart      # Restart client services
"""

import json
import sys
import time
import signal
import argparse
import subprocess
import os
from pathlib import Path
from typing import List, Optional

class FauxnosClient:
    def __init__(self):
        self.running = True
        self.config_file = Path.home() / "src" / "fauxnos-client" / "config.json"
        self.config = self.load_config()

    def log(self, message: str, level: str = "INFO"):
        """Log with color coding"""
        colors = {
            "INFO": "\033[1;36m",    # Bright Cyan
            "SUCCESS": "\033[0;32m", # Green
            "WARNING": "\033[1;33m", # Yellow
            "ERROR": "\033[0;31m",   # Red
        }
        reset = "\033[0m"
        prefix = "🔧" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
        print(f"{colors.get(level, '')}{prefix} {message}{reset}")

    def load_config(self):
        """Load client configuration"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            else:
                self.log(f"Config file not found: {self.config_file}", "WARNING")
                return {}
        except Exception as e:
            self.log(f"Failed to load config: {e}", "ERROR")
            return {}

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.log(f"Received signal {signum}, shutting down...")
        self.running = False

    def cleanup_old_services(self, dry_run: bool = False) -> bool:
        """Clean up orphaned client services that don't match current client ID"""
        self.log("🧹 Cleaning up old client services")
        self.log("=" * 50)

        current_client_id = self.config.get('client_id')
        if not current_client_id:
            self.log("No client ID found in config - skipping cleanup", "WARNING")
            return False

        self.log(f"Current client ID: {current_client_id}")

        success = True

        # Service patterns to check
        service_patterns = [
            "snapclient-fauxnos",
            "fauxnos-client-fauxnos"
        ]

        for pattern in service_patterns:
            try:
                # Get list of matching services
                result = subprocess.run(
                    ["systemctl", "--user", "list-units", "--all", "--no-legend", f"{pattern}*.service"],
                    capture_output=True, text=True, check=False
                )

                if result.returncode != 0:
                    continue

                # Parse service names from output
                services_to_check = []
                for line in result.stdout.strip().split('\n'):
                    if line and pattern in line:
                        parts = line.split()
                        if parts:
                            service_name = parts[0]
                            services_to_check.append(service_name)

                # Check each service
                for service_name in services_to_check:
                    # Extract client ID from service name
                    if pattern == "snapclient-fauxnos":
                        client_id = service_name.replace("snapclient-", "").replace(".service", "")
                    else:  # fauxnos-client-fauxnos
                        client_id = service_name.replace("fauxnos-client-", "").replace(".service", "")

                    # Check if this is an old service (not matching current client ID)
                    if client_id != current_client_id:
                        self.log(f"Found orphaned service: {service_name}", "WARNING")

                        if dry_run:
                            self.log(f"  DRY RUN: Would stop and disable {service_name}")
                        else:
                            # Stop the service
                            stop_result = subprocess.run(
                                ["systemctl", "--user", "stop", service_name],
                                capture_output=True, check=False
                            )

                            # Disable the service
                            disable_result = subprocess.run(
                                ["systemctl", "--user", "disable", service_name],
                                capture_output=True, check=False
                            )

                            # Remove the service file
                            service_path = Path.home() / ".config" / "systemd" / "user" / service_name
                            if service_path.exists():
                                service_path.unlink()
                                self.log(f"  ✓ Removed {service_name}", "SUCCESS")
                            else:
                                self.log(f"  Service file not found: {service_path}", "WARNING")

            except Exception as e:
                self.log(f"Error cleaning up {pattern} services: {e}", "ERROR")
                success = False

        # Reload systemd daemon if we made changes
        if not dry_run:
            try:
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                self.log("Reloaded systemd daemon", "SUCCESS")
            except Exception as e:
                self.log(f"Failed to reload systemd: {e}", "WARNING")

        return success

    def show_status(self):
        """Show current client status and services"""
        self.log("📊 Fauxnos Client Status")
        self.log("=" * 50)

        # Show client info
        client_id = self.config.get('client_id', 'Unknown')
        display_name = self.config.get('display_name', 'Unknown')
        mac = self.config.get('mac_address', 'Unknown')

        self.log(f"Client ID: {client_id}")
        self.log(f"Display Name: {display_name}")
        self.log(f"MAC Address: {mac}")
        print()

        # Show service status
        self.log("Service Status:")

        if client_id != 'Unknown':
            services = [
                f"snapclient-{client_id}.service",
                f"fauxnos-client-{client_id}.service"
            ]

            for service in services:
                try:
                    result = subprocess.run(
                        ["systemctl", "--user", "is-active", service],
                        capture_output=True, text=True, check=False
                    )
                    status = result.stdout.strip()

                    if status == "active":
                        self.log(f"  {service}: ✅ {status}", "SUCCESS")
                    elif status == "inactive":
                        self.log(f"  {service}: ⏸️  {status}", "WARNING")
                    else:
                        self.log(f"  {service}: ❌ {status}", "ERROR")

                except Exception as e:
                    self.log(f"  {service}: ❓ Unable to check ({e})", "ERROR")

        # Check for orphaned services
        print()
        self.log("Checking for orphaned services...")

        patterns = ["snapclient-fauxnos*.service", "fauxnos-client-fauxnos*.service"]
        orphaned = []

        for pattern in patterns:
            try:
                result = subprocess.run(
                    ["ls", "-1", f"{Path.home()}/.config/systemd/user/{pattern}"],
                    shell=True, capture_output=True, text=True, check=False
                )

                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line:
                            service_name = Path(line).name
                            # Check if this is not the current client's service
                            if client_id not in service_name:
                                orphaned.append(service_name)
            except:
                pass

        if orphaned:
            self.log(f"Found {len(orphaned)} orphaned service(s):", "WARNING")
            for service in orphaned:
                print(f"  - {service}")
            print()
            self.log("Run 'python3 fauxnos-client.py cleanup' to remove them")
        else:
            self.log("No orphaned services found", "SUCCESS")

    def restart_services(self):
        """Restart client services"""
        self.log("🔄 Restarting Client Services")
        self.log("=" * 50)

        client_id = self.config.get('client_id')
        if not client_id:
            self.log("No client ID found in config", "ERROR")
            return False

        services = [
            f"snapclient-{client_id}.service",
            f"fauxnos-client-{client_id}.service"
        ]

        for service in services:
            self.log(f"Restarting {service}...")
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "restart", service],
                    capture_output=True, text=True, check=False
                )

                if result.returncode == 0:
                    self.log(f"  ✓ {service} restarted", "SUCCESS")
                else:
                    self.log(f"  ✗ Failed to restart {service}: {result.stderr}", "ERROR")

            except Exception as e:
                self.log(f"  ✗ Error restarting {service}: {e}", "ERROR")

        return True

    def run(self):
        """Main client loop"""
        self.log("Fauxnos Client starting...")
        self.log(f"Client ID: {self.config.get('client_id', 'Unknown')}")
        self.log(f"Display Name: {self.config.get('display_name', 'Unknown')}")

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Main loop
        while self.running:
            try:
                # TODO: Implement actual client functionality
                # - Volume monitoring from go-librespot
                # - MQTT communication
                # - Source switching
                # - PulseAudio management

                time.sleep(30)

            except Exception as e:
                self.log(f"Error in main loop: {e}", "ERROR")
                time.sleep(5)

        self.log("Fauxnos Client stopped")

def main():
    parser = argparse.ArgumentParser(
        description="Fauxnos Client - Multiroom Audio Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  run       Run the client daemon
  cleanup   Clean up orphaned services
  status    Show client status and services
  restart   Restart client services

Examples:
  python3 fauxnos-client.py run       # Run the daemon
  python3 fauxnos-client.py cleanup   # Remove old services
  python3 fauxnos-client.py status    # Check status
  python3 fauxnos-client.py restart   # Restart services
        """
    )

    parser.add_argument('command',
                       choices=['run', 'cleanup', 'status', 'restart'],
                       help='Command to execute')

    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes (cleanup only)')

    args = parser.parse_args()

    client = FauxnosClient()

    if args.command == 'run':
        client.run()
    elif args.command == 'cleanup':
        success = client.cleanup_old_services(dry_run=args.dry_run)
        if not args.dry_run:
            if success:
                client.log("✅ Cleanup completed successfully", "SUCCESS")
            else:
                client.log("❌ Some cleanup operations failed", "ERROR")
                sys.exit(1)
    elif args.command == 'status':
        client.show_status()
    elif args.command == 'restart':
        client.restart_services()

if __name__ == '__main__':
    main()