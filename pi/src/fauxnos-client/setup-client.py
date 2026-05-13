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

        # Configuration — prefer env var (set by firstrun.sh), then fauxnos000.local
        if test_mode:
            self.server_hostname = "localhost"
        else:
            self.server_hostname = os.environ.get("FAUXNOS_SERVER_HOST", "fauxnos000.local")
        self.server_port = 8080
        self.client_dir = Path.home() / "src" / "fauxnos-client"
        # Store config in user's home directory, not in the source tree
        self.config_file = Path.home() / ".config" / "fauxnos" / "client_config.yaml"

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

        # Detect hardware capabilities
        aplay_output = ''
        try:
            aplay_result = subprocess.run(['aplay', '-l'], capture_output=True, text=True, timeout=5)
            aplay_output = aplay_result.stdout
        except Exception:
            pass

        registration_data = {
            "mac_address": mac_address,
            "hostname": socket.gethostname(),
            "display_name": display_name,
            "request_type": "register",
            "aplay_output": aplay_output,
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

    # Per-source fields whose source-of-truth is the template, not the
    # user. When the template changes any of these (e.g. spotify-volume-
    # sync flipped `volume_controller` from snapcast→go_librespot;
    # AirPlay local-per-device flipped `sink` from snapsink→airplaysink
    # and added `on_leave_command`), `migrate_config_from_template`
    # rewrites the matching field on the user's existing config without
    # touching user-tunable fields (label, starting_volume,
    # pa_calibration) or unrelated sources.
    #
    # Adding a new schema field that needs migration: extend this set,
    # nothing else.
    _SOURCE_SCHEMA_FIELDS = frozenset({
        "volume_controller", "sink", "type", "on_leave_command",
    })

    def initialize_config_from_template(self) -> bool:
        """Copy template config to proper location if it doesn't exist"""
        if self.config_file.exists():
            self.log("Config file already exists, skipping template copy")
            return True

        # Find template config (try new location first, fall back to old)
        template_path = self.client_dir / "client_config.yaml.template"
        if not template_path.exists():
            # Try old location for backward compatibility
            template_path = self.client_dir / "configs" / "config.yaml.template"

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

    def migrate_config_from_template(self) -> bool:
        """Bring an existing client_config.yaml up to date with the
        template's source schema.

        Why this exists:
        `initialize_config_from_template` only seeds a config if none
        exists, so it never touches an already-provisioned device. But
        the template evolves — spotify-volume-sync flipped spotify's
        volume_controller (snapcast → go_librespot); the AirPlay local-
        per-device rewrite changed airplay's sink (snapsink →
        airplaysink), flipped volume_controller (snapcast → external),
        and added on_leave_command. Without a migration step, install.sh
        updates the *code* on existing clients but leaves them with
        broken source wiring forever. (Surfaced 2026-05-12 when
        fauxnos001 came back from its first pipeline-updated install
        with phone-slider→snapcast bridge dead.)

        What this DOESN'T touch (user-tunable):
            label, starting_volume, pa_calibration, custom sources
            (any source with an id not in the template), top-level
            keys (display_name, mac, client_id, mqtt, etc.).

        What this DOES touch (per _SOURCE_SCHEMA_FIELDS):
            volume_controller, sink, type, on_leave_command — the
            technical wiring that's part of the platform schema, not a
            user choice.

        Sources present in template but missing on the user's config
        get appended wholesale (new built-in sources land cleanly).
        Sources only on the user's config (custom sources) stay
        untouched.

        Idempotent: re-running when the config already matches is a
        no-op.

        Returns True unless we fail catastrophically writing the file.
        Other failures (no PyYAML, no template, parse errors) log a
        warning and return True so install.sh doesn't abort over them —
        this is a hygiene step, not a blocker.
        """
        if yaml is None:
            self.log("PyYAML not available — skipping schema migration", "WARNING")
            return True
        if not self.config_file.exists():
            # initialize_config_from_template handled the seed earlier
            # in run_setup. Nothing to migrate against.
            return True
        template_path = self.client_dir / "client_config.yaml.template"
        if not template_path.exists():
            self.log(f"Template missing at {template_path} — skipping schema migration", "WARNING")
            return True
        try:
            with open(self.config_file) as f:
                existing = yaml.safe_load(f) or {}
            with open(template_path) as f:
                template = yaml.safe_load(f) or {}
        except Exception as e:
            self.log(f"Failed to load configs for schema migration: {e}", "WARNING")
            return True

        existing_sources = existing.get("sources") or []
        template_sources = template.get("sources") or []
        if not isinstance(existing_sources, list) or not isinstance(template_sources, list):
            self.log("Unexpected `sources` shape in config — skipping schema migration", "WARNING")
            return True

        existing_by_id = {
            s.get("id"): s
            for s in existing_sources
            if isinstance(s, dict) and s.get("id")
        }
        changed = False
        for tmpl_src in template_sources:
            if not isinstance(tmpl_src, dict):
                continue
            sid = tmpl_src.get("id")
            if not sid:
                continue
            existing_src = existing_by_id.get(sid)
            if existing_src is None:
                # New built-in source landed in the template. Append it
                # wholesale; preserves user's earlier source ordering
                # (new source goes at the end).
                existing_sources.append(dict(tmpl_src))
                existing_by_id[sid] = existing_sources[-1]
                self.log(f"Migration: added new source '{sid}' from template")
                changed = True
                continue

            # Existing source — diff the schema fields against the
            # template and rewrite where they disagree. Removing a
            # schema field from the template also removes it here
            # (keeps the schema authoritative).
            for field in self._SOURCE_SCHEMA_FIELDS:
                template_has = field in tmpl_src
                existing_has = field in existing_src
                if template_has:
                    if existing_src.get(field) != tmpl_src[field]:
                        prev = existing_src.get(field, "<absent>")
                        existing_src[field] = tmpl_src[field]
                        self.log(
                            f"Migration: source '{sid}' {field}: {prev!r} → {tmpl_src[field]!r}"
                        )
                        changed = True
                elif existing_has:
                    existing_src.pop(field, None)
                    self.log(
                        f"Migration: source '{sid}' removed field '{field}' (no longer in template)"
                    )
                    changed = True

        if not changed:
            self.log("Schema migration: no changes needed")
            return True
        existing["sources"] = existing_sources
        try:
            with open(self.config_file, "w") as f:
                yaml.dump(existing, f, default_flow_style=False)
            self.log("Schema migration: client_config.yaml updated", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Schema migration: failed to write {self.config_file}: {e}", "ERROR")
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
            # Fill in the registration info — update both top-level keys
            # and the device section (which config_manager.py reads from)
            config['client_id'] = client_id
            config['display_name'] = display_name
            config['mac'] = mac_address

            # Update the device section that config_manager parses
            if 'device' not in config or not isinstance(config['device'], dict):
                config['device'] = {}
            config['device']['name'] = client_id
            config['device']['mac'] = mac_address
            config['device']['display_name'] = display_name

            # Update server host if different
            config['server_host'] = self.server_hostname
            config['api_port'] = self.server_port

            # Update server connection info from registration response
            if 'server_port' in server_info:
                config['go_librespot_monitor_url'] = f"http://{self.server_hostname}:{server_info['server_port']}/player/volume"

            # Update sound file paths to use absolute paths
            if 'sounds' in config:
                for sound_key in config['sounds']:
                    if config['sounds'][sound_key].startswith('~/'):
                        # Replace ~/ with actual home path
                        config['sounds'][sound_key] = str(Path.home() / config['sounds'][sound_key][2:])

            # Log what we're updating
            self.log(f"  Client ID: {client_id}")
            self.log(f"  Display Name: {display_name}")
            self.log(f"  MAC Address: {mac_address}")
            self.log(f"  Server: {self.server_hostname}:{self.server_port}")
            if 'server_port' in server_info:
                self.log(f"  Go-librespot Monitor Port: {server_info['server_port']}")

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
        if current_hostname in ["fauxnos-server", "fauxnos000"] and not getattr(self, 'force_hostname', False):
            # If client_id is fauxnos000, allow hostname change to maintain consistency
            if client_id == "fauxnos000":
                self.log("Server machine assigned fauxnos000 - updating hostname for consistency")
            else:
                self.log(f"Detected server machine ({current_hostname}) but assigned different client ID ({client_id})", "WARNING")
                self.log("This may cause hostname/client ID mismatch", "WARNING")
                self.log("Use --force-hostname to override this behavior if needed", "INFO")
                return True

        self.log(f"Setting hostname to {client_id}...")

        if not self.execute(f"sudo hostnamectl set-hostname {client_id}", f"Setting hostname to {client_id}"):
            return False

        # Update /etc/hosts
        hosts_update = f"sudo sed -i 's/127.0.1.1.*/127.0.1.1\\t{client_id}/' /etc/hosts"
        if not self.execute(hosts_update, "Updating /etc/hosts"):
            return False

        # Configure cloud-init to not reset hostname on reboot (Debian Trixie/cloud-init OSes)
        self.execute(
            "sudo sed -i 's/^preserve_hostname:.*/preserve_hostname: true/' /etc/cloud/cloud.cfg",
            "Configuring cloud-init to preserve hostname"
        )
        return True

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

            # Enable + (re)start user services. `restart` rather than
            # `start` for the same reason setup_shairport uses it: this
            # path runs on BOTH fresh-installs (service not yet running
            # → restart is equivalent to start) and update re-runs
            # (service already running with stale on-disk config →
            # restart forces a reload). A bare `start` was the
            # 2026-05-12 bug on fauxnos001: setup-client rewrote
            # client_config.yaml with the new spotify-volume-sync /
            # AirPlay schema (volume_controller, on_leave_command, …),
            # then `start` no-op'd against the long-running daemon, so
            # auto-source-switch, phone-slider sync, and AirPlay
            # disconnect-on-leave all silently kept using stale config.
            for _, service_name in service_templates:
                service_name_without_extension = service_name.replace('.service', '')
                if not self.execute(f"systemctl --user enable {service_name}", f"Enabling user service {service_name_without_extension}"):
                    return False
                if not self.execute(f"systemctl --user restart {service_name}", f"(Re)starting user service {service_name_without_extension}"):
                    return False

            return True

        except Exception as e:
            self.log(f"Failed to deploy user services: {e}", "ERROR")
            return False

    def setup_shairport(self, display_name: str, mqtt_broker_host: str) -> bool:
        """Install the shairport-sync user unit + config so this client
        is reachable as an AirPlay receiver. shairport-sync itself is
        installed via apt in install.sh — here we only place the conf,
        the sessioncontrol claim-source.sh hook, and the user-systemd
        unit, then enable + start the service.

        Idempotent: a re-install can copy fresh copies over existing
        files. The unit is device-agnostic; two files get placeholder
        substitution so one repo template serves every device:

          * fauxnos.conf: __FAUXNOS_NAME__ → display_name, so the
            AirPlay picker shows e.g. "Server" / "Kitchen" / "Garage"
            instead of the (capitalized-by-iOS) hostname.
          * claim-source.sh: __FAUXNOS_MQTT_HOST__ → mqtt_broker_host,
            so the sessioncontrol hook publishes to the actual broker
            (which only runs on the server). Hardcoding `localhost`
            here was the 2026-05-12 auto-switch bug on fauxnos001.

        Both `display_name` and `mqtt_broker_host` are passed through
        from run_setup so fresh-install and update re-runs share one
        source of truth (client_config.yaml).
        """
        self.log("Setting up shairport-sync (AirPlay receiver)...")

        if self.dry_run or self.test_mode:
            self.log(f"Would install shairport-sync config + unit (name='{display_name}')")
            return True

        try:
            # 1. Copy claim-source.sh + render fauxnos.conf into ~/.config/shairport-sync/
            shairport_user_dir = Path.home() / ".config" / "shairport-sync"
            shairport_user_dir.mkdir(parents=True, exist_ok=True)

            src_conf = self.client_dir / "configs" / "shairport-sync" / "fauxnos.conf"
            src_hook = self.client_dir / "configs" / "shairport-sync" / "claim-source.sh"
            if not src_conf.exists() or not src_hook.exists():
                self.log(
                    f"shairport-sync configs not found at {src_conf.parent} — "
                    f"the install.sh asset list may be out of date", "ERROR"
                )
                return False

            # Render fauxnos.conf with the device's display_name. Escape
            # double-quotes and backslashes so a display_name like
            # 'Bedroom "Closet"' or 'C:\Path' can't break out of the
            # shairport string literal. Newlines are stripped too — they
            # would otherwise corrupt the conf parser.
            conf_template = src_conf.read_text(encoding="utf-8")
            safe_name = (
                display_name.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ").strip()
            ) or "Fauxnos"
            rendered = conf_template.replace("__FAUXNOS_NAME__", safe_name)
            (shairport_user_dir / "fauxnos.conf").write_text(rendered, encoding="utf-8")

            import shutil  # used for the user-systemd unit copy below

            # Render claim-source.sh with the MQTT broker host. Fall
            # back to fauxnos000.local if the caller passed nothing —
            # the conventional server hostname — but in practice
            # run_setup always supplies it from client_config.yaml.
            safe_broker = (mqtt_broker_host or "fauxnos000.local").strip() or "fauxnos000.local"
            hook_template = src_hook.read_text(encoding="utf-8")
            hook_rendered = hook_template.replace("__FAUXNOS_MQTT_HOST__", safe_broker)
            hook_dest = shairport_user_dir / "claim-source.sh"
            hook_dest.write_text(hook_rendered, encoding="utf-8")
            hook_dest.chmod(0o755)
            self.log(
                f"shairport-sync configs deployed to {shairport_user_dir} "
                f"(name='{safe_name}', mqtt_host='{safe_broker}')"
            )

            # 2. Install the user systemd unit. The unit references %h
            # (= the user's home dir as seen by systemd-user), so no
            # template substitution is needed — same file works for
            # every user account.
            user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
            user_systemd_dir.mkdir(parents=True, exist_ok=True)
            unit_src = self.client_dir / "configs" / "systemd" / "shairport-sync-fauxnos.service"
            if not unit_src.exists():
                self.log(f"shairport unit template missing: {unit_src}", "ERROR")
                return False
            shutil.copy(unit_src, user_systemd_dir / "shairport-sync-fauxnos.service")

            # 3. Enable + (re)start. We use `restart` rather than `start`
            # because update re-runs hit this path against an
            # already-running service: install.sh disabled the
            # competing system shairport (freeing port 5000), which
            # lets our user service auto-recover from its
            # port-collision restart loop *before* setup-client.py
            # has rewritten the conf. A bare `start` is a no-op there
            # and the process keeps using the stale on-disk conf —
            # exactly the bug that left fauxnos001/002 advertising as
            # "fauxnos001"/"fauxnos002" instead of Kitchen/Garage on
            # the 2026-05-13 update push. `restart` covers both
            # fresh-install (service not yet running → equivalent to
            # start) and update (already running → reload conf).
            # (Lingering was already enabled by deploy_services.)
            self.execute(
                "systemctl --user daemon-reload",
                "Reloading user systemd daemon for shairport unit",
            )
            if not self.execute(
                "systemctl --user enable shairport-sync-fauxnos.service",
                "Enabling shairport-sync-fauxnos user service",
            ):
                return False
            if not self.execute(
                "systemctl --user restart shairport-sync-fauxnos.service",
                "(Re)starting shairport-sync-fauxnos user service to pick up new conf",
            ):
                return False

            return True

        except Exception as e:
            self.log(f"shairport-sync setup failed: {e}", "ERROR")
            return False

    def setup_alsa_config(self) -> bool:
        """Configure ALSA to route through PulseAudio"""
        self.log("Setting up ALSA configuration...")

        if self.dry_run:
            self.log("DRY RUN: Would create /etc/asound.conf")
            return True

        if self.test_mode:
            self.log("TEST MODE: Skipping ALSA configuration", "WARNING")
            return True

        try:
            # Create /etc/asound.conf to route ALSA through PulseAudio
            asound_conf_content = """# Route ALSA applications through PulseAudio
pcm.!default {
  type pulse
}

ctl.!default {
  type pulse
}
"""
            # Write to /etc/asound.conf (requires sudo)
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                tmp.write(asound_conf_content)
                tmp_path = tmp.name

            # Copy to /etc/asound.conf with sudo
            result = subprocess.run(
                f"sudo cp {tmp_path} /etc/asound.conf",
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )

            # Clean up temp file
            subprocess.run(f"rm {tmp_path}", shell=True)

            self.log("ALSA config created at /etc/asound.conf", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Failed to setup ALSA config: {e}", "ERROR")
            return False

    def install_dependencies(self) -> bool:
        """Install Python dependencies from requirements.txt"""
        self.log("Installing Python dependencies...")

        if self.dry_run:
            self.log("DRY RUN: Would install Python dependencies")
            return True

        if self.test_mode:
            self.log("TEST MODE: Skipping dependency installation", "WARNING")
            return True

        requirements_file = self.client_dir / "requirements.txt"
        if not requirements_file.exists():
            self.log(f"Requirements file not found: {requirements_file}", "ERROR")
            return False

        # Install dependencies with --break-system-packages flag for Raspberry Pi OS
        cmd = f"pip3 install -r {requirements_file} --break-system-packages"
        return self.execute(cmd, "Installing Python dependencies")

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

        # Step 1: Install Python dependencies
        if not self.install_dependencies():
            return False

        # Step 2: Initialize config from template (no-op if exists)
        if not self.initialize_config_from_template():
            return False

        # Step 2b: Migrate any drift between existing config's source
        # schema fields and the current template. This is where update
        # pipeline runs against already-provisioned devices catch up
        # to e.g. spotify-volume-sync's controller flip or AirPlay's
        # sink/on_leave_command rewrite. Idempotent.
        if not self.migrate_config_from_template():
            return False

        # Step 3: Get display name (from CLI arg, env var, or interactive prompt)
        if getattr(self, 'display_name', ''):
            display_name = self.display_name
            self.log(f"Using display name: {display_name}")
        elif not self.test_mode and not self.dry_run:
            print(f"\n🔧 Setting up new Fauxnos client")
            display_name = input("Enter display name for this client (e.g., 'Kitchen', 'Living Room'): ").strip()
            if not display_name:
                display_name = "Fauxnos Client"
                print(f"Using default name: {display_name}")
        else:
            display_name = "Test Client"
            self.log(f"TEST MODE: Using display name '{display_name}'", "WARNING")

        # Step 4: Discover server
        server_ip = self.discover_server()
        if not server_ip:
            return False

        # Step 5: Get MAC address
        try:
            mac_address = self.get_mac_address()
        except Exception:
            return False

        # Step 6: Register with server
        registration_result = self.register_with_server(server_ip, mac_address, display_name)
        if not registration_result:
            return False

        client_id = registration_result.get('client_id')
        if not client_id:
            self.log("No client_id received from server", "ERROR")
            return False

        # Step 7: Update local configuration with registration info
        if not self.update_local_config(client_id, display_name, mac_address, registration_result):
            return False

        # Step 8: Apply hostname
        if not self.apply_hostname(client_id):
            return False

        # Step 9: Setup PulseAudio
        config = self.load_local_config()
        if not config:
            return False

        if not self.setup_pulseaudio(config):
            return False

        # Step 10: Setup ALSA to route through PulseAudio
        if not self.setup_alsa_config():
            return False

        # Step 11: Deploy services
        if not self.deploy_services(config):
            return False

        # Step 12: Deploy shairport-sync (AirPlay receiver). Treated
        # as a default capability — every fauxnos device is an AirPlay
        # target out of the box. The display_name passed here ends up
        # as the mDNS name in the iOS AirPlay picker; the MQTT broker
        # host is templated into the sessioncontrol claim-source.sh
        # hook so it auto-switches the active source on iPhone connect.
        mqtt_broker_host = (config.get("mqtt") or {}).get("broker_host") or "fauxnos000.local"
        if not self.setup_shairport(display_name, mqtt_broker_host):
            self.log("shairport-sync setup failed — AirPlay won't work on this device, "
                     "but the rest of the install will continue", "WARNING")

        # Step 13: Success!
        self.log("Client setup completed successfully!", "SUCCESS")
        self.log(f"Client ID: {client_id}")
        self.log(f"Display Name: {display_name}")
        self.log(f"Config file: {self.config_file}")
        self.log(f"Sources configured: {len(config.get('sources', []))}")


        # install.sh owns the final reboot. When run standalone, callers can
        # either reboot themselves or pass --no-reboot to skip. Default keeps
        # backwards-compat for direct invocations of setup-client.py.
        if (not self.test_mode and not self.dry_run
                and not getattr(self, 'no_reboot', False)):
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
    parser.add_argument('--display-name', default='',
                       help='Device display name (skips interactive prompt)')
    parser.add_argument('--server-host', default='',
                       help='Fauxnos server hostname (overrides FAUXNOS_SERVER_HOST env var)')
    parser.add_argument('--no-reboot', action='store_true',
                       help='Do not reboot at end of setup (caller is responsible)')

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
    setup.display_name = args.display_name
    setup.no_reboot = args.no_reboot
    if args.server_host:
        setup.server_hostname = args.server_host

    # Run setup
    success = setup.run_setup()
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()