#!/usr/bin/env python3
"""
Fauxnos Server API

Provides REST API endpoints for client registration, configuration management,
web UI serving, and zero-touch onboarding (firstrun.sh generation).

Test modes available for safe development.
"""

import json
import argparse
import subprocess
import socket
import os
import requests as http_requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response, send_from_directory, abort
from typing import Optional

from .config_manager import ConfigManager, ClientConfig

# Path to the web UI static files (relative to this module's location)
_SERVER_DIR = Path(__file__).parent.parent
WEB_DIR = _SERVER_DIR / "web"
CLIENT_INSTALL_SCRIPT = _SERVER_DIR.parent / "fauxnos-client" / "install.sh"
CLIENT_DIR = CLIENT_INSTALL_SCRIPT.parent

# Point Flask's built-in static handler at web/ so /static/style.css etc. work
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path='/static')


class FauxnosAPIServer:
    def __init__(self, config_manager: Optional[ConfigManager] = None, test_mode: bool = False, verbose: bool = False):
        self.test_mode = test_mode
        self.verbose = verbose
        self.config_manager = config_manager or ConfigManager(test_mode=test_mode)
        self.setup_routes()

    def log(self, message: str, level: str = "INFO"):
        if self.verbose or level in ["ERROR", "WARNING", "SUCCESS"]:
            colors = {
                "INFO": "\033[1;36m",
                "SUCCESS": "\033[0;32m",
                "WARNING": "\033[1;33m",
                "ERROR": "\033[0;31m",
            }
            reset = "\033[0m"
            prefix = "🔧" if level == "INFO" else "✓" if level == "SUCCESS" else "⚠" if level == "WARNING" else "✗"
            print(f"{colors.get(level, '')}{prefix} {message}{reset}")

    def setup_routes(self):
        """Setup all Flask routes"""

        # ── Web UI ────────────────────────────────────────────────────────────

        @app.route('/')
        def index():
            return self.handle_index()

        # ── Client management ─────────────────────────────────────────────────

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

        # ── Source management (per-client) ────────────────────────────────────

        @app.route('/api/clients/<client_id>/sources', methods=['GET'])
        def get_sources(client_id):
            return self.handle_get_sources(client_id)

        @app.route('/api/clients/<client_id>/sources', methods=['PUT'])
        def replace_sources(client_id):
            return self.handle_replace_sources(client_id)

        @app.route('/api/clients/<client_id>/sources', methods=['POST'])
        def add_source(client_id):
            return self.handle_add_source(client_id)

        @app.route('/api/clients/<client_id>/sources/<source_id>', methods=['PUT'])
        def update_source(client_id, source_id):
            return self.handle_update_source(client_id, source_id)

        @app.route('/api/clients/<client_id>/sources/<source_id>', methods=['DELETE'])
        def delete_source(client_id, source_id):
            return self.handle_delete_source(client_id, source_id)

        # ── Snapcast groups proxy ─────────────────────────────────────────────

        @app.route('/api/groups', methods=['GET'])
        def get_groups():
            return self.handle_get_groups()

        @app.route('/api/groups/join', methods=['POST'])
        def join_group():
            return self.handle_join_group()

        @app.route('/api/groups/return-home', methods=['POST'])
        def return_home():
            return self.handle_return_home()

        @app.route('/api/groups/stream', methods=['POST'])
        def set_group_stream():
            return self.handle_set_group_stream()

        @app.route('/api/groups/source', methods=['POST'])
        def set_group_source():
            return self.handle_set_group_source()

        # ── Status ────────────────────────────────────────────────────────────

        @app.route('/api/status', methods=['GET'])
        def get_status():
            return self.handle_get_status()

        @app.route('/api/server/status', methods=['GET'])
        def get_server_status():
            return self.handle_get_server_status()

        # ── Install / onboarding ──────────────────────────────────────────────

        @app.route('/api/install/firstrun.sh', methods=['GET'])
        def get_firstrun_sh():
            return self.handle_get_firstrun_sh()

        @app.route('/api/install/client.sh', methods=['GET'])
        def get_client_sh():
            return self.handle_get_client_sh()

        @app.route('/api/install/files/client/<path:filepath>')
        def serve_client_file(filepath):
            return self.handle_serve_client_file(filepath)

    # ── Web UI handler ─────────────────────────────────────────────────────────

    def handle_index(self):
        """Serve the web UI index page."""
        index_file = WEB_DIR / "index.html"
        if not index_file.exists():
            return Response(
                "<html><body><h1>Fauxnos Server</h1><p>Web UI not found. Deploy web/ directory.</p></body></html>",
                mimetype="text/html",
                status=200
            )
        with open(index_file) as f:
            return Response(f.read(), mimetype="text/html")

    # ── Client management handlers ─────────────────────────────────────────────

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

            # Check if this is the server device
            is_server_device = False
            try:
                if request.remote_addr in ['127.0.0.1', '::1']:
                    is_server_device = True
                    self.log("Detected server device via localhost")
                else:
                    result = subprocess.run(['ip', 'addr', 'show'], capture_output=True, text=True)
                    if mac_address.lower() in result.stdout.lower():
                        is_server_device = True
                        self.log("Detected server device via MAC match")
            except Exception as e:
                self.log(f"Error in server device detection: {e}", "WARNING")

            # Determine client ID
            if is_server_device:
                existing_server = self.config_manager.get_client_config("fauxnos000")
                if existing_server:
                    next_id = self.config_manager.get_next_client_id()
                else:
                    next_id = "fauxnos000"
            else:
                next_id = self.config_manager.get_next_client_id()

            if not display_name:
                display_name = f"Fauxnos {next_id[-3:]}"

            try:
                new_client = self.config_manager.add_client(
                    name=display_name,
                    mac=mac_address,
                    client_id=next_id
                )

                # Auto-populate default sources and detect hardware capabilities
                aplay_output = data.get('aplay_output', '').lower()
                has_adc = 'dacplusadc' in aplay_output or 'dac+adc' in aplay_output
                default_sources = [
                    {"id": "spotify", "label": "Spotify", "type": "internal", "category": "default",
                     "sink": "snapsink", "starting_volume": 50, "volume_controller": "snapcast"},
                    {"id": "airplay", "label": "AirPlay", "type": "internal", "category": "default",
                     "sink": "snapsink", "starting_volume": 50, "volume_controller": "snapcast"},
                ]
                if has_adc:
                    default_sources.append(
                        {"id": "analog", "label": "Analog In", "type": "internal", "category": "default",
                         "sink": "analogsink", "starting_volume": 50, "volume_controller": "self"}
                    )
                for client_entry in self.config_manager.server_config.get("clients", []):
                    if client_entry.get("id") == new_client.id:
                        client_entry["has_adc"] = has_adc
                        if "sources" not in client_entry:
                            client_entry["sources"] = default_sources
                        break

                if not self.test_mode:
                    self.log("Deploying server infrastructure...")
                    from .deploy import DeploymentManager
                    deployer = DeploymentManager(self.config_manager)

                    if deployer.deploy_server_configs():
                        self.log("Server infrastructure deployed", "SUCCESS")

                        import time
                        try:
                            subprocess.run(["systemctl", "--user", "restart", "snapserver"],
                                         check=True, timeout=10)
                            time.sleep(2)
                        except Exception as e:
                            self.log(f"Failed to restart snapserver: {e}", "WARNING")

                        from .group_manager import assign_all_clients_to_home
                        if assign_all_clients_to_home(self.config_manager, dry_run=False):
                            self.log(f"Client {new_client.id} assigned to home group", "SUCCESS")
                        else:
                            self.log(f"Failed to assign {new_client.id} to home group", "WARNING")
                    else:
                        self.log("Server deployment failed", "ERROR")
                        return jsonify({"error": "Failed to deploy server infrastructure"}), 500

                self.config_manager.save_server_config()
                self.log(f"Client registered: {new_client.id}", "SUCCESS")

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
        try:
            client = self.config_manager.get_client(client_id)
            if not client:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            server_host = "fauxnos-server.local" if not self.test_mode else "localhost"
            return jsonify({
                "client_id": client.id,
                "server_port": client.server_port,
                "zeroconf_port": client.zeroconf_port,
                "go_librespot_monitor_url": f"http://{server_host}:{client.server_port}/player/volume",
                "note": "Client owns its own configuration."
            })
        except Exception as e:
            self.log(f"Config retrieval error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_list_clients(self):
        """Handle GET /api/clients"""
        try:
            clients = self.config_manager.get_all_clients()

            # Enrich with snapcast connection status
            snapcast_status = self._get_snapcast_client_status()
            raw_map = {c.get("id"): c for c in self.config_manager.server_config.get("clients", [])}

            return jsonify({
                "clients": [
                    {
                        "client_id": client.id,
                        "name": client.name,
                        "mac": client.mac,
                        "server_port": client.server_port,
                        "zeroconf_port": client.zeroconf_port,
                        "connected": snapcast_status.get(client.id, False),
                        "has_adc": raw_map.get(client.id, {}).get("has_adc", False),
                    }
                    for client in clients
                ]
            })
        except Exception as e:
            self.log(f"Client list error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def _get_client_raw(self, client_id: str) -> Optional[dict]:
        """Get raw client dict from server_config."""
        for client in self.config_manager.server_config.get("clients", []):
            if client.get("id") == client_id:
                return client
        return None

    def _get_snapcast_client_status(self) -> dict:
        """Query snapcast for connected clients. Returns {client_id: bool}."""
        try:
            rpc = self._snapcast_rpc("Server.GetStatus")
            if not rpc or "result" not in rpc:
                return {}
            groups = rpc["result"].get("server", {}).get("groups", [])
            status = {}
            for group in groups:
                for c in group.get("clients", []):
                    cid = c.get("id", "")
                    status[cid] = c.get("connected", False)
            return status
        except Exception:
            return {}

    def _snapcast_rpc(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        """Send JSON-RPC request to snapserver."""
        try:
            payload = json.dumps({
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": 1
            }).encode() + b"\r\n"

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", 1705))
            sock.sendall(payload)

            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    return json.loads(data.decode())
                except json.JSONDecodeError:
                    continue
            sock.close()
            return None
        except Exception:
            return None

    def handle_update_client(self, client_id: str):
        """Handle PUT /api/clients/<client_id>

        Accepts any subset of:
          - name: string  → rename client
          - has_adc: bool → mark client as having an analog input. The UI
            gates whether the "Analog In" built-in source row appears in
            the SourcesPanel on this flag. The actual source must also
            exist in the device's local client_config.yaml for switching
            and calibration to work end-to-end (install.sh sets that up
            automatically when the hifiberry-dacplusadc dt-overlay is
            detected).
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400

            updated_fields = {}

            # Optional rename
            if 'name' in data:
                new_name = data.get('name')
                if not new_name or not isinstance(new_name, str) or not new_name.strip():
                    return jsonify({"error": "name must be a non-empty string"}), 400
                if not self.config_manager.rename_client(client_id, new_name.strip()):
                    return jsonify({"error": f"Client {client_id} not found"}), 404
                updated_fields["name"] = new_name.strip()

            # Optional has_adc toggle — written directly to the raw client
            # entry in server_config.json (config_manager has no typed
            # helper for it, but the raw dict is the source of truth).
            if 'has_adc' in data:
                has_adc = bool(data.get('has_adc'))
                raw = self._get_client_raw(client_id)
                if raw is None:
                    return jsonify({"error": f"Client {client_id} not found"}), 404
                raw["has_adc"] = has_adc
                updated_fields["has_adc"] = has_adc

            if not updated_fields:
                return jsonify({"error": "No supported fields provided (name, has_adc)"}), 400

            self.config_manager.save_server_config()
            for k, v in updated_fields.items():
                self.log(f"Client {client_id} {k} → {v}", "SUCCESS")
            return jsonify({"status": "updated", **updated_fields})

        except Exception as e:
            self.log(f"Client update error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_delete_client(self, client_id: str):
        """Handle DELETE /api/clients/<client_id>"""
        try:
            if self.config_manager.remove_client(client_id):
                self.config_manager.save_server_config()
                self.log(f"Client {client_id} removed", "SUCCESS")
                return jsonify({"status": "deleted"})
            else:
                return jsonify({"error": f"Client {client_id} not found"}), 404
        except Exception as e:
            self.log(f"Client deletion error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    # ── Source management handlers ─────────────────────────────────────────────

    def _get_client_config_yaml_path(self, client_id: str) -> Optional[Path]:
        """Find a client's config.json or config.yaml on disk (if accessible)."""
        # Clients store their config locally; server can't directly access it.
        # This endpoint operates on server_config.json client metadata.
        # For source management via API, we store sources in server_config.json.
        return None

    def _get_client_sources(self, client_id: str) -> Optional[list]:
        """Get sources for a client from server_config."""
        for client in self.config_manager.server_config.get("clients", []):
            if client.get("id") == client_id:
                return client.get("sources", [])
        return None

    # Default built-in sources synthesized when a client has no explicit
    # `sources` array in server_config.json (e.g. when it was registered
    # via the install.sh CLI path rather than the API /register endpoint,
    # which IS what populates them). Mirrors the BUILTIN_DEFS / ANALOG_DEF
    # defs in web-ui/src/components/SourcesPanel.jsx so the UI sees the
    # same set of built-ins regardless of registration path.
    _DEFAULT_BUILTIN_SOURCES = [
        {"id": "spotify", "label": "Spotify", "type": "internal",
         "category": "default", "sink": "snapsink",
         "starting_volume": 50, "volume_controller": "snapcast"},
        {"id": "airplay", "label": "AirPlay", "type": "internal",
         "category": "default", "sink": "snapsink",
         "starting_volume": 50, "volume_controller": "snapcast"},
    ]
    _DEFAULT_ANALOG_SOURCE = {
        "id": "analog", "label": "Analog In", "type": "internal",
        "category": "default", "sink": "analogsink",
        "starting_volume": 50, "volume_controller": "self",
    }

    def _effective_client_sources(self, client_id: str) -> list:
        """Return the sources we expose to the UI for `client_id`.

        We always include the built-in defaults (spotify, airplay, plus
        analog if has_adc=true) and merge the explicit `sources` array
        from server_config.json on top. Explicit entries override
        synthesized ones by id (so a user can store external_switch
        config on a built-in without losing it). Custom sources from
        explicit are appended after the built-ins.

        Why merge rather than fall back wholesale: if a user added a
        single custom source via POST /api/clients/<id>/sources to a
        freshly-registered client (whose explicit array was empty),
        the built-in defaults would otherwise vanish from the dropdown
        because the array is no longer empty. Merging keeps them
        present until the user explicitly changes them via PUT.

        This is purely a read-side projection — nothing is written back
        to server_config.json. The YAML on the device remains the
        single source of truth for what the daemon actually owns.
        """
        raw = self._get_client_raw(client_id)
        if raw is None:
            return []
        explicit = list(raw.get("sources") or [])
        explicit_by_id = {s.get("id"): s for s in explicit if s.get("id")}

        # Start with synthesized built-ins, in canonical order
        synthesized = list(self._DEFAULT_BUILTIN_SOURCES)
        if raw.get("has_adc"):
            synthesized.append(dict(self._DEFAULT_ANALOG_SOURCE))

        merged = []
        seen_ids = set()
        for default_src in synthesized:
            sid = default_src["id"]
            if sid in explicit_by_id:
                merged.append(explicit_by_id[sid])
            else:
                merged.append(dict(default_src))
            seen_ids.add(sid)

        # Append any custom (non-built-in) sources from explicit, in order
        for s in explicit:
            sid = s.get("id")
            if sid and sid not in seen_ids:
                merged.append(s)
                seen_ids.add(sid)

        return merged

    def _set_client_sources(self, client_id: str, sources: list) -> bool:
        """Set sources for a client in server_config."""
        for client in self.config_manager.server_config.get("clients", []):
            if client.get("id") == client_id:
                client["sources"] = sources
                self.config_manager.save_server_config()
                return True
        return False

    def handle_get_sources(self, client_id: str):
        """Handle GET /api/clients/<client_id>/sources"""
        try:
            raw = self._get_client_raw(client_id)
            if raw is None:
                return jsonify({"error": f"Client {client_id} not found"}), 404
            # Use effective (merged built-ins + explicit) so the SourcesPanel
            # and the GroupCard dropdown agree on what sources exist.
            sources = self._effective_client_sources(client_id)
            return jsonify({"client_id": client_id, "sources": sources, "has_adc": raw.get("has_adc", False)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_replace_sources(self, client_id: str):
        """Handle PUT /api/clients/<client_id>/sources — replace all sources"""
        try:
            data = request.get_json()
            if not data or "sources" not in data:
                return jsonify({"error": "sources array required"}), 400

            if not self._set_client_sources(client_id, data["sources"]):
                return jsonify({"error": f"Client {client_id} not found"}), 404

            return jsonify({"status": "updated", "sources": data["sources"]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_add_source(self, client_id: str):
        """Handle POST /api/clients/<client_id>/sources — add one source"""
        try:
            data = request.get_json()
            if not data or "id" not in data or "type" not in data:
                return jsonify({"error": "source must have 'id' and 'type'"}), 400

            sources = self._get_client_sources(client_id)
            if sources is None:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            # Check for duplicate ID
            if any(s.get("id") == data["id"] for s in sources):
                return jsonify({"error": f"Source '{data['id']}' already exists"}), 409

            sources.append(data)
            self._set_client_sources(client_id, sources)
            return jsonify({"status": "added", "source": data}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_update_source(self, client_id: str, source_id: str):
        """Handle PUT /api/clients/<client_id>/sources/<source_id> — patch a single source"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "No JSON data provided"}), 400

            sources = self._get_client_sources(client_id)
            if sources is None:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            for source in sources:
                if source.get("id") == source_id:
                    for key, value in data.items():
                        source[key] = value
                    self._set_client_sources(client_id, sources)
                    return jsonify({"status": "updated", "source": source})

            # Source not found — upsert (create with provided data)
            new_source = {"id": source_id, **data}
            sources.append(new_source)
            self._set_client_sources(client_id, sources)
            return jsonify({"status": "created", "source": new_source}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_delete_source(self, client_id: str, source_id: str):
        """Handle DELETE /api/clients/<client_id>/sources/<source_id>"""
        try:
            sources = self._get_client_sources(client_id)
            if sources is None:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            new_sources = [s for s in sources if s.get("id") != source_id]
            if len(new_sources) == len(sources):
                return jsonify({"error": f"Source '{source_id}' not found"}), 404

            self._set_client_sources(client_id, new_sources)
            return jsonify({"status": "deleted"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Snapcast group handlers ────────────────────────────────────────────────

    def handle_get_groups(self):
        """Handle GET /api/groups — proxy to snapcast, enriched with home/stream info"""
        try:
            rpc = self._snapcast_rpc("Server.GetStatus")
            if not rpc or "result" not in rpc:
                return jsonify({"groups": [], "error": "Snapcast unavailable"}), 503

            server_data = rpc["result"].get("server", {})
            groups = server_data.get("groups", [])
            streams = server_data.get("streams", [])

            # Build home_group → client_id map from raw server config
            raw_clients = self.config_manager.server_config.get("clients", [])
            home_group_map = {}  # group_id → client_id
            for client in raw_clients:
                hg = client.get("home_group")
                if hg:
                    home_group_map[hg] = client.get("id")

            # Build available streams list
            stream_list = [{"id": s.get("id", ""), "status": s.get("status", "")} for s in streams]

            # Build raw client map for source lookup
            raw_map = {c.get("id"): c for c in raw_clients}

            # Enrich each group
            for group in groups:
                gid = group.get("id", "")
                group["home_client_id"] = home_group_map.get(gid)

                # Filter streams belonging to this group's home client
                home_cid = group.get("home_client_id")
                if home_cid:
                    group["available_streams"] = [
                        s for s in stream_list if home_cid in s["id"]
                    ]
                else:
                    group["available_streams"] = stream_list

                # Include home client's configured sources. Falls back to
                # synthesized built-ins (spotify/airplay/+analog) when the
                # client has no explicit sources array, so the dropdown
                # always reflects what the SourcesPanel shows.
                if home_cid:
                    group["sources"] = self._effective_client_sources(home_cid)
                else:
                    group["sources"] = []

            return jsonify({"groups": groups, "streams": stream_list})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_set_group_stream(self):
        """Handle POST /api/groups/stream — {group_id, stream_id}"""
        try:
            data = request.get_json()
            group_id = data.get("group_id")
            stream_id = data.get("stream_id")
            if not group_id or not stream_id:
                return jsonify({"error": "group_id and stream_id required"}), 400

            rpc = self._snapcast_rpc("Group.SetStream", {"id": group_id, "stream_id": stream_id})
            if rpc and "result" in rpc:
                return jsonify({"status": "ok"})
            else:
                return jsonify({"error": "Failed to set stream"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_set_group_source(self):
        """Handle POST /api/groups/source — {group_id, home_client_id, source_id}

        Switches the active source for a group:
        1. Sets snapcast stream if one exists for this source
        2. Calls external switch API if configured on the source
        3. Publishes MQTT mode change
        """
        try:
            data = request.get_json()
            group_id = data.get("group_id")
            home_client_id = data.get("home_client_id")
            source_id = data.get("source_id")
            if not group_id or not home_client_id or not source_id:
                return jsonify({"error": "group_id, home_client_id, and source_id required"}), 400

            results = {"source_id": source_id}

            # 1. Try to set snapcast stream
            expected_stream = f"source_{home_client_id}_{source_id}"
            rpc = self._snapcast_rpc("Server.GetStatus")
            if rpc and "result" in rpc:
                streams = rpc["result"].get("server", {}).get("streams", [])
                stream_exists = any(s.get("id") == expected_stream for s in streams)
                if stream_exists:
                    set_rpc = self._snapcast_rpc("Group.SetStream", {"id": group_id, "stream_id": expected_stream})
                    results["stream_set"] = bool(set_rpc and "result" in set_rpc)
                else:
                    results["stream_set"] = False
                    results["stream_note"] = f"No stream '{expected_stream}'"

            # 2. Call external API if configured
            raw_client = self._get_client_raw(home_client_id)
            if raw_client:
                sources = raw_client.get("sources", [])
                source_cfg = next((s for s in sources if s.get("id") == source_id), None)
                if source_cfg:
                    # Built-in sources: API config under external_switch
                    ext = source_cfg.get("external_switch", {})
                    # Custom/external sources: API config at top level
                    api_url = ext.get("control_api") if ext.get("enabled") else None
                    api_payload = ext.get("control_payload", {})
                    api_content_type = ext.get("content_type", "json")
                    if not api_url and source_cfg.get("control_api"):
                        api_url = source_cfg["control_api"]
                        api_payload = source_cfg.get("control_payload", {})
                        api_content_type = source_cfg.get("content_type", "json")
                    if api_url:
                        try:
                            if api_content_type == "form":
                                resp = http_requests.post(api_url, data=api_payload, timeout=5)
                            else:
                                resp = http_requests.post(api_url, json=api_payload, timeout=5)
                            results["external_api"] = {"status": resp.status_code, "ok": resp.status_code == 200}
                        except Exception as e:
                            results["external_api"] = {"error": str(e)}

            # 3. Publish MQTT mode change
            try:
                subprocess.run(
                    ["mosquitto_pub", "-t", f"set/clients/{home_client_id}/mode", "-m", source_id],
                    timeout=2, capture_output=True
                )
                results["mqtt_mode"] = True
            except Exception:
                results["mqtt_mode"] = False

            return jsonify({"status": "ok", "results": results})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_join_group(self):
        """Handle POST /api/groups/join — {client_id, target_client_id}"""
        try:
            data = request.get_json()
            client_id = data.get("client_id")
            target_client_id = data.get("target_client_id")
            if not client_id or not target_client_id:
                return jsonify({"error": "client_id and target_client_id required"}), 400

            from .group_manager import SnapcastGroupManager
            gm = SnapcastGroupManager(config_manager=self.config_manager)
            if gm.join_client_to_group(client_id, target_client_id):
                return jsonify({"status": "joined"})
            else:
                return jsonify({"error": "Failed to join group"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def handle_return_home(self):
        """Handle POST /api/groups/return-home — {client_id}"""
        try:
            data = request.get_json() or {}
            client_id = data.get("client_id")

            from .group_manager import SnapcastGroupManager, assign_all_clients_to_home
            gm = SnapcastGroupManager(config_manager=self.config_manager)

            if client_id:
                success = gm.return_client_to_home(client_id)
            else:
                success = gm.return_all_clients_to_home()

            if success:
                return jsonify({"status": "ok"})
            else:
                return jsonify({"error": "Failed to return home"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Status handlers ────────────────────────────────────────────────────────

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

    def handle_get_server_status(self):
        """Handle GET /api/server/status — full system status"""
        try:
            clients = self.config_manager.get_all_clients()
            snapcast_status = self._get_snapcast_client_status()

            # Service states
            services = {}
            user_services = ["snapserver", "fauxnos-fifo-setup", "snapclient-fauxnos000"]
            for client in clients:
                user_services.append(f"go-librespot-{client.id}")

            for svc in user_services:
                try:
                    result = subprocess.run(
                        ["systemctl", "--user", "is-active", svc],
                        capture_output=True, text=True, timeout=3
                    )
                    services[svc] = {"active": result.stdout.strip() == "active", "scope": "user"}
                except Exception:
                    services[svc] = {"active": False, "scope": "user"}

            for svc in ["mosquitto", "avahi-daemon"]:
                try:
                    result = subprocess.run(
                        ["systemctl", "is-active", svc],
                        capture_output=True, text=True, timeout=3
                    )
                    services[svc] = {"active": result.stdout.strip() == "active", "scope": "system"}
                except Exception:
                    services[svc] = {"active": False, "scope": "system"}

            # Snapcast groups
            rpc = self._snapcast_rpc("Server.GetStatus")
            groups = []
            if rpc and "result" in rpc:
                groups = rpc["result"].get("server", {}).get("groups", [])

            return jsonify({
                "status": "running",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hostname": os.uname().nodename,
                "clients": [
                    {
                        "client_id": c.id,
                        "name": c.name,
                        "connected": snapcast_status.get(c.id, False),
                    }
                    for c in clients
                ],
                "services": services,
                "snapcast_groups": len(groups),
            })
        except Exception as e:
            self.log(f"Server status error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    # ── Install / onboarding handlers ──────────────────────────────────────────

    def handle_get_firstrun_sh(self):
        """Handle GET /api/install/firstrun.sh — generate zero-touch bootstrap"""
        display_name = request.args.get("display_name", "")

        # Sanitize display_name (shell safety)
        display_name = display_name.replace('"', '').replace("'", '').replace(';', '')[:64]

        script = self._generate_firstrun_sh(display_name)
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=firstrun.sh"}
        )

    def _generate_firstrun_sh(self, display_name: str = "") -> str:
        return f"""#!/bin/bash
# Fauxnos Client Bootstrap - Generated by fauxnos-server
# Place this file in /boot/firmware/ on your Raspberry Pi SD card.
# It will run automatically on first boot, install the client, and register
# with the fauxnos server. The file self-deletes after running.
#
# Generated: {datetime.now(timezone.utc).isoformat()}
# Server: fauxnos000.local

FAUXNOS_SERVER_HOST="fauxnos000.local"
DISPLAY_NAME="{display_name}"

# Wait for network and mDNS resolution (up to 120 seconds)
echo "[fauxnos] Waiting for network..."
for i in $(seq 1 24); do
  if avahi-resolve -n "$FAUXNOS_SERVER_HOST" &>/dev/null 2>&1; then
    echo "[fauxnos] Server found: $FAUXNOS_SERVER_HOST"
    break
  fi
  echo "[fauxnos] Waiting ($((i*5))s)..."
  sleep 5
done

# Download and run install script from server
export FAUXNOS_SERVER_HOST DISPLAY_NAME
echo "[fauxnos] Starting install from http://${{FAUXNOS_SERVER_HOST}}:8080/api/install/client.sh"
curl -sSL "http://${{FAUXNOS_SERVER_HOST}}:8080/api/install/client.sh" | bash

# Self-delete
rm -- "$0"
"""

    def handle_get_client_sh(self):
        """Handle GET /api/install/client.sh — serve client install script with server URL injected"""
        if not CLIENT_INSTALL_SCRIPT.exists():
            return Response(
                f"# Client install script not found at {CLIENT_INSTALL_SCRIPT}",
                mimetype="text/plain",
                status=404
            )

        with open(CLIENT_INSTALL_SCRIPT) as f:
            content = f.read()

        # Inject FAUXNOS_SERVER_URL so install.sh downloads files from this server
        # instead of GitHub, ensuring clients always get the current server's copy
        server_host = request.host  # includes port if non-standard
        server_url = f"http://{server_host}"
        content = content.replace(
            'REPO_URL="https://raw.githubusercontent.com/dmayman/fauxnos/main"',
            f'REPO_URL="https://raw.githubusercontent.com/dmayman/fauxnos/main"\nFAUXNOS_SERVER_URL="{server_url}"'
        )

        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=client-install.sh"}
        )

    def handle_serve_client_file(self, filepath: str):
        """Handle GET /api/install/files/client/<path> — serve individual client files"""
        # Prevent path traversal
        try:
            safe_path = (CLIENT_DIR / filepath).resolve()
            safe_path.relative_to(CLIENT_DIR.resolve())
        except (ValueError, RuntimeError):
            abort(403)

        if not safe_path.exists():
            abort(404)

        return send_from_directory(str(CLIENT_DIR), filepath)

    # ── MQTT mode listener ─────────────────────────────────────────────────────

    def start_mqtt_listener(self):
        """Start MQTT listener for mode status messages.

        When a client publishes its active mode (source), trigger the
        corresponding external API call if one is configured.  This keeps
        external hardware (e.g. Particle Photon input mux) in sync on boot
        and whenever the source changes from any control surface.
        """
        import paho.mqtt.client as mqtt_lib
        import threading

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                client.subscribe("status/clients/+/mode")
                self.log("MQTT listener connected, subscribed to mode status")

        def on_message(client, userdata, msg):
            parts = msg.topic.split("/")
            if len(parts) < 4:
                return
            client_id = parts[2]
            source_id = msg.payload.decode().strip()
            if not source_id:
                return
            self._trigger_external_for_source(client_id, source_id)

        mqtt_client = mqtt_lib.Client()
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        try:
            mqtt_client.connect("localhost", 1883, 60)
        except Exception as e:
            self.log(f"MQTT listener failed to connect: {e}", "ERROR")
            return
        self._mqtt_client = mqtt_client
        t = threading.Thread(target=mqtt_client.loop_forever, daemon=True)
        t.start()

    def _trigger_external_for_source(self, client_id: str, source_id: str):
        """Look up a client's source config and fire external API if present."""
        raw_client = self._get_client_raw(client_id)
        if not raw_client:
            return
        sources = raw_client.get("sources", [])
        source_cfg = next((s for s in sources if s.get("id") == source_id), None)
        if not source_cfg:
            return

        # Built-in sources: API under external_switch
        ext = source_cfg.get("external_switch", {})
        api_url = ext.get("control_api") if ext.get("enabled") else None
        api_payload = ext.get("control_payload", {})
        api_content_type = ext.get("content_type", "json")
        # Custom/external sources: API at top level
        if not api_url and source_cfg.get("control_api"):
            api_url = source_cfg["control_api"]
            api_payload = source_cfg.get("control_payload", {})
            api_content_type = source_cfg.get("content_type", "json")
        if not api_url:
            return

        try:
            if api_content_type == "form":
                resp = http_requests.post(api_url, data=api_payload, timeout=5)
            else:
                resp = http_requests.post(api_url, json=api_payload, timeout=5)
            self.log(f"External API for {client_id}/{source_id}: {resp.status_code}", "SUCCESS")
        except Exception as e:
            self.log(f"External API error for {client_id}/{source_id}: {e}", "WARNING")

    # ── Server runner ──────────────────────────────────────────────────────────

    def run(self, host: str = '0.0.0.0', port: int = 8080, debug: bool = False):
        self.log(f"Starting Fauxnos API Server on {host}:{port}")
        if self.test_mode:
            self.log("Running in TEST MODE", "WARNING")
        app.run(host=host, port=port, debug=debug)


def main():
    parser = argparse.ArgumentParser(description="Fauxnos API Server")
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()

    server = FauxnosAPIServer(test_mode=args.test, verbose=args.verbose)
    server.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
