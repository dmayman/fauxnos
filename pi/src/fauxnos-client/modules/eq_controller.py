#!/usr/bin/env python3
"""
Equalizer Controller

Pushes per-band gain updates to the local CamillaDSP daemon over its
WebSocket control plane (127.0.0.1:1234 by default, set in
~/.config/systemd/user/camilladsp.service).

CamillaDSP itself owns the persistent YAML at
~/.config/camilladsp/config.yml — it rewrites the file on every
successful SetConfigJson, so we don't need to manage filter persistence
ourselves. But CamillaDSP has no notion of an "enabled" toggle: when
the user disables the EQ in the UI we push a config with all gains at
0.0 dB (effectively flat passthrough — preserves the always-on
processing model so toggling is glitch-free). The user's desired
non-zero gains are stashed in a small sidecar at
~/.config/fauxnos/eq_state.json so re-enable restores them.

Design notes:
  - 10 ISO graphic-EQ frequencies, fixed: 31..16000 Hz, Q=1.4.
  - Round-trip latency to camilladsp: ~2 ms in probe testing — well
    inside a 60fps slider drag budget.
  - This module has no MQTT awareness; phase 6 wires it up from
    mqtt_client.py via SourceManager. Keeping the boundary clean here
    means the controller can also be exercised from unit tests / a
    REPL without spinning up an MQTT broker.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import websocket  # provided by the `websocket-client` pip dep (see install.sh)


# The 10 ISO graphic-EQ bands we expose to the UI. Order matters: it's
# the order sliders appear in the device panel, low → high.
BANDS_HZ: List[int] = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


class EqController:
    """Pushes EQ state to a local CamillaDSP daemon over WebSocket."""

    DEFAULT_WS_URL = "ws://127.0.0.1:1234"
    DEFAULT_STATE_FILE = Path.home() / ".config" / "fauxnos" / "eq_state.json"
    WS_TIMEOUT_SEC = 3.0

    def __init__(
        self,
        ws_url: str = DEFAULT_WS_URL,
        state_file: Optional[Path] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.ws_url = ws_url
        self.state_file = Path(state_file) if state_file else self.DEFAULT_STATE_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self) -> Dict:
        """
        Return the controller's persisted view of EQ state.

        Shape: {"enabled": bool, "bands": {freq_hz_str: gain_db, ...}}
        Missing/corrupt state file → defaults to enabled=False, all 0.0.
        Keys in "bands" are stringified frequencies to keep the JSON
        round-trip stable (the MQTT/REST surface in phase 6+ will use
        string keys too).
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

        # Defensive normalization: missing keys, wrong types, extra
        # bands — coerce to schema and drop anything unexpected. We'd
        # rather the UI show "flat" than blow up on a stale state file.
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
        """
        Update EQ state: persist the user's desired settings AND push
        live gains to camilladsp.

        Args:
            enabled: When False, camilladsp gets all-zero gains (flat
                     passthrough). The user's saved gains are kept in
                     the state file for the next enable.
            bands:   Partial or full dict of {freq_hz_str: gain_db}.
                     Missing bands are left at their previous saved
                     value. Pass None to leave all bands unchanged
                     (useful for enable/disable toggles).

        Returns:
            True if both persist + push succeeded. False on push error
            (state file is still updated so future reconnects converge).
        """
        current = self.get_state()
        new_bands = dict(current["bands"])
        if bands:
            for hz_str, gain in bands.items():
                if hz_str in new_bands and isinstance(gain, (int, float)):
                    new_bands[hz_str] = float(gain)

        new_state = {"enabled": bool(enabled), "bands": new_bands}
        self._write_state(new_state)

        # When disabled, the wire-level config is flat — but new_state
        # in eq_state.json still holds the user's saved gains.
        wire_gains = (
            [new_bands[str(hz)] for hz in BANDS_HZ]
            if enabled
            else [0.0] * len(BANDS_HZ)
        )
        return self._push_gains(wire_gains)

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

    def _push_gains(self, gains: List[float]) -> bool:
        """
        Read the current camilladsp config, swap in our gains, push it
        back via SetConfigJson. We don't rebuild the whole config from
        scratch — that would clobber any field we don't know about
        (resampler tuning, samplerate, etc.).
        """
        if len(gains) != len(BANDS_HZ):
            self.logger.error(
                f"_push_gains: expected {len(BANDS_HZ)} gains, got {len(gains)}"
            )
            return False

        try:
            ws = websocket.create_connection(self.ws_url, timeout=self.WS_TIMEOUT_SEC)
        except Exception as e:
            # camilladsp may be down (PA restart in flight, etc.). State
            # file already updated; next time the daemon comes back the
            # caller can re-push by reading get_state() and calling
            # set_state() again, or we can add a background reconnect
            # loop in phase 5.5 if real-world flakiness shows up.
            self.logger.warning(f"camilladsp WebSocket unreachable: {e}")
            return False

        try:
            ws.send(json.dumps("GetConfigJson"))
            reply = json.loads(ws.recv())
            cfg_str = reply.get("GetConfigJson", {}).get("value")
            if not cfg_str:
                self.logger.error(f"Unexpected GetConfigJson reply: {reply}")
                return False
            cfg = json.loads(cfg_str)

            filters = cfg.get("filters") or {}
            for hz, gain in zip(BANDS_HZ, gains):
                name = f"band_{hz}"
                if name not in filters:
                    self.logger.warning(
                        f"camilladsp config is missing filter '{name}'; "
                        f"skipping — config.yml may be out of sync with "
                        f"the bundled template (phase 2)"
                    )
                    continue
                filters[name]["parameters"]["gain"] = float(gain)

            ws.send(json.dumps({"SetConfigJson": json.dumps(cfg)}))
            push_reply = json.loads(ws.recv())
            result = push_reply.get("SetConfigJson", {}).get("result")
            if result != "Ok":
                self.logger.error(f"SetConfigJson rejected: {push_reply}")
                return False
            self.logger.debug(f"EQ pushed: {dict(zip(BANDS_HZ, gains))}")
            return True
        except Exception as e:
            self.logger.error(f"_push_gains failed: {e}")
            return False
        finally:
            try:
                ws.close()
            except Exception:
                pass
