"""Remaining and accumulated electricity sensors."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YunmuCoordinator

SENSORS = (
    SensorEntityDescription(
        key="remaining_energy",
        translation_key="remaining_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="estimated_balance",
        translation_key="estimated_balance",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="total_spent",
        translation_key="total_spent",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="last_read",
        translation_key="last_read",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add sensors with stable unique IDs."""
    coordinator: YunmuCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(YunmuSensor(coordinator, entry, description) for description in SENSORS)


class YunmuSensor(CoordinatorEntity[YunmuCoordinator], SensorEntity):
    """Expose a single field from the last successful BLE reading."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YunmuCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=entry.title,
            manufacturer="Yunmu (unofficial)",
            model="BLE prepaid electricity meter (experimental)",
            connections={("bluetooth", coordinator.address)},
        )

    @property
    def available(self) -> bool:
        """Keep the last good value visible after a failed coordinator refresh."""
        if self.entity_description.key == "total_spent":
            return self.coordinator.cost_ledger.value is not None
        return self.coordinator.data is not None

    @property
    def native_value(self) -> float | datetime | None:
        """Return the reading in kWh (or when the last read occurred)."""
        key = self.entity_description.key
        if key == "total_spent":
            return self.coordinator.cost_ledger.value
        if self.coordinator.data is None:
            return None
        if key == "estimated_balance":
            return round(
                self.coordinator.data.remaining_kwh * self.coordinator.electricity_price, 2
            )
        if key == "remaining_energy":
            return self.coordinator.data.remaining_kwh
        if self.entity_description.key == "total_energy":
            return self.coordinator.data.total_kwh
        if self.entity_description.key == "last_read":
            return self.coordinator.last_success
        return None
