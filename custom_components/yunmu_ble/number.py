"""Editable, per-device meter settings."""

from math import isfinite

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ELECTRICITY_PRICE,
    CONF_LOW_ENERGY_THRESHOLD,
    CONF_POLL_INTERVAL,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_LOW_ENERGY_THRESHOLD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_ELECTRICITY_PRICE,
    MAX_LOW_ENERGY_THRESHOLD,
    MAX_POLL_INTERVAL,
    MIN_ELECTRICITY_PRICE,
    MIN_LOW_ENERGY_THRESHOLD,
    MIN_POLL_INTERVAL,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Expose adjustable options as configuration entities on the device page."""
    async_add_entities(
        [
            YunmuPollInterval(entry),
            YunmuLowEnergyThreshold(entry),
            YunmuElectricityPrice(entry),
        ]
    )


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


class YunmuLowEnergyThreshold(NumberEntity):
    """Set the kWh threshold for a single low-energy notification."""

    _attr_has_entity_name = True
    _attr_translation_key = "low_energy_threshold"
    _attr_icon = "mdi:lightning-bolt-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_LOW_ENERGY_THRESHOLD
    _attr_native_max_value = MAX_LOW_ENERGY_THRESHOLD
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "kWh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        address = entry.data["address"]
        self._attr_unique_id = f"{address}_low_energy_threshold"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="Yunmu (unofficial)",
            model="BLE prepaid electricity meter (experimental)",
            connections={("bluetooth", address)},
        )

    @property
    def native_value(self) -> int:
        """Read the persisted threshold (0 means disabled)."""
        return int(self._entry.options.get(
            CONF_LOW_ENERGY_THRESHOLD, DEFAULT_LOW_ENERGY_THRESHOLD
        ))

    async def async_set_native_value(self, value: float) -> None:
        """Save a whole-kWh threshold and reload the coordinator via options."""
        if (
            not MIN_LOW_ENERGY_THRESHOLD <= value <= MAX_LOW_ENERGY_THRESHOLD
            or value != int(value)
        ):
            raise ValueError("Low-energy threshold must be an integer from 0 to 1000 kWh")
        new_threshold = int(value)
        if self.native_value == new_threshold:
            return
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_LOW_ENERGY_THRESHOLD: new_threshold},
        )


class YunmuElectricityPrice(NumberEntity):
    """Persist the per-kWh price used by monetary estimates."""

    _attr_has_entity_name = True
    _attr_translation_key = "electricity_price"
    _attr_icon = "mdi:currency-cny"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_ELECTRICITY_PRICE
    _attr_native_max_value = MAX_ELECTRICITY_PRICE
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = "CNY/kWh"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        address = entry.data["address"]
        self._attr_unique_id = f"{address}_electricity_price"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="Yunmu (unofficial)",
            model="BLE prepaid electricity meter (experimental)",
            connections={("bluetooth", address)},
        )

    @property
    def native_value(self) -> float:
        """Return the last configured rate without resetting existing prices."""
        return float(self._entry.options.get(CONF_ELECTRICITY_PRICE, DEFAULT_ELECTRICITY_PRICE))

    async def async_set_native_value(self, value: float) -> None:
        """Store the new price; the options listener reloads monetary estimates."""
        if not isfinite(value) or not MIN_ELECTRICITY_PRICE <= value <= MAX_ELECTRICITY_PRICE:
            raise ValueError("Electricity price must be a finite value from 0 to 10 CNY/kWh")
        new_price = float(value)
        if self.native_value == new_price:
            return
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_ELECTRICITY_PRICE: new_price},
        )
