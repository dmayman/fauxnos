#!/usr/bin/env python3
"""
Test the Noise settings: noise.env round-trips, partial updates merge,
out-of-range values are rejected, a change restarts the generator only
through try-restart (and not at all when nothing changed), the MQTT noise
command reaches NoiseSettings, and switching to Noise turns it back on.

Run: python3 test_noise_settings.py
"""

import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import modules.noise_settings as ns
from modules.mqtt_client import MQTTClient


def demo():
    runs = []
    ns.subprocess.run = lambda cmd, **kw: runs.append(cmd)  # no systemctl here

    with tempfile.TemporaryDirectory() as d:
        s = ns.NoiseSettings(env_path=Path(d) / "noise.env")
        assert s.get() == {"on": True, "color": "brown", "low_cut": 0, "high_cut": 0}

        assert s.set({"color": "pink", "low_cut": 80})
        assert s.set({"high_cut": 6000})  # partial: keeps colour and low cut
        assert s.get() == {"on": True, "color": "pink", "low_cut": 80, "high_cut": 6000}, s.get()
        assert "FAUXNOS_NOISE_LOW_CUT=80" in (Path(d) / "noise.env").read_text()
        assert runs[-1] == ["systemctl", "--user", "try-restart", "fauxnos-noise.service"]

        for bad in ({"color": "blue"}, {"low_cut": 5}, {"high_cut": 50000},
                    {"low_cut": 7000}, {"low_cut": "80"}, {"high_cut": True}, {"on": "no"}):
            assert not s.set(bad), bad
        assert s.get() == {"on": True, "color": "pink", "low_cut": 80, "high_cut": 6000}
        assert len(runs) == 2, "a rejected change must not restart the generator"
        assert s.set({"color": "pink"}) and len(runs) == 2, "no change, no restart gap"

        assert s.set({"on": False})
        assert "FAUXNOS_NOISE_ON=0" in (Path(d) / "noise.env").read_text()
        assert s.get()["on"] is False and len(runs) == 3
        assert s.set({"low_cut": 0, "high_cut": 0})  # 0 turns a cut off
        print("ok: noise.env round-trips, merges, and rejects out-of-range settings")

    # MQTT: set/clients/<id>/noise reaches the callback and republishes state.
    c = MQTTClient.__new__(MQTTClient)
    c.connected = False
    c.sources_list = ["spotify", "noise"]
    c._command_lock = threading.Lock()
    got, published = [], []
    c.noise_callback = lambda data: got.append(data) or True
    c.publish_noise_state = lambda: published.append(True)
    c.mode_callback = lambda sid, fade_ms=0: True
    c.source_volume_getter = lambda sid: None
    c.current_mode = "spotify"
    c._handle_command("set", "mode", "noise")
    assert got == [{"on": True}], "switching to Noise must turn it on"
    got.clear(); published.clear()
    c._handle_command("set", "noise", json.dumps({"color": "white"}))
    c._handle_command("set", "noise", "{not json")
    assert got == [{"color": "white"}] and published == [True], (got, published)
    c.sources_list = ["spotify"]
    c._handle_command("set", "noise", json.dumps({"color": "pink"}))
    assert got == [{"color": "white"}], "a device without noise must ignore it"
    print("ok: the MQTT noise command reaches NoiseSettings and republishes state")


if __name__ == "__main__":
    demo()
