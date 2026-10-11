"""Offline transport behavior tests: BLE subscription, one write, cleanup."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble"
SUCCESS_RESPONSE = bytes.fromhex("909181F091A65F9191A71B919B7C7190919FBC46")


def load_transport(monkeypatch, client):
    """Load the transport with fake Bleak imports, never load Home Assistant."""
    fake_bleak = ModuleType("bleak")
    fake_bleak.BleakClient = type("BleakClient", (), {})
    fake_backends = ModuleType("bleak.backends")
    fake_device = ModuleType("bleak.backends.device")
    fake_device.BLEDevice = type("BLEDevice", (), {})
    fake_connector = ModuleType("bleak_retry_connector")

    async def connect(*args, **kwargs):
        assert kwargs["max_attempts"] == 1
        return client

    fake_connector.establish_connection = connect
    for name, mod in (
        ("bleak", fake_bleak),
        ("bleak.backends", fake_backends),
        ("bleak.backends.device", fake_device),
        ("bleak_retry_connector", fake_connector),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    package_name = "_test_yunmu_ble"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)

    def load_file(name):
        full_name = f"{package_name}.{name}"
        spec = importlib.util.spec_from_file_location(full_name, INTEGRATION_DIR / f"{name}.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, mod)
        spec.loader.exec_module(mod)
        return mod

    load_file("const")
    load_file("protocol")
    return load_file("transport")


class FakeClient:
    def __init__(self, send_notify=True):
        self.is_connected = True
        self.send_notify = send_notify
        self.events = []
        self.callback = None

    async def start_notify(self, uuid, callback):
        self.events.append("start_notify")
        self.callback = callback

    async def write_gatt_char(self, uuid, data, response):
        self.events.append(("write", bytes(data), response))
        if self.send_notify:
            self.callback(None, bytearray(SUCCESS_RESPONSE))

    async def stop_notify(self, uuid):
        self.events.append("stop_notify")

    async def disconnect(self):
        self.events.append("disconnect")
        self.is_connected = False


def test_subscribe_then_one_read_then_disconnect(monkeypatch):
    client = FakeClient()
    transport = load_transport(monkeypatch, client)
    reading = asyncio.run(
        transport.read_meter(SimpleNamespace(address="22:08:03:01:4C:54"), 0)
    )
    assert reading.remaining_kwh == 139.62
    assert client.events == [
        "start_notify",
        ("write", bytes.fromhex("D4D5D5C4DD"), False),
        "stop_notify",
        "disconnect",
    ]


def test_timeout_does_not_retry_write_and_disconnects(monkeypatch):
    client = FakeClient(send_notify=False)
    transport = load_transport(monkeypatch, client)
    monkeypatch.setattr(transport, "RESPONSE_TIMEOUT", 0.01)
    with pytest.raises(transport.YunmuBLEError, match="Notify"):
        asyncio.run(
            transport.read_meter(SimpleNamespace(address="22:08:03:01:4C:54"), 0)
        )
    assert sum(isinstance(x, tuple) and x[0] == "write" for x in client.events) == 1
    assert client.events[-2:] == ["stop_notify", "disconnect"]
