"""Scheduled, low-rate meter reads. No cloud requests."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic

from bleak.exc import BleakError
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ELECTRICITY_PRICE,
    CONF_LOW_ENERGY_THRESHOLD,
    CONF_POLL_INTERVAL,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_LOW_ENERGY_THRESHOLD,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MANUAL_READ_COOLDOWN_SECONDS,
)
from .cost import ConsumptionCostLedger
from .protocol import MeterReading
from .transport import YunmuBLEError, read_meter

_LOGGER = logging.getLogger(__name__)

FAILURE_NOTIFICATION_THRESHOLD = 3


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
        self._consecutive_failures = 0
        self._failure_notification_sent = False
        self._low_energy_threshold = int(
            entry.options.get(CONF_LOW_ENERGY_THRESHOLD, DEFAULT_LOW_ENERGY_THRESHOLD)
        )
        self._low_energy_notified = False
        self.electricity_price = float(
            entry.options.get(CONF_ELECTRICITY_PRICE, DEFAULT_ELECTRICITY_PRICE)
        )
        self.cost_ledger = ConsumptionCostLedger(self.electricity_price)
        self._cost_store = Store(
            hass, 1, f"{DOMAIN}_cost_{self.address.replace(':', '').lower()}"
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.address}",
            config_entry=entry,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    async def async_load_cost(self) -> None:
        """Restore the accumulated expense checkpoint before the first read."""
        try:
            self.cost_ledger.restore(await self._cost_store.async_load())
        except Exception:
            _LOGGER.exception("Failed to restore Yunmu cost checkpoint")

    async def _async_save_cost(self, total_kwh: float) -> None:
        """Account for new usage and persist; never turn BLE success into failure."""
        try:
            self.cost_ledger.observe(total_kwh)
            await self._cost_store.async_save(self.cost_ledger.snapshot())
        except Exception:
            _LOGGER.exception("Failed to update Yunmu cost checkpoint")

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
                raise HomeAssistantError("Please wait 5 seconds before another manual meter read")
            # A scheduled read might have started while waiting for the lock.
            if self._read_in_progress:
                raise HomeAssistantError("A Yunmu meter read is already in progress")
            self._last_manual_attempt = now
            # async_refresh uses the coordinator's internal lock, shared with
            # scheduled refreshes; it bypasses request-refresh debounce.
            await self.async_refresh()
            if not self.last_update_success:
                raise HomeAssistantError("Yunmu meter read failed; check the HA logs")

    def _record_failed_read(self) -> None:
        """Alert once per uninterrupted streak of unsuccessful read attempts."""
        self._consecutive_failures += 1
        if (
            self._consecutive_failures >= FAILURE_NOTIFICATION_THRESHOLD
            and not self._failure_notification_sent
        ):
            persistent_notification.async_create(
                self.hass,
                (
                    f"电表 {self.address} 已连续 {self._consecutive_failures} 次抄表失败。"
                    "传感器保留上次成功的读数；请检查电表与蓝牙代理的连接。"
                ),
                title="云木蓝牙电表抄表失败",
                notification_id=f"{DOMAIN}_read_failure_{self.address.replace(':', '').lower()}",
            )
            self._failure_notification_sent = True

    def _check_low_energy(self, reading: MeterReading) -> None:
        """Notify once when a successful reading is at or below the configured threshold."""
        threshold = self._low_energy_threshold
        if threshold == 0 or reading.remaining_kwh > threshold:
            self._low_energy_notified = False
            return
        if self._low_energy_notified:
            return

        persistent_notification.async_create(
            self.hass,
            (
                f"电表 {self.address} 剩余电量仅 {reading.remaining_kwh:.2f} kWh，"
                f"已达到设定的 {threshold} kWh 提醒阈值，请及时关注电量余额。"
            ),
            title="云木蓝牙电表剩余电量不足",
            notification_id=f"{DOMAIN}_low_energy_{self.address.replace(':', '').lower()}",
        )
        self._low_energy_notified = True

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

            self._consecutive_failures = 0
            self._failure_notification_sent = False
            self.last_success = datetime.now(UTC)
            self._last_successful_id = msg_id
            self._check_low_energy(reading)
            await self._async_save_cost(reading.total_kwh)
            return reading
        except UpdateFailed:
            self._record_failed_read()
            raise
        finally:
            self._read_in_progress = False
