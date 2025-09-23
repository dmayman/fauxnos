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

    def __init__(self, config_file: str = "server_config.json"):
        self.config_file = config_file
        self.logger = logging.getLogger('ConfigManager')
        self.server_config = self._load_server_config()

    def _load_server_config(self) -> Dict[str, Any]:
        """Load server configuration from JSON file"""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error(f"Server config file not found: {self.config_file}")
            return self._create_default_config()
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in config file: {e}")
            raise

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

    def add_client(self, name: str, mac: str) -> str:
        """Add a new client to the configuration"""
        # Generate client ID
        existing_ids = [client['id'] for client in self.server_config['clients']]
        next_num = 1
        while f"fauxnos{next_num:03d}" in existing_ids:
            next_num += 1
        client_id = f"fauxnos{next_num:03d}"

        # Generate ports
        base_zeroconf = 49000
        base_server = 3600
        zeroconf_port = base_zeroconf + next_num
        server_port = base_server + next_num

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

        self.server_config['clients'].append(client_config)
        self.logger.info(f"Added client {client_id} ({name}) with MAC {mac}")

        return client_id

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

    def generate_go_librespot_config(self, client: ClientConfig) -> str:
        """Generate go-librespot configuration for a client"""
        fifo_base = os.path.expanduser(self.server_config['server']['paths']['fifo_base'])
        fifo_path = f"{fifo_base}/spotify_{client.id}"

        config = {
            'device_name': client.name,
            'initial_volume': 50,
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
        """Generate snapserver source configurations"""
        fifo_base = self.server_config['server']['paths']['fifo_base']
        sources = []

        for client in self.server_config['clients']:
            client_id = client['id']
            name = client['name']
            fifo_path = f"{fifo_base}/spotify_{client_id}"
            source_name = f"{name} Spotify"

            source_line = f"source = pipe://{fifo_path}?name={source_name}&mode=read"
            sources.append(source_line)

        return sources

    def generate_fifo_setup_script(self) -> str:
        """Generate FIFO setup script for all clients"""
        fifo_base = self.server_config['server']['paths']['fifo_base']

        script_lines = [
            "#!/bin/bash",
            "# Setup FIFO pipes for Spotify streams",
            "set -euo pipefail",
            "",
            f"# Ensure base FIFO directory exists",
            f"mkdir -p {fifo_base}",
            f"echo \"Ensured FIFO base directory: {fifo_base}\"",
            "",
            "# List of FIFO paths",
            "FIFOS=("
        ]

        for client in self.server_config['clients']:
            client_id = client['id']
            fifo_path = f'  "{fifo_base}/spotify_{client_id}"'
            script_lines.append(fifo_path)

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
        client_id = config_manager.add_client(args.name, args.mac)
        config_manager.save_server_config()
        print(f"Added client: {client_id}")

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