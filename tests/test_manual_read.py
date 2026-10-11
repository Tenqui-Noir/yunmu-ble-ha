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
        "homeassistant.components.persistent_notification",
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
    modules["homeassistant.components.persistent_notification"].async_create = (
        lambda *args, **kwargs: None
    )
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


def make_polling_coordinator(coordinator_class):
    """Construct a coordinator with a previously successful meter reading."""
    coordinator = coordinator_class.__new__(coordinator_class)
    coordinator.hass = object()
    coordinator.address = "22:08:03:01:4C:54"
    coordinator.data = SimpleNamespace(remaining_kwh=139.0, total_kwh=7163.0)
    coordinator.last_success = "last successful time"
    coordinator._last_successful_id = None
    coordinator._next_tx_msg_id = 0
    coordinator._consecutive_failures = 0
    coordinator._failure_notification_sent = False
    coordinator._low_energy_threshold = 10
    coordinator._low_energy_notified = False
    coordinator._read_in_progress = False
    return coordinator


def test_three_failures_notify_once_without_replacing_old_reading(monkeypatch):
    coordinator_module, _, _ = load_manual_modules(monkeypatch)
    coordinator = make_polling_coordinator(coordinator_module.YunmuCoordinator)
    original_reading = coordinator.data
    alerts = []

    monkeypatch.setattr(
        coordinator_module.bluetooth,
        "async_ble_device_from_address",
        lambda *args, **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module.persistent_notification,
        "async_create",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    async def fail_four_times():
        for _ in range(4):
            with pytest.raises(coordinator_module.UpdateFailed, match="not in range"):
                await coordinator._async_update_data()

    asyncio.run(fail_four_times())
    assert coordinator._consecutive_failures == 4
    assert coordinator.data is original_reading
    assert coordinator.last_success == "last successful time"
    assert len(alerts) == 1
    assert alerts[0][0][0] is coordinator.hass
    assert "连续 3 次" in alerts[0][0][1]
    assert "read_failure_220803014c54" in alerts[0][1]["notification_id"]
    assert not coordinator._read_in_progress


def test_success_resets_failure_counter_for_a_new_notification(monkeypatch):
    coordinator_module, _, _ = load_manual_modules(monkeypatch)
    coordinator = make_polling_coordinator(coordinator_module.YunmuCoordinator)
    alerts = []
    state = {"should_fail": True}

    monkeypatch.setattr(
        coordinator_module.bluetooth,
        "async_ble_device_from_address",
        lambda *args, **kwargs: SimpleNamespace(address=coordinator.address),
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module.persistent_notification,
        "async_create",
        lambda *args, **kwargs: alerts.append(kwargs),
    )

    async def fake_read_meter(device, msg_id):
        if state["should_fail"]:
            raise coordinator_module.YunmuBLEError("BLE timeout")
        return SimpleNamespace(remaining_kwh=138.9, total_kwh=7163.1)

    monkeypatch.setattr(coordinator_module, "read_meter", fake_read_meter)

    async def check():
        for _ in range(3):
            with pytest.raises(coordinator_module.UpdateFailed, match="BLE timeout"):
                await coordinator._async_update_data()
        assert len(alerts) == 1

        state["should_fail"] = False
        new_reading = await coordinator._async_update_data()
        assert new_reading.remaining_kwh == 138.9
        assert coordinator._consecutive_failures == 0
        assert not coordinator._failure_notification_sent

        state["should_fail"] = True
        for _ in range(3):
            with pytest.raises(coordinator_module.UpdateFailed, match="BLE timeout"):
                await coordinator._async_update_data()
        assert len(alerts) == 2

    asyncio.run(check())
    assert coordinator._consecutive_failures == 3
    assert not coordinator._read_in_progress


def test_low_energy_alert_once_until_a_reading_recovers(monkeypatch):
    coordinator_module, _, _ = load_manual_modules(monkeypatch)
    coordinator = make_polling_coordinator(coordinator_module.YunmuCoordinator)
    notifications = []
    energy = {"remaining": 11.0}

    monkeypatch.setattr(
        coordinator_module.bluetooth,
        "async_ble_device_from_address",
        lambda *args, **kwargs: SimpleNamespace(address=coordinator.address),
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module.persistent_notification,
        "async_create",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )

    async def read(device, msg_id):
        return SimpleNamespace(remaining_kwh=energy["remaining"], total_kwh=7163.0)

    monkeypatch.setattr(coordinator_module, "read_meter", read)

    async def check():
        await coordinator._async_update_data()
        assert notifications == []
        energy["remaining"] = 10.0  # Exactly at threshold triggers a notice.
        await coordinator._async_update_data()
        assert len(notifications) == 1
        assert "10.00 kWh" in notifications[0][0][1]
        assert "low_energy_220803014c54" in notifications[0][1]["notification_id"]
        energy["remaining"] = 6.0
        await coordinator._async_update_data()
        assert len(notifications) == 1
        energy["remaining"] = 12.0
        await coordinator._async_update_data()
        assert not coordinator._low_energy_notified
        energy["remaining"] = 9.0
        await coordinator._async_update_data()
        assert len(notifications) == 2

    asyncio.run(check())


def test_low_energy_alert_disabled_and_never_triggered_by_failure(monkeypatch):
    coordinator_module, _, _ = load_manual_modules(monkeypatch)
    coordinator = make_polling_coordinator(coordinator_module.YunmuCoordinator)
    notifications = []
    available = {"value": False}

    monkeypatch.setattr(
        coordinator_module.bluetooth,
        "async_ble_device_from_address",
        lambda *args, **kwargs: (
            SimpleNamespace(address=coordinator.address) if available["value"] else None
        ),
        raising=False,
    )
    monkeypatch.setattr(
        coordinator_module.persistent_notification,
        "async_create",
        lambda *args, **kwargs: notifications.append(kwargs),
    )

    async def read(device, msg_id):
        return SimpleNamespace(remaining_kwh=0.0, total_kwh=7163.0)

    monkeypatch.setattr(coordinator_module, "read_meter", read)

    async def check():
        with pytest.raises(coordinator_module.UpdateFailed):
            await coordinator._async_update_data()
        assert not notifications

        available["value"] = True
        coordinator._low_energy_threshold = 0
        await coordinator._async_update_data()
        assert not notifications
        coordinator._low_energy_threshold = 10
        await coordinator._async_update_data()
        assert len(notifications) == 1

    asyncio.run(check())
