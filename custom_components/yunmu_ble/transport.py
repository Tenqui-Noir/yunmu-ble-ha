"""One-shot, connection-oriented BLE meter reader using HA's Bluetooth routes."""

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import NOTIFY_UUID, RESPONSE_TIMEOUT, WRITE_UUID
from .protocol import (
    DEFAULT_XOR_KEY,
    MeterReading,
    ProtocolError,
    decode_read_response,
    encode_read_request,
)

_LOGGER = logging.getLogger(__name__)

# Short window used while probing obfuscation keys: a working meter answers in
# well under one second, so a full 256-key sweep costs at most ~2 minutes.
KEY_PROBE_TIMEOUT = 0.45

# Keys reported in the field; tried before the full sweep.
KNOWN_XOR_KEYS = (0xD5, 0xAA, 0x3E)


class YunmuBLEError(Exception):
    """A meter reading could not be obtained."""


class _Session:
    """One BLE connection, reused for several attempts."""

    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self._pending: asyncio.Future[MeterReading] | None = None
        self._expected_id: int | None = None

    def _on_notification(self, _: object, payload: bytearray) -> None:
        pending = self._pending
        if pending is None or pending.done():
            return
        try:
            reading = decode_read_response(
                bytes(payload), expected_id=self._expected_id
            )
        except ProtocolError as err:
            # Another client's reply, a stray packet, or a bad key guess.
            _LOGGER.debug(
                "Ignoring Notify len=%d raw=%s reason=%s",
                len(payload),
                bytes(payload).hex(),
                err,
            )
            return
        pending.set_result(reading)

    async def attempt(self, tx_msg_id: int, xor_key: int) -> MeterReading:
        """Send one read request and wait briefly for a matching Notify."""
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._expected_id = tx_msg_id
        await self.client.write_gatt_char(
            WRITE_UUID,
            encode_read_request(tx_msg_id, xor_key),
            response=False,
        )
        async with asyncio.timeout(KEY_PROBE_TIMEOUT):
            return await self._pending

    async def read(self, tx_msg_id: int, xor_key: int) -> MeterReading:
        """Send one read request and wait the full response timeout."""
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._expected_id = tx_msg_id
        await self.client.write_gatt_char(
            WRITE_UUID,
            encode_read_request(tx_msg_id, xor_key),
            response=False,
        )
        async with asyncio.timeout(RESPONSE_TIMEOUT):
            return await self._pending


async def read_meter(
    device: BLEDevice,
    tx_msg_id: int,
    xor_key: int = DEFAULT_XOR_KEY,
) -> MeterReading:
    """Connect, subscribe, send ONE read, then disconnect.

    Never automatically replay the same packet after a timeout: the device may
    have handled it even if its Notify was lost, and repeating a txMsgId makes
    the meter ignore that id for a while. `device` MUST come from HA's
    Bluetooth manager to support active ESPHome Bluetooth Proxies.
    """
    client: BleakClient | None = None
    notify_started = False

    try:
        # max_attempts=1 intentionally avoids a burst of connection retries.
        client = await establish_connection(
            BleakClient,
            device,
            device.address,
            max_attempts=1,
        )
        session = _Session(client)
        await client.start_notify(NOTIFY_UUID, session._on_notification)
        notify_started = True
        return await session.read(tx_msg_id, xor_key)
    except TimeoutError as err:
        raise YunmuBLEError("No matching Notify before timeout") from err
    except (ProtocolError, ValueError) as err:
        raise YunmuBLEError("Could not process the meter response") from err
    finally:
        # Notify teardown must not hide a successful reading/real error.
        if client is not None:
            if notify_started and client.is_connected:
                try:
                    await client.stop_notify(NOTIFY_UUID)
                except Exception:  # noqa: BLE001 - best-effort teardown
                    _LOGGER.debug("Could not stop Yunmu Notify", exc_info=True)
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    _LOGGER.debug("Could not disconnect Yunmu BLE", exc_info=True)


async def discover_meter_key(
    device: BLEDevice,
    tx_msg_id: int = 0,
) -> tuple[MeterReading, int]:
    """Find the unit's obfuscation key and return the reading that proved it.

    Byte 2 of every request is the key itself, so sweeping 0..255 is safe and
    self-verifying: the first Notify ends the search. Known keys are tried
    first, which covers all field reports without the full sweep.
    """
    order = list(KNOWN_XOR_KEYS) + [key for key in range(256) if key not in KNOWN_XOR_KEYS]
    client: BleakClient | None = None
    notify_started = False

    try:
        client = await establish_connection(
            BleakClient,
            device,
            device.address,
            max_attempts=1,
        )
        session = _Session(client)
        await client.start_notify(NOTIFY_UUID, session._on_notification)
        notify_started = True

        for index, xor_key in enumerate(order):
            # Rotate the id: the meter ignores a txMsgId it has just seen.
            mid = (tx_msg_id + index) & 0xFF
            try:
                reading = await session.attempt(mid, xor_key)
            except (TimeoutError, YunmuBLEError):
                continue
            _LOGGER.debug(
                "Discovered Yunmu obfuscation key 0x%02X after %d attempts",
                xor_key,
                index + 1,
            )
            return reading, xor_key

        raise YunmuBLEError("Meter did not answer any obfuscation key (0x00-0xFF)")
    finally:
        if client is not None:
            if notify_started and client.is_connected:
                try:
                    await client.stop_notify(NOTIFY_UUID)
                except Exception:  # noqa: BLE001 - best-effort teardown
                    _LOGGER.debug("Could not stop Yunmu Notify", exc_info=True)
            if client.is_connected:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    _LOGGER.debug("Could not disconnect Yunmu BLE", exc_info=True)
