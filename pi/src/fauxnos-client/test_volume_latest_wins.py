#!/usr/bin/env python3
"""
Test that MQTT volume commands are coalesced: while one command is being
applied, the commands that arrive behind it collapse to the newest value
instead of being replayed in order.

Run: python3 test_volume_latest_wins.py
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from modules.mqtt_client import MQTTClient


def demo():
    applied = []
    release = threading.Event()

    def slow_set_volume(v):
        applied.append(v)
        release.wait(2)  # the first command stalls, like a slow name lookup

    # __new__ skips __init__ so no broker or config file is needed.
    c = MQTTClient.__new__(MQTTClient)
    c.volume_callback = slow_set_volume
    c.connected = False
    c.current_volume = 0
    c._pending_volume = None
    c._volume_evt = threading.Event()
    c._command_lock = threading.Lock()
    threading.Thread(target=c._volume_worker, daemon=True).start()

    c._handle_command("set", "volume", "26")
    time.sleep(0.1)  # worker is now stuck applying 26
    for v in (22, 21, 20, 19):
        c._handle_command("set", "volume", str(v))
    release.set()
    time.sleep(0.2)

    assert applied == [26, 19], applied
    assert c.current_volume == 19, c.current_volume
    print("ok: stalled command followed by 4 queued → applied", applied)


if __name__ == "__main__":
    demo()
