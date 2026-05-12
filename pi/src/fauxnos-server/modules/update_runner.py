#!/usr/bin/env python3
"""
Fauxnos Update Runner — push an update to a single client over SSH
==================================================================

This is the **fauxnos000 → clients** leg of the deploy chain. The server
SSHes into the target client, runs `install.sh` with environment vars
that turn off the script's "fresh install" behavior (no interactive
prompts, no auto-reboot — we decide), then inspects the marker file
left by install.sh to decide whether a reboot is needed, performs it if
so, waits for the client to come back online via snapcast reconnect,
and records the deployed SHA in `server_config.json`.

Why a separate module from `install_runner.py`:

  * InstallRunner is calibrated for the first-install wizard: it has a
    step-pattern table, stall watchdog, "discover/connect/apt-update/
    /…/reboot/verify" state machine, and recovery semantics for fresh
    Pis. An update is a much narrower path; bolting an update mode onto
    InstallRunner would require branching every step.
  * Updates need to pass DIFFERENT env vars to install.sh (the orchestrator
    knows the device's persistent config — display_name, dac_overlay).
  * Update has its own concurrency model: at most one update-per-client,
    but multiple updates of *different* clients can run sequentially in
    a single "update all" pass.

Lifecycle of a single update:

    1. ssh_connect       — paramiko, reuse known_hosts from install
    2. exec install.sh   — set FAUXNOS_NO_REBOOT=1 + DISPLAY_NAME + …,
                           curl-pipe-bash with stdout streamed line-by-line
    3. check marker      — SSH a `test -f /tmp/fauxnos-install-needs-reboot`
    4. (maybe) reboot    — SSH `sudo reboot`, then wait for the client
                           to come back online (snapcast reconnect, ~30-90s)
    5. record deploy     — update_manager.record_client_deploy(sha, needs_reboot)

Events emitted on the subscriber queue (consumed by /api/clients/<id>/
update SSE):

    phase    — named step boundary: `connect`, `install`, `marker`,
               `reboot`, `wait`, `record`
    output   — a line of stdout from install.sh (or the reboot/wait phase)
    done     — terminal: status=succeeded|failed, sha, needs_reboot
"""

from __future__ import annotations

import logging
import queue
import shlex
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .install_runner import DEFAULT_KEY_PATH


logger = logging.getLogger("update_runner")


# ── Tunable timeouts ──────────────────────────────────────────────────────────

SSH_CONNECT_TIMEOUT_SECONDS = 10
INSTALL_TIMEOUT_SECONDS = 60 * 10        # install.sh takes 1-3 min steady-state
REBOOT_WAIT_TIMEOUT_SECONDS = 180        # Pi Zero 2W boots in ~30-60s typically
REBOOT_WAIT_POLL_SECONDS = 3


# ── Helpers (free functions; can be reused if we ever consolidate with
#    install_runner) ────────────────────────────────────────────────────────────

def _ssh_connect(
    target_host: str,
    ssh_user: str,
    ssh_key_path: Path,
    on_log: Callable[[str], None],
) -> Optional[Any]:
    """Open a paramiko SSH connection. Returns the client or None on failure.

    Mirrors `install_runner._ssh_connect` (key auth only, no agent,
    AutoAddPolicy for host keys) but takes its inputs as args instead of
    coupling to a runner's `self`. `on_log` receives a single human-readable
    line per outcome so the caller can stream it.
    """
    try:
        import paramiko
    except ImportError as e:
        on_log(f"paramiko not installed: {e}")
        return None

    if not ssh_key_path.exists():
        on_log(f"Server install key missing at {ssh_key_path}")
        return None

    client = paramiko.SSHClient()
    try:
        client.load_system_host_keys()
    except Exception:
        pass
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            target_host,
            username=ssh_user,
            key_filename=str(ssh_key_path),
            timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            banner_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            auth_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            allow_agent=False,
            look_for_keys=False,
        )
        on_log(f"SSH connected to {ssh_user}@{target_host}")
        return client
    except Exception as e:
        on_log(f"SSH connect failed: {e}")
        try:
            client.close()
        except Exception:
            pass
        return None


def _ssh_exec(ssh, cmd: str, timeout: Optional[float] = None) -> tuple[int, str, str]:
    """Run `cmd` on the SSH host; return (exit_code, stdout, stderr)."""
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


# ── UpdateRunner ──────────────────────────────────────────────────────────────


