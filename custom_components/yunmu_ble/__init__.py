"""Experimental, read-only integration for Yunmu BLE prepaid meters."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import YunmuCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize polling without requiring the device to be reachable now."""
    coordinator = YunmuCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_load_cost()
    # Allow HA to load the integration with initially unavailable entities.
    await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Retired period sensors are superseded by statistics on the raw total.
    registry = er.async_get(hass)
    for old_key in ("daily_usage", "weekly_usage", "monthly_usage", "yearly_usage"):
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{coordinator.address}_{old_key}"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop polling and unload entities."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)
