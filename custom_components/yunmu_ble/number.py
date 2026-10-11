"""Editable, per-device automatic meter polling interval."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Expose the polling interval on the meter's device page."""
    async_add_entities([YunmuPollInterval(entry)])


class YunmuPollInterval(NumberEntity):
    """Persist the polling interval to the config entry options."""

    _attr_has_entity_name = True
    _attr_translation_key = "poll_interval"
    _attr_icon = "mdi:timer-cog-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_POLL_INTERVAL
    _attr_native_max_value = MAX_POLL_INTERVAL
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        address = entry.data["address"]
        self._attr_unique_id = f"{address}_poll_interval"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="Yunmu (unofficial)",
            model="BLE prepaid electricity meter (experimental)",
            connections={("bluetooth", address)},
        )

    @property
    def native_value(self) -> int:
        """Reflect both settings dialog edits and device-level changes."""
        return int(self._entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

    async def async_set_native_value(self, value: float) -> None:
        """Save a new interval; the existing update listener reloads the scheduler."""
        if not MIN_POLL_INTERVAL <= value <= MAX_POLL_INTERVAL or value != int(value):
            raise ValueError("Polling interval must be a whole number from 5 to 120 minutes")
        new_interval = int(value)
        if self.native_value == new_interval:
            return
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_POLL_INTERVAL: new_interval},
        )
