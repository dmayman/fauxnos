"""Config flow for the Fauxnos integration."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_REST_URL,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_PORT,
    DEFAULT_REST_URL,
    DOMAIN,
)


class FauxnosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup for Fauxnos."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            rest_url = user_input[CONF_REST_URL].rstrip("/")
            user_input[CONF_REST_URL] = rest_url

            # Validate by enumerating devices over REST — that's the endpoint we
            # depend on at setup. (Broker reachability is verified at runtime.)
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(
                    f"{rest_url}/api/clients",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    await resp.json()
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(rest_url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Fauxnos", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_REST_URL, default=DEFAULT_REST_URL): str,
                vol.Required(CONF_MQTT_HOST, default=DEFAULT_MQTT_HOST): str,
                vol.Required(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): int,
                vol.Optional(CONF_MQTT_USERNAME): str,
                vol.Optional(CONF_MQTT_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
