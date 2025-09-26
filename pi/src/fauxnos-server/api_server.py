#!/usr/bin/env python3
"""
Fauxnos Server API

Provides REST API endpoints for client registration and configuration management.
Handles:
- Client registration via MAC address
- Configuration distribution
- Server-side config management integration

Test modes available for safe development.
"""

import json
import argparse
from flask import Flask, request, jsonify
from pathlib import Path
import sys
import os

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager, ClientConfig

app = Flask(__name__)

class FauxnosAPIServer:
    def __init__(self, test_mode: bool = False, verbose: bool = False):
        self.test_mode = test_mode
        self.verbose = verbose
        self.config_manager = ConfigManager(test_mode=test_mode)

        # Setup Flask routes
        self.setup_routes()

    def log(self, message: str, level: str = "INFO"):
        if self.verbose or level in ["ERROR", "WARNING"]:
            colors = {
                "INFO": "\033[1;36m",    # Bright Cyan (more visible than blue)
                "SUCCESS": "\033[0;32m", # Green
                "WARNING": "\033[1;33m", # Yellow
                "ERROR": "\033[0;31m",   # Red
            }
            reset = "\033[0m"
            prefix = "🔧" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
            print(f"{colors.get(level, '')}{prefix} {message}{reset}")

    def setup_routes(self):
        """Setup Flask routes"""

        @app.route('/api/clients/register', methods=['POST'])
        def register_client():
            return self.handle_client_registration()

        @app.route('/api/config/<client_id>', methods=['GET'])
        def get_client_config(client_id):
            return self.handle_get_client_config(client_id)

        @app.route('/api/clients', methods=['GET'])
        def list_clients():
            return self.handle_list_clients()

        @app.route('/api/clients/<client_id>', methods=['PUT'])
        def update_client(client_id):
            return self.handle_update_client(client_id)

        @app.route('/api/clients/<client_id>', methods=['DELETE'])
        def delete_client(client_id):
            return self.handle_delete_client(client_id)

        @app.route('/api/status', methods=['GET'])
        def get_status():
            return self.handle_get_status()

    def handle_client_registration(self):
        """Handle POST /api/clients/register"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400

            mac_address = data.get('mac_address')
            hostname = data.get('hostname', 'unknown')

            if not mac_address:
                return jsonify({"error": "mac_address is required"}), 400

            self.log(f"Registration request from {hostname} ({mac_address})")

            # Check if client already exists
            existing_client = self.config_manager.find_client_by_mac(mac_address)
            if existing_client:
                self.log(f"Client already registered: {existing_client.id}")
                return jsonify({
                    "status": "already_registered",
                    "client_id": existing_client.id,
                    "name": existing_client.name,
                    "server_port": existing_client.server_port,
                    "zeroconf_port": existing_client.zeroconf_port
                })

            # Generate new client ID
            next_id = self.config_manager.get_next_client_id()

            if self.test_mode:
                # In test mode, use mock data - no user input needed
                client_name = f"Test Client {next_id[-3:]}"
                self.log(f"TEST MODE: Auto-assigning name '{client_name}' to {next_id}", "WARNING")
            else:
                # In production, prompt for name
                print(f"\n🔧 New client registration: {next_id}")
                print(f"   MAC Address: {mac_address}")
                print(f"   Hostname: {hostname}")
                client_name = input("Enter display name for this client (e.g., 'Kitchen', 'Living Room'): ").strip()

                if not client_name:
                    client_name = f"Fauxnos {next_id[-3:]}"
                    print(f"Using default name: {client_name}")

            # Add client to configuration
            try:
                new_client = self.config_manager.add_client(
                    name=client_name,
                    mac=mac_address
                )

                if not self.test_mode:
                    # Deploy server-side infrastructure
                    self.log("Deploying server infrastructure...")
                    from deploy import DeploymentManager
                    deployer = DeploymentManager(self.config_manager)

                    if deployer.deploy_server_configs():
                        self.log("Server infrastructure deployed successfully", "SUCCESS")
                    else:
                        self.log("Server deployment failed", "ERROR")
                        return jsonify({"error": "Failed to deploy server infrastructure"}), 500

                self.log(f"Client registered successfully: {new_client.id} ({client_name})", "SUCCESS")

                return jsonify({
                    "status": "registered",
                    "client_id": new_client.id,
                    "name": new_client.name,
                    "server_port": new_client.server_port,
                    "zeroconf_port": new_client.zeroconf_port,
                    "config_url": f"/api/config/{new_client.id}"
                })

            except Exception as e:
                self.log(f"Failed to register client: {e}", "ERROR")
                return jsonify({"error": f"Registration failed: {str(e)}"}), 500

        except Exception as e:
            self.log(f"Registration error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_get_client_config(self, client_id: str):
        """Handle GET /api/config/<client_id>"""
        try:
            client = self.config_manager.get_client(client_id)
            if not client:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            # Generate full client configuration
            server_host = "fauxnos-server.local" if not self.test_mode else "localhost"

            config = {
                "client_id": client.id,
                "name": client.id.replace("fauxnos", "").lstrip("0") or client.id,  # e.g., "001" -> "1"
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
                        "control_payload": {"source": "alexa"}
                    }
                ],
                "log_file": f"~/logs/audio_controller_{client.id}.log",
                "mqtt": {
                    "broker_host": server_host,
                    "broker_port": 1883
                }
            }

            self.log(f"Served config for {client_id}")
            return jsonify(config)

        except Exception as e:
            self.log(f"Config retrieval error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_list_clients(self):
        """Handle GET /api/clients"""
        try:
            clients = self.config_manager.get_all_clients()
            return jsonify({
                "clients": [
                    {
                        "client_id": client.id,
                        "name": client.name,
                        "mac": client.mac,
                        "server_port": client.server_port,
                        "zeroconf_port": client.zeroconf_port
                    }
                    for client in clients
                ]
            })
        except Exception as e:
            self.log(f"Client list error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_update_client(self, client_id: str):
        """Handle PUT /api/clients/<client_id>"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400

            new_name = data.get('name')
            if not new_name:
                return jsonify({"error": "name is required"}), 400

            if self.config_manager.rename_client(client_id, new_name):
                self.log(f"Client {client_id} renamed to '{new_name}'", "SUCCESS")
                return jsonify({"status": "updated", "name": new_name})
            else:
                return jsonify({"error": f"Client {client_id} not found"}), 404

        except Exception as e:
            self.log(f"Client update error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_delete_client(self, client_id: str):
        """Handle DELETE /api/clients/<client_id>"""
        try:
            if self.config_manager.remove_client(client_id):
                self.log(f"Client {client_id} removed", "SUCCESS")
                return jsonify({"status": "deleted"})
            else:
                return jsonify({"error": f"Client {client_id} not found"}), 404

        except Exception as e:
            self.log(f"Client deletion error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_get_status(self):
        """Handle GET /api/status"""
        try:
            clients = self.config_manager.get_all_clients()
            return jsonify({
                "status": "running",
                "test_mode": self.test_mode,
                "total_clients": len(clients),
                "server_version": "1.0.0"
            })
        except Exception as e:
            self.log(f"Status error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def run(self, host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
        """Run the Flask server"""
        self.log(f"Starting Fauxnos API Server on {host}:{port}")
        if self.test_mode:
            self.log("Running in TEST MODE", "WARNING")

        app.run(host=host, port=port, debug=debug)

def main():
    parser = argparse.ArgumentParser(
        description="Fauxnos API Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in test mode for development
  python3 api_server.py --test --verbose

  # Run production server
  python3 api_server.py

  # Run with debug mode
  python3 api_server.py --debug --verbose
        """
    )

    parser.add_argument('--test', action='store_true',
                       help='Run in test mode (mock operations)')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed output')
    parser.add_argument('--debug', action='store_true',
                       help='Run Flask in debug mode')
    parser.add_argument('--host', default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8080,
                       help='Port to bind to (default: 8080)')

    args = parser.parse_args()

    # Create and run server
    server = FauxnosAPIServer(test_mode=args.test, verbose=args.verbose)
    server.run(host=args.host, port=args.port, debug=args.debug)

if __name__ == '__main__':
    main()