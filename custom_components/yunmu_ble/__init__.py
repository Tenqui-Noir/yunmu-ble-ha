"""Experimental, read-only integration for Yunmu BLE prepaid meters."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN, PLATFORMS
from .coordinator import YunmuCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize polling without requiring the device to be reachable now."""
    coordinator = YunmuCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    # Allow HA to load the integration with initially unavailable entities.
    await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator._usage_tracking_started = True
    # Sensors are registered now, so Recorder's statistic ID can be resolved.
    await coordinator.async_update_period_usage()

    @callback
    def _on_midnight(now) -> None:
        """Rollover period sensors even if BLE is currently unreachable."""
        hass.async_create_task(coordinator.async_update_period_usage())

    entry.async_on_unload(async_track_time_change(hass, _on_midnight, hour=0, minute=0, second=0))
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
