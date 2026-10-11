"""Offline manual-read button tests without a Home Assistant installation."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble"


def load_manual_modules(monkeypatch):
    """Stub the Home Assistant imports to exercise manual-read behavior."""
    names = [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.bluetooth",
        "homeassistant.components.button",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
        "bleak",
        "bleak.exc",
    ]
    modules = {}
    for name in names:
        module = ModuleType(name)
        modules[name] = module
        monkeypatch.setitem(sys.modules, name, module)

    class DummyDataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

    class HomeAssistantError(Exception):
        pass

    modules["homeassistant.components.button"].ButtonEntity = type("ButtonEntity", (), {})
    modules["homeassistant.config_entries"].ConfigEntry = type("ConfigEntry", (), {})
    modules["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})
    modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = (
        DummyDataUpdateCoordinator
    )
    modules["homeassistant.helpers.update_coordinator"].UpdateFailed = type(
        "UpdateFailed", (Exception,), {}
    )
    modules["bleak.exc"].BleakError = type("BleakError", (Exception,), {})

    package_name = "_test_yunmu_manual"
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
    transport_stub = ModuleType(f"{package_name}.transport")
    transport_stub.YunmuBLEError = type("YunmuBLEError", (Exception,), {})
    transport_stub.read_meter = lambda *args: None
    monkeypatch.setitem(sys.modules, transport_stub.__name__, transport_stub)
    coordinator = load_file("coordinator")
    button = load_file("button")
    return coordinator, button, HomeAssistantError


def make_coordinator(coordinator_class):
    coordinator = coordinator_class.__new__(coordinator_class)
    coordinator.address = "22:08:03:01:4C:54"
    coordinator._manual_lock = asyncio.Lock()
    coordinator._last_manual_attempt = None
    coordinator._read_in_progress = False
    coordinator.last_update_success = True
    coordinator.refresh_count = 0

    async def async_refresh():
        coordinator.refresh_count += 1

    coordinator.async_refresh = async_refresh
    return coordinator


def test_button_press_dispatches_single_manual_read(monkeypatch):
    coordinator_module, button_module, _ = load_manual_modules(monkeypatch)
    coordinator = make_coordinator(coordinator_module.YunmuCoordinator)
    button = button_module.YunmuReadButton(coordinator, SimpleNamespace(title="My meter"))
    asyncio.run(button.async_press())
    assert coordinator.refresh_count == 1
    assert button._attr_unique_id == "22:08:03:01:4C:54_read_now"
    assert button._attr_translation_key == "read_now"
    assert button._attr_device_info["identifiers"] == {
        ("yunmu_ble", "22:08:03:01:4C:54")
    }


def test_manual_read_cooldown_blocks_immediate_repeated_click(monkeypatch):
    coordinator_module, _, home_assistant_error = load_manual_modules(monkeypatch)
    coordinator = make_coordinator(coordinator_module.YunmuCoordinator)

    async def check():
        await coordinator.async_manual_read()
        with pytest.raises(home_assistant_error, match="5 seconds"):
            await coordinator.async_manual_read()

    asyncio.run(check())
    assert coordinator.refresh_count == 1


def test_manual_read_rejects_while_a_poll_is_in_progress(monkeypatch):
    coordinator_module, _, home_assistant_error = load_manual_modules(monkeypatch)
    coordinator = make_coordinator(coordinator_module.YunmuCoordinator)
    coordinator._read_in_progress = True

    with pytest.raises(home_assistant_error, match="already in progress"):
        asyncio.run(coordinator.async_manual_read())
    assert coordinator.refresh_count == 0


def test_failed_manual_refresh_is_reported(monkeypatch):
    coordinator_module, _, home_assistant_error = load_manual_modules(monkeypatch)
    coordinator = make_coordinator(coordinator_module.YunmuCoordinator)

    async def fail_refresh():
        coordinator.refresh_count += 1
        coordinator.last_update_success = False

    coordinator.async_refresh = fail_refresh
    with pytest.raises(home_assistant_error, match="read failed"):
        asyncio.run(coordinator.async_manual_read())
    assert coordinator.refresh_count == 1

def test_manual_read_allows_next_attempt_after_five_seconds(monkeypatch):
    coordinator_module, _, home_assistant_error = load_manual_modules(monkeypatch)
    coordinator = make_coordinator(coordinator_module.YunmuCoordinator)
    clock = [100.0]
    monkeypatch.setattr(coordinator_module, "monotonic", lambda: clock[0])

    async def check():
        await coordinator.async_manual_read()
        clock[0] += 4.99
        with pytest.raises(home_assistant_error, match="5 seconds"):
            await coordinator.async_manual_read()
        clock[0] += 0.01
        await coordinator.async_manual_read()

    asyncio.run(check())
    assert coordinator.refresh_count == 2
