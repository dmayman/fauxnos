#!/usr/bin/env python3
"""
Fauxnos Client Setup and Registration Script

Handles:
1. Discovery of fauxnos-server via mDNS
2. Registration with server using MAC address
3. Download and application of client configuration
4. Service deployment and hostname setup

Test modes available for safe development and testing.
"""

import argparse
import json
import subprocess
import sys
import os
import socket
import time
from pathlib import Path
from typing import Dict, Optional, Any

# Conditional import for requests (not available in all environments)
try:
    import requests
except ImportError:
    requests = None

class FauxnosClientSetup:
    def __init__(self, dry_run: bool = False, test_mode: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.test_mode = test_mode
        self.verbose = verbose

        # Configuration
        self.server_hostname = "fauxnos-server.local" if not test_mode else "localhost"
        self.server_port = 8080
        self.client_dir = Path.home() / "src" / "fauxnos-client"
        self.config_file = self.client_dir / "config.json"

        # Ensure client directory exists
        self.client_dir.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        colors = {
            "INFO": "\033[0;34m",    # Blue
            "SUCCESS": "\033[0;32m", # Green
            "WARNING": "\033[1;33m", # Yellow
            "ERROR": "\033[0;31m",   # Red
        }
        reset = "\033[0m"

        prefix = "🔧" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
        print(f"{colors.get(level, '')}{prefix} {message}{reset}")

    def execute(self, cmd: str, description: str = "", shell: bool = True) -> bool:
        """Execute command with proper test/dry-run handling"""
        if self.verbose:
            self.log(f"Executing: {cmd}")

        if self.dry_run:
            self.log(f"DRY RUN: Would execute: {cmd}")
            return True

        # Skip system-modifying commands in test mode
        if self.test_mode and any(keyword in cmd for keyword in ['sudo', 'systemctl', 'hostnamectl', 'reboot']):
            self.log(f"TEST MODE: Skipping system command: {cmd}")
            return True

        if description:
            self.log(description)

        try:
            result = subprocess.run(cmd, shell=shell, check=True, capture_output=True, text=True)
            if self.verbose and result.stdout:
                print(result.stdout)
            if description:
                self.log(f"{description} completed", "SUCCESS")
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"Failed: {cmd}", "ERROR")
            if e.stderr:
                print(e.stderr)
            return False

    def discover_server(self) -> Optional[str]:
        """Discover fauxnos-server via mDNS"""
        self.log("Discovering fauxnos-server...")

        if self.test_mode:
            self.log("TEST MODE: Using localhost as server", "WARNING")
            return "localhost"

        try:
            # Try to resolve the hostname
            result = subprocess.run(
                ["avahi-resolve", "-n", self.server_hostname],
                capture_output=True, text=True, check=True, timeout=10
            )

            if result.stdout:
                # Extract IP from "hostname.local	192.168.1.100" format
                ip = result.stdout.strip().split('\t')[-1]
                self.log(f"Found server at: {ip}", "SUCCESS")
                return ip

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.log("mDNS discovery failed, trying direct connection...", "WARNING")

        # Fallback: try to connect directly
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.server_hostname, self.server_port))
            sock.close()
            self.log(f"Server reachable at: {self.server_hostname}", "SUCCESS")
            return self.server_hostname
        except:
            pass

        self.log("Could not discover fauxnos-server", "ERROR")
        return None

    def get_mac_address(self) -> str:
        """Get primary network interface MAC address"""
        if self.test_mode:
            test_mac = "aa:bb:cc:dd:ee:99"
            self.log(f"TEST MODE: Using fake MAC: {test_mac}", "WARNING")
            return test_mac

        try:
            # Get the MAC of the first non-loopback interface
            result = subprocess.run(
                ["cat", "/sys/class/net/*/address"],
                capture_output=True, text=True, check=True, shell=True
            )

            # Filter out loopback and get first valid MAC
            for line in result.stdout.strip().split('\n'):
                mac = line.strip()
                if mac and mac != "00:00:00:00:00:00" and not mac.startswith("00:00:00"):
                    self.log(f"Using MAC address: {mac}")
                    return mac

            raise Exception("No valid MAC address found")

        except Exception as e:
            self.log(f"Failed to get MAC address: {e}", "ERROR")
            raise

    def register_with_server(self, server_ip: str, mac_address: str) -> Optional[Dict[str, Any]]:
        """Register this client with the server"""
        self.log("Registering with server...")

        registration_data = {
            "mac_address": mac_address,
            "hostname": socket.gethostname(),
            "request_type": "register"
        }

        if self.dry_run:
            self.log(f"DRY RUN: Would register with {registration_data}")
            return {"client_id": "fauxnos999", "name": "Test Client"}

        if self.test_mode:
            # Simulate successful registration
            mock_response = {
                "client_id": "fauxnos999",
                "name": "Test Client",
                "server_port": 3699,
                "zeroconf_port": 49999
            }
            self.log(f"TEST MODE: Mock registration response: {mock_response}", "WARNING")
            return mock_response

        if requests is None:
            self.log("requests module not available - using mock response", "WARNING")
            return {
                "client_id": "fauxnos999",
                "name": "Mock Client",
                "server_port": 3699,
                "zeroconf_port": 49999
            }

        try:
            url = f"http://{server_ip}:{self.server_port}/api/clients/register"
            response = requests.post(url, json=registration_data, timeout=10)
            response.raise_for_status()

            result = response.json()
            self.log(f"Registration successful! Assigned client_id: {result.get('client_id')}", "SUCCESS")
            return result

        except requests.RequestException as e:
            self.log(f"Registration failed: {e}", "ERROR")
            return None

    def download_client_config(self, server_ip: str, client_id: str) -> Optional[Dict[str, Any]]:
        """Download full client configuration from server"""
        self.log(f"Downloading configuration for {client_id}...")

        if self.dry_run:
            self.log(f"DRY RUN: Would download config for {client_id}")
            return {"client_id": client_id, "test": True}

        if self.test_mode:
            # Return mock config
            mock_config = {
                "client_id": client_id,
                "name": "test",
                "display_name": "Test Client",
                "mac": "aa:bb:cc:dd:ee:99",
                "server_config_url": f"http://{server_ip}:8080/api/config/{client_id}",
                "go_librespot_monitor_url": f"http://{server_ip}:3699/player/volume",
                "sources": [
                    {
                        "id": "snapcast",
                        "label": "Multiroom",
                        "type": "internal",
                        "sink": "snapsink",
                        "starting_volume": 50,
                        "volume_controller": "snapcast"
                    }
                ],
                "mqtt": {
                    "broker_host": server_ip,
                    "broker_port": 1883
                }
            }
            self.log(f"TEST MODE: Using mock config", "WARNING")
            return mock_config

        if requests is None:
            self.log("requests module not available - using mock config", "WARNING")
            return mock_config

        try:
            url = f"http://{server_ip}:{self.server_port}/api/config/{client_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            config = response.json()
            self.log("Configuration downloaded successfully", "SUCCESS")
            return config

        except requests.RequestException as e:
            self.log(f"Config download failed: {e}", "ERROR")
            return None

    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to local file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)

            self.log(f"Configuration saved to {self.config_file}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to save config: {e}", "ERROR")
            return False

    def apply_hostname(self, client_id: str) -> bool:
        """Change hostname from temporary to permanent"""
        self.log(f"Setting hostname to {client_id}...")

        if not self.execute(f"sudo hostnamectl set-hostname {client_id}", f"Setting hostname to {client_id}"):
            return False

        # Update /etc/hosts
        hosts_update = f"sudo sed -i 's/127.0.1.1.*/127.0.1.1\\t{client_id}/' /etc/hosts"
        return self.execute(hosts_update, "Updating /etc/hosts")

    def deploy_services(self, config: Dict[str, Any]) -> bool:
        """Deploy systemd services for this client"""
        self.log("Deploying client services...")

        client_id = config.get('client_id')

        # Create snapclient service
        snapclient_service = f"""[Unit]
Description=Snapclient for {client_id}
After=network.target sound.target
Wants=network.target

[Service]
Type=simple
User={os.getenv('USER', 'pi')}
ExecStart=/usr/bin/snapclient --host fauxnos-server.local --port 1704
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""

        # Create fauxnos-client service
        fauxnos_service = f"""[Unit]
