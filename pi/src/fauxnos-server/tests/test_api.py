#!/usr/bin/env python3
"""
L3 — API Functionality

Tests that verify the Flask API is returning correct responses.
"""

from test_utils import http_get, json_rpc, result, tcp_connect


API_BASE = "http://127.0.0.1:8080"


def test_l3_api():
    """L3: Check API endpoints."""
    tests = []

    # GET /api/status → 200 + {status: "running"}
    status_code, body = http_get(f"{API_BASE}/api/status")
    ok = status_code == 200 and isinstance(body, dict) and body.get("status") == "running"
    tests.append(result(
        "api_health", 3,
        ok,
        "" if ok else f"GET /api/status → {status_code}, body={body}",
        "journalctl --user -u fauxnos-server -n 30 --no-pager"
    ))

    # GET /api/clients → 200 + array
    status_code, body = http_get(f"{API_BASE}/api/clients")
    ok = status_code == 200 and isinstance(body, dict) and "clients" in body
    tests.append(result(
        "api_clients_list", 3,
        ok,
        "" if ok else f"GET /api/clients → {status_code}, body={body}",
        "journalctl --user -u fauxnos-server -n 30 --no-pager"
    ))

    # GET / → 200 + HTML (web UI)
    status_code, body = http_get(f"{API_BASE}/")
    ok = status_code == 200 and isinstance(body, str) and "<html" in body.lower()
    tests.append(result(
        "api_web_ui", 3,
        ok,
        "" if ok else f"GET / → {status_code} (expected 200 + HTML)",
        "Check that web/index.html exists in server code directory"
    ))

    # GET /api/install/firstrun.sh → 200 + bash script
    status_code, body = http_get(f"{API_BASE}/api/install/firstrun.sh")
    ok = status_code == 200 and isinstance(body, str) and "#!/bin/bash" in body
    tests.append(result(
        "api_firstrun_sh", 3,
        ok,
        "" if ok else f"GET /api/install/firstrun.sh → {status_code}",
        "journalctl --user -u fauxnos-server -n 30 --no-pager"
    ))

    # GET /api/install/client.sh → 200 + bash script
    status_code, body = http_get(f"{API_BASE}/api/install/client.sh")
    ok = status_code == 200 and isinstance(body, str) and "#!/bin/bash" in body
    tests.append(result(
        "api_client_sh", 3,
        ok,
        "" if ok else f"GET /api/install/client.sh → {status_code}",
        "Check that pi/src/fauxnos-client/install.sh exists on server"
    ))

    # GET /api/server/status → 200 + JSON
    status_code, body = http_get(f"{API_BASE}/api/server/status")
    ok = status_code == 200 and isinstance(body, dict)
    tests.append(result(
        "api_server_status", 3,
        ok,
        "" if ok else f"GET /api/server/status → {status_code}",
        "journalctl --user -u fauxnos-server -n 30 --no-pager"
    ))

    # Snapcast JSON-RPC: Server.GetStatus
    rpc_result = json_rpc("127.0.0.1", 1705, "Server.GetStatus")
    ok = (
        rpc_result is not None
        and "result" in rpc_result
        and "server" in rpc_result.get("result", {})
    )
    tests.append(result(
        "snapcast_rpc", 3,
        ok,
        "" if ok else f"Snapcast JSON-RPC Server.GetStatus failed: {rpc_result}",
        "journalctl --user -u snapserver -n 20 --no-pager"
    ))

    return tests


def run_all():
    return test_l3_api()