class UpdateRunner:
    """One client-update attempt. Threaded; events flow to subscribers.

    Caller responsibilities:
        * Construct with target hostname + client_id + env dict.
        * Inject:
          - `snapcast_status_fn()` → {client_id: bool}, used to detect when
            a rebooted client comes back online (avoids hard-coding snapcast
            plumbing in this module).
          - `record_deploy_fn(client_id, sha, needs_reboot, log_path)` →
            bool, the bookkeeping callback that writes back to
            server_config.json. Failures are non-fatal.
          - `server_sha` — the SHA we're deploying (computed from
            update_manager.get_server_git_status by the manager).
        * Call `.start()` to kick off the background thread.
        * Subscribe via `.subscribe()` to receive `{type, data}` events;
          drop your subscription via `.unsubscribe()` when done.
    """

    def __init__(
        self,
        client_id: str,
        target_host: str,
        env: Dict[str, str],
        server_sha: str,
        server_host: str = "fauxnos000.local",
        ssh_user: str = "user",
        ssh_key_path: Optional[Path] = None,
        snapcast_status_fn: Optional[Callable[[], Dict[str, bool]]] = None,
        record_deploy_fn: Optional[Callable[[str, str, bool, Optional[str]], bool]] = None,
    ):
        self.update_id = uuid.uuid4().hex
        self.client_id = client_id
        self.target_host = target_host
        self.env = dict(env)  # copy so caller can't mutate mid-run
        self.server_sha = server_sha
        self.server_host = server_host
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path or DEFAULT_KEY_PATH
        self._snapcast_status_fn = snapcast_status_fn or (lambda: {})
        self._record_deploy_fn = record_deploy_fn or (lambda *a, **kw: False)

        # Mirror InstallRunner pub/sub interface.
        self.status: str = "queued"  # queued|running|succeeded|failed|cancelled
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None
        self.error: Optional[str] = None
        self.needs_reboot: Optional[bool] = None  # set after marker check
        self.rebooted: bool = False               # True if we actually rebooted it
        self.deployed_sha: Optional[str] = None   # set on success

        # Subscriber queues + cancel flag.
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._log_lines: list[str] = []  # in-memory tail for snapshots

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> "UpdateRunner":
        if self._thread is not None:
            raise RuntimeError("UpdateRunner already started")
        self.status = "running"
        self.started_at = time.time()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"update-{self.client_id}-{self.update_id[:8]}",
        )
        self._thread.start()
        return self

    def cancel(self):
        """Signal cooperative cancel. The SSH operation in flight will be
        torn down at the next checkpoint (we can't always interrupt paramiko
        mid-read but we can stop the wait-for-return loop)."""
        self._cancel.set()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._subscribers.append(q)
            try:
                q.put_nowait({"type": "snapshot", "data": self.snapshot()})
            except queue.Full:
                pass
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "update_id": self.update_id,
                "client_id": self.client_id,
                "target_host": self.target_host,
                "status": self.status,
                "needs_reboot": self.needs_reboot,
                "rebooted": self.rebooted,
                "deployed_sha": self.deployed_sha,
                "server_sha": self.server_sha,
                "error": self.error,
                "started_at": self._iso(self.started_at),
                "ended_at": self._iso(self.ended_at),
                "log_tail": self._log_lines[-200:],
            }

    @staticmethod
    def _iso(ts: Optional[float]) -> Optional[str]:
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    # ── Event emission ────────────────────────────────────────────────────────

    def _emit(self, event_type: str, data: Dict[str, Any]):
        event = {"type": event_type, "data": data}
        with self._lock:
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except queue.Full:
                    # Drop oldest to keep the stream live.
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except Exception:
                        pass

    def _phase(self, name: str, message: str, **extra):
        payload = {"name": name, "message": message}
        payload.update(extra)
        self._emit("phase", payload)

    def _output(self, line: str):
        with self._lock:
            self._log_lines.append(line)
            # Cap memory at 2000 lines — install.sh output is bounded.
            if len(self._log_lines) > 2000:
                self._log_lines = self._log_lines[-1500:]
        self._emit("output", {"line": line})

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _run(self):
        ssh = None
        try:
            # 1. SSH connect
            self._phase("connect", f"Connecting to {self.target_host}...")
            ssh = _ssh_connect(
                self.target_host, self.ssh_user, self.ssh_key_path, self._output
            )
            if ssh is None:
                self._finish("failed", "SSH connection failed")
                return
            if self._cancel.is_set():
                self._finish("cancelled", "Cancelled before install started")
                return

            # 2. Run install.sh
            self._phase("install", "Running install.sh...")
            rc = self._stream_install(ssh)
            if rc != 0:
                self._finish("failed", f"install.sh exited with code {rc}")
                return
            if self._cancel.is_set():
                self._finish("cancelled", "Cancelled after install completed")
                return

            # 3. Check marker file
            self._phase("marker", "Checking /tmp/fauxnos-install-needs-reboot...")
            self.needs_reboot = self._check_marker(ssh)
            self._output(
                f"needs_reboot = {self.needs_reboot}"
                + (" — will reboot client" if self.needs_reboot else " — no reboot required")
            )

            # 4. Reboot if needed (auto, per user's Phase B preference)
            if self.needs_reboot:
                self._phase("reboot", "Rebooting client...")
                try:
                    _ssh_exec(ssh, "sudo reboot", timeout=5)
                except Exception:
                    # The reboot itself kills sshd, so we usually get a
                    # disconnect / timeout exception here. That's expected.
                    pass
                try:
                    ssh.close()
                except Exception:
                    pass
                ssh = None
                self.rebooted = True

                # 5. Wait for client to come back online (snapcast reconnect)
                self._phase("wait", "Waiting for client to come back online...")
                if not self._wait_for_return():
                    self._finish(
                        "failed",
                        f"Client did not reconnect within {REBOOT_WAIT_TIMEOUT_SECONDS}s",
                    )
                    return

            # 6. Record deploy
            self._phase("record", "Recording deploy in server_config.json...")
            ok = self._record_deploy_fn(
                self.client_id, self.server_sha, bool(self.needs_reboot), None
            )
            if not ok:
                # Don't fail the whole update — the install itself succeeded;
                # bookkeeping failure is annoying but not catastrophic.
                self._output("record_client_deploy returned False (see server log)")

            self.deployed_sha = self.server_sha
            self._finish("succeeded", None)
        except Exception as e:
            logger.exception("UpdateRunner crashed")
            self._finish("failed", str(e))
        finally:
            if ssh is not None:
                try:
                    ssh.close()
                except Exception:
                    pass

    def _stream_install(self, ssh) -> int:
        """Run install.sh on the target with the configured env vars.

        Stdin / stdout / stderr all go through one PTY so bash, curl, pip,
        apt, etc. line-buffer their output (otherwise they batch and the UI
        looks frozen). Each completed line is forwarded to subscribers via
        `_output()` as soon as it's read.
        """
        # Build the env-prefix for the remote bash. shlex.quote each value
        # to be safe against names with spaces (display_name "Bedroom 2").
        env_parts = []
        for k, v in self.env.items():
            env_parts.append(f"{k}={shlex.quote(str(v))}")
        env_prefix = " ".join(env_parts)

        # Run install.sh straight from the server via the same endpoint
        # first-install uses. install.sh itself respects FAUXNOS_SERVER_URL
        # to pull the rest of the client files back from us — that's how we
        # avoid GitHub being a hard dependency for clients.
        cmd = (
            f"{env_prefix} bash -c "
            f"'curl -sSL \"http://{self.server_host}:8080/api/install/client.sh\" | bash'"
        )
        self._output(f"$ {cmd}")

        transport = ssh.get_transport()
        if transport is None:
            self._output("(no SSH transport)")
            return 255

        chan = transport.open_session()
        chan.get_pty()
        chan.exec_command(cmd)

        buf = b""
        deadline = time.time() + INSTALL_TIMEOUT_SECONDS
        while True:
            if self._cancel.is_set():
                try:
                    chan.close()
                except Exception:
                    pass
                return 130  # cancelled
            if time.time() > deadline:
                self._output(f"[timeout: install exceeded {INSTALL_TIMEOUT_SECONDS}s]")
                try:
                    chan.close()
                except Exception:
                    pass
                return 124
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break

            recvd = False
            if chan.recv_ready():
                buf += chan.recv(4096)
                recvd = True
            if chan.recv_stderr_ready():
                # Merge stderr into the stdout line stream — install.sh
                # uses sudo + apt + pip which all write to stderr; we
                # care about the chronological order, not the channel.
                buf += chan.recv_stderr(4096)
                recvd = True

            if recvd:
                # Drain complete lines; keep any partial trailing line.
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").rstrip("\r")
                    # Strip ANSI color codes — install.sh uses them
                    # liberally for human readability, but they're noise
                    # in the SSE stream.
                    text = _strip_ansi(text)
                    if text:
                        self._output(text)
            else:
                time.sleep(0.05)

        # Flush any partial trailing bytes.
        if buf:
            text = _strip_ansi(buf.decode("utf-8", errors="replace").rstrip("\r\n"))
            if text:
                self._output(text)

        return chan.recv_exit_status()

    def _check_marker(self, ssh) -> bool:
        """SSH a `test -f /tmp/fauxnos-install-needs-reboot`. True if present."""
        try:
            rc, _out, _err = _ssh_exec(
                ssh, "test -f /tmp/fauxnos-install-needs-reboot", timeout=5
            )
            return rc == 0
        except Exception as e:
            self._output(f"marker check failed: {e}")
            # When in doubt, assume reboot needed — better to reboot
            # unnecessarily than miss a kernel-update reboot.
            return True

    def _wait_for_return(self) -> bool:
        """Poll snapcast until our client_id shows as connected."""
        deadline = time.time() + REBOOT_WAIT_TIMEOUT_SECONDS
        last_state = None
        while time.time() < deadline and not self._cancel.is_set():
            try:
                connected_map = self._snapcast_status_fn() or {}
            except Exception:
                connected_map = {}
            is_connected = bool(connected_map.get(self.client_id, False))
            if is_connected != last_state:
                self._output(
                    f"snapcast: {self.client_id} {'connected' if is_connected else 'disconnected'}"
                )
                last_state = is_connected
            if is_connected:
                return True
            time.sleep(REBOOT_WAIT_POLL_SECONDS)
        return False

    def _finish(self, status: str, error: Optional[str]):
        with self._lock:
            self.status = status
            self.error = error
            self.ended_at = time.time()
        self._emit("done", self.snapshot())


