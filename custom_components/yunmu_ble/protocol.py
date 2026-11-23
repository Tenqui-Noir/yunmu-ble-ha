"""Observed *read-only* Yunmu BLE command and meter response protocol.

Reverse engineered from YM-M4-BE captures in October 2026. This module has no
Home Assistant or Bluetooth dependencies. Do not extend it with meter control,
recharge, clearing, or raw-command passthrough functionality.

Obfuscation is *per unit*, not a protocol constant. Three request keys have been
observed in the field (0xD5, 0xAA, 0x3E) and the key is echoed in byte 2 of
every read request. The response key is derivable from the packet itself: the
first decoded byte must be 0x01, so ``key = packet[0] ^ 0x01``.

IMPORTANT: Response integrity bytes 17..19 are not yet understood; the checks
below are structural plausibility checks, NOT cryptographic or CRC validation.
"""

from dataclasses import dataclass

# Legacy fixed keys kept for backwards compatibility with earlier captures.
OBFUSCATION_KEY = 0x91
DEFAULT_XOR_KEY = 0xD5

RESPONSE_SIZE = 20
REQUEST_SIZE = 5

# Every valid response starts with this value after de-obfuscation.
_RESPONSE_MAGIC = 0x01
_RESPONSE_KIND = 0x10


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
    # Key that successfully de-obfuscated this response; None when unknown.
    response_xor_key: int | None = None


def encode_read_request(tx_msg_id: int, xor_key: int = DEFAULT_XOR_KEY) -> bytes:
    """Build the five-byte meter read request.

    ``xor_key`` is unit specific. The frame is self-describing: byte 2 equals
    ``xor_key`` and byte 0 equals ``0x01 ^ xor_key``, so a central can discover
    the key by sweeping 0..255 and watching for the first Notify.

    Passing ``0xD5`` reproduces the packets captured on the original unit.
    """
    if not 0 <= tx_msg_id <= 0xFF:
        raise ValueError("tx_msg_id must be an unsigned 8-bit integer")
    if not 0 <= xor_key <= 0xFF:
        raise ValueError("xor_key must be an unsigned 8-bit integer")

    return bytes(
        (
            _RESPONSE_MAGIC ^ xor_key,
            tx_msg_id ^ xor_key,
            xor_key,
            ((tx_msg_id + 0x11) & 0xFF) ^ xor_key,
            (tx_msg_id ^ 0x08) ^ xor_key,
        )
    )


def response_xor_key(packet: bytes) -> int | None:
    """Derive the response key from a raw Notify payload, or None if implausible."""
    if len(packet) != RESPONSE_SIZE:
        return None
    return packet[0] ^ _RESPONSE_MAGIC


def decode_read_response(
    packet: bytes,
    expected_id: int | None = None,
    xor_key: int | None = None,
) -> MeterReading:
    """Decode a captured 20-byte Notify payload.

    When ``xor_key`` is omitted the key is derived from the packet itself
    (``packet[0] ^ 0x01``), falling back to the legacy 0x91 constant. The two
    kWh fields use unsigned big-endian 32-bit integers scaled by 1/100.
    """
    if len(packet) != RESPONSE_SIZE:
        raise ProtocolError(f"Expected {RESPONSE_SIZE} bytes, received {len(packet)}")

    if xor_key is None:
        candidates = [key for key in (packet[0] ^ _RESPONSE_MAGIC, OBFUSCATION_KEY) if key is not None]
    else:
        if not 0 <= xor_key <= 0xFF:
            raise ProtocolError("xor_key must be an unsigned 8-bit integer")
        candidates = [xor_key]

    last_error: ProtocolError | None = None
    for key in candidates:
        try:
            return _decode_with_key(packet, key, expected_id)
        except ProtocolError as err:
            last_error = err

    raise last_error or ProtocolError("Unrecognized Yunmu meter response header")


def _decode_with_key(
    packet: bytes,
    xor_key: int,
    expected_id: int | None,
) -> MeterReading:
    data = bytes(value ^ xor_key for value in packet)

    # Bytes 3..4 changed from 61 00 to 62 00 after a recharge. They match
    # 97 -> 98 recharge records, but that meaning and 16-bit LE layout are
    # hypotheses, not confirmed protocol semantics. Do not freeze them.
    if data[0] != _RESPONSE_MAGIC or data[2] != _RESPONSE_KIND:
        raise ProtocolError("Unrecognized Yunmu meter response header")

    candidate_recharge_count = int.from_bytes(data[3:5], "little")
    tx_msg_id = data[1]
    if expected_id is not None and tx_msg_id != expected_id:
        raise ProtocolError(f"Unexpected txMsgId {tx_msg_id}; expected {expected_id}")

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
        response_xor_key=xor_key,
    )
