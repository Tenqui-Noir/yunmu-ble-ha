"""Observed *read-only* Yunmu BLE command and meter response protocol.

Reverse engineered from YM-M4-BE captures in October 2026. This module has no
Home Assistant or Bluetooth dependencies. Do not extend it with meter control,
recharge, clearing, or raw-command passthrough functionality.

IMPORTANT: Response integrity bytes 17..19 are not yet understood; the checks
below are structural plausibility checks, NOT cryptographic or CRC validation.
"""

from dataclasses import dataclass

OBFUSCATION_KEY = 0x91
RESPONSE_SIZE = 20


class ProtocolError(ValueError):
    """The received bytes are not a recognized meter reading."""


@dataclass(frozen=True, slots=True)
class MeterReading:
    """Electricity reading captured from a response."""

    tx_msg_id: int
    remaining_kwh: float
    total_kwh: float
    # Hypothesis only: decoded bytes 3..4 correlate with a recharge record count.
    candidate_recharge_count: int | None = None


def encode_read_request(tx_msg_id: int) -> bytes:
    """Build the five-byte meter read request observed with IDs 0, 1, 147, 152, 153.

    The request layout is inferred from captures; arbitrary IDs are untested.
    Only IDs 0 and 1 are used by the HA integration until further validation.
    """
    if not 0 <= tx_msg_id <= 0xFF:
        raise ValueError("tx_msg_id must be an unsigned 8-bit integer")

    return bytes(
        (
            0xD4,
            tx_msg_id ^ 0xD5,
            0xD5,
            ((tx_msg_id + 0x11) & 0xFF) ^ 0xD5,
            tx_msg_id ^ 0x08 ^ 0xD5,
        )
    )


def decode_read_response(packet: bytes, expected_id: int | None = None) -> MeterReading:
    """Decode a captured 20-byte Notify payload.

    The two kWh fields use unsigned big-endian 32-bit integers scaled by 1/100.
    Reject structurally wrong packets and responses for another request ID.
    """
    if len(packet) != RESPONSE_SIZE:
        raise ProtocolError(f"Expected {RESPONSE_SIZE} bytes, received {len(packet)}")

    data = bytes(value ^ OBFUSCATION_KEY for value in packet)
    # Bytes 3..4 changed from 61 00 to 62 00 after a recharge. They match
    # 97 -> 98 recharge records, but that meaning and 16-bit LE layout are
    # hypotheses, not confirmed protocol semantics. Do not freeze them.
    if data[0] != 0x01 or data[2] != 0x10:
        raise ProtocolError("Unrecognized Yunmu meter response header")

    candidate_recharge_count = int.from_bytes(data[3:5], "little")
    tx_msg_id = data[1]
    if expected_id is not None and tx_msg_id != expected_id:
        raise ProtocolError(
            f"Unexpected txMsgId {tx_msg_id}; expected {expected_id}"
        )

    remaining = int.from_bytes(data[7:11], "big") / 100
    total = int.from_bytes(data[11:15], "big") / 100
    # Protective bounds only; these do not validate the unknown trailing checksum.
    if not (0 <= remaining <= 10_000_000 and 0 <= total <= 10_000_000):
        raise ProtocolError("Implausible meter reading")

    return MeterReading(
        tx_msg_id=tx_msg_id,
        remaining_kwh=remaining,
        total_kwh=total,
        candidate_recharge_count=candidate_recharge_count,
    )
