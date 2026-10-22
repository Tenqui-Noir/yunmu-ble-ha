"""One-shot, connection-oriented BLE meter reader using HA's Bluetooth routes."""

import asyncio
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection

from .const import NOTIFY_UUID, RESPONSE_TIMEOUT, WRITE_UUID
from .protocol import MeterReading, ProtocolError, decode_read_response, encode_read_request

_LOGGER = logging.getLogger(__name__)


class YunmuBLEError(Exception):
    """A meter reading could not be obtained."""


async def read_meter(device: BLEDevice, tx_msg_id: int) -> MeterReading:
    """Connect, subscribe to notifications, send ONE read, then disconnect.

    Never automatically replay the same packet after a timeout: the device may
    have handled it even if its Notify was lost. `device` MUST come from HA's
    Bluetooth manager to support active ESPHome Bluetooth Proxies.
    """
    client: BleakClient | None = None
    notify_started = False
    loop = asyncio.get_running_loop()
    response: asyncio.Future[MeterReading] = loop.create_future()

    def on_notification(_: object, payload: bytearray) -> None:
        if response.done():
            return
        try:
            reading = decode_read_response(bytes(payload), expected_id=tx_msg_id)
        except ProtocolError as err:
            # An unrelated official-app packet is not our response.
            _LOGGER.debug(
                "Ignoring meter Notify: len=%d raw=%s reason=%s",
                len(payload),
                bytes(payload).hex(),
                err,
            )
            return
        _LOGGER.debug(
            "Decoded meter Notify: txMsgId=%d candidate_recharge_count=%s",
            reading.tx_msg_id,
            reading.candidate_recharge_count,
        )
        response.set_result(reading)

    try:
        # max_attempts=1 intentionally avoids a burst of connection retries.
        client = await establish_connection(
            BleakClient,
            device,
            device.address,
            max_attempts=1,
        )
        await client.start_notify(NOTIFY_UUID, on_notification)
        notify_started = True
        await client.write_gatt_char(
            WRITE_UUID,
            encode_read_request(tx_msg_id),
            response=False,
        )
        async with asyncio.timeout(RESPONSE_TIMEOUT):
            return await response
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
