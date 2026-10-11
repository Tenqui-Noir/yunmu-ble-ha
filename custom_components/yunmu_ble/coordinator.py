"""Scheduled, low-rate meter reads. No cloud requests."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MANUAL_READ_COOLDOWN_SECONDS,
)
from .protocol import MeterReading
from .transport import YunmuBLEError, read_meter

_LOGGER = logging.getLogger(__name__)


class YunmuCoordinator(DataUpdateCoordinator[MeterReading]):
    """Polls a single meter with just one read command each interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.address = entry.data["address"]
        self.last_success: datetime | None = None
        self._next_tx_msg_id = 0
        self._last_successful_id: int | None = None
        self._manual_lock = asyncio.Lock()
        self._last_manual_attempt: float | None = None
        self._read_in_progress = False
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.address}",
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    async def async_manual_read(self) -> None:
        """Request one immediate read, rejecting bursts and overlapping BLE reads."""
        if self._manual_lock.locked() or self._read_in_progress:
            raise HomeAssistantError("A Yunmu meter read is already in progress")

        async with self._manual_lock:
            now = monotonic()
            if (
                self._last_manual_attempt is not None
                and now - self._last_manual_attempt < MANUAL_READ_COOLDOWN_SECONDS
            ):
                raise HomeAssistantError("Please wait 30 seconds before another manual meter read")
            # A scheduled read might have started while waiting for the lock.
            if self._read_in_progress:
                raise HomeAssistantError("A Yunmu meter read is already in progress")
            self._last_manual_attempt = now
            # async_refresh uses the coordinator's internal lock, shared with
            # scheduled refreshes; it bypasses request-refresh debounce.
            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError("Yunmu meter read failed; check the HA logs")

    async def _async_update_data(self) -> MeterReading:
        self._read_in_progress = True
        try:
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if device is None:
                raise UpdateFailed(
                    f"Meter {self.address} not in range of a connectable Bluetooth adapter/proxy"
                )

            # Both read paths share these IDs. Advance even on a lost Notify.
            msg_id = self._next_tx_msg_id
            self._next_tx_msg_id = 1 - msg_id

            try:
                reading = await read_meter(device, msg_id)
            except (YunmuBLEError, BleakError, TimeoutError, OSError) as err:
                raise UpdateFailed(f"Meter read failed: {err}") from err

            self.last_success = datetime.now(UTC)
            self._last_successful_id = msg_id
            return reading
        finally:
            self._read_in_progress = False