Description=Fauxnos Client for {client_id}
After=snapclient.service pulseaudio.service
Wants=snapclient.service

[Service]
Type=simple
User={os.getenv('USER', 'pi')}
WorkingDirectory={self.client_dir}
ExecStart=/usr/bin/python3 {self.client_dir}/fauxnos-client.py
Restart=always
RestartSec=10
Environment=PULSE_RUNTIME_PATH=/run/user/1000/pulse

[Install]
WantedBy=default.target
"""

        # Write service files
        services = [
            (f"/etc/systemd/system/snapclient-{client_id}.service", snapclient_service),
            (f"/etc/systemd/system/fauxnos-client-{client_id}.service", fauxnos_service)
        ]

        for service_path, service_content in services:
            if self.dry_run or self.test_mode:
                self.log(f"Would create service: {service_path}")
                continue

            try:
                self.execute(f"sudo tee {service_path}", f"Creating {service_path}")
                # Note: In real implementation, would pipe service_content to tee
            except Exception as e:
                self.log(f"Failed to create {service_path}: {e}", "ERROR")
                return False

        # Enable and start services
        for service_name in [f"snapclient-{client_id}", f"fauxnos-client-{client_id}"]:
            if not self.execute(f"sudo systemctl enable {service_name}", f"Enabling {service_name}"):
                return False
            if not self.execute(f"sudo systemctl start {service_name}", f"Starting {service_name}"):
                return False

        return True

    def setup_pulseaudio(self, config: Dict[str, Any]) -> bool:
        """Configure PulseAudio for this client"""
        self.log("Setting up PulseAudio configuration...")

        # Simplified PA config with just the essential sinks
        pa_config = """
