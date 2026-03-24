#!/usr/bin/env python3
"""
L4 — Snapcast Integration

Tests that verify go-librespot instances are running, FIFOs exist,
and snapcast sources match the configured clients.
"""

import os
import glob
from test_utils import run_cmd, json_rpc, result, load_server_config


def test_l4_integration():
    """L4: Check integration between go-librespot, FIFOs, and snapcast sources."""
    tests = []

    config = load_server_config()
    if not config:
        tests.append(result(
            "config_load", 4, False,
            "Cannot load server_config.json — skipping L4 tests",
            "Check ~/src/fauxnos-server/server_config.json"
        ))
        return tests

    clients = config.get("clients", [])
    fifo_base = config.get("server", {}).get("paths", {}).get("fifo_base", "/tmp/snapfifo")

    # go-librespot: one running instance per client
    for client in clients:
        client_id = client["id"]
        code, out, _ = run_cmd(f"systemctl --user is-active go-librespot-{client_id}")
        active = out == "active"
        tests.append(result(
            f"go_librespot_{client_id}", 4,
            active,
            "" if active else f"go-librespot-{client_id} not active",
            f"journalctl --user -u go-librespot-{client_id} -n 20 --no-pager"
        ))

    # FIFO pipes exist for each client
    for client in clients:
        client_id = client["id"]
        fifo_path = f"{fifo_base}/spotify_{client_id}"
        is_fifo = os.path.exists(fifo_path) and not os.path.isfile(fifo_path)
        # Check it's a named pipe
        try:
            import stat
            is_fifo = stat.S_ISFIFO(os.stat(fifo_path).st_mode)
        except Exception:
            is_fifo = False
        tests.append(result(
            f"fifo_pipe_{client_id}", 4,
            is_fifo,
            "" if is_fifo else f"FIFO not found: {fifo_path}",
            "journalctl --user -u fauxnos-fifo-setup -n 20 --no-pager"
        ))

    # Snapcast sources match config clients
    rpc_result = json_rpc("127.0.0.1", 1705, "Server.GetStatus")
    if rpc_result and "result" in rpc_result:
        streams = rpc_result["result"].get("server", {}).get("streams", [])
        stream_ids = [s.get("id", "") for s in streams]

        for client in clients:
            client_id = client["id"]
            expected_source = f"source_{client_id}_spotify"
            found = expected_source in stream_ids
            tests.append(result(
                f"snapcast_source_{client_id}", 4,
                found,
                "" if found else f"Source '{expected_source}' not found in snapcast streams: {stream_ids}",
                "journalctl --user -u snapserver -n 30 --no-pager  |  cat ~/.config/snapcast/snapserver.conf"
            ))
    else:
        tests.append(result(
            "snapcast_sources", 4,
            False,
            "Could not query snapcast — snapserver may not be running",
            "journalctl --user -u snapserver -n 20 --no-pager"
        ))

    # snapclient for server device (fauxnos000) should be running
    code, out, _ = run_cmd("systemctl --user is-active snapclient-fauxnos000 2>/dev/null || echo inactive")
    active = out == "active"
    tests.append(result(
        "snapclient_fauxnos000", 4,
        active,
        "" if active else "snapclient-fauxnos000 user service not active (server won't play audio locally)",
        "journalctl --user -u snapclient-fauxnos000 -n 20 --no-pager"
    ))

    return tests


def run_all():
    return test_l4_integration()
