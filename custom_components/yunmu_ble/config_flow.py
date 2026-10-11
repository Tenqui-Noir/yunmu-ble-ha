"""UI configuration and Bluetooth discovery for Yunmu BLE meters."""
from __future__ import annotations


import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)

_MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")


class YunmuConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the meter; never send a BLE command during configuration."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_address: str | None = None
        self._discovered_name: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: bluetooth.BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Start a flow when a connectable YUNM advertisement is received."""
        name = discovery_info.name or discovery_info.device.name or ""
        if not discovery_info.connectable or not name.upper().startswith("YUNM"):
            return self.async_abort(reason="unsupported_device")
        address = discovery_info.address.upper()
        if not _MAC_RE.fullmatch(address):
            return self.async_abort(reason="unsupported_device")
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovered_address = address
        self._discovered_name = name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Confirm an auto-discovered device before adding it."""
        if user_input is not None and self._discovered_address is not None:
            return self.async_create_entry(
                title=self._discovered_name or f"Yunmu {self._discovered_address}",
                data={CONF_ADDRESS: self._discovered_address},
            )
        return self.async_show_form(step_id="confirm")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Allow a known BLE MAC to be added without exposing command controls."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not _MAC_RE.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Yunmu {address}", data={CONF_ADDRESS: address}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> YunmuOptionsFlow:
        """Return the options form."""
        return YunmuOptionsFlow(config_entry)


class YunmuOptionsFlow(config_entries.OptionsFlow):
    """Permit a conservative polling interval to be configured."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    )
                }
            ),
        )