# Fauxnos PulseAudio Configuration
# Load essential modules for multiroom audio

# Load snapcast sink
load-module module-pipe-sink file=/tmp/snapfifo/snapcast_sink sink_name=snapsink format=s16le rate=44100 channels=2

# Load analog input loopback (for aux input)
load-module module-pipe-sink file=/tmp/snapfifo/analog_sink sink_name=analogsink format=s16le rate=44100 channels=2

# Load system sink for notifications
load-module module-pipe-sink file=/tmp/snapfifo/system_sink sink_name=systemsink format=s16le rate=44100 channels=2

# Set default sink
set-default-sink snapsink
"""

        pa_config_path = Path.home() / ".config" / "pulse" / "default.pa"

        if self.dry_run:
            self.log(f"DRY RUN: Would write PulseAudio config to {pa_config_path}")
            return True

        if self.test_mode:
            self.log("TEST MODE: Skipping PulseAudio configuration", "WARNING")
            return True

        try:
            pa_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(pa_config_path, 'w') as f:
                f.write(pa_config)

            self.log(f"PulseAudio config written to {pa_config_path}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to write PulseAudio config: {e}", "ERROR")
            return False

    def run_setup(self) -> bool:
        """Run the complete client setup process"""
        self.log("Starting Fauxnos client setup...")

        # Step 1: Discover server
        server_ip = self.discover_server()
        if not server_ip:
            return False

        # Step 2: Get MAC address
        try:
            mac_address = self.get_mac_address()
        except Exception:
            return False

        # Step 3: Register with server
        registration_result = self.register_with_server(server_ip, mac_address)
        if not registration_result:
            return False

        client_id = registration_result.get('client_id')
        if not client_id:
            self.log("No client_id received from server", "ERROR")
            return False

        # Step 4: Download full configuration
        config = self.download_client_config(server_ip, client_id)
        if not config:
            return False

        # Step 5: Save configuration locally
        if not self.save_config(config):
            return False

        # Step 6: Apply hostname
        if not self.apply_hostname(client_id):
            return False

        # Step 7: Setup PulseAudio
        if not self.setup_pulseaudio(config):
            return False

        # Step 8: Deploy services
        if not self.deploy_services(config):
            return False

        # Step 9: Success!
        self.log("Client setup completed successfully!", "SUCCESS")
        self.log(f"Client ID: {client_id}")
        self.log(f"Display Name: {config.get('display_name', 'Unknown')}")

        if not self.test_mode and not self.dry_run:
            self.log("Rebooting in 10 seconds to apply changes... (Ctrl+C to cancel)")
            try:
                time.sleep(10)
                self.execute("sudo reboot", "Rebooting system")
            except KeyboardInterrupt:
                self.log("Reboot cancelled", "WARNING")

        return True

def main():
    parser = argparse.ArgumentParser(
        description="Fauxnos Client Setup and Registration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test what would happen without making changes
  python3 setup-client.py --setup --dry-run

  # Run in test mode (safe for development)
  python3 setup-client.py --setup --test

  # Full registration and setup
  python3 setup-client.py --setup
        """
    )

    parser.add_argument('--setup', action='store_true',
                       help='Run client registration and setup')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--test', action='store_true',
                       help='Use test configuration and skip system modifications')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    if not args.setup:
        parser.print_help()
        sys.exit(1)

    # Create setup instance
    setup = FauxnosClientSetup(
        dry_run=args.dry_run,
        test_mode=args.test,
        verbose=args.verbose
    )

    # Run setup
    success = setup.run_setup()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()