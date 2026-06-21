"""Fauxnos media_player entities — one per device, mirrored over MQTT."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_DEVICE_NEW, signal_device_update
from .coordinator import FauxnosHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a media_player per known device, plus any that appear later."""
    hub: FauxnosHub = hass.data[DOMAIN][entry.entry_id]

    known: set[str] = set()

    @callback
    def _add(device_id: str) -> None:
        if device_id in known:
            return
        known.add(device_id)
        async_add_entities([FauxnosMediaPlayer(hub, device_id)])

    for device_id in list(hub.devices):
        _add(device_id)

    # Devices that announce themselves (hello) after setup get an entity too.
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_NEW, _add)
    )


class FauxnosMediaPlayer(MediaPlayerEntity):
    """One Fauxnos room as an HA media_player.

    Volume + source are the real controls; state reflects Fauxnos `activity`.
    No transport/EQ here — that stays in the iOS / web UIs (see ticket scope).
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )
    _attr_volume_step = 0.05

    def __init__(self, hub: FauxnosHub, device_id: str) -> None:
        self._hub = hub
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}"

    @property
    def _device(self):
        return self._hub.devices.get(self._device_id)

    @property
    def name(self) -> str:
        device = self._device
        return device.name if device else self._device_id

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.name if device else self._device_id,
            manufacturer="Fauxnos",
            model="Fauxnos room",
        )

    @property
    def available(self) -> bool:
        device = self._device
        return bool(self._hub.mqtt_connected and device and device.connected)

    @property
    def state(self) -> MediaPlayerState | None:
        device = self._device
        if not device:
            return None
        if device.activity == "playing":
            return MediaPlayerState.PLAYING
        if device.activity == "silent":
            return MediaPlayerState.IDLE
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        device = self._device
        if not device or device.volume is None:
            return None
        return max(0.0, min(1.0, device.volume / 100))

    @property
    def source(self) -> str | None:
        device = self._device
        return device.current_source if device else None

    @property
    def source_list(self) -> list[str]:
        device = self._device
        return device.source_list if device else []

    async def async_set_volume_level(self, volume: float) -> None:
        await self._hub.async_set_volume(self._device_id, round(volume * 100))

    async def async_select_source(self, source: str) -> None:
        device = self._device
        if not device:
            return
        source_id = device.label_to_id(source)
        if source_id is None:
            _LOGGER.warning(
                "Unknown source %r for %s", source, self._device_id
            )
            return
        await self._hub.async_select_source(self._device_id, source_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_device_update(self._device_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
