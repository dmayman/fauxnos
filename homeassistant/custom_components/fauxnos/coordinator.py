"""Fauxnos hub — owns the MQTT connection + REST enumeration.

Fauxnos stays the source of truth. This hub is a *pure mirror*: it reflects
device state from the retained `status/clients/+/...` topics and issues commands
back over `set/clients/<id>/...`. It never holds a divergent desired-state that
could fight the iOS / web UIs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import aiohttp
import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DOMAIN,
    SIGNAL_DEVICE_NEW,
    STATUS_SUBSCRIPTIONS,
    TOPIC_GET_ALL_STATUS,
    signal_device_update,
    topic_set_mode,
    topic_set_volume,
)

_LOGGER = logging.getLogger(__name__)

_REST_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _prettify(source_id: str) -> str:
    """Human-readable fallback when REST hasn't supplied a source label yet."""
    return source_id.replace("-", " ").replace("_", " ").title()


@dataclass
class FauxnosDevice:
    """Mirrored state for one Fauxnos device (one HA media_player)."""

    device_id: str
    name: str
    connected: bool = False
    volume: int | None = None          # 0-100
    mode: str | None = None            # current source_id
    activity: str | None = None        # "playing" | "silent"
    source_ids: list[str] = field(default_factory=list)
    source_labels: dict[str, str] = field(default_factory=dict)  # id -> label

    @property
    def source_list(self) -> list[str]:
        return [self.source_labels.get(sid, _prettify(sid)) for sid in self.source_ids]

    @property
    def current_source(self) -> str | None:
        if self.mode is None:
            return None
        return self.source_labels.get(self.mode, _prettify(self.mode))

    def label_to_id(self, label: str) -> str | None:
        for sid in self.source_ids:
            if self.source_labels.get(sid, _prettify(sid)) == label:
                return sid
        # Tolerate callers passing a raw source_id straight through.
        return label if label in self.source_ids else None


class FauxnosHub:
    """REST enumeration + a single shared MQTT connection for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        rest_url: str,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str | None,
        mqtt_password: str | None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.rest_url = rest_url.rstrip("/")
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port
        self._mqtt_username = mqtt_username
        self._mqtt_password = mqtt_password
        self.devices: dict[str, FauxnosDevice] = {}
        self.mqtt_connected = False
        self._client: mqtt.Client | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────
    async def async_setup(self) -> None:
        await self._async_load_rest()
        await self._async_start_mqtt()

    async def async_shutdown(self) -> None:
        if self._client is not None:
            await self.hass.async_add_executor_job(self._client.loop_stop)
            await self.hass.async_add_executor_job(self._client.disconnect)
            self._client = None

    # ── REST enumeration ────────────────────────────────────────────────────
    async def _async_load_rest(self) -> None:
        session = async_get_clientsession(self.hass)
        async with session.get(
            f"{self.rest_url}/api/clients", timeout=_REST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        for client in data.get("clients", []):
            device_id = client.get("client_id")
            if not device_id:
                continue
            self.devices[device_id] = FauxnosDevice(
                device_id=device_id,
                name=client.get("name") or device_id,
                connected=bool(client.get("connected")),
            )
        for device in self.devices.values():
            await self._async_load_sources(device)

    async def _async_load_sources(self, device: FauxnosDevice) -> None:
        """Populate id→label source map from the REST sources endpoint."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{self.rest_url}/api/clients/{device.device_id}/sources",
                timeout=_REST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning(
                "Could not load sources for %s: %s", device.device_id, err
            )
            return
        ids: list[str] = []
        labels: dict[str, str] = {}
        for source in data.get("sources", []):
            sid = source.get("id")
            if not sid:
                continue
            ids.append(sid)
            labels[sid] = source.get("label") or _prettify(sid)
        if ids:
            device.source_ids = ids
            device.source_labels = labels
        async_dispatcher_send(self.hass, signal_device_update(device.device_id))

    # ── MQTT ────────────────────────────────────────────────────────────────
    async def _async_start_mqtt(self) -> None:
        client_id = f"fauxnos-ha-{self.entry.entry_id[:8]}"
        try:
            # paho-mqtt 2.x requires an explicit callback API version; pin v1 so
            # our callback signatures stay valid across both 1.x and 2.x.
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1, client_id=client_id
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=client_id)
        if self._mqtt_username:
            client.username_pw_set(self._mqtt_username, self._mqtt_password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        await self.hass.async_add_executor_job(
            client.connect, self._mqtt_host, self._mqtt_port, 60
        )
        client.loop_start()

    # paho callbacks run on paho's network thread — marshal everything that
    # touches HA state onto the event loop with call_soon_threadsafe.
    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            _LOGGER.error("Fauxnos MQTT connect failed (rc=%s)", rc)
            return
        self.mqtt_connected = True
        for topic in STATUS_SUBSCRIPTIONS:
            client.subscribe(topic)
        client.publish(TOPIC_GET_ALL_STATUS, "")
        self.hass.loop.call_soon_threadsafe(self._dispatch_all)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self.mqtt_connected = False
        self.hass.loop.call_soon_threadsafe(self._dispatch_all)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = msg.payload.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            return
        self.hass.loop.call_soon_threadsafe(self._handle_message, msg.topic, payload)

    @callback
    def _handle_message(self, topic: str, payload: str) -> None:
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != "status" or parts[1] != "clients":
            return
        device_id, leaf = parts[2], parts[3]
        is_new = device_id not in self.devices
        device = self.devices.get(device_id)
        if device is None:
            device = FauxnosDevice(device_id=device_id, name=device_id)
            self.devices[device_id] = device

        if leaf == "volume":
            try:
                device.volume = int(payload)
            except ValueError:
                return
            device.connected = True
        elif leaf == "mode":
            device.mode = payload or None
            device.connected = True
        elif leaf == "activity":
            device.activity = payload or None
            device.connected = True
        elif leaf == "hello":
            try:
                data = json.loads(payload)
            except ValueError:
                return
            device.name = data.get("name") or device.name
            ids = data.get("sources") or []
            if ids:
                device.source_ids = ids
                for sid in ids:
                    device.source_labels.setdefault(sid, _prettify(sid))
                # Refresh human labels from REST out-of-band (don't block here).
                self.hass.async_create_task(self._async_load_sources(device))
            device.connected = True
        else:
            return

        if is_new:
            async_dispatcher_send(self.hass, SIGNAL_DEVICE_NEW, device_id)
        else:
            async_dispatcher_send(self.hass, signal_device_update(device_id))

    @callback
    def _dispatch_all(self) -> None:
        for device_id in self.devices:
            async_dispatcher_send(self.hass, signal_device_update(device_id))

    # ── commands out ────────────────────────────────────────────────────────
    def _publish(self, topic: str, payload: str) -> None:
        if self._client is not None:
            self._client.publish(topic, payload)

    async def async_set_volume(self, device_id: str, volume_0_100: int) -> None:
        clamped = max(0, min(100, int(volume_0_100)))
        await self.hass.async_add_executor_job(
            self._publish, topic_set_volume(device_id), str(clamped)
        )

    async def async_select_source(self, device_id: str, source_id: str) -> None:
        await self.hass.async_add_executor_job(
            self._publish, topic_set_mode(device_id), source_id
        )
