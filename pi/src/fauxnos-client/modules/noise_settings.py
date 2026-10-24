#!/usr/bin/env python3
"""
Noise Settings

Power, colour and low/high cuts for the Noise source. They live in
~/.config/fauxnos/noise.env, the EnvironmentFile of fauxnos-noise.service,
which scripts/noise-generator.sh reads on start:

    FAUXNOS_NOISE_ON=1|0          0 = silent, but still the source
    FAUXNOS_NOISE_COLOR=white|pink|brown
    FAUXNOS_NOISE_LOW_CUT=<Hz>    high-pass; 0 = off
    FAUXNOS_NOISE_HIGH_CUT=<Hz>   low-pass; 0 = off

A change restarts the generator only if it's running (noise is playing),
so it's heard straight away; otherwise it applies the next time Noise
starts.
"""

import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional

COLORS = ("white", "pink", "brown")
DEFAULTS = {"on": True, "color": "brown", "low_cut": 0, "high_cut": 0}
LOW_CUT_RANGE = (20, 2000)
HIGH_CUT_RANGE = (200, 20000)

_ENV_KEYS = {
    "on": "FAUXNOS_NOISE_ON",
    "color": "FAUXNOS_NOISE_COLOR",
    "low_cut": "FAUXNOS_NOISE_LOW_CUT",
    "high_cut": "FAUXNOS_NOISE_HIGH_CUT",
}


class NoiseSettings:
    def __init__(self, env_path: Optional[Path] = None,
                 service: str = "fauxnos-noise.service"):
        self.logger = logging.getLogger(__name__)
        self.env_path = env_path or Path.home() / ".config" / "fauxnos" / "noise.env"
        self.service = service

    def get(self) -> Dict:
        """Current settings, with defaults for anything unset or unreadable."""
        state = dict(DEFAULTS)
        try:
            lines = self.env_path.read_text().splitlines()
        except FileNotFoundError:
            return state
        by_env = {v: k for k, v in _ENV_KEYS.items()}
        for line in lines:
            key, _, value = line.partition("=")
            field = by_env.get(key.strip())
            if not field:
                continue
            value = value.strip().strip('"')
            if field == "on":
                state["on"] = value != "0"
            elif field == "color":
                if value in COLORS:
                    state["color"] = value
            else:
                try:
                    state[field] = int(value)
                except ValueError:
                    pass
        return state

    @staticmethod
    def validate(state: Dict) -> Optional[str]:
        """Return an error message, or None if `state` is valid."""
        if not isinstance(state["on"], bool):
            return "on must be true or false"
        if state["color"] not in COLORS:
            return f"color must be one of {COLORS}"
        for field, (lo, hi) in (("low_cut", LOW_CUT_RANGE), ("high_cut", HIGH_CUT_RANGE)):
            value = state[field]
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{field} must be an integer"
            if value != 0 and not lo <= value <= hi:
                return f"{field} must be 0 (off) or {lo}-{hi} Hz"
        if state["low_cut"] and state["high_cut"] and state["low_cut"] >= state["high_cut"]:
            return "low_cut must be below high_cut"
        return None

    def set(self, changes: Dict) -> bool:
        """Merge `changes` into the stored settings, save, apply. False if invalid."""
        current = self.get()
        state = {**current, **{k: v for k, v in changes.items() if k in DEFAULTS}}
        error = self.validate(state)
        if error:
            self.logger.error(f"Noise settings rejected ({error}): {changes}")
            return False
        if state == current:
            return True  # nothing changed: skip the restart and its gap

        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        self.env_path.write_text(
            "".join(f"{_ENV_KEYS[k]}={int(state[k]) if k == 'on' else state[k]}\n"
                    for k in ("on", "color", "low_cut", "high_cut"))
        )
        self.logger.info(f"Noise settings: {state}")

        # try-restart: restart only if it's running. A ~1 s gap, so the UI
        # sends a change when a slider is released, not on every step.
        subprocess.run(["systemctl", "--user", "try-restart", self.service],
                       capture_output=True, timeout=10)
        return True