# ── Manager ───────────────────────────────────────────────────────────────────


class UpdateManager:
    """Singleton-ish manager. Holds one active update, plus history for the
    most recently-finished update per client (for status polling after the
    SSE stream disconnects).
    """

    def __init__(
        self,
        server_host: str = "fauxnos000.local",
        snapcast_status_fn: Optional[Callable[[], Dict[str, bool]]] = None,
        record_deploy_fn: Optional[Callable[[str, str, bool, Optional[str]], bool]] = None,
        ssh_key_path: Optional[Path] = None,
    ):
        self.server_host = server_host
        self.snapcast_status_fn = snapcast_status_fn
        self.record_deploy_fn = record_deploy_fn
        self.ssh_key_path = ssh_key_path
        self._active: Dict[str, UpdateRunner] = {}     # client_id → runner (running)
        self._last: Dict[str, UpdateRunner] = {}       # client_id → most recent finished
        self._lock = threading.RLock()

    def start(
        self,
        client_id: str,
        target_host: str,
        env: Dict[str, str],
        server_sha: str,
    ) -> UpdateRunner:
        with self._lock:
            existing = self._active.get(client_id)
            if existing is not None and existing.status == "running":
                raise UpdateAlreadyRunning(existing)
            runner = UpdateRunner(
                client_id=client_id,
                target_host=target_host,
                env=env,
                server_sha=server_sha,
                server_host=self.server_host,
                ssh_key_path=self.ssh_key_path,
                snapcast_status_fn=self.snapcast_status_fn,
                record_deploy_fn=self.record_deploy_fn,
            )
            self._active[client_id] = runner
            self._last[client_id] = runner

            # When the runner finishes, drop it from _active so the next
            # request can start a new one. Done via a tiny watcher thread
            # that subscribes to the runner and waits for `done`.
            self._spawn_completion_watcher(runner)
            runner.start()
            return runner

    def current(self, client_id: str) -> Optional[UpdateRunner]:
        with self._lock:
            r = self._active.get(client_id)
            if r is not None and r.status == "running":
                return r
            return None

    def current_or_last(self, client_id: str) -> Optional[UpdateRunner]:
        with self._lock:
            r = self._active.get(client_id)
            if r is not None and r.status == "running":
                return r
            return self._last.get(client_id)

    def cancel(self, client_id: str):
        r = self.current(client_id)
        if r is not None:
            r.cancel()

    def _spawn_completion_watcher(self, runner: UpdateRunner):
        """Drop the runner from _active when it finishes."""
        def watcher():
            sub = runner.subscribe()
            try:
                while True:
                    try:
                        ev = sub.get(timeout=30)
                    except queue.Empty:
                        continue
                    if ev["type"] == "done":
                        break
            finally:
                runner.unsubscribe(sub)
                with self._lock:
                    if self._active.get(runner.client_id) is runner:
                        del self._active[runner.client_id]
        threading.Thread(
            target=watcher,
            daemon=True,
            name=f"update-watcher-{runner.client_id}",
        ).start()


class UpdateAlreadyRunning(Exception):
    def __init__(self, runner: UpdateRunner):
        super().__init__(
            f"Update {runner.update_id} for {runner.client_id} is already running"
        )
        self.runner = runner


# ── Internals ─────────────────────────────────────────────────────────────────

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)
