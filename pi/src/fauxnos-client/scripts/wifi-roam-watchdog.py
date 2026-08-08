#!/usr/bin/env python3
"""
wifi roam watchdog
------------------
Detects the "sticky client parked on a far AP" state and bounces wlan0 so the
supplicant re-associates — normally onto the near AP it should have been on.

Background
==========
Pi Zero 2 W (brcmfmac, 2.4GHz only) is a sticky client: it picks an AP at
association time and then essentially never re-evaluates. In a multi-AP mesh
that is usually harmless — until the near AP goes away for a moment.

Observed on fauxnos001 (Kitchen), 2026-08-08:
  02:20  near AP (~-26 dBm) sends deauth reason=2, then rejects six
         re-association attempts (CTRL-EVENT-ASSOC-REJECT status_code=16 —
         the AP was rebooting).
  02:20  supplicant latches onto a far mesh node at -59 dBm.
  11:xx  still there. Zero CTRL-EVENT-CONNECTED in the intervening 9 hours.

Why the far-AP state is fatal rather than merely worse: every AP in that house
is on channel 11, and the near AP is ~33 dB louder than the one the Pi is
trying to hear, so it deafens the Pi's receiver. AP→client rate control
collapses to 1–7 Mbit/s legacy 802.11b rates (client→AP stays fine at 65–72).
Downlink is the audio direction, and snapcast PCM needs ~1.5 Mbit/s sustained.
The result in snapclient's log is the familiar dropout chain:

    Not enough frames available
    XRUN while waiting for PCM: Broken pipe
    Time sync request failed: Connection timed out
    → TCP reset → reconnect every ~30s

Note what this does NOT look like: ping showed 0% packet loss with avg 360 ms /
max 1218 ms RTT *on a LAN*. Loss-free and latency-fatal, which is why every
prior investigation — all of them hunting for packet loss — missed it.

The primary fix is a pinned BSSID in NetworkManager (plus an unpinned
lower-priority fallback profile so a headless device can never lock itself
out). This watchdog closes the residual hole in that fix: if the pinned AP
reboots, the client falls back to the unpinned profile, lands on a far node,
and is sticky there indefinitely until a human notices.

How it works
============
Runs as a root system oneshot on a 60s timer. Each run it:
  1. Reads the current link (`iw dev <iface> link`) — a netlink query, no radio
     cost. Falls back to /proc/net/wireless for signal.
  2. If the signal is stronger than WEAK_DBM, stops right there. This is the
     whole point of the two-stage trigger: a scan takes the radio off-channel
     for a second or so and can itself glitch audio, so we only pay for one
     once we already believe we are degraded.
  3. Scans, and looks for a *same-SSID* BSS at least MARGIN_DB stronger than
     the one we are on. No better AP → not actionable, no bounce. Weak signal
     alone is never enough: a genuinely far-from-any-AP room would otherwise
     bounce forever.
  4. Bounces `<iface>` — subject to two guards, mirroring
     go-librespot-watchdog.py:
       - Idle-deferral: if any fauxnos null sink is RUNNING the room is
         actively playing, so defer — but only up to MAX_DEFER_S of
         *continuous* degradation, then bounce anyway. Bounded because a
         degraded-but-playing room is exactly the case we exist to fix, and
         an unbounded defer would let it play badly forever.
       - Rate cap: at most MAX_BOUNCES_PER_HOUR, so two mediocre APs can't
         make us flap.
  5. Verifies afterwards by pinging the default gateway from `ip route`.
  6. Logs state transitions and actions only, and stays SILENT on healthy
     runs — so every journal line is a real event.

Anti-stranding
==============
These are headless devices with no ethernet. A wifi bounce that does not come
back is unrecoverable without physically pulling the SD card, so the bounce is
deliberately the *lightest* thing that forces re-association:

  - We only ever call `nmcli device disconnect` / `nmcli device connect` /
    `nmcli connection up`. We never edit, add or delete a NM profile, never
    touch wpa_supplicant directly, never restart NetworkManager, never reboot.
  - Reconnect is a fallback chain: `device connect` (lets NM apply its own
    autoconnect-priority ranking, which is what honours a pinned profile) →
    the profile that was active before → every autoconnect-enabled wifi
    profile in priority order. So a pinned-BSSID profile whose AP is down
    falls through to the unpinned fallback profile exactly as intended.
  - `--ensure-connected` (wired to ExecStopPost, so it runs even if the main
    pass is killed or times out mid-bounce) re-runs that reconnect chain if
    the interface is still down within ENSURE_WINDOW_S of a bounce we
    started. This is the guarantee that a half-finished bounce self-heals on
    the next timer tick rather than stranding the device.

State (degradation clock + bounce timestamps) persists across runs in a small
JSON sidecar, since each timer firing is a fresh process.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time


# ─── Tunables (env-overridable so they can change without a redeploy) ──────────
def _int_env(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Signal (dBm) at or below which we consider the link degraded enough to be
# worth a scan. -45 is deliberately generous: a healthy fauxnos room sits at
# -23..-28 dBm (a year of 1Hz samples on fauxnos001 says so), and the bad
# state was -59. Anything past -45 in this house means we are not on the AP
# in the room.
WEAK_DBM = _int_env("FAUXNOS_ROAM_WEAK_DBM", -45)
# How much stronger (dB) a same-SSID BSS must be before it's worth bouncing
# for. 15 dB is ~30x the power and comfortably past both scan-to-scan jitter
# (a few dB) and the point where same-channel APs start deafening each other.
# The failure case was a 32 dB gap, so this has plenty of headroom.
MARGIN_DB = _int_env("FAUXNOS_ROAM_MARGIN_DB", 15)
# Bounces allowed per rolling hour. The fix is a one-shot event (re-associate
# onto the good AP), so needing more than a couple per hour means bouncing
# isn't the answer and we should stop making it worse.
MAX_BOUNCES_PER_HOUR = _int_env("FAUXNOS_ROAM_MAX_BOUNCES", 2)
# Longest we'll defer a bounce while the room is playing. At a 60s cadence
# this is ~10 checks. A bounce costs ~5s of silence; ten minutes of 1 Mbit/s
# downlink costs continuous XRUN stuttering, so the trade flips well before
# here.
MAX_DEFER_S = _int_env("FAUXNOS_ROAM_MAX_DEFER", 600)
# How long after a bounce --ensure-connected stays armed.
ENSURE_WINDOW_S = _int_env("FAUXNOS_ROAM_ENSURE_WINDOW", 600)
# Seconds to wait for the interface to come back after a bounce.
VERIFY_TIMEOUT_S = _int_env("FAUXNOS_ROAM_VERIFY_TIMEOUT", 45)
# Optional space-separated MHz list to narrow the scan (e.g. "2412 2437 2462").
# Unset = scan every channel the radio supports. Narrowing cuts off-channel
# time roughly proportionally, at the cost of missing a same-SSID AP that
# moved channels.
SCAN_FREQS = os.environ.get("FAUXNOS_ROAM_SCAN_FREQS", "").split()

STATE_FILE = os.environ.get(
    "FAUXNOS_ROAM_STATE", "/var/lib/fauxnos/roam-watchdog-state.json"
)

IFACE_OVERRIDE = os.environ.get("FAUXNOS_ROAM_IFACE", "")

IW = "/usr/sbin/iw"
NMCLI = "/usr/bin/nmcli"


def log(msg):
    """Single-line event log. Journal supplies the timestamp."""
    print(f"[wifi-roam-watchdog] {msg}", flush=True)


def _run(argv, timeout=15):
    """Run a command, returning (rc, stdout). Never raises."""
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=timeout
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


# ─── Parsers (pure — exercised by --self-test) ─────────────────────────────────
_LINK_BSSID_RE = re.compile(r"^Connected to ([0-9a-fA-F:]{17})")
_LINK_FIELD_RE = {
    "ssid": re.compile(r"^\s*SSID:\s*(.*)$"),
    "freq": re.compile(r"^\s*freq:\s*(\d+)"),
    "signal": re.compile(r"^\s*signal:\s*(-?\d+)"),
    "rx_bitrate": re.compile(r"^\s*rx bitrate:\s*([\d.]+)"),
}


def parse_iw_link(text):
    """
    Parse `iw dev <iface> link`. Returns a dict with bssid/ssid/signal/freq/
    rx_bitrate, or None when the interface isn't associated ("Not connected.").
    Any field the driver didn't report comes back None.
    """
    link = {"bssid": None, "ssid": None, "signal": None,
            "freq": None, "rx_bitrate": None}
    for line in text.splitlines():
        m = _LINK_BSSID_RE.match(line)
        if m:
            link["bssid"] = m.group(1).lower()
            continue
        for key, rx in _LINK_FIELD_RE.items():
            if link[key] is not None:
                continue
            m = rx.match(line)
            if m:
                raw = m.group(1)
                if key == "ssid":
                    link[key] = raw.strip()
                elif key == "rx_bitrate":
                    link[key] = float(raw)
                else:
                    link[key] = int(raw)
    return link if link["bssid"] else None


def parse_proc_wireless(text, iface):
    """
    Fallback signal read from /proc/net/wireless (no privilege, no radio cost).
    The level column is dBm with a trailing '.' (e.g. '-28.'). Returns int or
    None.
    """
    for line in text.splitlines():
        if not line.strip().startswith(f"{iface}:"):
            continue
        parts = line.split()
        if len(parts) < 4:
            return None
        try:
            return int(float(parts[3].rstrip(".")))
        except ValueError:
            return None
    return None


_SCAN_BSS_RE = re.compile(r"^BSS ([0-9a-fA-F:]{17})")
_SCAN_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?[\d.]+)\s*dBm")
_SCAN_SSID_RE = re.compile(r"^\s*SSID:\s*(.*)$")
_SCAN_FREQ_RE = re.compile(r"^\s*freq:\s*(\d+)")


def parse_iw_scan(text):
    """
    Parse `iw dev <iface> scan` into a list of
    {bssid, ssid, signal, freq, associated}. Only BSSes that reported a dBm
    signal are returned — some drivers emit unspecified units ('60.00/70'),
    which we can't compare against a dBm threshold.
    """
    out = []
    cur = None
    for line in text.splitlines():
        m = _SCAN_BSS_RE.match(line)
        if m:
            if cur and cur["signal"] is not None:
                out.append(cur)
            cur = {
                "bssid": m.group(1).lower(),
                "ssid": None,
                "signal": None,
                "freq": None,
                "associated": "associated" in line,
            }
            continue
        if cur is None:
            continue
        m = _SCAN_SIGNAL_RE.match(line)
        if m and cur["signal"] is None:
            cur["signal"] = int(round(float(m.group(1))))
            continue
        m = _SCAN_FREQ_RE.match(line)
        if m and cur["freq"] is None:
            cur["freq"] = int(m.group(1))
            continue
        m = _SCAN_SSID_RE.match(line)
        if m and cur["ssid"] is None:
            cur["ssid"] = m.group(1).strip()
    if cur and cur["signal"] is not None:
        out.append(cur)
    return out


def better_candidates(link, bsses):
    """
    Same-SSID BSSes that beat the current one by at least MARGIN_DB, strongest
    first. Empty list means "weak, but there is nothing better to move to" —
    which is explicitly NOT a bounce condition.
    """
    if not link or link["signal"] is None or not link["ssid"]:
        return []
    floor = link["signal"] + MARGIN_DB
    cands = [
        b for b in bsses
        if b["ssid"] == link["ssid"]
        and b["bssid"] != link["bssid"]
        and b["signal"] is not None
        and b["signal"] >= floor
    ]
    return sorted(cands, key=lambda b: b["signal"], reverse=True)


# ─── Decision (pure — exercised by --self-test) ────────────────────────────────
def evaluate(link, scan_fn, playing, state, now):
    """
    Decide what this pass should do. Pure apart from `scan_fn`, which is only
    invoked once the cheap precondition already says we're degraded — tests
    assert on that gating by passing a scan_fn that records its calls.

    Returns (action, message, best_candidate_or_None) where action is one of:
      not-connected | unknown-signal | healthy | no-better-ap |
      rate-limited | defer | bounce

    Mutates `state["degraded_since"]` (the continuous-degradation clock) — the
    only piece of state the decision itself owns.
    """
    if link is None:
        # NetworkManager owns normal reconnects; --ensure-connected owns the
        # ones we caused. Nothing for the main pass to do.
        state.pop("degraded_since", None)
        return "not-connected", f"{state.get('iface', 'wlan')} is not associated", None

    if link["signal"] is None:
        state.pop("degraded_since", None)
        return "unknown-signal", "driver reported no signal level", None

    where = f"{link['bssid']} ({link['ssid']!r}) at {link['signal']} dBm"

    if link["signal"] > WEAK_DBM:
        state.pop("degraded_since", None)
        return "healthy", f"on {where}", None

    # Weak — and only now is a scan worth its off-channel cost.
    cands = better_candidates(link, scan_fn())
    if not cands:
        state.pop("degraded_since", None)
        return ("no-better-ap",
                f"weak on {where} but no same-SSID AP is "
                f"{MARGIN_DB}+ dB stronger — nowhere better to go", None)

    best = cands[0]
    degraded_since = state.get("degraded_since")
    if not isinstance(degraded_since, (int, float)):
        degraded_since = now
        state["degraded_since"] = degraded_since
    elapsed = int(now - degraded_since)

    gap = best["signal"] - link["signal"]
    why = (f"on {where}; {best['bssid']} is {gap} dB stronger "
           f"({best['signal']} dBm)")

    bounces = [t for t in state.get("bounces", []) if now - t < 3600]
    if len(bounces) >= MAX_BOUNCES_PER_HOUR:
        return ("rate-limited",
                f"{why} — but {len(bounces)} bounces in the last hour, "
                f"leaving alone", best)

    if playing and elapsed < MAX_DEFER_S:
        return ("defer",
                f"{why} — but the room is playing, deferring "
                f"({elapsed}s/{MAX_DEFER_S}s)", best)

    reason = "idle" if not playing else f"forced after {elapsed}s degraded"
    return "bounce", f"{why} ({reason})", best


# ─── Device I/O ────────────────────────────────────────────────────────────────
def detect_iface():
    """First NM-managed wifi device, or wlan0. Env override wins."""
    if IFACE_OVERRIDE:
        return IFACE_OVERRIDE
    rc, out = _run([NMCLI, "-t", "-f", "DEVICE,TYPE", "device"], timeout=10)
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "wifi":
                return parts[0]
    return "wlan0"


def read_link(iface):
    rc, out = _run([IW, "dev", iface, "link"], timeout=10)
    if rc != 0:
        log(f"WARN: iw link failed on {iface}: {out.strip()}")
        return None
    link = parse_iw_link(out)
    if link and link["signal"] is None:
        # Rare, but some brcmfmac builds omit signal from `link` while still
        # populating /proc/net/wireless. Cheap either way.
        try:
            with open("/proc/net/wireless") as f:
                link["signal"] = parse_proc_wireless(f.read(), iface)
        except OSError:
            pass
    return link


def scan(iface):
    """
    Fresh scan. On EBUSY (NetworkManager scanning concurrently) fall back to
    the kernel's cached BSS table rather than skipping the pass — stale-ish
    results still beat no results, and the 15 dB margin absorbs the staleness.
    """
    argv = [IW, "dev", iface, "scan"]
    if SCAN_FREQS:
        argv += ["freq"] + SCAN_FREQS
    rc, out = _run(argv, timeout=30)
    if rc != 0:
        rc2, out2 = _run([IW, "dev", iface, "scan", "dump"], timeout=15)
        if rc2 != 0:
            log(f"WARN: scan failed on {iface}: {out.strip()}")
            return []
        log(f"scan busy ({out.strip().splitlines()[:1]}) — using cached BSS table")
        out = out2
    return parse_iw_scan(out)


def is_playing():
    """
    True when this room is actually making sound.

    The fauxnos PA graph keeps everything downstream permanently open —
    module-suspend-on-idle is unloaded (see feedback_ir_latency_rules), so
    alsa_output and eq_sink read RUNNING around the clock and are useless as
    an activity signal. The *null* sinks (systemsink/analogsink/snapsink/
    airplaysink) are not: they only go RUNNING when a source is writing into
    them. Matching on module-null-sink.c rather than sink names keeps this
    generic as sources come and go.

    Unknown counts as not-playing, matching go-librespot-watchdog's treatment
    of an unreadable snapcast status: the deferral is a courtesy, not a gate.
    """
    sockets = sorted(glob.glob("/run/user/*/pulse/native"))
    if not sockets:
        return False
    uid = sockets[0].split("/")[3]
    # We run as root, so we have to ask PA as the user that owns the daemon.
    if os.geteuid() == 0:
        argv = ["/usr/bin/sudo", "-n", "-u", f"#{uid}", "env",
                f"XDG_RUNTIME_DIR=/run/user/{uid}",
                "pactl", "list", "short", "sinks"]
    else:
        argv = ["pactl", "list", "short", "sinks"]
    rc, out = _run(argv, timeout=10)
    if rc != 0:
        return False
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) >= 5 and cols[2] == "module-null-sink.c" \
                and cols[4].strip() == "RUNNING":
            return True
    return False


def default_gateway(iface):
    """Gateway for `iface` from the routing table. None if there isn't one."""
    rc, out = _run(["/usr/sbin/ip", "route", "show", "default"], timeout=10)
    if rc != 0:
        rc, out = _run(["ip", "route", "show", "default"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts and "dev" in parts:
            via = parts[parts.index("via") + 1]
            dev = parts[parts.index("dev") + 1]
            if dev == iface:
                return via
    return None


def device_state(iface):
    """NM's state string for `iface` ('connected', 'disconnected', …)."""
    rc, out = _run([NMCLI, "-t", "-f", "DEVICE,STATE", "device"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] == iface:
            return parts[1]
    return None


def active_profile(iface):
    """Name of the connection profile currently active on `iface`."""
    rc, out = _run([NMCLI, "-t", "-f", "NAME,DEVICE", "connection", "show",
                    "--active"], timeout=10)
    if rc != 0:
        return None
    for line in out.splitlines():
        # Profile names may contain ':' — nmcli escapes those as '\:', so
        # split from the right on the last unescaped field.
        if line.endswith(f":{iface}"):
            return line[: -(len(iface) + 1)].replace("\\:", ":")
    return None


def autoconnect_wifi_profiles():
    """Wifi profiles with autoconnect on, highest autoconnect-priority first."""
    rc, out = _run([NMCLI, "-t", "-f",
                    "NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY",
                    "connection", "show"], timeout=10)
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        name, ctype, auto, prio = (parts[-4], parts[-3], parts[-2], parts[-1])
        if ctype != "802-11-wireless" or auto != "yes":
            continue
        try:
            prio = int(prio)
        except ValueError:
            prio = 0
        found.append((prio, name.replace("\\:", ":")))
    return [n for _, n in sorted(found, key=lambda p: p[0], reverse=True)]


def reconnect(iface, preferred_profile):
    """
    Bring `iface` back up, lightest option first. Returns True on the first
    step that reports success.

      1. `device connect` — NM re-runs its own candidate ranking, which is
         what makes a pinned high-priority profile win when its AP is back and
         lose gracefully to the unpinned fallback when it isn't.
      2. the profile that was active before we disconnected.
      3. every autoconnect wifi profile, priority order.

    Deliberately never touches profile contents, wpa_supplicant, or the
    NetworkManager service itself.
    """
    attempts = [([NMCLI, "device", "connect", iface], f"device connect {iface}")]
    if preferred_profile:
        attempts.append(([NMCLI, "connection", "up", preferred_profile,
                          "ifname", iface], f"connection up {preferred_profile!r}"))
    for name in autoconnect_wifi_profiles():
        if name == preferred_profile:
            continue
        attempts.append(([NMCLI, "connection", "up", name, "ifname", iface],
                         f"connection up {name!r}"))

    for argv, label in attempts:
        rc, out = _run(argv, timeout=VERIFY_TIMEOUT_S)
        if rc == 0:
            return True, label
        log(f"  reconnect via {label} failed: {out.strip().splitlines()[:1]}")
    return False, "all reconnect attempts failed"


def verify(iface, deadline_s=VERIFY_TIMEOUT_S):
    """Wait for NM 'connected', then ping the gateway. Returns a status str."""
    end = time.time() + deadline_s
    while time.time() < end:
        if device_state(iface) == "connected":
            break
        time.sleep(2)
    else:
        return "NOT CONNECTED after bounce"

    gw = default_gateway(iface)
    if not gw:
        return "connected, but no default gateway on this interface"
    rc, _ = _run(["ping", "-c", "3", "-W", "2", "-q", gw], timeout=20)
    link = read_link(iface)
    where = (f"{link['bssid']} at {link['signal']} dBm, "
             f"rx {link['rx_bitrate']} Mbit/s") if link else "unknown BSS"
    return (f"connected to {where}; gateway {gw} "
            f"{'reachable' if rc == 0 else 'UNREACHABLE'}")


# ─── State ─────────────────────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
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


# ─── Main pass ─────────────────────────────────────────────────────────────────
def run(dry_run=False, now=None):
    now = time.time() if now is None else now
    state = load_state()
    iface = detect_iface()
    state["iface"] = iface

    link = read_link(iface)
    # Only pay for the playback probe when a bounce is actually on the table.
    playing = bool(link and link["signal"] is not None
                   and link["signal"] <= WEAK_DBM and is_playing())

    action, message, _best = evaluate(
        link, lambda: scan(iface), playing, state, now
    )

    # Silent when healthy: log a line only when the situation changes. Every
    # journal entry is therefore a real transition, and "how often does this
    # fire?" is answerable straight from journalctl.
    if action != state.get("last_action"):
        if action == "healthy" and state.get("last_action") not in (None, "healthy"):
            log(f"recovered — {message}")
        elif action != "healthy":
            log(f"{action}: {message}")
    state["last_action"] = action

    if action != "bounce":
        save_state(state)
        return 0

    if dry_run:
        log(f"WOULD bounce {iface} — {message} [dry-run]")
        save_state(state)
        return 0

    profile = active_profile(iface)
    log(f"BOUNCING {iface} — {message} (profile {profile!r})")

    # Record the bounce and arm --ensure-connected BEFORE touching the radio.
    # If this process dies mid-bounce, ExecStopPost still knows to finish the
    # job — and the rate cap still counts the attempt, so a bounce that keeps
    # failing can't churn.
    state.setdefault("bounces", [])
    state["bounces"] = [t for t in state["bounces"] if now - t < 3600] + [now]
    state["last_bounce"] = now
    state["last_profile"] = profile
    state.pop("degraded_since", None)
    state["last_action"] = "bounce"
    save_state(state)

    rc, out = _run([NMCLI, "device", "disconnect", iface], timeout=30)
    if rc != 0:
        log(f"  disconnect returned {rc}: {out.strip().splitlines()[:1]}")
    time.sleep(2)

    ok, how = reconnect(iface, profile)
    if not ok:
        log(f"  RECONNECT FAILED — {how}; ExecStopPost will retry")
        return 1

    log(f"  reconnected via {how}; {verify(iface)}")
    return 0


# ─── ensure-connected (ExecStopPost safety net) ────────────────────────────────
def ensure_connected(now=None):
    """
    Cheap 'did our bounce actually come back?' check. Armed only for
    ENSURE_WINDOW_S after a bounce *we* started, so it never fights
    NetworkManager during normal boot or a user-initiated reconfiguration.
    """
    now = time.time() if now is None else now
    state = load_state()
    last = state.get("last_bounce")
    if not isinstance(last, (int, float)) or now - last > ENSURE_WINDOW_S:
        return 0

    iface = state.get("iface") or detect_iface()
    st = device_state(iface)
    if st is None or st.startswith("connected"):
        return 0

    log(f"ensure-connected: {iface} is '{st}' {int(now - last)}s after a bounce "
        f"— reconnecting")
    ok, how = reconnect(iface, state.get("last_profile"))
    log(f"ensure-connected: {'recovered via ' + how if ok else 'FAILED — ' + how}")
    return 0 if ok else 1


# ─── Simulation / self-test (no device access) ─────────────────────────────────
def _scenario(link, bsses, playing, state=None, now=1_000_000.0):
    """Run evaluate() against canned inputs; returns (action, message, scanned)."""
    calls = []

    def fake_scan():
        calls.append(1)
        return bsses

    st = dict(state or {})
    action, message, _ = evaluate(link, fake_scan, playing, st, now)
    return action, message, bool(calls), st


def _link(bssid, signal, ssid="Palacio de Mila"):
    return {"bssid": bssid, "ssid": ssid, "signal": signal,
            "freq": 2462, "rx_bitrate": 72.2}


def _bss(bssid, signal, ssid="Palacio de Mila"):
    return {"bssid": bssid, "ssid": ssid, "signal": signal,
            "freq": 2462, "associated": False}


NEAR = "00:ab:48:80:e0:05"
FAR = "c4:f1:74:9f:0c:87"

# Real `iw dev wlan0 link` output captured from fauxnos001 after the BSSID pin.
SAMPLE_LINK = """Connected to 00:ab:48:80:e0:05 (on wlan0)
\tSSID: Palacio de Mila
\tfreq: 2462
\tRX: 1907070 bytes (7542 packets)
\tTX: 470094 bytes (4651 packets)
\tsignal: -27 dBm
\trx bitrate: 72.2 MBit/s
\ttx bitrate: 72.2 MBit/s

\tbss flags:\tshort-preamble
\tdtim period:\t2
\tbeacon int:\t100
"""

SAMPLE_SCAN = """BSS 00:ab:48:80:e0:05(on wlan0)
\tTSF: 123456789 usec (1d, 10:17:36)
\tfreq: 2462
\tbeacon interval: 100 TUs
\tcapability: ESS Privacy ShortSlotTime (0x0411)
\tsignal: -26.00 dBm
\tlast seen: 100 ms ago
\tSSID: Palacio de Mila
\tSupported rates: 1.0* 2.0* 5.5* 11.0*
BSS c4:f1:74:9f:0c:87(on wlan0) -- associated
\tfreq: 2462
\tsignal: -59.00 dBm
\tlast seen: 60 ms ago
\tSSID: Palacio de Mila
BSS aa:bb:cc:dd:ee:ff(on wlan0)
\tfreq: 2437
\tsignal: -40.00 dBm
\tSSID: SomeNeighbour
"""

SAMPLE_PROC_WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets\
               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   70.  -28.  -256        0      0      0     12      0        0
"""


def self_test():
    failures = 0

    def check(name, got, expected):
        nonlocal failures
        ok = got == expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"         expected {expected!r}")
            print(f"         got      {got!r}")
            failures += 1

    print("parsers")
    link = parse_iw_link(SAMPLE_LINK)
    check("iw link → bssid", link["bssid"], NEAR)
    check("iw link → ssid", link["ssid"], "Palacio de Mila")
    check("iw link → signal", link["signal"], -27)
    check("iw link → rx bitrate", link["rx_bitrate"], 72.2)
    check("iw link → not connected", parse_iw_link("Not connected.\n"), None)
    check("/proc/net/wireless → signal",
          parse_proc_wireless(SAMPLE_PROC_WIRELESS, "wlan0"), -28)
    check("/proc/net/wireless → other iface",
          parse_proc_wireless(SAMPLE_PROC_WIRELESS, "wlan1"), None)

    bsses = parse_iw_scan(SAMPLE_SCAN)
    check("iw scan → count", len(bsses), 3)
    check("iw scan → signals",
          [b["signal"] for b in bsses], [-26, -59, -40])
    check("iw scan → associated flag",
          [b["bssid"] for b in bsses if b["associated"]], [FAR])
    check("iw scan → ssid filter picks near AP only",
          [b["bssid"] for b in better_candidates(_link(FAR, -59), bsses)],
          [NEAR])
    check("iw scan → empty input", parse_iw_scan(""), [])

    print("\ntrigger logic")
    # The bug this exists for: parked on the far node at -59 with the near AP
    # 33 dB louder, room idle.
    action, msg, scanned, _ = _scenario(_link(FAR, -59), bsses, playing=False)
    check("far-AP + idle → bounce", action, "bounce")
    check("far-AP + idle → scan was run", scanned, True)
    print(f"         → {msg}")

    # Healthy post-fix state: -27 dBm. Must not even scan.
    action, msg, scanned, _ = _scenario(_link(NEAR, -27), bsses, playing=False)
    check("healthy → no action", action, "healthy")
    check("healthy → scan NOT run (radio untouched)", scanned, False)

    # Weak but genuinely nothing better — a far room, not a sticky client.
    action, msg, scanned, _ = _scenario(
        _link(FAR, -62), [_bss(FAR, -62), _bss(NEAR, -55)], playing=False)
    check("weak but only 7 dB better → no bounce", action, "no-better-ap")
    check("weak → scan WAS run", scanned, True)

    # Same trigger, but the room is playing: defer, then force at the bound.
    action, msg, _, st = _scenario(_link(FAR, -59), bsses, playing=True)
    check("far-AP + playing → defer", action, "defer")
    check("defer → degradation clock started",
          isinstance(st.get("degraded_since"), float), True)
    action, msg, _, _ = _scenario(
        _link(FAR, -59), bsses, playing=True,
        state={"degraded_since": 1_000_000.0 - MAX_DEFER_S - 1})
    check("far-AP + playing past the bound → bounce anyway", action, "bounce")
    print(f"         → {msg}")

    # Rate cap.
    action, msg, _, _ = _scenario(
        _link(FAR, -59), bsses, playing=False,
        state={"bounces": [1_000_000.0 - 60] * MAX_BOUNCES_PER_HOUR})
    check("at the hourly cap → rate-limited", action, "rate-limited")
    action, msg, _, _ = _scenario(
        _link(FAR, -59), bsses, playing=False,
        state={"bounces": [1_000_000.0 - 4000] * MAX_BOUNCES_PER_HOUR})
    check("cap entries older than an hour are pruned", action, "bounce")

    # Degradation clock must reset once we're healthy again.
    _, _, _, st = _scenario(_link(NEAR, -27), bsses, playing=False,
                            state={"degraded_since": 1.0})
    check("recovery clears the degradation clock",
          "degraded_since" in st, False)

    # Edge cases.
    check("not associated → no action",
          _scenario(None, bsses, playing=False)[0], "not-connected")
    check("no signal reported → no action",
          _scenario({"bssid": NEAR, "ssid": "x", "signal": None,
                     "freq": None, "rx_bitrate": None},
                    bsses, playing=False)[0], "unknown-signal")
    check("a stronger AP on a DIFFERENT ssid is ignored",
          _scenario(_link(FAR, -59),
                    [_bss("11:22:33:44:55:66", -20, ssid="Neighbour")],
                    playing=False)[0], "no-better-ap")
    check("our own BSS reported stronger by the scan is ignored",
          _scenario(_link(FAR, -59), [_bss(FAR, -20)], playing=False)[0],
          "no-better-ap")

    total = failures
    print(f"\n{'ALL PASS' if not total else str(total) + ' FAILURE(S)'}")
    return 1 if total else 0


def simulate(path):
    """
    Exercise the trigger against a JSON scenario file, touching no hardware:

      {"link": "<iw dev wlan0 link output>",
       "scan": "<iw dev wlan0 scan output>",
       "playing": false,
       "state": {}}
    """
    with open(path) as f:
        sc = json.load(f)
    link = parse_iw_link(sc.get("link", ""))
    bsses = parse_iw_scan(sc.get("scan", ""))
    action, msg, scanned, st = _scenario(
        link, bsses, bool(sc.get("playing")), sc.get("state"),
        float(sc.get("now", time.time())),
    )
    print(f"action:  {action}")
    print(f"reason:  {msg}")
    print(f"scanned: {scanned}  (False = radio never left channel)")
    print(f"state:   {json.dumps(st, sort_keys=True)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="fauxnos wifi roam watchdog")
    ap.add_argument("--self-test", action="store_true",
                    help="run parser + trigger unit tests and exit "
                         "(no device access)")
    ap.add_argument("--simulate", metavar="FILE",
                    help="evaluate a JSON scenario file instead of the live "
                         "radio (no device access)")
    ap.add_argument("--dry-run", action="store_true",
                    help="read the live radio and log the decision, but never "
                         "bounce")
    ap.add_argument("--ensure-connected", action="store_true",
                    help="safety net: reconnect the interface if a recent "
                         "bounce left it down (wired to ExecStopPost)")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.simulate:
        return simulate(args.simulate)
    if args.ensure_connected:
        return ensure_connected()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
