#!/usr/bin/env python3
"""
Test MQTT presence: the retained last will, `online` on every (re)connect,
and `offline` on a clean stop.

Run: python3 test_mqtt_online.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from modules.mqtt_client import MQTTClient, KEEPALIVE_S


class FakePaho:
    def __init__(self):
        self.log = []

    def will_set(self, topic, payload, retain=False):
        self.log.append(("will", topic, payload, retain))

    def publish(self, topic, payload, retain=False):
        self.log.append(("pub", topic, payload, retain))
        return SimpleNamespace(wait_for_publish=lambda timeout=None: None)

    def subscribe(self, topic):
        pass

    def connect(self, host, port, keepalive):
        self.log.append(("connect", keepalive))

    def disconnect(self):
        self.log.append(("disconnect",))

    def loop_start(self):
        pass

    def loop_stop(self):
        self.log.append(("loop_stop",))


def make():
    # __new__ skips __init__ so no broker or config file is needed.
    c = MQTTClient.__new__(MQTTClient)
    c.device_id = "fauxnos003"
    c.display_name = "Office"
    c.client = FakePaho()
    c.connected = False
    c.should_run = True
    c.broker_host, c.broker_port = "broker", 1883
    c._subscribe_to_control_topics = lambda: None
    c._send_hello = lambda: None
    return c


TOPIC = "status/clients/fauxnos003/online"


def test_init_sets_will_before_connect():
    import modules.mqtt_client as m
    cfg = SimpleNamespace(
        device_config=SimpleNamespace(name="fauxnos003", display_name="Office"),
        config={}, server_host="broker", sources={"spotify": {}},
    )
    real, m.mqtt.Client = m.mqtt.Client, lambda **kw: FakePaho()
    try:
        c = MQTTClient(cfg, volume_callback=None, mode_callback=None)
    finally:
        m.mqtt.Client = real
    assert c.client.log == [("will", TOPIC, "offline", True)], c.client.log
    assert 30 <= KEEPALIVE_S * 1.5 <= 60, "dead rooms must show offline in 30-60s"
    print("ok: init sets a retained offline will; keepalive gives a 30-60s ceiling")


def test_online_on_every_connect():
    c = make()
    c._on_connect(c.client, None, None, 0)
    c._on_connect(c.client, None, None, 0)  # broker reconnect
    assert c.client.log == [("pub", TOPIC, "online", True)] * 2, c.client.log
    c.client.log.clear()
    c._on_connect(c.client, None, None, 5)  # refused: say nothing
    assert c.client.log == []
    print("ok: every accepted (re)connect publishes retained online")


def test_connect_uses_keepalive():
    c = make()
    c.connected = True  # skip the wait loop
    c.start()
    assert ("connect", KEEPALIVE_S) in c.client.log
    print("ok: connect passes KEEPALIVE_S")


def test_clean_stop_publishes_offline_before_disconnect():
    c = make()
    c.connected = True
    c.stop()
    assert c.client.log == [
        ("pub", TOPIC, "offline", True), ("disconnect",), ("loop_stop",)
    ], c.client.log
    print("ok: clean stop publishes retained offline, then disconnects")


if __name__ == "__main__":
    test_init_sets_will_before_connect()
    test_online_on_every_connect()
    test_connect_uses_keepalive()
    test_clean_stop_publishes_offline_before_disconnect()
    print("all passed")
