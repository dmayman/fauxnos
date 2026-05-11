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
import queue as queue_mod
import time
import requests as http_requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, jsonify, Response, send_from_directory, abort, stream_with_context
from typing import Optional

from .config_manager import ConfigManager, ClientConfig
from .install_runner import InstallManager, InstallAlreadyRunning, DEFAULT_KEY_PATH
from .dac_overlays import (
    ALLOWED_OVERLAYS,
    DAC_OVERLAYS,
    DEFAULT_OVERLAY,
    SERVER_OVERLAY,
    is_allowed as _dac_is_allowed,
    remote_apply as _dac_remote_apply,
)

# Path to the web UI static files (relative to this module's location)
_SERVER_DIR = Path(__file__).parent.parent
WEB_DIR = _SERVER_DIR / "web"
CLIENT_INSTALL_SCRIPT = _SERVER_DIR.parent / "fauxnos-client" / "install.sh"
CLIENT_DIR = CLIENT_INSTALL_SCRIPT.parent

# Point Flask's built-in static handler at web/ so /static/style.css etc. work
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path='/static')


def _sse_event(event_type: str, data) -> str:
    """Format an SSE event the way the spec wants: blank line terminator."""
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


class FauxnosAPIServer:
    def __init__(self, config_manager: Optional[ConfigManager] = None, test_mode: bool = False, verbose: bool = False):
        self.test_mode = test_mode
        self.verbose = verbose
        self.config_manager = config_manager or ConfigManager(test_mode=test_mode)
        # Singleton InstallManager — drives the Add Device wizard. The runner
        # injections let it call back into our snapcast/client status without
        # re-implementing the JSON-RPC plumbing.
        self.install_manager = InstallManager(
            server_host="fauxnos000.local",
            client_status_fn=self._list_clients_for_runner,
            snapcast_status_fn=self._get_snapcast_client_status,
            on_install_succeeded=self._cleanup_after_install,
        )
        # IR learn pub/sub: per-client list of SSE subscriber queues
        # + last-seen event payload (delivered as a snapshot when a new
        # subscriber connects so a late tab catches an in-flight learn).
        # Keyed by client_id. Guarded by _ir_learn_lock.
        import threading as _threading
        self._ir_learn_subscribers: dict = {}
        self._ir_learn_last_event: dict = {}
        self._ir_learn_lock = _threading.Lock()
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

        @app.route('/api/clients/<client_id>/dac_overlay/apply', methods=['POST'])
        def apply_dac_overlay(client_id):
            return self.handle_apply_dac_overlay(client_id)

        @app.route('/api/dac_overlays', methods=['GET'])
        def list_dac_overlays():
            return jsonify({
                "overlays": [{"id": oid, "label": lbl} for oid, lbl in DAC_OVERLAYS],
                "default": DEFAULT_OVERLAY,
            })

        # ── IR remote (per-client hardware remote) ────────────────────────────
        # GET returns the server's cached mirror of the client's ir state.
        # PUT accepts {"enabled": bool} and/or {"clear": "command_id"} and
        # publishes the corresponding MQTT command to the client; the
        # client applies + echoes back via status/clients/<id>/ir/state,
        # which our MQTT listener catches and writes into server_config.
        # Learn endpoints live in phase 4 under .../ir/learn.

        @app.route('/api/clients/<client_id>/ir', methods=['GET'])
        def get_client_ir(client_id):
            return self.handle_get_client_ir(client_id)

        @app.route('/api/clients/<client_id>/ir', methods=['PUT'])
        def put_client_ir(client_id):
            return self.handle_put_client_ir(client_id)

        @app.route('/api/clients/<client_id>/ir/learn', methods=['POST'])
        def start_client_ir_learn(client_id):
            return self.handle_start_client_ir_learn(client_id)

        @app.route('/api/clients/<client_id>/ir/learn/cancel', methods=['POST'])
        def cancel_client_ir_learn(client_id):
            return self.handle_cancel_client_ir_learn(client_id)

        @app.route('/api/clients/<client_id>/ir/stream', methods=['GET'])
        def stream_client_ir(client_id):
            return self.handle_stream_client_ir(client_id)

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

        @app.route('/api/snapcast/cleanup-orphans', methods=['POST'])
        def cleanup_snapcast_orphans():
            return self.handle_cleanup_orphans()

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

        # ── Server-driven install (Add Device wizard) ─────────────────────────

        @app.route('/api/install/server-pubkey', methods=['GET'])
        def get_server_pubkey():
            return self.handle_get_server_pubkey()

        @app.route('/api/install/start', methods=['POST'])
        def start_install():
            return self.handle_start_install()

        @app.route('/api/install/status', methods=['GET'])
        def install_status():
            return self.handle_install_status()

        @app.route('/api/install/stream', methods=['GET'])
        def install_stream():
            return self.handle_install_stream()

        @app.route('/api/install/cancel', methods=['POST'])
        def cancel_install():
            return self.handle_cancel_install()

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
                        # dac_overlay: server is locked to SERVER_OVERLAY.
                        # Clients default to DEFAULT_OVERLAY when nothing has
                        # been written yet (pre-existing clients from before
                        # this field was added). UI shows the dropdown as
                        # disabled for fauxnos000.
                        "dac_overlay": (
                            SERVER_OVERLAY if client.id == "fauxnos000"
                            else (raw_map.get(client.id, {}).get("dac_overlay") or DEFAULT_OVERLAY)
                        ),
                        "dac_overlay_locked": client.id == "fauxnos000",
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

    def _snapcast_delete_client(self, snapcast_id: str) -> bool:
        """Delete a client from snapserver's persistent state.

        Snapserver remembers every client that has ever connected — disconnect
        only flips connected=false, the registration (group, volume, last-seen)
        sticks around forever in ~/.config/snapserver/server.json. This sends
        Server.DeleteClient which is the only way to actually remove it.
        Returns True on RPC success.
        """
        rpc = self._snapcast_rpc("Server.DeleteClient", {"id": snapcast_id})
        return bool(rpc and "result" in rpc)

    def _get_snapcast_clients_full(self) -> list:
        """Return [{id, connected, host_mac, host_name, group_id}, …] for every
        client snapserver knows about. Used by orphan-cleanup and the extended
        DELETE /api/clients/<id> path which need to match by MAC as well as id."""
        out = []
        rpc = self._snapcast_rpc("Server.GetStatus")
        if not rpc or "result" not in rpc:
            return out
        for group in rpc["result"].get("server", {}).get("groups", []):
            for c in group.get("clients", []):
                host = c.get("host", {}) or {}
                out.append({
                    "id": c.get("id", ""),
                    "connected": bool(c.get("connected", False)),
                    "host_mac": (host.get("mac") or "").lower(),
                    "host_name": host.get("name", ""),
                    "group_id": group.get("id", ""),
                })
        return out

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

            # Optional dac_overlay update — saves only; the install path
            # picks it up next time install.sh runs against this device.
            # Use POST /api/clients/<id>/dac_overlay/apply to push the
            # change live (rewrite config.txt + reboot). The server's own
            # overlay is locked at SERVER_OVERLAY because the analog-input
            # source detection in the server install keys off it.
            if 'dac_overlay' in data:
                if client_id == "fauxnos000":
                    return jsonify({"error": "server overlay is locked"}), 400
                overlay = (data.get('dac_overlay') or "").strip()
                if not _dac_is_allowed(overlay):
                    return jsonify({
                        "error": f"unknown dac_overlay '{overlay}'",
                        "allowed": sorted(ALLOWED_OVERLAYS),
                    }), 400
                raw = self._get_client_raw(client_id)
                if raw is None:
                    return jsonify({"error": f"Client {client_id} not found"}), 404
                raw["dac_overlay"] = overlay
                updated_fields["dac_overlay"] = overlay

            if not updated_fields:
                return jsonify({"error": "No supported fields provided (name, has_adc, dac_overlay)"}), 400

            self.config_manager.save_server_config()
            for k, v in updated_fields.items():
                self.log(f"Client {client_id} {k} → {v}", "SUCCESS")
            return jsonify({"status": "updated", **updated_fields})

        except Exception as e:
            self.log(f"Client update error: {e}", "ERROR")
            return jsonify({"error": "Internal server error"}), 500

    def handle_apply_dac_overlay(self, client_id: str):
        """Handle POST /api/clients/<client_id>/dac_overlay/apply.

        SSHes into the client at <client_id>.local using the server's
        install key, rewrites /boot/firmware/config.txt to use the
        currently-saved dac_overlay value, and schedules a reboot. Returns
        as soon as the reboot is scheduled (~2s out) — the device will be
        offline for 30-60s on a Pi Zero 2 W.

        Body is optional. If `{"dac_overlay": "<id>"}` is provided, that
        value is saved first (same validation as PUT) and then applied
        atomically. Otherwise the currently-saved value is applied. The
        server's own overlay is locked.
        """
        try:
            if client_id == "fauxnos000":
                return jsonify({"error": "server overlay is locked"}), 400

            raw = self._get_client_raw(client_id)
            if raw is None:
                return jsonify({"error": f"Client {client_id} not found"}), 404

            data = request.get_json(silent=True) or {}
            if 'dac_overlay' in data:
                overlay = (data.get('dac_overlay') or "").strip()
                if not _dac_is_allowed(overlay):
                    return jsonify({
                        "error": f"unknown dac_overlay '{overlay}'",
                        "allowed": sorted(ALLOWED_OVERLAYS),
                    }), 400
                raw["dac_overlay"] = overlay
                self.config_manager.save_server_config()
            else:
                overlay = raw.get("dac_overlay") or DEFAULT_OVERLAY

            target_host = f"{client_id}.local"
            self.log(f"Applying dac_overlay={overlay} to {target_host}", "INFO")
            ok, msg = _dac_remote_apply(target_host, overlay)
            if not ok:
                self.log(f"Apply dac_overlay failed: {msg}", "ERROR")
                return jsonify({"error": msg}), 502
            self.log(f"Apply dac_overlay ok: {msg}", "SUCCESS")
            return jsonify({
                "status": "applied",
                "client_id": client_id,
                "dac_overlay": overlay,
                "target_host": target_host,
                "message": msg,
                # Hint for the UI's reboot-watch state. Pi Zero 2 W is the
                # slowest target; bigger Pis come back faster.
                "expected_reboot_seconds": 60,
            })
        except Exception as e:
            self.log(f"Apply dac_overlay error: {e}", "ERROR")
            return jsonify({"error": f"Internal server error: {e}"}), 500

    # ── IR remote handlers ────────────────────────────────────────────────────

    # Canonical command IDs for the hardware-remote feature. Must match
    # COMMAND_IDS in client/modules/ir_listener.py.
    IR_COMMAND_IDS = (
        'volume_up', 'volume_down', 'mute', 'source_cycle',
        'play_pause', 'next', 'previous',
    )

    @staticmethod
    def _empty_ir_block() -> dict:
        return {'enabled': False, 'mappings': {}}

    def handle_get_client_ir(self, client_id: str):
        """GET /api/clients/<id>/ir — return server's cached mirror.

        The client (modules/ir_listener.py) owns the source of truth in
        client_state.json; the server's mirror is updated on every
        status/clients/<id>/ir/state MQTT message AND on every hello.
        Returns the empty block if we haven't seen this client yet.
        """
        raw = self._get_client_raw(client_id)
        if raw is None:
            return jsonify({"error": f"Client {client_id} not found"}), 404
        ir = raw.get('ir') or self._empty_ir_block()
        return jsonify({
            'client_id': client_id,
            'ir': {
                'enabled': bool(ir.get('enabled', False)),
                'mappings': dict(ir.get('mappings') or {}),
            },
        })

    def handle_put_client_ir(self, client_id: str):
        """PUT /api/clients/<id>/ir — toggle enabled or clear a mapping.

        Body (any combination):
          {"enabled": true|false}        → publishes set/.../ir/enabled
          {"clear": "<command_id>"}      → publishes set/.../ir/clear/<cmd>

        Both effects are fire-and-forget over MQTT: the client applies
        the change and echoes back via status/clients/<id>/ir/state,
        which the MQTT listener catches and writes into server_config.
        We return the (possibly-stale) current mirror so the UI can do
        an optimistic update.

        Learning is handled by a separate endpoint in phase 4.
        """
        raw = self._get_client_raw(client_id)
        if raw is None:
            return jsonify({"error": f"Client {client_id} not found"}), 404

        data = request.get_json(silent=True) or {}
        published = []

        if 'enabled' in data:
            enabled = bool(data['enabled'])
            ok = self._publish_mqtt(
                f"set/clients/{client_id}/ir/enabled",
                "true" if enabled else "false",
            )
            if not ok:
                return jsonify({"error": "MQTT broker unreachable"}), 502
            published.append('enabled')

        if 'clear' in data:
            command_id = data['clear']
            if command_id not in self.IR_COMMAND_IDS:
                return jsonify({
                    "error": f"unknown command_id '{command_id}'",
                    "allowed": list(self.IR_COMMAND_IDS),
                }), 400
            ok = self._publish_mqtt(
                f"set/clients/{client_id}/ir/clear/{command_id}",
                "",
            )
            if not ok:
                return jsonify({"error": "MQTT broker unreachable"}), 502
            published.append(f'clear:{command_id}')

        if not published:
            return jsonify({
                "error": "No supported fields provided (enabled, clear)",
            }), 400

        # Return current mirror; the client's echo will update it shortly.
        return jsonify({
            'client_id': client_id,
            'published': published,
            'ir': raw.get('ir') or self._empty_ir_block(),
        })

    def _publish_mqtt(self, topic: str, payload: str) -> bool:
        """Publish a one-shot MQTT message via the server's listener client.

        Returns False if the broker connection isn't up. We piggyback on
        the listener client (started by start_mqtt_listener) so we don't
        need a second client just to publish.
        """
        client = getattr(self, '_mqtt_client', None)
        if client is None:
            self.log("MQTT publish skipped: no listener client", "WARNING")
            return False
        try:
            result = client.publish(topic, payload)
            # paho returns MQTTMessageInfo; rc=0 means queued for send.
            return getattr(result, 'rc', 1) == 0
        except Exception as e:
            self.log(f"MQTT publish error on {topic}: {e}", "ERROR")
            return False

    def handle_start_client_ir_learn(self, client_id: str):
        """POST /api/clients/<id>/ir/learn.

        Body: {"command_id": "<id>", "timeout_s": <number>}.
        timeout_s defaults to 15 if omitted, clamped to [1, 60].

        Publishes set/clients/<id>/ir/learn/start over MQTT. The client
        echoes the started/captured/timeout/cancelled lifecycle via
        status/clients/<id>/ir/learn_event, which our MQTT listener
        catches and broadcasts to /ir/stream subscribers.

        202 if accepted (the client is the authority on whether it can
        actually enter learn mode — e.g. listener might be disabled, in
        which case it'll publish a 'rejected' learn_event back).
        """
        if self._get_client_raw(client_id) is None:
            return jsonify({"error": f"Client {client_id} not found"}), 404
        data = request.get_json(silent=True) or {}
        command_id = data.get('command_id')
        if command_id not in self.IR_COMMAND_IDS:
            return jsonify({
                "error": f"unknown command_id '{command_id}'",
                "allowed": list(self.IR_COMMAND_IDS),
            }), 400
        try:
            timeout_s = float(data.get('timeout_s', 15.0))
        except (TypeError, ValueError):
            return jsonify({"error": "timeout_s must be a number"}), 400
        timeout_s = max(1.0, min(60.0, timeout_s))

        payload = json.dumps({
            'command_id': command_id,
            'timeout_s': timeout_s,
        })
        ok = self._publish_mqtt(
            f"set/clients/{client_id}/ir/learn/start", payload
        )
        if not ok:
            return jsonify({"error": "MQTT broker unreachable"}), 502
        return jsonify({
            'status': 'accepted',
            'client_id': client_id,
            'command_id': command_id,
            'timeout_s': timeout_s,
        }), 202

    def handle_cancel_client_ir_learn(self, client_id: str):
        """POST /api/clients/<id>/ir/learn/cancel — abort any in-flight learn."""
        if self._get_client_raw(client_id) is None:
            return jsonify({"error": f"Client {client_id} not found"}), 404
        ok = self._publish_mqtt(
            f"set/clients/{client_id}/ir/learn/cancel", ""
        )
        if not ok:
            return jsonify({"error": "MQTT broker unreachable"}), 502
        return jsonify({'status': 'cancel_published', 'client_id': client_id}), 202

    def handle_stream_client_ir(self, client_id: str):
        """GET /api/clients/<id>/ir/stream — SSE of learn_event payloads.

        Pattern matches install_runner's subscriber model. The new tab
        gets the last-seen event as a snapshot so a learn in progress
        is visible immediately. Heartbeats every 15s keep proxies happy.
        """
        if self._get_client_raw(client_id) is None:
            return jsonify({"error": f"Client {client_id} not found"}), 404
        q = self._ir_learn_subscribe(client_id)

        @stream_with_context
        def gen():
            try:
                last_heartbeat = time.time()
                while True:
                    # Wait up to 5s for an event; emit heartbeat at 15s.
                    try:
                        ev = q.get(timeout=5.0)
                        yield _sse_event(ev['type'], ev['data'])
                    except queue_mod.Empty:
                        pass
                    now = time.time()
                    if now - last_heartbeat >= 15.0:
                        yield ": heartbeat\n\n"
                        last_heartbeat = now
            finally:
                self._ir_learn_unsubscribe(client_id, q)

        return Response(gen(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        })

    def _ir_learn_subscribe(self, client_id: str):
        """Register a new SSE subscriber queue; deliver the last event as snapshot."""
        q = queue_mod.Queue(maxsize=200)
        with self._ir_learn_lock:
            self._ir_learn_subscribers.setdefault(client_id, []).append(q)
            last = self._ir_learn_last_event.get(client_id)
        if last is not None:
            try:
                q.put_nowait({'type': 'snapshot', 'data': last})
            except queue_mod.Full:
                pass
        return q

    def _ir_learn_unsubscribe(self, client_id: str, q):
        with self._ir_learn_lock:
            subs = self._ir_learn_subscribers.get(client_id)
            if subs and q in subs:
                subs.remove(q)
            if subs is not None and not subs:
                self._ir_learn_subscribers.pop(client_id, None)

    def _ir_learn_emit(self, client_id: str, payload: dict):
        """Cache + broadcast a learn_event to all subscribers for this client."""
        with self._ir_learn_lock:
            self._ir_learn_last_event[client_id] = payload
            subs = list(self._ir_learn_subscribers.get(client_id, []))
        event = {'type': 'learn_event', 'data': payload}
        for q in subs:
            try:
                q.put_nowait(event)
            except queue_mod.Full:
                # Slow consumer — drop oldest so the live stream keeps up.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    def _ingest_client_ir_state(self, client_id: str, ir_block: dict):
        """Write the client's ir state into server_config (mirror update).

        Called from the MQTT listener for both status/.../ir/state and
        hello payloads. Idempotent — skips the disk write if the value
        is unchanged (hello fires often during startup).
        """
        raw = self._get_client_raw(client_id)
        if raw is None:
            return
        new_ir = {
            'enabled': bool(ir_block.get('enabled', False)),
            'mappings': dict(ir_block.get('mappings') or {}),
        }
        old_ir = raw.get('ir')
        if old_ir == new_ir:
            return
        raw['ir'] = new_ir
        try:
            self.config_manager.save_server_config()
            self.log(
                f"ir mirror updated for {client_id}: "
                f"enabled={new_ir['enabled']}, "
                f"mappings={sum(1 for v in new_ir['mappings'].values() if v)} set",
                "INFO",
            )
        except Exception as e:
            self.log(f"Failed to persist ir mirror for {client_id}: {e}", "ERROR")

    def handle_delete_client(self, client_id: str):
        """Handle DELETE /api/clients/<client_id>.

        Removes the device from server_config.json AND scrubs snapserver's
        record so the offline card disappears from Groups for good. Matches
        snapcast clients by id OR by MAC — orphan registrations from before
        a hostname rename keep the MAC as their snapcast id, so id-only
        matching would miss them. Snapcast deletes are best-effort and
        don't fail the request; the device-config delete is authoritative.
        """
        try:
            # Capture the MAC before deletion so we can match snapcast orphans.
            target_mac = ""
            for c in self.config_manager.server_config.get("clients", []):
                if c.get("id") == client_id:
                    target_mac = (c.get("mac") or "").lower()
                    break

            if not self.config_manager.remove_client(client_id):
                return jsonify({"error": f"Client {client_id} not found"}), 404
            self.config_manager.save_server_config()

            deleted_snapcast = []
            try:
                for sc in self._get_snapcast_clients_full():
                    if sc["id"] == client_id or (target_mac and sc["host_mac"] == target_mac):
                        if self._snapcast_delete_client(sc["id"]):
                            deleted_snapcast.append(sc["id"])
            except Exception as sc_err:
                self.log(f"Snapcast cleanup for {client_id} failed: {sc_err}", "WARNING")

            self.log(f"Client {client_id} removed (snapcast cleared: {deleted_snapcast})", "SUCCESS")
            return jsonify({"status": "deleted", "snapcast_deleted": deleted_snapcast})
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
        """Handle GET /api/groups — proxy to snapcast, enriched with home/stream info.

        Filters offline snapclients from each group's `clients` array, and
        drops any group that empties out as a result. The server-side filter
        is the "groups come and go as devices come online/offline" rule:
        when a Pi powers off its card vanishes from Groups, but its persistent
        config (sources, has_adc, custom external_switch APIs) lives in
        server_config.json — untouched here — so the device pops back into
        Groups intact when its snapclient reconnects. snapserver retains the
        offline registration too, preserving group memberships and volumes.
        """
        try:
            rpc = self._snapcast_rpc("Server.GetStatus")
            if not rpc or "result" not in rpc:
                return jsonify({"groups": [], "error": "Snapcast unavailable"}), 503

            server_data = rpc["result"].get("server", {})
            groups = server_data.get("groups", [])
            streams = server_data.get("streams", [])

            # Hide offline snapclients (Layer A). Drop empty groups.
            visible_groups = []
            for g in groups:
                g["clients"] = [c for c in g.get("clients", []) if c.get("connected")]
                if g["clients"]:
                    visible_groups.append(g)
            groups = visible_groups

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

    def handle_cleanup_orphans(self):
        """Handle POST /api/snapcast/cleanup-orphans.

        Walks snapserver's client registry and deletes any client whose `id`
        is NOT a registered fauxnos device (i.e. not in
        server_config.json's clients[].id). Common cause of orphans: during
        a fresh install the snapclient registers with snapserver while the
        Pi is still under its Pi-Imager hostname (`fauxnos-client`) — the
        registration uses the MAC as its id and lingers after the rename to
        `fauxnos001`. Idempotent. Registered-but-disconnected clients are
        intentionally left alone so volume/group memberships persist across
        power-cycles.
        """
        registered = {
            (c.get("id") or "")
            for c in self.config_manager.server_config.get("clients", [])
        }
        registered.discard("")
        snapcast_clients = self._get_snapcast_clients_full()
        deleted = []
        failed = []
        for sc in snapcast_clients:
            if sc["id"] in registered:
                continue
            if self._snapcast_delete_client(sc["id"]):
                deleted.append({
                    "id": sc["id"],
                    "host_name": sc["host_name"],
                    "host_mac": sc["host_mac"],
                })
            else:
                failed.append({"id": sc["id"], "host_name": sc["host_name"]})
        self.log(
            f"Cleanup orphans: deleted={len(deleted)} failed={len(failed)} "
            f"registered={len(registered)} total_snapcast={len(snapcast_clients)}",
            "INFO",
        )
        return jsonify({
            "deleted": deleted,
            "failed": failed,
            "registered_count": len(registered),
        })

    def _cleanup_after_install(self, client_id: Optional[str]):
        """Hook called by InstallRunner after a successful install.

        Two things happen here:
          1) handle_cleanup_orphans evicts the install-time snapclient
             registration that lingers under the pre-rename hostname.
          2) ensure_client_home_assignment_with_mapping saves a home_group
             for the freshly-installed client. The verify step has just
             confirmed the snapclient reconnected post-reboot, so this is
             the first moment the client is actually present in
             snapserver's group roster — closing the race where register
             writes server_config.json BEFORE snapclient connects (which
             left home_group=None and broke the Settings gear icon with a
             404 on /api/clients/null/sources).

        Both are best-effort; failures are non-fatal because the install
        itself already succeeded.
        """
        try:
            self.handle_cleanup_orphans()
            self.log(f"Auto-cleanup completed after install of {client_id}", "INFO")
        except Exception as e:
            self.log(f"Auto-cleanup after install failed: {e}", "WARNING")

        if not client_id:
            return
        try:
            client_config = None
            for c in self.config_manager.server_config.get("clients", []):
                if c.get("id") == client_id:
                    client_config = c
                    break
            if not client_config:
                self.log(f"Auto-assign skipped: {client_id} not in server_config", "WARNING")
                return
            home_source = client_config.get("home_source")
            if not home_source:
                self.log(f"Auto-assign skipped: {client_id} has no home_source", "WARNING")
                return
            from .group_manager import SnapcastGroupManager
            gm = SnapcastGroupManager(config_manager=self.config_manager)
            if gm.ensure_client_home_assignment_with_mapping(
                config_id=client_id,
                snapcast_id=client_id,
                preferred_source=home_source,
            ):
                self.log(f"Auto-assigned home_group for {client_id} after install", "SUCCESS")
            else:
                self.log(f"Auto-assign returned False for {client_id}", "WARNING")
        except Exception as e:
            self.log(f"Auto-assign after install failed: {e}", "WARNING")

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

        # Optional ?dac_overlay= override. Brand-new clients aren't yet in
        # server_config.json so we can't look up a per-device value here —
        # the caller has to pass one if they want non-default. Validated
        # against the allowlist so a bad query string can't smuggle an
        # arbitrary string into config.txt.
        requested_overlay = (request.args.get("dac_overlay") or "").strip()
        if requested_overlay and not _dac_is_allowed(requested_overlay):
            return jsonify({"error": f"unknown dac_overlay '{requested_overlay}'"}), 400
        dac_overlay = requested_overlay or DEFAULT_OVERLAY

        script = self._generate_firstrun_sh(display_name, dac_overlay)
        return Response(
            script,
            mimetype="text/plain",
            headers={"Content-Disposition": "attachment; filename=firstrun.sh"}
        )

    def _generate_firstrun_sh(self, display_name: str = "", dac_overlay: str = "") -> str:
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
FAUXNOS_DAC_OVERLAY="{dac_overlay or DEFAULT_OVERLAY}"

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
export FAUXNOS_SERVER_HOST DISPLAY_NAME FAUXNOS_DAC_OVERLAY
echo "[fauxnos] Starting install from http://${{FAUXNOS_SERVER_HOST}}:8080/api/install/client.sh"
echo "[fauxnos] DAC overlay: ${{FAUXNOS_DAC_OVERLAY}}"
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

    # ── Server-driven install handlers ─────────────────────────────────────────

    def _list_clients_for_runner(self) -> list:
        """Adapter for InstallRunner.client_status_fn — returns a minimal list
        of {client_id, connected} dicts so the runner can detect a brand-new
        client appearing in the roster after reboot without depending on the
        full Flask request context."""
        try:
            clients = self.config_manager.get_all_clients()
            connected_map = self._get_snapcast_client_status()
            return [
                {"client_id": c.id, "connected": connected_map.get(c.id, False)}
                for c in clients
            ]
        except Exception:
            return []

    def handle_get_server_pubkey(self):
        """Handle GET /api/install/server-pubkey — text/plain Ed25519 public key.

        The user pastes this into Pi Imager when flashing a new client (along
        with their personal key). install.sh writes the keypair on first run.
        """
        pub_path = Path(str(DEFAULT_KEY_PATH) + ".pub")
        try:
            text = pub_path.read_text()
        except FileNotFoundError:
            return Response(
                f"# Server install key not found at {pub_path}.\n"
                f"# Run install.sh on this server (or its setup_install_keypair step) to generate it.\n",
                mimetype="text/plain",
                status=404,
            )
        except OSError as e:
            return Response(f"# Error reading key: {e}\n", mimetype="text/plain", status=500)
        return Response(text, mimetype="text/plain")

    def handle_start_install(self):
        """Handle POST /api/install/start — kick off a wizard install.

        Body: { display_name: str, target_host?: str (default fauxnos-client.local) }
        Returns 200 {install_id, …} on success, 409 if another install is running.
        """
        data = request.get_json(silent=True) or {}
        display_name = (data.get("display_name") or "").strip()[:64]
        target_host = (data.get("target_host") or "fauxnos-client.local").strip()
        if not display_name:
            return jsonify({"error": "display_name is required"}), 400
        try:
            runner = self.install_manager.start(target_host=target_host, display_name=display_name)
            self.log(f"Install started: {runner.install_id} → {target_host} ({display_name})", "SUCCESS")
            return jsonify(runner.snapshot()), 200
        except InstallAlreadyRunning as e:
            return jsonify({
                "error": "already_running",
                **e.runner.snapshot(),
            }), 409
        except Exception as e:
            self.log(f"Install start failed: {e}", "ERROR")
            return jsonify({"error": str(e)}), 500

    def handle_install_status(self):
        """Handle GET /api/install/status — snapshot of the current or last install."""
        runner = self.install_manager.current_or_last()
        if runner is None:
            return jsonify({"status": "idle"})
        return jsonify(runner.snapshot())

    def handle_install_stream(self):
        """Handle GET /api/install/stream — SSE stream of install events.

        Events:
          - snapshot: full state (sent first to a new subscriber)
          - step: a step's state changed
          - tail: a new stdout line was captured
          - done: the install finished (final snapshot)
        Plus a `:keepalive` comment every 15s to defeat proxies.
        """
        runner = self.install_manager.current_or_last()
        if runner is None:
            # Nothing to stream yet — return an empty SSE stream that idles
            # until a runner starts. We still want a 200 + heartbeat so the
            # browser EventSource stays open.
            def empty_stream():
                while True:
                    yield ": keepalive\n\n"
                    time.sleep(15)
            return Response(stream_with_context(empty_stream()),
                            mimetype="text/event-stream",
                            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        sub = runner.subscribe()
        terminal = runner.status in ("succeeded", "failed", "cancelled")

        def gen(rnr=runner, q=sub, already_done=terminal):
            try:
                if already_done:
                    # Replay the final state then close — the UI uses this to
                    # rehydrate after a refresh on a finished install.
                    yield _sse_event("done", rnr.snapshot())
                    return
                last_keepalive = time.time()
                while True:
                    try:
                        ev = q.get(timeout=15)
                    except queue_mod.Empty:
                        yield ": keepalive\n\n"
                        last_keepalive = time.time()
                        continue
                    yield _sse_event(ev["type"], ev["data"])
                    if ev["type"] == "done":
                        return
                    if time.time() - last_keepalive > 15:
                        yield ": keepalive\n\n"
                        last_keepalive = time.time()
            finally:
                rnr.unsubscribe(q)

        return Response(stream_with_context(gen()),
                        mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def handle_cancel_install(self):
        """Handle POST /api/install/cancel — cancel the active install (best-effort)."""
        runner = self.install_manager.current()
        if runner is None:
            return jsonify({"status": "idle"})
        runner.cancel()
        return jsonify({"status": "cancelling", "install_id": runner.install_id})

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
                # Existing: track each client's active source.
                client.subscribe("status/clients/+/mode")
                # IR mirroring: hello carries the full ir block on
                # (re)connect; ir/state is fired on every change;
                # learn_event is the per-learn lifecycle stream.
                client.subscribe("status/clients/+/hello")
                client.subscribe("status/clients/+/ir/state")
                client.subscribe("status/clients/+/ir/learn_event")
                # Nudge every client to re-hello so the server's mirror
                # is fresh after a server restart. Clients handle this
                # in mqtt_client.py via the "get/clients/all/status"
                # subscription.
                client.publish("get/clients/all/status", "")
                self.log(
                    "MQTT listener connected, subscribed to "
                    "mode/hello/ir-state/ir-learn_event"
                )

        def on_message(client, userdata, msg):
            parts = msg.topic.split("/")
            if len(parts) < 4:
                return
            client_id = parts[2]
            action = parts[3]
            sub_action = parts[4] if len(parts) >= 5 else None

            if action == "mode":
                source_id = msg.payload.decode().strip()
                if source_id:
                    self._trigger_external_for_source(client_id, source_id)
                return

            if action == "hello":
                try:
                    hello = json.loads(msg.payload.decode() or "{}")
                except Exception:
                    return
                ir = hello.get("ir")
                if isinstance(ir, dict):
                    self._ingest_client_ir_state(client_id, ir)
                return

            if action == "ir" and sub_action == "state":
                try:
                    ir = json.loads(msg.payload.decode() or "{}")
                except Exception:
                    return
                if isinstance(ir, dict):
                    self._ingest_client_ir_state(client_id, ir)
                return

            if action == "ir" and sub_action == "learn_event":
                try:
                    ev = json.loads(msg.payload.decode() or "{}")
                except Exception:
                    return
                if isinstance(ev, dict) and ev.get('event'):
                    self._ir_learn_emit(client_id, ev)
                return

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
