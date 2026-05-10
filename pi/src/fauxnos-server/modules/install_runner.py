#!/usr/bin/env python3
"""
InstallRunner — server-driven client install with live progress timeline.

The Add Device wizard (web UI) hands a target hostname + display name to this
runner. The runner SSHes in as `user@<target_host>` using the server-owned key
at ~/.ssh/id_ed25519_fauxnos, invokes the client install one-liner, and parses
install.sh's `log_section` markers off stdout into a timeline of steps. Each
step transition (pending → active → succeeded/failed/stalled) is broadcast as
an SSE event to whoever is subscribed.

Reboot is a flag, not a failure: when install.sh prints "Rebooting now…" we
close the SSH session deliberately and transition into the `verify` step,
which polls snapcast (via the existing JSON-RPC path) until the freshly-
registered client_id is connected.

Concurrency: at most one runner active at a time. The InstallManager holds
the singleton and 409s overlapping starts.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("fauxnos.install_runner")

# ── Step table ─────────────────────────────────────────────────────────────────
#
# Each tuple is (step_id, label, list_of_completion_regexes). The first regex
# transitions the step from `pending → active` (the step "starts"); the last
# regex transitions it to `succeeded`. Intermediate regexes are advisory and
# only refresh `last_stdout_at` so the stall watchdog doesn't trip.
#
# The matcher walks the table top-to-bottom and never moves backwards. If a
# line matches the start of step N, every step before N that's still pending
# is auto-marked succeeded (covers cases where a step's start line never
# printed because, say, a sub-section was no-op'd).
#
STEP_TABLE: list[tuple[str, str, list[str]]] = [
    ("discover", "Find target host",
        []),  # populated by runner code itself, not stdout-driven
    ("connect", "Connect over SSH",
        []),  # ditto
    ("apt-update", "Update system packages", [
        r"=== Installing System Dependencies ===",
        r"Updating package lists",
        r"Installing core dependencies",
        r"✓ System dependencies installed",
    ]),
    ("configure-system", "Configure system & audio", [
        r"=== Configuring System ===",
        r"✓ System configuration completed",
    ]),
    ("disable-snapclient", "Disable apt snapclient", [
        r"Disabling system snapclient\.service",
        r"✓ System snapclient disabled",
    ]),
    ("pulseaudio", "Switch to PulseAudio", [
        r"=== Switching from PipeWire to PulseAudio ===",
        r"✓ PulseAudio user services configured",
    ]),
    ("download-code", "Download client code", [
        r"=== Downloading Fauxnos Client ===",
        r"✓ Client code downloaded",
    ]),
    ("register", "Register with server", [
        r"=== Registering Client with Server ===",
        # Capture client_id from this last line.
        r"✓ Registration successful! Assigned client_id: (?P<client_id>fauxnos\d+)",
    ]),
    ("deploy-services", "Deploy systemd services", [
        r"=== (Creating|Deploying) (Systemd|Client) Services? ===|Created user service:",
        r"Starting user services?|Services? enabled and started|✓ Services? enabled",
    ]),
    ("reboot", "Reboot client", [
        r"Rebooting (now|in)\b",
        # No success line over SSH — we close the channel ourselves.
    ]),
    ("verify", "Wait for client to come back",
        []),  # populated by runner code itself
]

REBOOT_PATTERN = re.compile(r"Rebooting (now|in)\b")
CLIENT_ID_PATTERN = re.compile(r"Assigned client_id:\s*(?P<client_id>fauxnos\d+)")

STALL_THRESHOLD_SECONDS = 30
STALL_WATCHDOG_INTERVAL = 5
DISCOVER_TIMEOUT_SECONDS = 180
DISCOVER_RETRY_SECONDS = 5
SSH_CONNECT_TIMEOUT_SECONDS = 30
VERIFY_TIMEOUT_SECONDS = 180  # post-reboot the Pi takes a while; be generous
VERIFY_POLL_SECONDS = 4
LOG_TAIL_MAXLEN = 20

DEFAULT_KEY_PATH = Path.home() / ".ssh" / "id_ed25519_fauxnos"


# ── State dataclasses ─────────────────────────────────────────────────────────


@dataclass
class StepState:
    id: str
    label: str
    status: str = "pending"  # pending|active|succeeded|failed|stalled|skipped
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    log_tail: deque = field(default_factory=lambda: deque(maxlen=LOG_TAIL_MAXLEN))
    note: Optional[str] = None  # short human note (e.g. why stalled, what failed)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "started_at": _iso(self.started_at),
            "ended_at": _iso(self.ended_at),
            "duration_seconds": (
                (self.ended_at or time.time()) - self.started_at
                if self.started_at else None
            ),
            "log_tail": list(self.log_tail),
            "note": self.note,
        }


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── Runner ────────────────────────────────────────────────────────────────────


class InstallRunner:
    """One install attempt. Threaded; emits step/tail/done events."""

    def __init__(
        self,
        target_host: str,
        display_name: str,
        ssh_user: str = "user",
        ssh_key_path: Optional[Path] = None,
        server_host: str = "fauxnos000.local",
        client_status_fn: Optional[Callable[[], dict]] = None,
        snapcast_status_fn: Optional[Callable[[], dict]] = None,
    ):
        self.install_id = uuid.uuid4().hex
        self.target_host = target_host
        self.display_name = display_name
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path or DEFAULT_KEY_PATH
        self.server_host = server_host
        # Injected so the runner doesn't reach into Flask's `app` or rebuild
        # snapcast plumbing. `client_status_fn` returns {client_id: connected}.
        self._snapcast_status_fn = snapcast_status_fn or (lambda: {})
        self._list_clients_fn = client_status_fn or (lambda: [])

        self.status: str = "queued"  # queued|running|succeeded|failed|cancelled
        self.client_id: Optional[str] = None
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None

        # Initialize all steps as pending in declaration order.
        self.steps: list[StepState] = [StepState(id=s, label=l) for s, l, _ in STEP_TABLE]
        self._current_step_idx: int = 0

        # Pub/sub bookkeeping.
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ssh_client = None
        self._last_stdout_at: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> "InstallRunner":
        if self._thread is not None:
            raise RuntimeError("InstallRunner already started")
        self.status = "running"
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"install-{self.install_id[:8]}")
        self._thread.start()
        return self

    def cancel(self):
        if self.status not in ("running", "queued"):
            return
        self._cancel.set()
        ssh = self._ssh_client
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(q)
        # Send a snapshot first so a late subscriber sees the current state.
        try:
            q.put_nowait({"type": "snapshot", "data": self.snapshot()})
        except queue.Full:
            pass
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "install_id": self.install_id,
                "target_host": self.target_host,
                "display_name": self.display_name,
                "status": self.status,
                "current_step": self.steps[self._current_step_idx].id if self.steps else None,
                "steps": [s.snapshot() for s in self.steps],
                "client_id": self.client_id,
                "error": self.error,
                "started_at": _iso(self.started_at),
                "ended_at": _iso(self.ended_at),
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _emit(self, event_type: str, payload: dict):
        event = {"type": event_type, "data": payload}
        with self._lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    # Slow consumer — drop oldest to keep the stream live.
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except Exception:
                        pass

    def _step_by_id(self, step_id: str) -> Optional[StepState]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def _enter_step(self, step_id: str):
        with self._lock:
            for i, s in enumerate(self.steps):
                if s.id == step_id:
                    # Auto-succeed any earlier active steps.
                    if s.status not in ("active",):
                        s.status = "active"
                        s.started_at = s.started_at or time.time()
                        s.ended_at = None
                    for j in range(i):
                        prev = self.steps[j]
                        if prev.status in ("pending",):
                            prev.status = "skipped"
                            prev.started_at = prev.started_at or time.time()
                            prev.ended_at = time.time()
                        elif prev.status == "active":
                            prev.status = "succeeded"
                            prev.ended_at = time.time()
                    self._current_step_idx = i
                    self._last_stdout_at = time.time()
                    self._emit("step", s.snapshot())
                    return

    def _succeed_step(self, step_id: str):
        with self._lock:
            s = self._step_by_id(step_id)
            if s and s.status not in ("succeeded", "failed"):
                s.status = "succeeded"
                s.ended_at = time.time()
                self._emit("step", s.snapshot())

    def _fail_step(self, step_id: str, note: str):
        with self._lock:
            s = self._step_by_id(step_id)
            if s and s.status not in ("succeeded", "failed"):
                s.status = "failed"
                s.note = note
                s.ended_at = time.time()
                self._emit("step", s.snapshot())

    def _append_tail(self, line: str):
        if not line:
            return
        with self._lock:
            s = self.steps[self._current_step_idx]
            s.log_tail.append(line)
            self._last_stdout_at = time.time()
            # Clear stalled flag on fresh output.
            if s.status == "stalled":
                s.status = "active"
                s.note = None
                self._emit("step", s.snapshot())
        self._emit("tail", {"step_id": self.steps[self._current_step_idx].id, "line": line})

    def _stall_watchdog(self):
        while self.status == "running" and not self._cancel.is_set():
            time.sleep(STALL_WATCHDOG_INTERVAL)
            with self._lock:
                if not self.steps:
                    continue
                s = self.steps[self._current_step_idx]
                if s.status != "active":
                    continue
                if self._last_stdout_at == 0:
                    continue
                idle = time.time() - self._last_stdout_at
                if idle > STALL_THRESHOLD_SECONDS:
                    s.status = "stalled"
                    s.note = f"No output for {int(idle)}s"
                    self._emit("step", s.snapshot())

    # ── Main lifecycle ────────────────────────────────────────────────────────

    def _run(self):
        try:
            watchdog = threading.Thread(target=self._stall_watchdog, daemon=True, name=f"watchdog-{self.install_id[:8]}")
            watchdog.start()

            self._enter_step("discover")
            if not self._discover():
                self._fail_step("discover", f"Could not resolve {self.target_host}")
                return self._finish("failed", f"Could not resolve {self.target_host}")
            self._succeed_step("discover")

            self._enter_step("connect")
            ssh = self._ssh_connect()
            if ssh is None:
                self._fail_step("connect", "SSH connection failed")
                return self._finish("failed", "SSH connection failed")
            self._ssh_client = ssh
            self._succeed_step("connect")

            # Now run the client install one-liner. Stay in `apt-update` until
            # stdout matches a later step's start line.
            self._enter_step("apt-update")
            rc, reboot_seen = self._stream_install(ssh)

            if self._cancel.is_set():
                return self._finish("cancelled", "Cancelled")

            if not reboot_seen and rc != 0:
                # SSH ended without ever reaching the reboot line.
                cur = self.steps[self._current_step_idx]
                self._fail_step(cur.id, f"install.sh exited with code {rc}")
                return self._finish("failed", f"install.sh exited with code {rc}")

            # If we did see the reboot line, mark `reboot` succeeded; the
            # SSH disconnect that followed is expected.
            if reboot_seen:
                self._succeed_step("reboot")

            # Verify: poll until the new client appears connected.
            self._enter_step("verify")
            if not self._verify_back_online():
                self._fail_step("verify", "Client did not come back online in time")
                return self._finish("failed", "Client did not come back online")
            self._succeed_step("verify")

            self._finish("succeeded", None)
        except Exception as e:
            logger.exception("InstallRunner crashed")
            cur = self.steps[self._current_step_idx]
            self._fail_step(cur.id, str(e))
            self._finish("failed", str(e))

    def _finish(self, status: str, error: Optional[str]):
        with self._lock:
            self.status = status
            self.error = error
            self.ended_at = time.time()
            # Close out current active/stalled step state if not already.
            for s in self.steps:
                if s.status in ("active", "stalled"):
                    s.status = "failed" if status != "succeeded" else "succeeded"
                    s.ended_at = time.time()
                    if status != "succeeded" and not s.note:
                        s.note = error or "Aborted"
        self._emit("done", self.snapshot())
        if self._ssh_client is not None:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None

    # ── Step impls ────────────────────────────────────────────────────────────

    def _discover(self) -> bool:
        deadline = time.time() + DISCOVER_TIMEOUT_SECONDS
        while time.time() < deadline and not self._cancel.is_set():
            try:
                ip = socket.gethostbyname(self.target_host)
                self._append_tail(f"Resolved {self.target_host} → {ip}")
                return True
            except OSError as e:
                self._append_tail(f"Waiting on mDNS for {self.target_host} ({e})")
                time.sleep(DISCOVER_RETRY_SECONDS)
        return False

    def _ssh_connect(self):
        try:
            import paramiko  # imported lazily so the rest of the server can run without it
        except ImportError as e:
            self._append_tail(f"paramiko not installed: {e}")
            return None

        if not self.ssh_key_path.exists():
            self._append_tail(f"Server install key missing at {self.ssh_key_path}; run install.sh first")
            return None

        # Re-flashing a Pi gives it a brand-new host key under the same name
        # (`fauxnos-client.local`). If the server's known_hosts already has the
        # previous flash's key, paramiko raises BadHostKeyException and the
        # whole install dies at the connect step. Strip stale entries for the
        # target hostname (and its current IP, if resolvable) before connecting,
        # then let AutoAddPolicy persist the fresh key for next time.
        self._clear_stale_host_keys(self.target_host)

        client = paramiko.SSHClient()
        # Re-load known_hosts AFTER cleaning so AutoAddPolicy can append the
        # fresh key back to it during connect().
        try:
            client.load_system_host_keys()
        except Exception:
            pass
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.target_host,
                username=self.ssh_user,
                key_filename=str(self.ssh_key_path),
                timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                banner_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                auth_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
                allow_agent=False,
                look_for_keys=False,
            )
            self._append_tail(f"SSH connected as {self.ssh_user}@{self.target_host}")
            return client
        except Exception as e:
            self._append_tail(f"SSH connect failed: {e}")
            try:
                client.close()
            except Exception:
                pass
            return None

    def _clear_stale_host_keys(self, host: str):
        """Remove any existing known_hosts entries for `host` (and its IP).
        ssh-keygen -R is the canonical way; falling back to silent no-op if it
        isn't installed (vanishingly unlikely on a Pi running install.sh)."""
        import shutil
        import subprocess
        if not shutil.which("ssh-keygen"):
            return
        targets = [host]
        try:
            ip = socket.gethostbyname(host)
            if ip and ip != host:
                targets.append(ip)
        except OSError:
            pass
        for t in targets:
            try:
                subprocess.run(
                    ["ssh-keygen", "-R", t],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except Exception as e:
                # Non-fatal — worst case AutoAddPolicy will still add the key,
                # but a stale conflicting key would already have triggered a
                # BadHostKeyException by then. Log so we know.
                self._append_tail(f"ssh-keygen -R {t} failed: {e}")

    def _stream_install(self, ssh) -> tuple[int, bool]:
        """Run the client install one-liner; returns (exit_code, reboot_seen).

        Reading stdout/stderr line-by-line is the whole point — we feed each
        line into the step matcher AND into the active step's log_tail so the
        UI shows real-time progress.
        """
        # sanitize display_name for the bash invocation; quoted via shlex below.
        import shlex
        cmd = (
            f"FAUXNOS_SERVER_HOST={shlex.quote(self.server_host)} "
            f"DISPLAY_NAME={shlex.quote(self.display_name)} "
            f"bash -c 'curl -sSL \"http://{self.server_host}:8080/api/install/client.sh\" | bash'"
        )
        self._append_tail(f"Running: {cmd}")

        # Use exec_command + a manual loop because Paramiko's makefile() can
        # buffer aggressively; we want each line as soon as it lands.
        transport = ssh.get_transport()
        if transport is None:
            return (255, False)
        chan = transport.open_session()
        chan.get_pty()  # forces line-buffered output from bash + curl + pip
        chan.exec_command(cmd)

        reboot_seen = False
        buf_out = b""
        buf_err = b""
        compiled = self._compile_step_matchers()

        while True:
            if self._cancel.is_set():
                try:
                    chan.close()
                except Exception:
                    pass
                break

            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break

            # Read whatever is available; ANSI color codes are common, strip them.
            if chan.recv_ready():
                buf_out += chan.recv(4096)
                buf_out = self._drain_lines(buf_out, compiled, is_stderr=False, ctx={"reboot": False})
            if chan.recv_stderr_ready():
                buf_err += chan.recv_stderr(4096)
                buf_err = self._drain_lines(buf_err, compiled, is_stderr=True, ctx={"reboot": False})

            # Reboot line check — when seen, give bash 2s to actually reboot
            # then close the channel so we can move on. install.sh prints
            # "Rebooting in N seconds..." then "Rebooting now..." — either
            # works because the regex is loose.
            if not reboot_seen and self._reboot_seen_in_steps():
                reboot_seen = True
                # Drop a marker line so the UI sees it.
                self._enter_step("reboot")
                self._append_tail("Reboot triggered; waiting for client to come back")
                try:
                    # Don't wait forever — the channel may hang once sshd dies.
                    time.sleep(2)
                    chan.close()
                except Exception:
                    pass
                break

            time.sleep(0.05)

        # Flush any straggler bytes.
        try:
            self._drain_lines(buf_out, compiled, is_stderr=False, ctx={"reboot": False}, flush=True)
            self._drain_lines(buf_err, compiled, is_stderr=True, ctx={"reboot": False}, flush=True)
        except Exception:
            pass

        try:
            rc = chan.recv_exit_status() if not reboot_seen else 0
        except Exception:
            rc = 0 if reboot_seen else 1
        return (rc, reboot_seen)

    def _reboot_seen_in_steps(self) -> bool:
        s = self._step_by_id("reboot")
        return s is not None and s.started_at is not None

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    def _drain_lines(self, buf: bytes, compiled: list, is_stderr: bool, ctx: dict, flush: bool = False) -> bytes:
        """Split `buf` on newlines and dispatch each completed line. Returns the
        unconsumed remainder."""
        text = buf.decode("utf-8", errors="replace")
        if flush and text:
            text += "\n"
        lines = text.split("\n")
        if not flush:
            remainder = lines.pop()
        else:
            remainder = ""

        for raw in lines:
            line = self._ANSI_RE.sub("", raw).rstrip("\r")
            if not line:
                continue
            self._handle_line(line, compiled)
        return remainder.encode("utf-8") if remainder else b""

    def _compile_step_matchers(self) -> list[tuple[str, list[re.Pattern], list[re.Pattern]]]:
        """Pre-compile patterns for each step. Returns
        [(step_id, [first_patterns], [later_patterns]), …]."""
        out = []
        for sid, _label, patterns in STEP_TABLE:
            if not patterns:
                continue
            firsts = [re.compile(patterns[0])]
            lasts = [re.compile(patterns[-1])] if len(patterns) > 1 else []
            out.append((sid, firsts, lasts))
        return out

    def _handle_line(self, line: str, compiled: list):
        # Always append to current step's tail.
        self._append_tail(line)

        # Capture client_id off the registration line, regardless of step state.
        m = CLIENT_ID_PATTERN.search(line)
        if m and not self.client_id:
            self.client_id = m.group("client_id")
            with self._lock:
                self._emit("step", {"client_id": self.client_id})

        # Reboot line is a hard transition — let _stream_install pick it up.
        if REBOOT_PATTERN.search(line):
            self._enter_step("reboot")
            return

        # Walk steps top-to-bottom. If any step's first pattern matches, jump
        # to it; if the current step's last pattern matches, mark it done.
        for sid, firsts, lasts in compiled:
            for p in firsts:
                if p.search(line):
                    self._enter_step(sid)
                    break
            for p in lasts:
                if p.search(line) and self._step_by_id(sid).status == "active":
                    self._succeed_step(sid)
                    break

    def _verify_back_online(self) -> bool:
        # We need a client_id to look for; if we never saw the registration
        # line, fall back to "any new fauxnosNNN that wasn't here before".
        deadline = time.time() + VERIFY_TIMEOUT_SECONDS
        # Snapshot the existing roster so we can detect a brand-new id.
        try:
            initial = {c.get("client_id") for c in self._list_clients_fn()}
        except Exception:
            initial = set()

        while time.time() < deadline and not self._cancel.is_set():
            try:
                connected = self._snapcast_status_fn() or {}
            except Exception:
                connected = {}
            if self.client_id and connected.get(self.client_id):
                self._append_tail(f"{self.client_id} connected")
                return True
            if not self.client_id:
                # Detect a new id appearing in the roster.
                try:
                    current = {c.get("client_id") for c in self._list_clients_fn()}
                except Exception:
                    current = set()
                new_ids = (current - initial) - {None}
                for nid in new_ids:
                    if connected.get(nid):
                        self.client_id = nid
                        self._append_tail(f"{nid} connected")
                        return True
            time.sleep(VERIFY_POLL_SECONDS)
        return False


# ── Manager singleton ─────────────────────────────────────────────────────────


class InstallManager:
    """Holds at most one active InstallRunner. Keeps the most recent finished
    runner around for `/api/install/status` after the install ends."""

    def __init__(
        self,
        server_host: str = "fauxnos000.local",
        client_status_fn: Optional[Callable[[], dict]] = None,
        snapcast_status_fn: Optional[Callable[[], dict]] = None,
    ):
        self.server_host = server_host
        self._client_status_fn = client_status_fn
        self._snapcast_status_fn = snapcast_status_fn
        self._runner: Optional[InstallRunner] = None
        self._last_runner: Optional[InstallRunner] = None
        self._lock = threading.RLock()

    def start(self, target_host: str, display_name: str) -> InstallRunner:
        with self._lock:
            if self._runner is not None and self._runner.status == "running":
                raise InstallAlreadyRunning(self._runner)
            runner = InstallRunner(
                target_host=target_host,
                display_name=display_name,
                server_host=self.server_host,
                client_status_fn=self._client_status_fn,
                snapcast_status_fn=self._snapcast_status_fn,
            )
            self._runner = runner
            self._last_runner = runner
            runner.start()
            return runner

    def cancel(self):
        with self._lock:
            r = self._runner
        if r is not None:
            r.cancel()

    def current_or_last(self) -> Optional[InstallRunner]:
        with self._lock:
            if self._runner is not None and self._runner.status == "running":
                return self._runner
            return self._last_runner

    def current(self) -> Optional[InstallRunner]:
        with self._lock:
            if self._runner is not None and self._runner.status == "running":
                return self._runner
            return None


class InstallAlreadyRunning(Exception):
    def __init__(self, runner: InstallRunner):
        super().__init__(f"Install {runner.install_id} is already running")
        self.runner = runner
