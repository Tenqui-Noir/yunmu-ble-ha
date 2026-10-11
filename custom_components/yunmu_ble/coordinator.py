"""Scheduled, low-rate meter reads. No cloud requests."""

from datetime import UTC, datetime, timedelta
import logging

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN
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
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.address}",
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> MeterReading:
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"Meter {self.address} not in range of a connectable Bluetooth adapter/proxy"
            )

        # This is an experiment: 0 and 1 are the only local IDs independently
        # verified. Advance even on timeout because a lost Notify might follow
        # a successfully handled request. Starting ID after a restart is unknown;
        # at worst that first poll may time out, then the ID is switched.
        msg_id = self._next_tx_msg_id
        self._next_tx_msg_id = 1 - msg_id

        try:
            reading = await read_meter(device, msg_id)
        except (YunmuBLEError, BleakError, TimeoutError, OSError) as err:
            raise UpdateFailed(f"Meter read failed: {err}") from err

        self.last_success = datetime.now(UTC)
        self._last_successful_id = msg_id
        return reading
