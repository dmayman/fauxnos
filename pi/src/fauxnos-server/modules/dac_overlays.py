"""DAC dt-overlay registry + remote-apply helper.

Single source of truth for which `dtoverlay=...` strings the install path
will write into a client's /boot/firmware/config.txt. Centralised here so
the allowlist is shared between:

  - api_server.py validation on PUT /api/clients/<id>/dac_overlay
  - api_server.py firstrun.sh env-var injection (FAUXNOS_DAC_OVERLAY)
  - install.sh's case-statement (validated independently in bash)
  - the React Devices-tab dropdown (kept in sync manually with DAC_OVERLAYS)

Adding a new overlay: append it to DAC_OVERLAYS, add it to install.sh's
case-statement, and add it to the React dropdown options list.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional, Tuple


# (overlay_id, human label). The order is the order shown in the UI dropdown.
DAC_OVERLAYS: list[tuple[str, str]] = [
    ("allo-boss-dac-pcm512x-audio", "Allo Boss / INNO-MAKER PCM5122"),
    ("hifiberry-dac",               "HiFiBerry DAC+ Light / MiniAmp / generic PCM5102"),
    ("hifiberry-dacplus",           "HiFiBerry DAC+ Standard / Pro"),
    ("hifiberry-dacplusadc",        "HiFiBerry DAC+ ADC (line-in)"),
    ("iqaudio-dacplus",             "IQaudIO Pi-DAC+"),
]

ALLOWED_OVERLAYS: set[str] = {oid for oid, _ in DAC_OVERLAYS}

# The server hardware path is locked at hifiberry-dacplusadc because the
# analog-input source detection in the server install keys off this exact
# string. Don't propose changing the server's overlay through this UI.
SERVER_OVERLAY = "hifiberry-dacplusadc"

# Default for a brand-new client when nothing else is specified. Picked
# 2026-05-09 after swapping fauxnos001's chip from HiFiBerry DAC+ to an
# INNO-MAKER PCM5122 hat: allo-boss-dac-pcm512x-audio drives both the
# INNO-MAKER and any genuine Allo Boss with the full PCM512x mixer
# enabled. Users with HiFiBerry hats can switch via the Devices tab
# after install.
DEFAULT_OVERLAY = "allo-boss-dac-pcm512x-audio"


def is_allowed(overlay: str) -> bool:
    return overlay in ALLOWED_OVERLAYS


def remote_apply(
    target_host: str,
    overlay: str,
    *,
    ssh_user: str = "user",
    ssh_key_path: Optional[Path] = None,
    timeout: int = 20,
    reboot_delay_seconds: int = 2,
) -> Tuple[bool, str]:
    """SSH into a client and rewrite /boot/firmware/config.txt to use
    `overlay`, then schedule a reboot via systemd-run.

    Returns (ok, message). On ok=True the device has been instructed to
    reboot — the SSH session itself returns before the reboot fires (the
    systemd-run delay leaves time for the response to drain back).

    The strip-then-append pattern matches what install.sh does, so a
    previous overlay (e.g. hifiberry-dac) gets cleaned out of config.txt
    instead of accumulating across re-applies.
    """
    if not is_allowed(overlay):
        return False, f"overlay '{overlay}' is not in the allowlist"

    try:
        import paramiko
    except ImportError as e:
        return False, f"paramiko not installed: {e}"

    if ssh_key_path is None:
        # Lazy import to keep this module import-cheap. install_runner
        # already owns the canonical key path constant.
        from .install_runner import DEFAULT_KEY_PATH
        ssh_key_path = DEFAULT_KEY_PATH
    if not ssh_key_path.exists():
        return False, f"server install key missing at {ssh_key_path}"

    # Re-flashes/renames produce fresh host keys. Same trick install_runner
    # uses — strip stale entries before connecting and let AutoAddPolicy
    # repopulate.
    _clear_stale_host_keys(target_host)

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
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        return False, f"SSH connect to {target_host} failed: {e}"

    # config.txt may live in /boot/firmware (newer Pi OS) or /boot (older).
    # We strip every overlay we manage so re-applying with a different
    # value doesn't leave stragglers behind. systemd-run schedules the
    # reboot a couple seconds out so this exec_command can return cleanly.
    cmd = f"""
set -e
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
[ -f "$CFG" ] || {{ echo 'no config.txt found' >&2; exit 1; }}
sudo cp "$CFG" "$CFG.bak.$(date +%s)"
sudo sed -i '/^dtoverlay=hifiberry/d; /^dtoverlay=allo-/d; /^dtoverlay=iqaudio-/d' "$CFG"
echo 'dtoverlay={overlay}' | sudo tee -a "$CFG" > /dev/null
echo "applied {overlay} to $CFG"
sudo systemd-run --on-active={reboot_delay_seconds} systemctl reboot >/dev/null 2>&1
echo "reboot scheduled in {reboot_delay_seconds}s"
"""
    try:
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            return False, f"remote command failed (rc={rc}): {err or out}"
        return True, out or "applied"
    except Exception as e:
        return False, f"remote command error: {e}"
    finally:
        try:
            client.close()
        except Exception:
            pass


def _clear_stale_host_keys(host: str) -> None:
    """ssh-keygen -R for the host (and its current IP). Best-effort."""
    import shutil
    import subprocess

    if not shutil.which("ssh-keygen"):
        return
    targets = [host]
    try:
        ip = socket.gethostbyname(host)
        if ip and ip != host:
            targets.append(ip)
    except Exception:
        pass
    for t in targets:
        try:
            subprocess.run(
                ["ssh-keygen", "-R", t],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            pass
