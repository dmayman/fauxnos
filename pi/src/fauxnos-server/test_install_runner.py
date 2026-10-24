#!/usr/bin/env python3
"""
Test that the Add Device install runner fails fast or moves on instead of
hanging: a Pi whose sudo wants a password fails at connect with a recovery
marker, a reboot countdown with no trailing newline still reaches the reboot
step, and a channel that dies mid-install ends the stream.

Run: python3 test_install_runner.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.install_runner import InstallRunner


class FakeChannel:
    """Feeds `chunks` to recv(); afterwards the transport reports dead."""

    def __init__(self, chunks, exit_status=None):
        self.chunks = [c.encode() for c in chunks]
        self.closed = False
        self.status_event = threading.Event()
        self.exit_status = exit_status
        if exit_status is not None:
            self.status_event.set()

    def get_pty(self): pass
    def exec_command(self, cmd): pass
    def close(self): self.closed = True
    def recv_ready(self): return bool(self.chunks)
    def recv(self, n): return self.chunks.pop(0)
    def recv_stderr_ready(self): return False
    def exit_status_ready(self): return self.status_event.is_set()
    def recv_exit_status(self): return self.exit_status


class FakeTransport:
    def __init__(self, chan): self.chan = chan
    def set_keepalive(self, s): self.keepalive = s
    def open_session(self): return self.chan
    # Wi-Fi went away without a TCP close: keepalives fail after the last byte.
    def is_active(self): return bool(self.chan.chunks)


class FakeStdout:
    def __init__(self, chan): self.channel = chan


class FakeSSH:
    def __init__(self, chan=None, sudo_rc=0):
        self.chan = chan
        self.sudo_rc = sudo_rc
        self.commands = []

    def get_transport(self): return FakeTransport(self.chan)
    def close(self): pass

    def exec_command(self, cmd, timeout=None):
        self.commands.append(cmd)
        return None, FakeStdout(FakeChannel([], exit_status=self.sudo_rc)), None


def _runner():
    return InstallRunner("fauxnos-client.local", "Office")


def test_sudo_password_fails_fast():
    r = _runner()
    ssh = FakeSSH(sudo_rc=1)
    r._discover = lambda: True
    r._ssh_connect = lambda: ssh
    r._stream_install = lambda ssh: (_ for _ in ()).throw(AssertionError("install must not start"))
    r.status = "running"
    r._run()
    connect = r._step_by_id("connect")
    assert r.status == "failed", r.status
    assert connect.status == "failed"
    assert connect.fallback_kind == "sudo_password_required"
    assert "010_user-nopasswd" in connect.note
    assert ssh.commands == ["sudo -n true"]


def test_reboot_countdown_without_newline():
    r = _runner()
    chan = FakeChannel([
        "✓ Services enabled\r\n",
        "\rRebooting in 30 seconds... ",
        "\rRebooting in 29 seconds... ",
    ])
    t0 = time.time()
    rc, reboot_seen = r._stream_install(FakeSSH(chan))
    assert reboot_seen, "countdown line without a newline must start the reboot step"
    assert rc == 0
    assert r._step_by_id("reboot").status == "active"
    assert time.time() - t0 < 5


def test_dead_channel_mid_install_ends_stream():
    r = _runner()
    chan = FakeChannel(["=== Installing System Dependencies ===\r\n", "Updating package lists"])
    t0 = time.time()
    rc, reboot_seen = r._stream_install(FakeSSH(chan))
    assert (rc, reboot_seen) == (255, False)
    assert "dropped" in r._stream_error
    assert time.time() - t0 < 5


if __name__ == "__main__":
    test_sudo_password_fails_fast()
    test_reboot_countdown_without_newline()
    test_dead_channel_mid_install_ends_stream()
    print("ok")
