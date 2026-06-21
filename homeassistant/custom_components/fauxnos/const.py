"""Constants for the Fauxnos Home Assistant integration."""

from __future__ import annotations

DOMAIN = "fauxnos"

PLATFORMS = ["media_player"]

# ── Config-flow keys ────────────────────────────────────────────────────────
CONF_REST_URL = "rest_url"
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"

# Fauxnos answers at the bare hostname (mDNS CNAME + :80→:8080 redirect on the
# server). The mosquitto broker runs on fauxnos000 itself, port 1883, no auth.
DEFAULT_REST_URL = "http://fauxnos.local"
DEFAULT_MQTT_HOST = "fauxnos000.local"
DEFAULT_MQTT_PORT = 1883

# ── MQTT topic contract (mirrors pi/src/fauxnos-client/modules/mqtt_client.py) ─
# Subscribe to every device's current-state topics (all retained client-side).
TOPIC_STATUS_VOLUME = "status/clients/+/volume"
TOPIC_STATUS_MODE = "status/clients/+/mode"
TOPIC_STATUS_ACTIVITY = "status/clients/+/activity"
TOPIC_STATUS_HELLO = "status/clients/+/hello"
STATUS_SUBSCRIPTIONS = (
    TOPIC_STATUS_VOLUME,
    TOPIC_STATUS_MODE,
    TOPIC_STATUS_ACTIVITY,
    TOPIC_STATUS_HELLO,
)
# Published once on connect to make every client re-announce hello + republish
# its status topics, so HA gets a full snapshot even though it subscribes late.
TOPIC_GET_ALL_STATUS = "get/clients/all/status"


def topic_set_volume(device_id: str) -> str:
    """`set/clients/<id>/volume` — payload is an int 0-100 as a string."""
    return f"set/clients/{device_id}/volume"


def topic_set_mode(device_id: str) -> str:
    """`set/clients/<id>/mode` — payload is the bare source_id string."""
    return f"set/clients/{device_id}/mode"


# ── Dispatcher signals ──────────────────────────────────────────────────────
SIGNAL_DEVICE_NEW = f"{DOMAIN}_device_new"


def signal_device_update(device_id: str) -> str:
    """Per-device update signal so each entity only re-renders on its own news."""
    return f"{DOMAIN}_update_{device_id}"
