"""The Fauxnos integration — media_player mirror over the Fauxnos MQTT bus."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_REST_URL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import FauxnosHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fauxnos from a config entry."""
    hub = FauxnosHub(
        hass,
        entry,
        rest_url=entry.data[CONF_REST_URL],
        mqtt_host=entry.data[CONF_MQTT_HOST],
        mqtt_port=entry.data[CONF_MQTT_PORT],
        mqtt_username=entry.data.get(CONF_MQTT_USERNAME),
        mqtt_password=entry.data.get(CONF_MQTT_PASSWORD),
    )
    await hub.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub: FauxnosHub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_shutdown()
    return unload_ok
