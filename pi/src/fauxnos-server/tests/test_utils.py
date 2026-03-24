#!/usr/bin/env python3
"""
Shared utilities for Fauxnos server test suite.
"""

import subprocess
import socket
import json
import urllib.request
import urllib.error
import os
from typing import Optional, Dict, Any, Tuple


def run_cmd(cmd: str, timeout: int = 10) -> Tuple[int, str, str]:
    """Run a shell command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def check_service(service: str, scope: str = "user") -> bool:
    """Return True if a systemd service is active."""
    if scope == "user":
        code, out, _ = run_cmd(f"systemctl --user is-active {service}")
    else:
        code, out, _ = run_cmd(f"systemctl is-active {service}")
    return out == "active"


def tcp_connect(host: str, port: int, timeout: int = 3) -> bool:
    """Return True if a TCP connection can be established."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


def http_get(url: str, timeout: int = 5) -> Tuple[int, Optional[Any]]:
    """Perform GET request, return (status_code, parsed_json_or_None)."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None


def json_rpc(host: str, port: int, method: str, params: Optional[Dict] = None, timeout: int = 5) -> Optional[Dict]:
    """Send a JSON-RPC 2.0 request, return response dict or None."""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1
    }).encode()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(payload + b"\r\n")

        response_data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_data += chunk
            try:
                return json.loads(response_data.decode())
            except json.JSONDecodeError:
                continue
        sock.close()
        return None
    except Exception:
        return None


def result(name: str, level: int, passed: bool, message: str = "", hint: str = "") -> Dict[str, Any]:
    """Build a test result dict."""
    return {
        "name": name,
        "level": level,
        "status": "pass" if passed else "fail",
        "message": message,
        "hint": hint,
    }


def get_server_dir() -> str:
    """Return the fauxnos-server source directory."""
    return os.path.expanduser("~/src/fauxnos-server")


def get_config_path() -> str:
    """Return path to server_config.json."""
    return os.path.join(get_server_dir(), "server_config.json")


def load_server_config() -> Optional[Dict]:
    """Load and return server_config.json, or None on failure."""
    config_path = get_config_path()
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return None
