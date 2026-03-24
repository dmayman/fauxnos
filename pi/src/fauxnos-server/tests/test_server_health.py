#!/usr/bin/env python3
"""
L1 — Binaries & Files
L2 — Services Running

These tests verify that installation succeeded: required binaries exist,
config files are present and parseable, and all services are active.
"""

import os
from test_utils import run_cmd, check_service, tcp_connect, result, load_server_config, get_server_dir


def test_l1_binaries_and_files():
    """L1: Check required binaries and files exist."""
    tests = []

    # snapserver binary
    code, _, _ = run_cmd("which snapserver || test -f /usr/bin/snapserver")
    tests.append(result(
        "snapserver_binary", 1,
        code == 0,
        "" if code == 0 else "/usr/bin/snapserver not found",
        "sudo apt install snapserver  OR  install from GitHub releases"
    ))

    # go-librespot binary
    exists = os.path.isfile("/usr/local/bin/go-librespot")
    tests.append(result(
        "go_librespot_binary", 1,
        exists,
        "" if exists else "/usr/local/bin/go-librespot not found",
        "Run server install.sh to install go-librespot"
    ))

    # mosquitto binary
    code, _, _ = run_cmd("mosquitto --version 2>&1 | head -1")
    tests.append(result(
        "mosquitto_binary", 1,
        code == 0,
        "" if code == 0 else "mosquitto not found",
        "sudo apt install mosquitto"
    ))

    # avahi-daemon (may be in /usr/sbin which isn't in regular $PATH)
    code, _, _ = run_cmd(
        "which avahi-daemon || test -f /usr/sbin/avahi-daemon || test -f /usr/bin/avahi-daemon"
    )
    tests.append(result(
        "avahi_binary", 1,
        code == 0,
        "" if code == 0 else "avahi-daemon not found",
        "sudo apt install avahi-daemon"
    ))

    # server code present
    server_script = os.path.join(get_server_dir(), "fauxnos-server.py")
    exists = os.path.isfile(server_script)
    tests.append(result(
        "server_code_present", 1,
        exists,
        "" if exists else f"{server_script} not found",
        "Run install.sh to download server code"
    ))

    # server config exists and parses
    config = load_server_config()
    tests.append(result(
        "server_config_exists", 1,
        config is not None,
        "" if config is not None else "server_config.json missing or invalid JSON",
        f"Check {get_server_dir()}/server_config.json"
    ))

    # snapserver.conf exists
    snapserver_conf = os.path.expanduser("~/.config/snapcast/snapserver.conf")
    exists = os.path.isfile(snapserver_conf)
    tests.append(result(
        "snapserver_conf_exists", 1,
        exists,
        "" if exists else f"{snapserver_conf} not found",
        "Run: python3 fauxnos-server.py deploy-server"
    ))

    # setup-fifo.sh exists
    fifo_script = os.path.expanduser("~/scripts/setup-fifo.sh")
    exists = os.path.isfile(fifo_script) and os.access(fifo_script, os.X_OK)
    tests.append(result(
        "fifo_setup_script", 1,
        exists,
        "" if exists else f"{fifo_script} not found or not executable",
        "Run: python3 fauxnos-server.py deploy-server"
    ))

    return tests


def test_l2_services():
    """L2: Check required services are running."""
    tests = []

    # mosquitto (system service)
    active = check_service("mosquitto", "system")
    tests.append(result(
        "mosquitto_running", 2,
        active,
        "" if active else "mosquitto is not active",
        "sudo systemctl start mosquitto  |  journalctl -u mosquitto -n 20"
    ))

    # avahi-daemon (system service)
    active = check_service("avahi-daemon", "system")
    tests.append(result(
        "avahi_running", 2,
        active,
        "" if active else "avahi-daemon is not active",
        "sudo systemctl start avahi-daemon  |  journalctl -u avahi-daemon -n 20"
    ))

    # snapserver (user service)
    active = check_service("snapserver", "user")
    tests.append(result(
        "snapserver_running", 2,
        active,
        "" if active else "snapserver user service is not active",
        "journalctl --user -u snapserver -n 20 --no-pager"
    ))

    # fauxnos-server (user service)
    active = check_service("fauxnos-server", "user")
    tests.append(result(
        "fauxnos_server_running", 2,
        active,
        "" if active else "fauxnos-server user service is not active",
        "journalctl --user -u fauxnos-server -n 20 --no-pager"
    ))

    # fauxnos-fifo-setup (user service)
    # This is oneshot; check via is-active (should be "active" after completion)
    active = check_service("fauxnos-fifo-setup", "user")
    tests.append(result(
        "fifo_setup_service", 2,
        active,
        "" if active else "fauxnos-fifo-setup service did not complete successfully",
        "journalctl --user -u fauxnos-fifo-setup -n 20 --no-pager"
    ))

    # API port 8080
    port_open = tcp_connect("127.0.0.1", 8080)
    tests.append(result(
        "api_port_open", 2,
        port_open,
        "" if port_open else "Nothing listening on port 8080",
        "journalctl --user -u fauxnos-server -n 20 --no-pager"
    ))

    # Snapcast JSON-RPC port 1705
    port_open = tcp_connect("127.0.0.1", 1705)
    tests.append(result(
        "snapcast_port_open", 2,
        port_open,
        "" if port_open else "Nothing listening on port 1705 (snapserver)",
        "journalctl --user -u snapserver -n 20 --no-pager"
    ))

    # MQTT port 1883
    port_open = tcp_connect("127.0.0.1", 1883)
    tests.append(result(
        "mqtt_port_open", 2,
        port_open,
        "" if port_open else "Nothing listening on port 1883 (mosquitto)",
        "sudo systemctl status mosquitto  |  journalctl -u mosquitto -n 20"
    ))

    return tests


def run_all():
    return test_l1_binaries_and_files() + test_l2_services()
