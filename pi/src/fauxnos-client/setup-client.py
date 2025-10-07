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

# Conditional imports for requests and yaml (not available in all environments)
try:
    import requests
except ImportError:
    requests = None

try:
    import yaml
except ImportError:
    yaml = None

class FauxnosClientSetup:
    def __init__(self, dry_run: bool = False, test_mode: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.test_mode = test_mode
        self.verbose = verbose

        # Configuration
        self.server_hostname = "fauxnos-server.local" if not test_mode else "localhost"
        self.server_port = 8080
        self.client_dir = Path.home() / "src" / "fauxnos-client"
        # Store config in user's home directory, not in the source tree
        self.config_file = Path.home() / ".config" / "fauxnos" / "config.yaml"

        # Ensure directories exist
        self.client_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        colors = {
            "INFO": "\033[1;36m",    # Bright Cyan (more visible than blue)
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

        except FileNotFoundError:
            self.log("avahi-resolve not found, trying direct connection...", "WARNING")
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

        # Final fallback: try localhost (for server-client on same machine)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("localhost", self.server_port))
            sock.close()
            self.log("Found server on localhost (same machine)", "SUCCESS")
            return "localhost"
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
            import os

            # Get all network interfaces except loopback
            found_macs = []
            for interface in sorted(os.listdir('/sys/class/net/')):
                if interface == 'lo':  # Skip loopback
                    continue

                address_file = f'/sys/class/net/{interface}/address'
                if os.path.exists(address_file):
                    try:
                        with open(address_file, 'r') as f:
                            mac = f.read().strip().lower()
                            found_macs.append(f"{interface}: {mac}")

                            # Basic MAC validation - just check it's not all zeros and has proper format
                            if (mac and
                                mac != "00:00:00:00:00:00" and
                                len(mac) == 17 and
                                ':' in mac):
                                self.log(f"Using MAC address from {interface}: {mac}")
                                return mac
                    except Exception as e:
                        if self.verbose:
                            self.log(f"Could not read MAC from {interface}: {e}")
                        continue

            # If we get here, log what we found for debugging
            self.log(f"Found MACs: {', '.join(found_macs)}")

            # If no MAC found, try the original method as fallback
            result = subprocess.run(
                ["cat", "/sys/class/net/*/address"],
                capture_output=True, text=True, check=False, shell=True
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    mac = line.strip().lower()
                    if (mac and
                        mac != "00:00:00:00:00:00" and
                        len(mac) == 17 and
                        ':' in mac):
                        self.log(f"Using MAC address: {mac}")
                        return mac

            raise Exception("No valid MAC address found")

        except Exception as e:
            self.log(f"Failed to get MAC address: {e}", "ERROR")
            raise

    def register_with_server(self, server_ip: str, mac_address: str, display_name: str) -> Optional[Dict[str, Any]]:
        """Register this client with the server"""
        self.log("Registering with server...")

        registration_data = {
            "mac_address": mac_address,
            "hostname": socket.gethostname(),
            "display_name": display_name,
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
            response = requests.post(url, json=registration_data, timeout=60)  # Increased timeout for interactive prompts
            response.raise_for_status()

            result = response.json()
            self.log(f"Registration successful! Assigned client_id: {result.get('client_id')}", "SUCCESS")
            return result

        except requests.RequestException as e:
            self.log(f"Registration failed: {e}", "ERROR")
            return None

    def initialize_config_from_template(self) -> bool:
        """Copy template config to proper location if it doesn't exist"""
        if self.config_file.exists():
            self.log("Config file already exists, skipping template copy")
            return True

        # Find template config
        template_path = self.client_dir / "config.yaml"
        if not template_path.exists():
            self.log(f"Template config not found: {template_path}", "ERROR")
            self.log("Make sure you've downloaded the complete fauxnos-client directory")
            return False

        try:
            # Copy template to proper location
            if self.dry_run:
                self.log(f"DRY RUN: Would copy {template_path} to {self.config_file}")
                return True

            self.log(f"Copying template config from {template_path}")
            with open(template_path, 'r') as src:
                template_content = src.read()

            with open(self.config_file, 'w') as dst:
                dst.write(template_content)

            self.log(f"Template config copied to {self.config_file}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to copy template config: {e}", "ERROR")
            return False

    def load_local_config(self) -> Optional[Dict[str, Any]]:
        """Load the local YAML configuration file"""
        if yaml is None:
            self.log("PyYAML not available - cannot load config", "ERROR")
            return None

        if not self.config_file.exists():
            self.log(f"Config file not found: {self.config_file}", "ERROR")
            return None

        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
            self.log("Local config loaded successfully")
            return config
        except yaml.YAMLError as e:
            self.log(f"Failed to load YAML config: {e}", "ERROR")
            return None
        except Exception as e:
            self.log(f"Failed to load config: {e}", "ERROR")
            return None

    def update_local_config(self, client_id: str, display_name: str, mac_address: str,
                           server_info: Dict[str, Any]) -> bool:
        """Update the local YAML config with registration info"""
        self.log("Updating local configuration...")

        # Load current config
        config = self.load_local_config()
        if not config:
            return False

        if self.dry_run:
            self.log(f"DRY RUN: Would update config with {client_id}, {display_name}")
            return True

        try:
            # Fill in the registration info
            config['client_id'] = client_id
            config['display_name'] = display_name
            config['mac'] = mac_address

            # Update server connection info from registration response
            if 'server_port' in server_info:
                config['go_librespot_monitor_url'] = f"http://{self.server_hostname}:{server_info['server_port']}/player/volume"

            return self.save_config(config)

        except Exception as e:
            self.log(f"Failed to update config: {e}", "ERROR")
            return False

    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to local YAML file"""
        if yaml is None:
            self.log("PyYAML not available - cannot save config", "ERROR")
            return False

        try:
            with open(self.config_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, indent=2)

            self.log(f"Configuration saved to {self.config_file}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to save config: {e}", "ERROR")
            return False

    def apply_hostname(self, client_id: str) -> bool:
        """Change hostname from temporary to permanent"""

        # Check if we're on the server machine
        current_hostname = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
        if current_hostname == "fauxnos-server" and not getattr(self, 'force_hostname', False):
            self.log("Detected server machine - skipping hostname change to preserve 'fauxnos-server'", "WARNING")
            self.log("This client will use the server hostname but operate as a client", "INFO")
            self.log("Use --force-hostname to override this behavior if needed", "INFO")
            return True

        self.log(f"Setting hostname to {client_id}...")

        if not self.execute(f"sudo hostnamectl set-hostname {client_id}", f"Setting hostname to {client_id}"):
            return False

        # Update /etc/hosts
        hosts_update = f"sudo sed -i 's/127.0.1.1.*/127.0.1.1\\t{client_id}/' /etc/hosts"
        return self.execute(hosts_update, "Updating /etc/hosts")

    def deploy_services(self, config: Dict[str, Any]) -> bool:
        """Deploy systemd user services for this client"""
        self.log("Deploying client user services...")

        client_id = config.get('client_id')
        user = os.getenv('USER', 'pi')

        if self.dry_run or self.test_mode:
            self.log(f"Would create user services for {client_id}")
            return True

        try:
            # Ensure user systemd directory exists
            user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
            user_systemd_dir.mkdir(parents=True, exist_ok=True)

            # Load and customize service templates
            service_templates = [
                ("snapclient.service", f"snapclient-{client_id}.service"),
                ("fauxnos-client.service", f"fauxnos-client-{client_id}.service")
            ]

            for template_name, service_name in service_templates:
                # Read template file
                template_path = self.client_dir / "configs" / "systemd" / template_name
                if not template_path.exists():
                    self.log(f"Service template not found: {template_path}", "ERROR")
                    return False

                with open(template_path, 'r') as f:
                    service_content = f.read()

                # Replace template variables
                service_content = service_content.replace('{CLIENT_ID}', client_id)
                service_content = service_content.replace('{USER}', user)
                service_content = service_content.replace('{CLIENT_DIR}', str(self.client_dir))

                # Write to user systemd directory (no sudo needed!)
                service_path = user_systemd_dir / service_name
                with open(service_path, 'w') as f:
                    f.write(service_content)

                self.log(f"Created user service: {service_path}", "SUCCESS")

            # Enable user lingering for automatic startup on boot
            if not self.execute("sudo loginctl enable-linger $USER", "Enabling user lingering for automatic service startup"):
                return False

            # Reload user daemon
            if not self.execute("systemctl --user daemon-reload", "Reloading user systemd daemon"):
                return False

            # Enable and start user services
            for _, service_name in service_templates:
                service_name_without_extension = service_name.replace('.service', '')
                if not self.execute(f"systemctl --user enable {service_name}", f"Enabling user service {service_name_without_extension}"):
                    return False
                if not self.execute(f"systemctl --user start {service_name}", f"Starting user service {service_name_without_extension}"):
                    return False

            return True

        except Exception as e:
            self.log(f"Failed to deploy user services: {e}", "ERROR")
            return False

    def setup_pulseaudio(self, config: Dict[str, Any]) -> bool:
        """Configure PulseAudio for this client"""
        self.log("Setting up PulseAudio configuration...")

        if self.dry_run:
            self.log("DRY RUN: Would copy PulseAudio config")
            return True

        if self.test_mode:
            self.log("TEST MODE: Skipping PulseAudio configuration", "WARNING")
            return True

        try:
            # Copy the PulseAudio config from downloaded files
            source_path = self.client_dir / "configs" / "pulseaudio" / "default.pa"
            target_path = Path.home() / ".config" / "pulse" / "default.pa"

            if not source_path.exists():
                self.log(f"PulseAudio config not found at {source_path}", "ERROR")
                return False

            # Create target directory
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Copy config file
            import shutil
            shutil.copy2(source_path, target_path)

            self.log(f"PulseAudio config copied to {target_path}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to setup PulseAudio config: {e}", "ERROR")
            return False

    def run_setup(self) -> bool:
        """Run the complete client setup process"""
        self.log("Starting Fauxnos client setup...")

        # Step 1: Initialize config from template
        if not self.initialize_config_from_template():
            return False

        # Step 2: Get user input for display name
        if not self.test_mode and not self.dry_run:
            print(f"\n🔧 Setting up new Fauxnos client")
            display_name = input("Enter display name for this client (e.g., 'Kitchen', 'Living Room'): ").strip()
            if not display_name:
                display_name = "Fauxnos Client"
                print(f"Using default name: {display_name}")
        else:
            display_name = "Test Client"
            self.log(f"TEST MODE: Using display name '{display_name}'", "WARNING")

        # Step 3: Discover server
        server_ip = self.discover_server()
        if not server_ip:
            return False

        # Step 4: Get MAC address
        try:
            mac_address = self.get_mac_address()
        except Exception:
            return False

        # Step 5: Register with server
        registration_result = self.register_with_server(server_ip, mac_address, display_name)
        if not registration_result:
            return False

        client_id = registration_result.get('client_id')
        if not client_id:
            self.log("No client_id received from server", "ERROR")
            return False

        # Step 6: Update local configuration with registration info
        if not self.update_local_config(client_id, display_name, mac_address, registration_result):
            return False

        # Step 7: Apply hostname
        if not self.apply_hostname(client_id):
            return False

        # Step 8: Setup PulseAudio
        config = self.load_local_config()
        if not config:
            return False

        if not self.setup_pulseaudio(config):
            return False

        # Step 9: Deploy services
        if not self.deploy_services(config):
            return False

        # Step 10: Success!
        self.log("Client setup completed successfully!", "SUCCESS")
        self.log(f"Client ID: {client_id}")
        self.log(f"Display Name: {display_name}")
        self.log(f"Config file: {self.config_file}")
        self.log(f"Sources configured: {len(config.get('sources', []))}")


        if not self.test_mode and not self.dry_run:
            self.log("Rebooting in 10 seconds to apply changes... (Ctrl+C to cancel)")
            try:
                time.sleep(10)
                self.execute("sudo reboot", "Rebooting system")
            except KeyboardInterrupt:
                self.log("Reboot cancelled", "WARNING")

        return True


def show_client_config(verbose: bool = False):
    """Show current client configuration in readable format"""
    print("⚙️  Fauxnos Client Configuration")
    print("=" * 40)

    # Check if client config exists
    config_file = Path.home() / ".config" / "fauxnos" / "config.yaml"
    if not config_file.exists():
        print("❌ No client configuration found")
        print(f"   Expected location: {config_file}")
        print("   Run 'python3 setup-client.py --setup' to configure this client")
        return

    try:
        import yaml
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

        # Basic client info
        print(f"📍 Client ID: {config.get('client_id', 'Not set')}")
        print(f"🏷️  Display Name: {config.get('display_name', 'Not set')}")
        print(f"🌐 MAC Address: {config.get('mac_address', 'Not set')}")

        # Server connection
        server_config = config.get('server', {})
        print(f"\n🔗 Server Connection:")
        print(f"   Host: {server_config.get('host', 'Not set')}")
        print(f"   Port: {server_config.get('port', 'Not set')}")

        # Snapcast configuration
        snapcast_config = config.get('snapcast', {})
        print(f"\n🔊 Snapcast Configuration:")
        print(f"   Server: {snapcast_config.get('server', 'Not set')}")
        print(f"   Port: {snapcast_config.get('port', 'Not set')}")

        # Go-Librespot configuration
        librespot_config = config.get('go_librespot', {})
        print(f"\n🎵 Go-Librespot Configuration:")
        print(f"   Monitor URL: {librespot_config.get('monitor_url', 'Not set')}")

        # Audio configuration
        audio_config = config.get('audio', {})
        if audio_config:
            print(f"\n🔉 Audio Configuration:")
            for key, value in audio_config.items():
                print(f"   {key.replace('_', ' ').title()}: {value}")

        # Service status
        print(f"\n⚙️  Services:")
        client_id = config.get('client_id', 'unknown')
        services = [
            f"snapclient-{client_id}",
            f"fauxnos-client-{client_id}"
        ]

        import subprocess
        for service in services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=5
                )
                status = result.stdout.strip()
                if status == "active":
                    print(f"   ✅ {service}: Running")
                elif status == "inactive":
                    print(f"   ⭕ {service}: Stopped")
                else:
                    print(f"   ❓ {service}: {status}")
            except:
                print(f"   ❌ {service}: Unknown")

        # File locations
        if verbose:
            print(f"\n📁 Configuration Files:")
            print(f"   Client Config: {config_file}")
            print(f"   Systemd Services: ~/.config/systemd/user/")
            print(f"   PulseAudio Config: ~/.config/pulse/")

    except Exception as e:
        print(f"❌ Error reading configuration: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Fauxnos Client Setup and Registration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current client configuration
  python3 setup-client.py --config

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
    parser.add_argument('--config', action='store_true',
                       help='Show current client configuration')
    parser.add_argument('--force-hostname', action='store_true',
                       help='Force hostname change even on server machine')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--test', action='store_true',
                       help='Use test configuration and skip system modifications')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')

    args = parser.parse_args()

    if args.config:
        show_client_config(args.verbose)
        sys.exit(0)

    if not args.setup:
        parser.print_help()
        sys.exit(1)

    # Create setup instance
    setup = FauxnosClientSetup(
        dry_run=args.dry_run,
        test_mode=args.test,
        verbose=args.verbose
    )
    setup.force_hostname = args.force_hostname

    # Run setup
    success = setup.run_setup()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()