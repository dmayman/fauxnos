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

# Module imports handled by relative imports

from .config_manager import ConfigManager, ClientConfig
from typing import Optional

app = Flask(__name__)

class FauxnosAPIServer:
    def __init__(self, config_manager: Optional[ConfigManager] = None, test_mode: bool = False, verbose: bool = False):
        self.test_mode = test_mode
        self.verbose = verbose
        self.config_manager = config_manager or ConfigManager(test_mode=test_mode)

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
            display_name = data.get('display_name', 'Fauxnos Client')

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
                    "server_port": existing_client.server_port,
                    "zeroconf_port": existing_client.zeroconf_port
                })

            # Check if this is the server device and assign fauxnos000
            # Server device is detected by checking if request comes from localhost or server's own MAC
            import socket
            import subprocess

            is_server_device = False
            try:
                # Check if request comes from localhost
                self.log(f"Request remote_addr: {request.remote_addr}")
                if request.remote_addr in ['127.0.0.1', '::1']:
                    is_server_device = True
                    self.log("Detected server device via localhost", "INFO")
                else:
                    # Check if MAC address matches server's primary interface
                    result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True)
                    if mac_address.lower() in result.stdout.lower():
                        is_server_device = True
                        self.log("Detected server device via MAC match", "INFO")
            except Exception as e:
                self.log(f"Error in server device detection: {e}", "WARNING")

            # Generate client ID
            self.log(f"is_server_device: {is_server_device}")
            if is_server_device:
                # Check if fauxnos000 is already taken
                existing_server = self.config_manager.get_client_config("fauxnos000")
                self.log(f"fauxnos000 existing_server: {existing_server}")
                if existing_server:
                    # Server device already registered, assign next available ID
                    next_id = self.config_manager.get_next_client_id()
                    self.log(f"fauxnos000 taken, assigned: {next_id}")
                else:
                    # Reserve fauxnos000 for server device
                    next_id = "fauxnos000"
                    self.log(f"Reserved fauxnos000 for server device")
            else:
                next_id = self.config_manager.get_next_client_id()
                self.log(f"Regular client assigned: {next_id}")

            if self.test_mode:
                # In test mode, use mock data - no user input needed
                client_name = f"Test Client {next_id[-3:]}"
                self.log(f"TEST MODE: Auto-assigning name '{client_name}' to {next_id}", "WARNING")
            else:
                # In production, prompt for name
                print(f"\n🔧 New client registration: {next_id}")
                print(f"   MAC Address: {mac_address}")
                print(f"   Hostname: {hostname}")
                # Use display name provided by client instead of prompting
                client_name = display_name

                if not client_name:
                    client_name = f"Fauxnos {next_id[-3:]}"
                    print(f"Using default name: {client_name}")

            # Add client to configuration
            try:
                new_client = self.config_manager.add_client(
                    name=display_name,
                    mac=mac_address,
                    client_id=next_id  # Pass the determined client_id (fauxnos000 for server, auto-assigned otherwise)
                )

                if not self.test_mode:
                    # Deploy server-side infrastructure
                    self.log("Deploying server infrastructure...")
                    from .deploy import DeploymentManager
                    deployer = DeploymentManager(self.config_manager)

                    if deployer.deploy_server_configs():
                        self.log("Server infrastructure deployed successfully", "SUCCESS")

                        # Restart snapserver to load new configuration before group assignment
                        self.log("Restarting snapserver to load new client configuration...")
                        import subprocess
                        try:
                            subprocess.run(["systemctl", "--user", "restart", "snapserver"], check=True, timeout=10)
                            self.log("Snapserver restarted successfully", "SUCCESS")

                            # Wait a moment for snapserver to fully start
                            import time
                            time.sleep(2)
                        except Exception as e:
                            self.log(f"Failed to restart snapserver: {e}", "WARNING")

                        # Auto-assign new client to home group
                        self.log("Assigning new client to home group...")
                        from .group_manager import assign_all_clients_to_home

                        if assign_all_clients_to_home(self.config_manager, dry_run=False):
                            self.log(f"Client {new_client.id} assigned to home group", "SUCCESS")
                        else:
                            self.log(f"Failed to assign {new_client.id} to home group", "WARNING")
                            # Don't fail registration if group assignment fails
                    else:
                        self.log("Server deployment failed", "ERROR")
                        return jsonify({"error": "Failed to deploy server infrastructure"}), 500

                # Save server configuration
                self.log("Saving server configuration...")
                self.config_manager.save_server_config()
                self.log("Server configuration saved successfully", "SUCCESS")

                self.log(f"Client registered successfully: {new_client.id} ({client_name})", "SUCCESS")

                return jsonify({
                    "status": "registered",
                    "client_id": new_client.id,
                    "server_port": new_client.server_port,
                    "zeroconf_port": new_client.zeroconf_port
                })

            except Exception as e:
                self.log(f"Failed to register client: {e}", "ERROR")
                return jsonify({"error": f"Registration failed: {str(e)}"}), 500

        except Exception as e:
            self.log(f"Registration error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_get_client_config(self, client_id: str):
        """Handle GET /api/config/<client_id>"""
        # NOTE: This endpoint is deprecated in the new architecture.
        # Clients now own their config and don't download it from server.
        # Keeping for backward compatibility or debugging.
        try:
            client = self.config_manager.get_client(client_id)
            if not client:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            # Return basic server info only
            server_host = "fauxnos-server.local" if not self.test_mode else "localhost"

            basic_info = {
                "client_id": client.id,
                "server_port": client.server_port,
                "zeroconf_port": client.zeroconf_port,
                "go_librespot_monitor_url": f"http://{server_host}:{client.server_port}/player/volume",
                "note": "Client owns its own configuration. This endpoint provides server connection info only."
            }

            self.log(f"Served basic server info for {client_id}")
            return jsonify(basic_info)

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