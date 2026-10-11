"""Manual, rate-limited read button for a Yunmu BLE meter."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import YunmuCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Register a press-to-read entity on the same device as the sensors."""
    coordinator: YunmuCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([YunmuReadButton(coordinator, entry)])


class YunmuReadButton(ButtonEntity):
    """Trigger a single manual BLE reading."""

    _attr_has_entity_name = True
    _attr_translation_key = "read_now"
    _attr_icon = "mdi:refresh"
    _attr_should_poll = False

    def __init__(self, coordinator: YunmuCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_read_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=entry.title,
            manufacturer="Yunmu (unofficial)",
            model="BLE prepaid electricity meter (experimental)",
            connections={("bluetooth", coordinator.address)},
        )

    async def async_press(self) -> None:
        """Perform a guarded read; never send raw commands from the button."""
        await self.coordinator.async_manual_read()
