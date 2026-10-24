#!/usr/bin/env python3
"""
Test the MQTT surface for local sources: fade-aware mode payloads and
the library/play + library/stop commands.

Run: python3 test_mqtt_local_sources.py
"""

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.mqtt_client import MQTTClient, MAX_FADE_MS


def make(sources=("spotify", "noise", "library")):
    # __new__ skips __init__ so no broker or config file is needed.
    c = MQTTClient.__new__(MQTTClient)
    c.connected = False
    c.sources_list = list(sources)
    c.current_mode = "idle"
    c.current_volume = 0
    c._command_lock = threading.Lock()
    c.calls = []
    c.mode_callback = lambda sid, fade_ms=0: c.calls.append(("mode", sid, fade_ms)) or True
    c.source_volume_getter = lambda sid: {"noise": 30, "library": 40}.get(sid, 50)
    c.library_play_callback = lambda items, loop, fade: c.calls.append(("play", items, loop, fade)) or True
    c.library_stop_callback = lambda fade_ms: c.calls.append(("stop", fade_ms)) or True
    c.noise_callback = None
    c.library_control_callback = lambda action: c.calls.append(("control", action)) or True
    c.library_seek_callback = lambda ms: c.calls.append(("seek", ms)) or True
    return c


def test_parse_mode_payload():
    p = MQTTClient._parse_mode_payload
    assert p("spotify") == ("spotify", 0)
    assert p('{"source": "noise", "fade_ms": 8000}') == ("noise", 8000)
    assert p('{"source": "noise"}') == ("noise", 0)
    assert p('{"source": "noise", "fade_ms": -5}') == ("noise", 0)
    assert p('{"source": "noise", "fade_ms": "x"}') == ("noise", 0)
    assert p('{"source": "noise", "fade_ms": 99999999}') == ("noise", MAX_FADE_MS)
    assert p("{not json") == ("{not json", 0)
    print("ok: mode payload is a bare id or {source, fade_ms}; bad fades mean no fade")


def test_mode_with_and_without_fade():
    c = make()
    c._handle_command("set", "mode", "noise")
    c._handle_command("set", "mode", json.dumps({"source": "spotify", "fade_ms": 5000}))
    assert c.calls == [("mode", "noise", 0), ("mode", "spotify", 5000)], c.calls
    assert c.current_mode == "spotify"
    c._handle_command("set", "mode", json.dumps({"source": "nope", "fade_ms": 5000}))
    assert len(c.calls) == 2, "unknown source must be rejected"
    print("ok: plain and faded mode commands reach switch_source; mode is published")


def test_library_play():
    c = make()
    c._handle_command("set", "library", json.dumps(
        {"items": ["lullabies/a.mp3", "lullabies/b.mp3"], "loop": True, "fade_ms": 2000}), "play")
    c._handle_command("set", "library", json.dumps({"item": "lullabies/a.mp3"}), "play")
    assert c.calls == [
        ("play", ["lullabies/a.mp3", "lullabies/b.mp3"], True, 2000),
        ("play", ["lullabies/a.mp3"], False, 0),
    ], c.calls
    assert c.current_mode == "library" and c.current_volume == 40
    for bad in ("not json", "[]", json.dumps({"items": []}), json.dumps({"items": "a.mp3"})):
        c._handle_command("set", "library", bad, "play")
    assert len(c.calls) == 2, "malformed play payloads must be rejected"
    c._handle_command("set", "library", "", "stop")
    assert c.calls[-1] == ("stop", 0)
    print("ok: library/play queues items (item or items), switches mode; library/stop stops")


def test_library_play_without_library_source():
    c = make(sources=("spotify", "noise"))
    c._handle_command("set", "library", json.dumps({"item": "a.mp3"}), "play")
    assert c.calls == [], c.calls
    print("ok: library/play is ignored on a device without the library source")


def test_library_transport_and_now_playing():
    c = make()
    for action in ("toggle", "next", "prev", "bogus"):
        c._handle_command("set", "library", "", action)
    assert [x for x in c.calls if x[0] == "control"] == [
        ("control", "toggle"), ("control", "next"), ("control", "prev")], c.calls

    from modules import library_player as lp
    p = lp.LibraryPlayer(server_host="fauxnos000.local")
    out = "http://fauxnos000.local:8080/library/Mom%20-%20Twinkle.mp3\n[paused]  #2/3   0:14/2:00 (11%)\nvolume: n/a\n"
    lp.subprocess.run = lambda cmd, **kw: type("R", (), {"returncode": 0, "stdout": out})()
    np = p.now_playing()
    assert (np["state"], np["path"], np["position"], np["queue_length"], np["elapsed_ms"], np["duration_ms"]) == \
        ("pause", "Mom - Twinkle.mp3", 2, 3, 14000, 120000), np
    lp.subprocess.run = lambda cmd, **kw: type("R", (), {"returncode": 0, "stdout": "volume: n/a\n"})()
    assert p.now_playing()["state"] == "stop"
    c._handle_command("set", "library", "104000", "seek")
    c._handle_command("set", "library", "soon", "seek")
    assert [x for x in c.calls if x[0] == "seek"] == [("seek", 104000)], c.calls
    seeks = []
    lp.subprocess.run = lambda cmd, **kw: seeks.append(cmd) or type("R", (), {"returncode": 0, "stderr": ""})()
    p.seek(104900)
    assert seeks[-1][-2:] == ["seek", "104"], seeks[-1]
    print("ok: library transport and seek reach the player; now-playing is parsed from mpc")


def test_library_stop_fade_payload():
    c = make()
    c._handle_command("set", "library", json.dumps({"fade_ms": 60000}), "stop")
    assert c.calls[-1] == ("stop", 60000), c.calls
    c._handle_command("set", "library", json.dumps({"fade_ms": 99999999}), "stop")
    assert c.calls[-1] == ("stop", MAX_FADE_MS)
    for junk in ("", "{not json", json.dumps({"fade_ms": "x"}), json.dumps([1])):
        c._handle_command("set", "library", junk, "stop")
        assert c.calls[-1] == ("stop", 0), (junk, c.calls[-1])
    print("ok: library/stop takes {fade_ms}; empty or bad payloads stop at once")


if __name__ == "__main__":
    test_parse_mode_payload()
    test_mode_with_and_without_fade()
    test_library_play()
    test_library_play_without_library_source()
    test_library_transport_and_now_playing()
    test_library_stop_fade_payload()
