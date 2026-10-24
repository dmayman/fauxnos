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
    c.library_stop_callback = lambda: c.calls.append(("stop",)) or True
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
    assert c.calls[-1] == ("stop",)
    print("ok: library/play queues items (item or items), switches mode; library/stop stops")


def test_library_play_without_library_source():
    c = make(sources=("spotify", "noise"))
    c._handle_command("set", "library", json.dumps({"item": "a.mp3"}), "play")
    assert c.calls == [], c.calls
    print("ok: library/play is ignored on a device without the library source")


if __name__ == "__main__":
    test_parse_mode_payload()
    test_mode_with_and_without_fade()
    test_library_play()
    test_library_play_without_library_source()
