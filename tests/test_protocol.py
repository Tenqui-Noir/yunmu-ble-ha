"""Offline regression tests using captured meter read packets, no hardware needed."""

import importlib.util
import sys
from pathlib import Path

import pytest

# Import the protocol by file to avoid loading Home Assistant's integration
# __init__.py; this keeps offline protocol tests entirely dependency-free.
PROTOCOL_FILE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble" / "protocol.py"
)
spec = importlib.util.spec_from_file_location("yunmu_test_protocol", PROTOCOL_FILE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

encode = module.encode_read_request
decode = module.decode_read_response
ProtocolError = module.ProtocolError


@pytest.mark.parametrize(
    ("msg_id", "expected"),
    [
        (0, "D4D5D5C4DD"),
        (1, "D4D4D5C7DC"),
        (147, "D446D5714E"),
        (152, "D44DD57C45"),
        (153, "D44CD57F44"),
    ],
)
def test_request_against_real_or_observed_examples(msg_id, expected):
    assert encode(msg_id).hex().upper() == expected


@pytest.mark.parametrize("msg_id", [-1, 256, 1000])
def test_request_id_rejected(msg_id):
    with pytest.raises(ValueError):
        encode(msg_id)


@pytest.mark.parametrize(
    ("hex_response", "tx_msg_id", "remaining", "total", "candidate_counter"),
    [
        ("909181F091A65F9191A71E919B7C4A909199B65F", 0, 139.67, 7162.51, 97),
        ("909181F091A65F9191A71B919B7C7190919FBC46", 0, 139.62, 7162.56, 97),
        ("909081F091A65F9191A719919B7C7390911939C1", 1, 139.60, 7162.58, 97),
        ("900881F091A65F9191A711919B7C7B909119D159", 153, 139.52, 7162.66, 97),
        # Captured from HA immediately after recharge (18:58:47 on 2026-10-22).
        ("909181F391A65F9191D003919A8B3790910F547A", 0, 167.86, 7277.18, 98),
    ],
)
def test_decode_captured_readings(hex_response, tx_msg_id, remaining, total, candidate_counter):
    reading = decode(bytes.fromhex(hex_response), expected_id=tx_msg_id)
    assert reading.remaining_kwh == pytest.approx(remaining)
    assert reading.total_kwh == pytest.approx(total)
    assert reading.tx_msg_id == tx_msg_id
    assert reading.candidate_recharge_count == candidate_counter


def test_official_id_152_reading():
    pkt = bytes.fromhex("900981F091A65F9191A715919B7C77909110A955")
    reading = decode(pkt, expected_id=152)
    assert reading.remaining_kwh == 139.56
    assert reading.total_kwh == 7162.62


@pytest.mark.parametrize("candidate_counter", [153, 255, 256, 65535])
def test_candidate_counter_is_not_fixed_header(candidate_counter):
    # Synthetic layout check only: trailing integrity bytes are still unknown.
    pkt = bytearray(bytes.fromhex("909181F091A65F9191A71E919B7C4A909199B65F"))
    pkt[3] = (candidate_counter & 0xFF) ^ 0x91
    pkt[4] = (candidate_counter >> 8) ^ 0x91
    reading = decode(bytes(pkt), expected_id=0)
    assert reading.candidate_recharge_count == candidate_counter
    assert reading.remaining_kwh == 139.67
    assert reading.total_kwh == 7162.51


def test_wrong_id_is_rejected():
    pkt = bytes.fromhex("900881F091A65F9191A711919B7C7B909119D159")
    with pytest.raises(ProtocolError, match="Unexpected txMsgId"):
        decode(pkt, expected_id=0)


def test_post_recharge_wrong_id_is_rejected():
    pkt = bytes.fromhex("909181F391A65F9191D003919A8B3790910F547A")
    with pytest.raises(ProtocolError, match="Unexpected txMsgId"):
        decode(pkt, expected_id=1)


def test_short_or_unknown_header_rejected():
    with pytest.raises(ProtocolError, match="Expected 20 bytes"):
        decode(b"\x90\x91")
    with pytest.raises(ProtocolError, match="header"):
        decode(bytes(20))
