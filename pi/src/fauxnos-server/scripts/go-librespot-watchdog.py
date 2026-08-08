#!/usr/bin/env python3
"""
go-librespot dealer watchdog
----------------------------
Detects the go-librespot "dead dealer" zombie state and restarts the affected
per-client Spotify Connect endpoint.

Background
==========
go-librespot maintains a WebSocket ("dealer") to Spotify's backend for control
(play/pause, session handoff, Connect discovery). When that socket dies (network
blip, Spotify-side disconnect) go-librespot does NOT exit and does NOT reconnect
on its own — it just prints, every 30s, forever:

    level=error msg="did not receive last pong from dealer, <N>s passed"

The process stays `active`, so systemd's Restart=always never fires (nothing
exits). But the endpoint is a zombie: still advertised over mDNS, yet every
Spotify "connect to <room>" hangs on "Connecting…". The only fix is to restart
that one unit, which re-establishes a fresh dealer connection.

This watchdog runs as a --user oneshot on a 60s timer. Each run it:
  1. Discovers all loaded `go-librespot-fauxnos*` units.
  2. Reads each unit's recent journal and measures how long the dealer has been
     dead (the built-in "<N>s passed" counter — self-describing, no clock math).
  3. If a unit has been dead >= THRESHOLD_S (default 180s = 6 missed pongs, well
     past any transient), restarts it — subject to two guards:
       - Idle-deferral: if snapcast still shows the client's Spotify stream
         `playing`, defer up to MAX_DEFERS cycles so we don't cut a live song.
         Bounded, because snapcast reports a pipe-writer as `playing` even when
         the endpoint is a fresh idle restart — an unbounded defer could let a
         genuinely-stuck-but-"playing" endpoint hang forever.
       - Rate cap: at most MAX_RESTARTS_PER_HOUR restarts per unit, so a
         persistently-broken endpoint (bad creds, network down) can't churn.
  4. Logs every action (zombie found / deferred / restarted / rate-limited) and
     stays SILENT on healthy runs — so every journal line is a real event and
     "how often does this fire?" is answerable from `journalctl`.

State (defer counts + restart timestamps) persists across runs in a small JSON
sidecar, since each timer firing is a fresh process.

Detection string note: the "did not receive last pong from dealer" message is
go-librespot's wording as of 0.7.x. A version bump could change it; if the
watchdog goes quiet across an upgrade, re-check this against the current logs.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time

# ─── Tunables (env-overridable so they can change without a redeploy) ──────────
def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

# Seconds the dealer must be continuously dead before a unit is restart-eligible.
# go-librespot bumps the "<N>s passed" counter every 30s, so 180 == 6 missed
# pongs — comfortably past any transient reconnect.
THRESHOLD_S = _int_env("FAUXNOS_WATCHDOG_THRESHOLD", 180)
# Per-unit restart ceiling within a rolling hour.
MAX_RESTARTS_PER_HOUR = _int_env("FAUXNOS_WATCHDOG_MAX_RESTARTS", 4)
# Consecutive cycles we'll defer a restart while snapcast reports `playing`
# before forcing it anyway (guards against a stale/false `playing`).
MAX_DEFERS = _int_env("FAUXNOS_WATCHDOG_MAX_DEFERS", 3)
# How far back to read each unit's journal. Must exceed THRESHOLD_S with margin.
JOURNAL_SINCE = os.environ.get("FAUXNOS_WATCHDOG_JOURNAL_SINCE", "8 min ago")

SNAPCAST_HOST = os.environ.get("FAUXNOS_SNAPCAST_HOST", "127.0.0.1")
SNAPCAST_PORT = _int_env("FAUXNOS_SNAPCAST_PORT", 1705)

STATE_FILE = os.path.expanduser(
    os.environ.get(
        "FAUXNOS_WATCHDOG_STATE",
        "~/.config/fauxnos/go-librespot-watchdog-state.json",
    )
)

UNIT_GLOB = "go-librespot-fauxnos*.service"
PONG_RE = re.compile(r"did not receive last pong from dealer,\s*(\d+)s passed")


def log(msg):
    """Single-line event log. Journal supplies the timestamp."""
    print(f"[go-librespot-watchdog] {msg}", flush=True)


# ─── Detection (pure, unit-tested via --self-test) ─────────────────────────────
def dead_seconds(journal_lines):
    """
    Given a unit's recent journal lines (oldest first), return how many seconds
    the dealer has been continuously dead as of the newest line, or None if the
    unit looks healthy / recovered.

    Rule:
      - A "did not receive last pong from dealer, <N>s passed" line sets the dead
        counter to N.
      - Any `level=info` line means go-librespot is doing real work again (fresh
        start banner, track load, reconnect) → clears the dead state. While the
        dealer is truly dead, go-librespot emits ONLY the 30s pong error and no
        info lines, so an info line is a reliable "alive/recovered" signal.
      - Other `level=error` lines (e.g. the interleaved "websocket connection
        errored … EOF") neither set nor clear the counter — they don't prove
        recovery, so the last pong count stands.
    """
    dead = None
    for line in journal_lines:
        m = PONG_RE.search(line)
        if m:
            dead = int(m.group(1))
            continue
        if "level=info" in line:
            dead = None
    return dead


# ─── Systemd / journal helpers ─────────────────────────────────────────────────
def discover_units():
    """Return loaded go-librespot-fauxnos* unit names."""
    try:
        out = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service",
             "--all", "--plain", "--no-legend", UNIT_GLOB],
            capture_output=True, text=True, check=False,
        ).stdout
    except Exception as e:
        log(f"ERROR: could not list units: {e}")
        return []
    units = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].endswith(".service") and parts[0].startswith("go-librespot-"):
            units.append(parts[0])
    return units


def client_id_from_unit(unit):
    return unit[len("go-librespot-"):-len(".service")]


def read_journal(unit):
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", unit, "--since", JOURNAL_SINCE,
             "-o", "cat", "--no-pager"],
            capture_output=True, text=True, check=False,
        ).stdout
    except Exception as e:
        log(f"ERROR: journalctl failed for {unit}: {e}")
        return []
    return out.splitlines()


def restart_unit(unit):
    r = subprocess.run(
        ["systemctl", "--user", "restart", unit],
        capture_output=True, text=True, check=False,
    )
    return r.returncode == 0, (r.stderr or r.stdout).strip()


# ─── Snapcast idle check ───────────────────────────────────────────────────────
def snap_stream_status(client_id, timeout=3):
    """
    Return the snapcast status ('playing'/'idle'/…) for this client's Spotify
    stream (`source_<id>_spotify`), or None if it can't be determined.
    """
    stream_id = f"source_{client_id}_spotify"
    req = json.dumps(
        {"jsonrpc": "2.0", "method": "Server.GetStatus", "id": 1}
    ).encode() + b"\r\n"
    try:
        with socket.create_connection((SNAPCAST_HOST, SNAPCAST_PORT), timeout) as s:
            s.settimeout(timeout)
            s.sendall(req)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        data = json.loads(buf.split(b"\n")[0])
        for st in data["result"]["server"]["streams"]:
            if st.get("id") == stream_id:
                return st.get("status")
    except Exception as e:
        log(f"WARN: snapcast status query failed for {client_id}: {e}")
    return None


# ─── State ─────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log(f"WARN: could not persist state: {e}")


def _entry(state, cid):
    e = state.get(cid)
    if not isinstance(e, dict):
        e = {}
    e.setdefault("defers", 0)
    e.setdefault("restarts", [])
    state[cid] = e
    return e


# ─── Main pass ─────────────────────────────────────────────────────────────────
def run(dry_run=False, now=None):
    now = time.time() if now is None else now
    state = load_state()
    units = discover_units()

    for unit in units:
        cid = client_id_from_unit(unit)
        dead = dead_seconds(read_journal(unit))

        if dead is None or dead < THRESHOLD_S:
            # Healthy / recovered / transient — clear any pending defer streak.
            e = _entry(state, cid)
            if e["defers"]:
                e["defers"] = 0
            continue

        e = _entry(state, cid)
        # Prune restart history to the rolling hour.
        e["restarts"] = [t for t in e["restarts"] if now - t < 3600]

        if len(e["restarts"]) >= MAX_RESTARTS_PER_HOUR:
            log(f"{unit}: dealer dead {dead}s but rate-limited "
                f"({len(e['restarts'])} restarts in last hour) — leaving alone")
            continue

        status = snap_stream_status(cid)
        if status == "playing" and e["defers"] < MAX_DEFERS:
            e["defers"] += 1
            log(f"{unit}: dealer dead {dead}s but stream is playing — "
                f"deferring restart ({e['defers']}/{MAX_DEFERS})")
            continue

        reason = "idle" if status != "playing" else f"forced after {MAX_DEFERS} defers"
        if dry_run:
            log(f"{unit}: WOULD restart — dealer dead {dead}s, stream={status} ({reason}) [dry-run]")
            continue

        ok, err = restart_unit(unit)
        if ok:
            e["restarts"].append(now)
            e["defers"] = 0
            log(f"{unit}: RESTARTED — dealer was dead {dead}s, stream={status} ({reason})")
        else:
            log(f"{unit}: restart FAILED — {err}")

    # Drop state for units that no longer exist.
    live = {client_id_from_unit(u) for u in units}
    for cid in list(state.keys()):
        if cid not in live:
            del state[cid]

    save_state(state)
    return 0


# ─── Self-test (no device access; validates dead_seconds) ──────────────────────
def self_test():
    cases = [
        ("healthy (info only)",
         ['level=info msg="loaded track \\"X\\""'],
         None),
        ("fresh restart banner",
         ['level=info msg="running go-librespot 0.7.1"',
          'level=info msg="api server listening on [::]:3601"',
          'level=info msg="zeroconf server listening on port 49001"'],
         None),
        ("below threshold",
         ['level=error msg="did not receive last pong from dealer, 30s passed"',
          'level=error msg="did not receive last pong from dealer, 60s passed"'],
         60),
        ("zombie at 180s",
         ['level=error msg="did not receive last pong from dealer, 120s passed"',
          'level=error msg="did not receive last pong from dealer, 150s passed"',
          'level=error msg="did not receive last pong from dealer, 180s passed"'],
         180),
        ("recovered after dead streak",
         ['level=error msg="did not receive last pong from dealer, 120s passed"',
          'level=error msg="did not receive last pong from dealer, 150s passed"',
          'level=info msg="loaded track \\"Y\\""'],
         None),
        ("interleaved EOF does not clear",
         ['level=error msg="did not receive last pong from dealer, 150s passed"',
          'level=error msg="websocket connection errored" error="failed to get reader: EOF"',
          'level=error msg="did not receive last pong from dealer, 180s passed"'],
         180),
        ("EOF is newest line, count stands",
         ['level=error msg="did not receive last pong from dealer, 900s passed"',
          'level=error msg="websocket connection errored" error="EOF"'],
         900),
        ("empty journal",
         [],
         None),
    ]
    failures = 0
    for name, lines, expected in cases:
        got = dead_seconds(lines)
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: expected={expected} got={got}")
        if not ok:
            failures += 1
    print(f"\n{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description="go-librespot dealer watchdog")
    ap.add_argument("--self-test", action="store_true",
                    help="run detector unit tests and exit (no device access)")
    ap.add_argument("--dry-run", action="store_true",
                    help="assess and log decisions but do not restart anything")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
