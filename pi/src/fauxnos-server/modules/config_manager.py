#!/usr/bin/env python3
"""
Fauxnos Configuration Manager
-----------------------------
Centralized configuration management for the Fauxnos multiroom audio system.
Generates and deploys all server and client configurations from a single source of truth.
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


@dataclass
class ClientConfig:
    """Client configuration data structure"""
    id: str
    name: str
    mac: str
    zeroconf_port: int
    server_port: int


class ConfigManager:
    """Manages configuration generation and deployment for Fauxnos system"""

    def __init__(self, config_file: str = "server_config.json", test_mode: bool = False):
        self.config_file = config_file
        self.test_mode = test_mode
        self.logger = logging.getLogger('ConfigManager')

        # Initialize from template if config doesn't exist
        self._ensure_config_exists()
        self.server_config = self._load_server_config()

        # No longer need client template - client owns its config

    def _ensure_config_exists(self):
        """Ensure config file exists, create from template if needed"""
        if not os.path.exists(self.config_file):
            # Look for template
            template_path = Path(__file__).parent.parent / "configs" / "server_config.json.template"
            if template_path.exists():
                self.logger.info(f"Initializing server config from template: {template_path}")
                try:
                    with open(template_path, 'r') as src:
                        template_data = json.load(src)
                    with open(self.config_file, 'w') as dst:
                        json.dump(template_data, dst, indent=2)
                    self.logger.info(f"Created server config: {self.config_file}")
                except Exception as e:
                    self.logger.error(f"Failed to create config from template: {e}")
            else:
                self.logger.warning(f"No template found at {template_path}, will create default config")

    def _load_server_config(self) -> Dict[str, Any]:
        """Load server configuration from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                cfg = json.load(f)
        except FileNotFoundError:
            self.logger.error(f"Server config file not found: {self.config_file}")
            return self._create_default_config()
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in config file: {e}")
            raise

        changed_sha = self._migrate_legacy_deployed_sha(cfg)
        changed_home_group = self._migrate_drop_home_group(cfg)
        changed_evc = self._migrate_external_volume_controller(cfg)
        if changed_sha or changed_home_group or changed_evc:
            # Write the migrated shape back so subsequent loads are
            # no-ops and any consumer reading the file directly sees
            # the new field names.
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(cfg, f, indent=2)
                if changed_sha:
                    self.logger.info("server_config: migrated legacy deployed_sha → deployed_client_sha")
                if changed_home_group:
                    self.logger.info("server_config: dropped legacy home_group field(s) (now derived from home_source ↔ stream_id)")
                if changed_evc:
                    self.logger.info("server_config: added missing external_volume_controller defaults to clients")
            except Exception as e:
                # Persistence failure is non-fatal — the in-memory dict is
                # already migrated, so the server runs correctly this
                # session; the migration will retry on next load.
                self.logger.warning(f"server_config: migration save failed (will retry next load): {e}")
        return cfg

    @staticmethod
    def _migrate_drop_home_group(cfg: Dict[str, Any]) -> bool:
        """Drop the legacy per-client `home_group` (snapcast group UUID) field.

        The 2026-05-24 group-state refactor removed this field. snapcast
        auto-prunes empty groups, so any saved UUID went stale the moment
        a client joined another room (its original group emptied → pruned →
        UUID gone forever). The new architecture derives group ownership
        from `home_source` matching the snapcast group's current `stream_id`,
        so the UUID is purely vestigial.

        Idempotent and additive — only deletes when present, never touches
        anything else.
        """
        changed = False
        for client in cfg.get("clients", []) or []:
            if isinstance(client, dict) and "home_group" in client:
                client.pop("home_group", None)
                changed = True
        return changed

    @staticmethod
    def _migrate_legacy_deployed_sha(cfg: Dict[str, Any]) -> bool:
        """Rename per-client `deployed_sha` → `deployed_client_sha`.

        Phase F1 (2026-05-13) split the single `deployed_sha` field into
        a server-wide `server_deployed_sha` (top-level) and a per-client
        `deployed_client_sha`. This migration handles the rename only;
        the server-wide field starts None and is filled on first server
        self-update.

        Idempotent and additive: only renames when the old field is
        present AND the new isn't. Never deletes the new field. Returns
        True if any change was made (caller should persist).
        """
        changed = False
        for client in cfg.get("clients", []) or []:
            if not isinstance(client, dict):
                continue
            if "deployed_sha" in client and "deployed_client_sha" not in client:
                client["deployed_client_sha"] = client.pop("deployed_sha")
                changed = True
            elif "deployed_sha" in client and "deployed_client_sha" in client:
                # Both present (shouldn't happen but be defensive). Trust
                # the new field, drop the stale duplicate.
                client.pop("deployed_sha", None)
                changed = True
        return changed

    @staticmethod
    def _migrate_external_volume_controller(cfg: Dict[str, Any]) -> bool:
        """Ensure every client has a fully-populated `external_volume_controller` blob.

        Added 2026-05-26 to support routing the device-wide volume slider
        through an external endpoint instead of attenuating via PulseAudio
        or snapcast. When `enabled` is true, the fauxnos UI sends each
        slider move out via the configured transport; the device's local
        audio chain is pinned at unity so the external controller owns
        attenuation end-to-end.

        Schema supports two transports:

          { "enabled": bool,
            "transport": "http" | "mqtt",
            # HTTP fields — outbound POST when transport=http:
            "control_api":    "https://…",
            "control_payload": {…} | "raw string",
            "content_type":   "json" | "form",
            # MQTT fields — broker is always fauxnos's own mosquitto
            # (LAN-local, no auth), so the user doesn't configure it:
            "mqtt_topic_out":   "device/setVolume",  # we publish here
            "mqtt_payload_out": "{{volume}}/100",     # template
            "mqtt_topic_in":    "device/volume",      # we subscribe here
            # Broker-IP push (optional, for devices that can't resolve
            # mDNS — Particle Photon being the canonical case). Reuses
            # the HTTP-call shape (URL + payload-with-placeholder + encoding)
            # but the placeholder is {{ip}} (fauxnos's current LAN IPv4),
            # not {{volume}}. Fired on server startup when the detected IP
            # differs from the last-pushed value, or via manual UI button.
            "broker_update_enabled":       False,
            "broker_update_api":           "",
            "broker_update_payload":       {},
            "broker_update_content_type":  "json" }

        `{{volume}}` is substituted with the current 0-100 slider value at
        dispatch time, in both HTTP and MQTT outbound payloads. The
        broker_update_payload uses `{{ip}}` for the server's current LAN IP.

        Additive at the field level: clients that already had a partial
        blob (from earlier 2026-05-26 deploy) get the new MQTT fields
        filled in with defaults without losing any HTTP config the user
        already entered. Idempotent — running this twice changes nothing.
        """
        defaults = {
            "enabled": False,
            "transport": "http",
            # HTTP defaults
            "control_api": "",
            "control_payload": {},
            "content_type": "json",
            # MQTT defaults
            "mqtt_topic_out": "",
            "mqtt_payload_out": "{{volume}}/100",
            "mqtt_topic_in": "",
            "broker_update_enabled": False,
            "broker_update_api": "",
            "broker_update_payload": {},
            "broker_update_content_type": "json",
        }
        changed = False
        # Existing configs that already have a non-empty broker_update_api
        # should auto-flip enabled→True at migration time so live VinylTable
        # configs don't silently lose the push behavior they were relying on.
        for client in cfg.get("clients", []) or []:
            if not isinstance(client, dict):
                continue
            evc = client.get("external_volume_controller") or {}
            if (evc.get("broker_update_api") or "").strip() and "broker_update_enabled" not in evc:
                evc["broker_update_enabled"] = True
                changed = True
        for client in cfg.get("clients", []) or []:
            if not isinstance(client, dict):
                continue
            evc = client.get("external_volume_controller")
            if evc is None:
                client["external_volume_controller"] = dict(defaults)
                changed = True
                continue
            # Fill in any missing keys (additive) without touching user values
            for k, v in defaults.items():
                if k not in evc:
                    evc[k] = v if not isinstance(v, dict) else dict(v)
                    changed = True
        return changed

    def _create_default_config(self) -> Dict[str, Any]:
        """Create default server configuration"""
        return {
            "server": {
                "snapcast": {
                    "host": "localhost",
                    "port": 1705
                },
                "mqtt": {
                    "broker_host": "localhost",
                    "broker_port": 1883
                },
                "paths": {
                    "fifo_base": "/tmp/snapfifo",
                    "go_librespot_config_base": "~/.config/go-librespot"
                }
            },
            "clients": []
        }

    def save_server_config(self):
        """Save current server configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.server_config, f, indent=2)
            self.logger.info(f"Server config saved to {self.config_file}")
        except Exception as e:
            self.logger.error(f"Failed to save server config: {e}")
            raise

    # Template methods no longer needed - client owns its config

    def add_client(self, name: str, mac: str, client_id: Optional[str] = None, is_server_device: bool = False) -> ClientConfig:
        """Add a new client to the configuration

        Args:
            name: Client display name
            mac: Client MAC address
            client_id: Optional specific client ID to use (e.g., 'fauxnos000' for server device)
            is_server_device: If True, forces client_id to 'fauxnos000' (for server's own hardware)
        """
        existing_ids = [client['id'] for client in self.server_config['clients']]

        # Generate client ID if not provided
        if client_id is None:
            if is_server_device:
                # Server device always gets fauxnos000
                client_id = "fauxnos000"
                if client_id in existing_ids:
                    raise ValueError("Server device (fauxnos000) already exists")
                next_num = 0
            else:
                # Regular clients start from 001
                next_num = 1
                while f"fauxnos{next_num:03d}" in existing_ids:
                    next_num += 1
                client_id = f"fauxnos{next_num:03d}"
        else:
            # Validate provided client_id is not already in use
            if client_id in existing_ids:
                raise ValueError(f"Client ID {client_id} already exists")
            # Extract number from client_id for port calculation
            next_num = int(client_id.replace('fauxnos', ''))

        # Generate ports based on client number
        base_zeroconf = 49000
        base_server = 3600
        zeroconf_port = base_zeroconf + next_num
        server_port = base_server + next_num

        # Client owns its config - server just tracks basic info
        # Generate home source name (group will be auto-detected)
        home_source = f"source_{client_id}_spotify"

        # Add client to configuration
        client_config = {
            "id": client_id,
            "name": name,
            "mac": mac,
            "go_librespot": {
                "zeroconf_port": zeroconf_port,
                "server_port": server_port
            }
        }

        # Track home_source only. Group ownership is derived live by matching
        # this against the snapcast group's current stream_id; no home_group
        # UUID needs to be stored.
        client_config["home_source"] = home_source

        self.server_config['clients'].append(client_config)
        self.logger.info(f"Added client {client_id} ({name}) with MAC {mac}")

        # Return ClientConfig object instead of just the ID
        return ClientConfig(
            id=client_id,
            name=name,
            mac=mac,
            zeroconf_port=zeroconf_port,
            server_port=server_port
        )

    def remove_client(self, client_id: str) -> bool:
        """Remove a client from the configuration"""
        initial_count = len(self.server_config['clients'])
        self.server_config['clients'] = [
            client for client in self.server_config['clients']
            if client['id'] != client_id
        ]

        removed = len(self.server_config['clients']) < initial_count
        if removed:
            self.logger.info(f"Removed client {client_id}")
        else:
            self.logger.warning(f"Client {client_id} not found for removal")

        return removed

    def rename_client(self, client_id: str, new_name: str) -> bool:
        """Rename a client's display name"""
        for client in self.server_config['clients']:
            if client['id'] == client_id:
                old_name = client['name']
                client['name'] = new_name
                self.logger.info(f"Renamed client {client_id}: '{old_name}' → '{new_name}'")
                return True

        self.logger.warning(f"Client {client_id} not found for rename")
        return False

    def get_client_config(self, client_id: str) -> Optional[ClientConfig]:
        """Get configuration for a specific client"""
        for client in self.server_config['clients']:
            if client['id'] == client_id:
                return ClientConfig(
                    id=client['id'],
                    name=client['name'],
                    mac=client['mac'],
                    zeroconf_port=client['go_librespot']['zeroconf_port'],
                    server_port=client['go_librespot']['server_port']
                )
        return None

    def list_clients(self) -> List[ClientConfig]:
        """List all configured clients"""
        return [
            ClientConfig(
                id=client['id'],
                name=client['name'],
                mac=client['mac'],
                zeroconf_port=client['go_librespot']['zeroconf_port'],
                server_port=client['go_librespot']['server_port']
            )
            for client in self.server_config['clients']
        ]

    def get_all_clients(self) -> List[ClientConfig]:
        """Alias for list_clients for API compatibility"""
        return self.list_clients()

    def get_client(self, client_id: str) -> Optional[ClientConfig]:
        """Alias for get_client_config for API compatibility"""
        return self.get_client_config(client_id)

    def find_client_by_mac(self, mac_address: str) -> Optional[ClientConfig]:
        """Find a client by MAC address"""
        for client in self.server_config['clients']:
            if client['mac'].lower() == mac_address.lower():
                return ClientConfig(
                    id=client['id'],
                    name=client['name'],
                    mac=client['mac'],
                    zeroconf_port=client['go_librespot']['zeroconf_port'],
                    server_port=client['go_librespot']['server_port']
                )
        return None

    def get_next_client_id(self) -> str:
        """Generate the next available client ID"""
        existing_ids = [client['id'] for client in self.server_config['clients']]

        # Reserve fauxnos000 for the server device
        # Start client IDs from fauxnos001
        for i in range(1, 1000):
            client_id = f"fauxnos{i:03d}"
            if client_id not in existing_ids:
                return client_id

        raise Exception("No available client IDs (maximum reached)")

    def generate_go_librespot_config(self, client: ClientConfig,
                                     device_name_override: Optional[str] = None) -> str:
        """Generate go-librespot configuration for a client.

        `device_name_override` lets a caller pin the Spotify Connect device
        name to something other than the persisted display name — used to
        reflect group membership (e.g. "Kitchen +1") without mutating the
        stored client.name. When None, falls back to client.name.
        """
        fifo_base = os.path.expanduser(self.server_config['server']['paths']['fifo_base'])
        fifo_path = f"{fifo_base}/spotify_{client.id}"

        # `external_volume: true` means go-librespot does NOT
        # attenuate its audio output at all — it pipes Spotify audio
        # to the FIFO at full level and treats its own /player/volume
        # value as a label that's echoed to/from Spotify Connect.
        # Audio attenuation happens downstream at snapcast (single
        # stage there; the client side pins PA at 100). The brief
        # described this as "go-librespot does all attenuation" but
        # that would actually require external_volume:false, which
        # forces attenuation to happen before the FIFO buffer and
        # adds ~1s of buffer lag to every slider move. Mirroring
        # value to go-librespot via HTTP is what keeps the Spotify
        # mobile-app slider in sync with fauxnos UI.
        #
        # `volume_steps: 100` rescales the HTTP API + WebSocket event
        # volume range from the default 0-65535 to 0-100 so the wire
        # contract matches fauxnos's UI scale. (initial_volume is also
        # interpreted in that range.)
        config = {
            'device_name': device_name_override or client.name,
            'initial_volume': 50,
            'volume_steps': 100,
            'external_volume': True,
            'device_type': 'speaker',
            'audio_backend': 'pipe',
            'audio_output_pipe': fifo_path,
            'bitrate': 320,
            'zeroconf_port': client.zeroconf_port,
            'server': {
                'enabled': True,
                'address': '0.0.0.0',
                'port': client.server_port
            }
        }

        # Convert to YAML format
        yaml_lines = []
        for key, value in config.items():
            if key == 'server':
                yaml_lines.append(f"{key}:")
                for sub_key, sub_value in value.items():
                    yaml_lines.append(f"  {sub_key}: {sub_value}")
            else:
                if isinstance(value, str):
                    yaml_lines.append(f'{key}: "{value}"')
                else:
                    yaml_lines.append(f"{key}: {value}")

        return "\n".join(yaml_lines)

    def generate_snapserver_sources(self) -> List[str]:
        """Generate snapserver source configurations (Spotify per client)

        Uses mode=create on the pipe sources, NOT mode=read. With mode=read
        snapserver opens the FIFO O_RDONLY; if no writer is connected at open
        time the first read returns EOF and snapcast's AsioStream treats that
        as fatal, stops reading, and never reopens. With no reader-end held
        open, when go-librespot later tries to open the FIFO for writing it
        gets ENXIO ("no such device or address"), and Spotify playback hangs
        before the playhead ever moves. mode=create has snapserver open the
        FIFO O_RDWR so there's always a reader attached and EOF can't happen.
        """
        fifo_base = self.server_config['server']['paths']['fifo_base']
        sources = []

        for client in self.server_config['clients']:
            client_id = client['id']

            # Spotify source
            spotify_fifo = f"{fifo_base}/spotify_{client_id}"
            spotify_name = f"source_{client_id}_spotify"
            sources.append(f"source = pipe://{spotify_fifo}?name={spotify_name}&mode=create")

        return sources

    def generate_snapserver_config(self) -> str:
        """Generate complete snapserver.conf file"""
        snapcast_config = self.server_config['server']['snapcast']

        # Get all client sources
        sources = self.generate_snapserver_sources()

        config_content = f"""###############################################################################
#     ______                                                                  #
#    / _____)                                                                 #
#   ( (____   ____   _____  ____    ___  _____   ____  _   _  _____   ____    #
#    \____ \ |  _ \ (____ ||  _ \  /___)| ___ | / ___)| | | || ___ | / ___)   #
#    _____) )| | | |/ ___ || |_| ||___ || ____|| |     \ V / | ____|| |       #
#   (______/ |_| |_|\_____||  __/ (___/ |_____)|_|      \_/  |_____)|_|       #
#                          |_|                                                #
#                                                                             #
#  Snapserver config file - Generated by Fauxnos ConfigManager               #
#                                                                             #
###############################################################################

[server]
threads = -1

[http]
enabled = true
bind_to_address = 0.0.0.0
port = 1780
doc_root = /usr/share/snapserver/snapweb
host = <hostname>

[tcp]
enabled = true
bind_to_address = 0.0.0.0
port = {snapcast_config['port']}

[stream]
bind_to_address = 0.0.0.0
port = 1704

# Generated sources for Fauxnos clients
"""

        # Add all client sources
        for source in sources:
            config_content += f"{source}\n"

        config_content += f"""
# Default sample format and codec
sampleformat = 44100:16:2
codec = pcm
chunk_ms = 50
buffer = 2000
send_to_muted = false

[streaming_client]
initial_volume = 30

[logging]
filter = *:info
"""

        return config_content.strip()

    def generate_snapserver_service(self) -> str:
        """Generate systemd service for user snapserver"""
        config_file = os.path.expanduser("~/.config/snapcast/snapserver.conf")

        # Note: depend on fauxnos-fifo-pinner.service. Without that pinner,
        # snapcast 0.31's PipeStream opens a writerless FIFO, hits EOF, and
        # silently abandons the source — Spotify then fails with ENXIO when
        # go-librespot tries to write. The pinner keeps a no-op writer on
        # each FIFO so snapserver always sees a writer at startup.
        service_content = f"""[Unit]
Description=Snapcast Server (User)
After=network.target fauxnos-fifo-setup.service fauxnos-fifo-pinner.service
Requires=fauxnos-fifo-setup.service fauxnos-fifo-pinner.service

[Service]
Type=simple
ExecStart=/usr/bin/snapserver --config {config_file}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
        return service_content.strip()

    def generate_fifo_pinner_script(self) -> str:
        """Generate the FIFO writer-pinner script.

        Why this exists: snapcast 0.31's PipeStream opens FIFOs O_RDONLY. If
        no writer is attached at the moment of open, the kernel's first read
        returns EOF, asio reports it as fatal, and snapserver permanently
        abandons that FIFO source. With no reader, when go-librespot later
        tries to open the FIFO for writing it gets ENXIO ("no such device
        or address") and audio fails silently. This script pins a no-op
        writer (a backgrounded `sleep infinity` holding the FD open) on
        each FIFO so snapserver always finds a writer at startup and EOF
        can never happen.
        """
        fifo_base = self.server_config['server']['paths']['fifo_base']

        lines = [
            "#!/bin/bash",
            "# FIFO writer-pinner — keeps a no-op writer attached to every fauxnos FIFO.",
            "# See modules/config_manager.py::generate_fifo_pinner_script for the full",
            "# rationale. Short version: snapcast 0.31's PipeStream gives up on",
            "# writerless FIFOs at startup, so we always need at least one writer pinned.",
            "set -euo pipefail",
            "",
            "FIFOS=(",
        ]
        for client in self.server_config['clients']:
            client_id = client['id']
            lines.append(f'  "{fifo_base}/spotify_{client_id}"')
        lines.extend([
            ")",
            "",
            "# Open each FIFO O_WRONLY on a numbered FD on this bash process,",
            "# starting at fd 3. Then exec into `sleep infinity` so the FDs",
            "# stay open for the lifetime of the (long-lived) sleep process.",
            "fd=3",
            'for f in "${FIFOS[@]}"; do',
            '  eval "exec ${fd}>\\"$f\\""',
            "  fd=$((fd+1))",
            "done",
            "",
            "exec sleep infinity",
        ])
        return "\n".join(lines)

    def generate_fifo_pinner_service(self) -> str:
        """Generate systemd user service for the FIFO pinner."""
        scripts_dir = os.path.expanduser("~/scripts")
        service_content = f"""[Unit]
Description=Fauxnos FIFO writer pinner (keeps a no-op writer on each snapcast FIFO so snapserver doesn't EOF on startup)
After=fauxnos-fifo-setup.service
Requires=fauxnos-fifo-setup.service

[Service]
Type=simple
ExecStart={scripts_dir}/fifo-pinner.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
"""
        return service_content.strip()

    def generate_fifo_setup_script(self) -> str:
        """Generate FIFO setup script for all clients (Spotify)"""
        fifo_base = self.server_config['server']['paths']['fifo_base']

        script_lines = [
            "#!/bin/bash",
            "# Setup FIFO pipes for audio streams (Spotify)",
            "set -euo pipefail",
            "",
            f"# Ensure base FIFO directory exists.",
            f"# Note: snapserver's apt postinst creates {fifo_base} as a named pipe",
            f"# (its default source). If that's there, mkdir -p would fail because the",
            f"# path exists as a non-directory, so remove it first.",
            f"if [ -e {fifo_base} ] && [ ! -d {fifo_base} ]; then",
            f"  rm -f {fifo_base}",
            f"  echo \"Removed non-directory at {fifo_base} (likely snapserver default FIFO)\"",
            f"fi",
            f"mkdir -p {fifo_base}",
            f"echo \"Ensured FIFO base directory: {fifo_base}\"",
            "",
            "# List of FIFO paths",
            "FIFOS=("
        ]

        for client in self.server_config['clients']:
            client_id = client['id']
            script_lines.append(f'  "{fifo_base}/spotify_{client_id}"')

        script_lines.extend([
            ")",
            "",
            "for fifo in \"${FIFOS[@]}\"; do",
            "  # Remove existing FIFO/file if it exists",
            "  if [ -p \"$fifo\" ] || [ -e \"$fifo\" ]; then",
            "    rm -f \"$fifo\"",
            "    echo \"Removed existing FIFO at $fifo\"",
            "  fi",
            "",
            "  # Create new FIFO",
            "  mkfifo \"$fifo\"",
            "  echo \"Created FIFO at $fifo\"",
            "",
            "  # Set permissions to 666 (readable/writable by all)",
            "  chmod 666 \"$fifo\"",
            "  echo \"Set FIFO permissions to 666 at $fifo\"",
            "done",
            "",
            "echo \"Ready: ${FIFOS[*]}\""
        ])

        return "\n".join(script_lines)

    def generate_systemd_service(self, client: ClientConfig) -> str:
        """Generate systemd service file for go-librespot instance"""
        config_base = os.path.expanduser(self.server_config['server']['paths']['go_librespot_config_base'])
        config_path = f"{config_base}/{client.id}/config.yml"

        service_content = f"""[Unit]
Description=Go-Librespot Spotify Connect daemon for {client.name} ({client.id})
After=network.target fauxnos-fifo-setup.service
Requires=fauxnos-fifo-setup.service

[Service]
Type=simple
ExecStart=/usr/local/bin/go-librespot --config_dir {os.path.dirname(config_path)}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
        return service_content.strip()

    def generate_fifo_setup_service(self) -> str:
        """Generate systemd service for FIFO setup (runs once before all go-librespot instances)"""
        service_content = f"""[Unit]
Description=Fauxnos FIFO Setup
After=network.target

[Service]
Type=oneshot
ExecStart={os.path.expanduser('~/scripts/setup-fifo.sh')}
RemainAfterExit=yes

[Install]
WantedBy=default.target
"""
        return service_content.strip()

    def generate_client_json_config(self, client: ClientConfig) -> Dict[str, Any]:
        """Generate JSON configuration for fauxnos-client"""
        server_host = "fauxnos-server.local"  # Assume mDNS

        config = {
            "client_id": client.id,
            "name": client.name.lower(),
            "display_name": client.name,
            "mac": client.mac,
            "server_config_url": f"http://{server_host}:8080/api/config/{client.id}",
            "go_librespot_monitor_url": f"http://{server_host}:{client.server_port}/player/volume",
            "sounds": {
                "switch": "~/src/sounds/source_switch.wav",
                "volume_up": "~/src/sounds/volume_up.wav",
                "volume_down": "~/src/sounds/volume_down.wav"
            },
            "sources": [
                {
                    "id": "snapcast",
                    "label": "Multiroom",
                    "type": "internal",
                    "sink": "snapsink",
                    "starting_volume": 50,
                    "volume_controller": "snapcast"
                },
                {
                    "id": "analog",
                    "label": "Analog In",
                    "type": "internal",
                    "sink": "analogsink",
                    "starting_volume": 30,
                    "volume_controller": "self"
                },
                {
                    "id": "alexa",
                    "label": "Alexa",
                    "type": "external",
                    "control_api": "https://webhook.site/example",
                    "control_payload": {
                        "source": "alexa"
                    }
                }
            ],
            "log_file": f"~/logs/audio_controller_{client.id}.log",
            "mqtt": {
                "broker_host": server_host,
                "broker_port": 1883
            }
        }

        return config

    def validate_configuration(self) -> List[str]:
        """Validate current configuration and return list of issues"""
        issues = []

        # Check for duplicate client IDs
        client_ids = [client['id'] for client in self.server_config['clients']]
        if len(client_ids) != len(set(client_ids)):
            issues.append("Duplicate client IDs found")

        # Check for duplicate MAC addresses
        macs = [client['mac'] for client in self.server_config['clients']]
        if len(macs) != len(set(macs)):
            issues.append("Duplicate MAC addresses found")

        # Check for port conflicts
        zeroconf_ports = [client['go_librespot']['zeroconf_port'] for client in self.server_config['clients']]
        server_ports = [client['go_librespot']['server_port'] for client in self.server_config['clients']]

        if len(zeroconf_ports) != len(set(zeroconf_ports)):
            issues.append("Duplicate zeroconf ports found")

        if len(server_ports) != len(set(server_ports)):
            issues.append("Duplicate server ports found")

        # Check for valid client names
        for client in self.server_config['clients']:
            if not client['name'] or not client['name'].strip():
                issues.append(f"Empty name for client {client['id']}")

        return issues


def main():
    """Command-line interface for ConfigManager"""
    import argparse

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    parser = argparse.ArgumentParser(description='Fauxnos Configuration Manager')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Add client command
    add_parser = subparsers.add_parser('add-client', help='Add a new client')
    add_parser.add_argument('--name', required=True, help='Client display name')
    add_parser.add_argument('--mac', required=True, help='Client MAC address')

    # Remove client command
    remove_parser = subparsers.add_parser('remove-client', help='Remove a client')
    remove_parser.add_argument('client_id', help='Client ID to remove')

    # Rename client command
    rename_parser = subparsers.add_parser('rename-client', help='Rename a client')
    rename_parser.add_argument('client_id', help='Client ID to rename')
    rename_parser.add_argument('--name', required=True, help='New client display name')

    # List clients command
    subparsers.add_parser('list-clients', help='List all clients')

    # Validate command
    subparsers.add_parser('validate', help='Validate configuration')

    # Generate commands
    gen_parser = subparsers.add_parser('generate', help='Generate configurations')
    gen_parser.add_argument('type', choices=['go-librespot', 'snapserver', 'fifo-script', 'client-config'],
                           help='Type of configuration to generate')
    gen_parser.add_argument('--client-id', help='Client ID (for client-specific configs)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    config_manager = ConfigManager()

    if args.command == 'add-client':
        new_client = config_manager.add_client(args.name, args.mac)
        config_manager.save_server_config()
        print(f"Added client: {new_client.id}")

    elif args.command == 'remove-client':
        if config_manager.remove_client(args.client_id):
            config_manager.save_server_config()
            print(f"Removed client: {args.client_id}")
        else:
            print(f"Client not found: {args.client_id}")

    elif args.command == 'rename-client':
        if config_manager.rename_client(args.client_id, args.name):
            config_manager.save_server_config()
            print(f"Renamed client {args.client_id} to '{args.name}'")
        else:
            print(f"Client not found: {args.client_id}")

    elif args.command == 'list-clients':
        clients = config_manager.list_clients()
        if not clients:
            print("No clients configured")
        else:
            print("Configured clients:")
            for client in clients:
                print(f"  {client.id}: {client.name} ({client.mac})")
                print(f"    Ports: zeroconf={client.zeroconf_port}, server={client.server_port}")

    elif args.command == 'validate':
        issues = config_manager.validate_configuration()
        if not issues:
            print("Configuration is valid")
        else:
            print("Configuration issues found:")
            for issue in issues:
                print(f"  - {issue}")

    elif args.command == 'generate':
        if args.type == 'snapserver':
            sources = config_manager.generate_snapserver_sources()
            print("# Add these lines to snapserver.conf [stream] section:")
            for source in sources:
                print(source)

        elif args.type == 'fifo-script':
            script = config_manager.generate_fifo_setup_script()
            print(script)

        elif args.type in ['go-librespot', 'client-config']:
            if not args.client_id:
                print(f"--client-id required for {args.type}")
                return

            client = config_manager.get_client_config(args.client_id)
            if not client:
                print(f"Client not found: {args.client_id}")
                return

            if args.type == 'go-librespot':
                config = config_manager.generate_go_librespot_config(client)
                print(config)

            elif args.type == 'client-config':
                config = config_manager.generate_client_json_config(client)
                print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()