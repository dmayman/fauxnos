#!/usr/bin/env python3
"""
L4 — Client Registration Simulation

Simulates a new client registration via POST /api/clients/register
using a throwaway test MAC address.
"""

import json
import urllib.request
import urllib.error
from test_utils import result, load_server_config

API_BASE = "http://127.0.0.1:8080"
TEST_MAC = "de:ad:be:ef:00:01"
TEST_HOSTNAME = "fauxnos-test-reg"
TEST_DISPLAY_NAME = "Test Registration Client"


def test_l4_registration():
    """L4: Simulate client registration flow."""
    tests = []

    config = load_server_config()
    if not config:
        tests.append(result(
            "registration_prereq", 4, False,
            "Cannot load server_config.json",
            ""
        ))
        return tests

    # Check if test MAC is already registered (from previous run)
    existing_clients = config.get("clients", [])
    already_registered = any(
        c.get("mac", "").lower() == TEST_MAC.lower()
        for c in existing_clients
    )

    if already_registered:
        # Already exists — just verify we get "already_registered" response
        payload = json.dumps({
            "mac_address": TEST_MAC,
            "hostname": TEST_HOSTNAME,
            "display_name": TEST_DISPLAY_NAME,
        }).encode()
        req = urllib.request.Request(
            f"{API_BASE}/api/clients/register",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                ok = resp.status == 200 and body.get("status") in ("already_registered", "registered")
                tests.append(result(
                    "client_registration_sim", 4,
                    ok,
                    "" if ok else f"Unexpected response for already-registered MAC: {body}",
                    "journalctl --user -u fauxnos-server -n 30 --no-pager"
                ))
        except Exception as e:
            tests.append(result(
                "client_registration_sim", 4,
                False,
                f"Registration request failed: {e}",
                "journalctl --user -u fauxnos-server -n 30 --no-pager"
            ))
        return tests

    # First time: send registration, expect "registered" status
    payload = json.dumps({
        "mac_address": TEST_MAC,
        "hostname": TEST_HOSTNAME,
        "display_name": TEST_DISPLAY_NAME,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/clients/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
            ok = (
                resp.status == 200
                and body.get("status") == "registered"
                and "client_id" in body
                and body.get("client_id", "").startswith("fauxnos")
            )
            msg = "" if ok else f"Unexpected registration response: {body}"
            tests.append(result(
                "client_registration_sim", 4, ok, msg,
                "journalctl --user -u fauxnos-server -n 30 --no-pager"
            ))
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        tests.append(result(
            "client_registration_sim", 4,
            False,
            f"HTTP {e.code}: {body}",
            "journalctl --user -u fauxnos-server -n 30 --no-pager"
        ))
    except Exception as e:
        tests.append(result(
            "client_registration_sim", 4,
            False,
            f"Request failed: {e}",
            "journalctl --user -u fauxnos-server -n 30 --no-pager"
        ))

    return tests


def run_all():
    return test_l4_registration()
