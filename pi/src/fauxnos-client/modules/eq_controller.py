#!/usr/bin/env python3
"""
Equalizer Controller (CAPS Eq10X2 / module-ladspa-sink)

Replaces the previous CamillaDSP control plane. The end-of-chain
10-band graphic EQ now runs inline in PulseAudio's audio thread via
`module-ladspa-sink` loading CAPS `Eq10X2`. There is no separate
process, no WebSocket, no IPC.

Apply path:
  1. eq_state.json is the source-of-truth sidecar:
     {"enabled": bool, "bands": {"31": dB, ..., "16000": dB}}
  2. ~/.config/pulse/default.pa contains the live `control=` line on
     the `load-module module-ladspa-sink` row. We rewrite this file on
     every apply so PA picks up the new gains on its next idle-spawn.
     The eq_state.json `enabled` flag controls whether `control=` is
     rendered with the user's saved gains (enabled=true) or with all
     zeros (enabled=false, passthrough).
  3. To make the change audible immediately (rather than at next PA
     restart), we run a pactl unload/load dance — drop the 4 dependent
     loopbacks, drop the eq_sink module, reload eq_sink with new gains,
     reload the 4 loopbacks. ~1 second of audio interruption per apply.
     The web UI's commit-style "Apply" button bundles enabled + all 10
     bands so each user-intent change incurs the reload exactly once.

Why this is fine here (and wasn't before):
  module-ladspa-sink was originally disqualified because there's no
  DBUS surface for live gain updates. The Apply-button UI pattern
  trades that requirement away — a ~1s reload at commit time is
  acceptable; what isn't acceptable is unbounded latency drift,
  which the CamillaDSP path had.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional


# The 10 ISO graphic-EQ bands we expose to the UI. Order matters: it's
# the order sliders appear in the device panel AND the order CAPS
# Eq10X2 expects its `control=` values. CAPS Eq10X2 bands are fixed at
# these ISO frequencies; we don't choose them.
BANDS_HZ: List[int] = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

# Loopbacks that feed eq_sink. Order matches default.pa exactly.
# (source, media_role) — the role is what pulse_controller's per-source
# calibration code uses to find each loopback after reload.
_EQ_LOOPBACKS: List[tuple] = [
    ("systemsink.monitor", "fauxnos-systemsink-out"),
    ("analogsink.monitor", "fauxnos-analogsink-out"),
    ("snapsink.monitor", "fauxnos-snapsink-out"),
    ("airplaysink.monitor", "fauxnos-airplaysink-out"),
]

_HARDWARE_SINK = "alsa_output.platform-soc_sound.stereo-fallback"
_EQ_SINK_NAME = "eq_sink"
_LOOPBACK_LATENCY_MSEC = 80
_EQ_CONTROL_PLACEHOLDER = "__EQ_CONTROL__"


class EqController:
    """Persist EQ state and apply it to PulseAudio via module-ladspa-sink.

    The controller is the single writer of both ~/.config/fauxnos/
    eq_state.json (the sidecar source of truth) and the `control=`
    parameter inside ~/.config/pulse/default.pa.
    """

    DEFAULT_STATE_FILE = Path.home() / ".config" / "fauxnos" / "eq_state.json"
    DEFAULT_PA_FILE = Path.home() / ".config" / "pulse" / "default.pa"

    def __init__(
        self,
        state_file: Optional[Path] = None,
        default_pa_file: Optional[Path] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.state_file = Path(state_file) if state_file else self.DEFAULT_STATE_FILE
        self.default_pa_file = (
            Path(default_pa_file) if default_pa_file else self.DEFAULT_PA_FILE
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # On startup, make sure default.pa's control= line matches
        # eq_state.json. install.sh already does this at provision time,
        # but a stale default.pa (e.g. a hand-edit, or a migration from
        # an older template that had the placeholder) would otherwise
        # produce silent drift between what the UI shows and what the
        # ear hears. Cheap idempotent rewrite — no PA reload unless the
        # file actually changed.
        self._sync_on_startup()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self) -> Dict:
        """Persisted view: {"enabled": bool, "bands": {hz_str: dB}}.

        Missing/corrupt state file → defaults to enabled=False + all-zero
        bands. Keys in "bands" are stringified frequencies for stable
        JSON round-trips through MQTT and the REST surface.
        """
        if not self.state_file.exists():
            return self._default_state()
        try:
            with self.state_file.open() as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            self.logger.warning(
                f"eq_state.json unreadable ({e}); falling back to defaults"
            )
            return self._default_state()

        # Defensive normalization — drop unexpected keys, coerce types.
        bands = {str(hz): 0.0 for hz in BANDS_HZ}
        for hz_key, gain in (raw.get("bands") or {}).items():
            if hz_key in bands and isinstance(gain, (int, float)):
                bands[hz_key] = float(gain)
        return {
            "enabled": bool(raw.get("enabled", False)),
            "bands": bands,
        }

    def set_state(
        self,
        enabled: bool,
        bands: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Atomic commit: update saved state + rewrite default.pa + live reload.

        Args:
            enabled: When False, the ladspa-sink is loaded with all-zero
                     gains (passthrough). eq_state.json still holds the
                     user's saved gains so re-enable restores them.
            bands:   Partial dict {hz_str: dB} — missing bands keep
                     their previous saved values. Pass None to leave
                     bands unchanged (used for enable-only toggles).

        Returns:
            True on success. False if default.pa rewrite or live reload
            failed; state file is still updated so the next reboot
            converges to the requested state.
        """
        current = self.get_state()
        new_bands = dict(current["bands"])
        if bands:
            for hz_str, gain in bands.items():
                if hz_str in new_bands and isinstance(gain, (int, float)):
                    new_bands[hz_str] = float(gain)

        new_state = {"enabled": bool(enabled), "bands": new_bands}
        self._write_state(new_state)

        wire_gains = (
            [new_bands[str(hz)] for hz in BANDS_HZ]
            if enabled
            else [0.0] * len(BANDS_HZ)
        )

        rewrite_ok = self._rewrite_default_pa(wire_gains)
        reload_ok = self._live_reload(wire_gains)
        return rewrite_ok and reload_ok

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _default_state() -> Dict:
        return {
            "enabled": False,
            "bands": {str(hz): 0.0 for hz in BANDS_HZ},
        }

    def _write_state(self, state: Dict) -> None:
        """Atomically replace the state file (tmp + rename)."""
        tmp = self.state_file.with_suffix(".json.tmp")
        try:
            with tmp.open("w") as f:
                json.dump(state, f, indent=2)
                f.write("\n")
            os.replace(tmp, self.state_file)
        except OSError as e:
            self.logger.error(f"Failed to persist eq_state.json: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _sync_on_startup(self) -> None:
        """Make sure default.pa's control= line matches eq_state.json.

        Best-effort: if the file is missing or we can't write it, log
        and move on — install.sh's setup_default_pa step is the
        authoritative renderer on provision.
        """
        if not self.default_pa_file.exists():
            self.logger.info(
                f"default.pa not found at {self.default_pa_file}; "
                f"eq sync at startup skipped"
            )
            return
        state = self.get_state()
        wire_gains = (
            [state["bands"][str(hz)] for hz in BANDS_HZ]
            if state["enabled"]
            else [0.0] * len(BANDS_HZ)
        )
        if self._rewrite_default_pa(wire_gains, only_if_changed=True):
            self.logger.info(
                f"eq sync at startup: default.pa control= aligned with "
                f"eq_state.json ({dict(zip(BANDS_HZ, wire_gains))})"
            )

    def _rewrite_default_pa(
        self,
        wire_gains: List[float],
        only_if_changed: bool = False,
    ) -> bool:
        """Substitute the `control=...` value on the module-ladspa-sink line.

        Tolerates both the install-time placeholder (__EQ_CONTROL__) and
        any previous control=GAINS rendering. The line is identified by
        the `module-ladspa-sink` substring + `control=`, so the rewrite
        is robust to comment/formatting drift in the template.
        """
        try:
            original = self.default_pa_file.read_text()
        except OSError as e:
            self.logger.error(f"default.pa unreadable: {e}")
            return False

        gains_str = ",".join(_format_gain(g) for g in wire_gains)
        new_text, changed = _replace_ladspa_control(original, gains_str)
        if not changed and only_if_changed:
            return True
        if new_text == original:
            return True

        tmp = self.default_pa_file.with_suffix(".pa.tmp")
        try:
            tmp.write_text(new_text)
            os.replace(tmp, self.default_pa_file)
            self.logger.debug(
                f"default.pa rewritten with control={gains_str}"
            )
            return True
        except OSError as e:
            self.logger.error(f"default.pa rewrite failed: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def _live_reload(self, wire_gains: List[float]) -> bool:
        """Drop and re-load eq_sink + the 4 dependent loopbacks via pactl.

        Order matters: loopbacks first (they hold a ref on eq_sink),
        then eq_sink itself, then reload eq_sink with new control=,
        then reload loopbacks. Mirrors `~/scripts/fauxnos-eq-set.sh` on
        fauxnos000 which is the audibly-verified live-edit dance.

        Returns False on any subprocess failure. eq_state.json + default.pa
        are already updated by the time we get here, so a failure means
        "audio is currently still on the old gains; will converge on next
        PA restart".
        """
        if not _have_pactl():
            self.logger.info("pactl not available; skipping live reload")
            return True

        gains_str = ",".join(_format_gain(g) for g in wire_gains)

        try:
            # 1. Unload the 4 loopbacks feeding eq_sink.
            for src, _role in _EQ_LOOPBACKS:
                mod_id = _find_loopback_module_id(src)
                if mod_id is not None:
                    _pactl(["unload-module", str(mod_id)])

            # 2. Unload existing eq_sink.
            eq_mod = _find_ladspa_sink_module_id()
            if eq_mod is not None:
                _pactl(["unload-module", str(eq_mod)])

            # 3. Reload eq_sink with new gains.
            _pactl([
                "load-module", "module-ladspa-sink",
                f"sink_name={_EQ_SINK_NAME}",
                f"master={_HARDWARE_SINK}",
                "plugin=caps",
                "label=Eq10X2",
                f"control={gains_str}",
            ])

            # 4. Reload the 4 loopbacks.
            for src, role in _EQ_LOOPBACKS:
                _pactl([
                    "load-module", "module-loopback",
                    f"source={src}",
                    f"sink={_EQ_SINK_NAME}",
                    f"latency_msec={_LOOPBACK_LATENCY_MSEC}",
                    f"sink_input_properties=media.role={role}",
                ])

            self.logger.info(f"EQ live reload OK: control={gains_str}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(
                f"EQ live reload failed: {e.cmd} → rc={e.returncode} "
                f"stderr={e.stderr!r}"
            )
            return False
        except Exception as e:
            self.logger.error(f"EQ live reload unexpected error: {e}")
            return False


# ------------------------------------------------------------------------
# Module-level helpers (kept outside the class so they're easy to unit-test)
# ------------------------------------------------------------------------


def _format_gain(g: float) -> str:
    """Render a dB gain as a short decimal string ('0' for zero, '4.5' etc).

    Avoids '4.0' → '4' rounding noise that would shift the diff
    needlessly when round-tripping through default.pa. We keep one
    decimal of precision (matches the 0.5 dB UI slider step).
    """
    rounded = round(float(g), 1)
    if rounded == 0:
        return "0"
    if rounded == int(rounded):
        return f"{int(rounded)}.0"
    return f"{rounded:.1f}"


def _replace_ladspa_control(text: str, new_control: str) -> tuple:
    """Find the module-ladspa-sink line and swap its `control=` value.

    Returns (new_text, changed_flag). If no module-ladspa-sink line is
    present, returns the text unchanged (changed=False) — install.sh
    is the authority on rendering the template; missing line means we
    haven't been provisioned yet.
    """
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if "module-ladspa-sink" not in line:
            continue
        # Replace either __EQ_CONTROL__ or an existing comma list.
        new_line, n = _swap_control_token(line, new_control)
        if n > 0 and new_line != line:
            lines[i] = new_line
            changed = True
        break
    return "".join(lines), changed


def _swap_control_token(line: str, new_control: str) -> tuple:
    """Swap the `control=...` token on a single load-module line.

    Tokens on a pactl/PA line are whitespace-separated. We don't try
    to be clever with shell-quoting (PA doesn't either for module
    arguments) — just find the token starting with `control=` and
    replace its tail.
    """
    parts = line.rstrip("\n").split(" ")
    trailing_newline = "\n" if line.endswith("\n") else ""
    n = 0
    for i, tok in enumerate(parts):
        if tok.startswith("control="):
            parts[i] = f"control={new_control}"
            n += 1
            break
    return (" ".join(parts) + trailing_newline, n)


def _have_pactl() -> bool:
    try:
        subprocess.run(
            ["pactl", "--version"],
            check=True, capture_output=True, timeout=2,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _pactl(args: List[str]) -> str:
    """Run `pactl <args>` and return stdout. Raises on non-zero exit."""
    res = subprocess.run(
        ["pactl"] + args,
        check=True, capture_output=True, text=True, timeout=5,
    )
    return res.stdout


def _find_loopback_module_id(source: str) -> Optional[int]:
    """Return the module ID of the module-loopback with `source=<source>`."""
    try:
        out = _pactl(["list", "short", "modules"])
    except subprocess.SubprocessError:
        return None
    needle = f"source={source} "
    for row in out.splitlines():
        # rows: "<id>\tmodule-loopback\t<args>"
        cols = row.split("\t")
        if len(cols) < 3:
            continue
        if cols[1] != "module-loopback":
            continue
        # args field has tokens separated by spaces; the trailing space
        # in `needle` avoids matching `source=spotifysink` when we want
        # `source=systemsink`.
        if needle in (cols[2] + " "):
            try:
                return int(cols[0])
            except ValueError:
                return None
    return None


def _find_ladspa_sink_module_id() -> Optional[int]:
    try:
        out = _pactl(["list", "short", "modules"])
    except subprocess.SubprocessError:
        return None
    for row in out.splitlines():
        cols = row.split("\t")
        if len(cols) < 2:
            continue
        if cols[1] == "module-ladspa-sink":
            try:
                return int(cols[0])
            except ValueError:
                return None
    return None
