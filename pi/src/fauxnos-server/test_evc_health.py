#!/usr/bin/env python3
"""
Test the external-volume-controller health tracking in FauxnosAPIServer: a volume
command that gets no answer marks the room's controller "unresponsive", and
the controller's next volume report marks it "ok" again.

Run: python3 test_evc_health.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.api_server import FauxnosAPIServer


def _fresh():
    # __new__ skips __init__ so no Flask app, config file or broker is needed.
    s = FauxnosAPIServer.__new__(FauxnosAPIServer)
    s._ext_vol_lock = threading.Lock()
    s._evc_health = {}
    s._EVC_REPLY_TIMEOUT_S = 0.1
    s.published = []
    s._publish_mqtt = lambda topic, payload, retain=False: s.published.append((topic, payload, retain)) or True
    s.log = lambda *a, **k: None
    return s


def demo():
    topic = "status/clients/fauxnos001/volume_controller"

    # A command that is answered in time publishes nothing but "ok".
    s = _fresh()
    s._expect_evc_reply("fauxnos001")
    s._note_evc_reply("fauxnos001")
    time.sleep(0.25)
    assert s.published == [(topic, "ok", True)], s.published

    # A drag with no answer flags the controller once, not once per command.
    s = _fresh()
    for _ in range(5):
        s._expect_evc_reply("fauxnos001")
    time.sleep(0.25)
    assert s.published == [(topic, "unresponsive", True)], s.published

    # Its next volume report clears the warning, and repeats publish nothing.
    s._note_evc_reply("fauxnos001")
    s._note_evc_reply("fauxnos001")
    assert s.published[1:] == [(topic, "ok", True)], s.published
    print("ok: unanswered command → unresponsive (once); next report → ok")


if __name__ == "__main__":
    demo()
