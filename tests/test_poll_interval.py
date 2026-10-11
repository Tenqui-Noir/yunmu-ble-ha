"""Tests for configuring polling directly on the device page."""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

INTEGRATION_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble"


def load_number(monkeypatch):
    modules = {}
    for name in (
        "homeassistant", "homeassistant.components", "homeassistant.components.number",
        "homeassistant.config_entries", "homeassistant.core", "homeassistant.helpers",
        "homeassistant.helpers.device_registry", "homeassistant.helpers.entity",
        "homeassistant.helpers.entity_platform",
    ):
        module = ModuleType(name)
        modules[name] = module
        monkeypatch.setitem(sys.modules, name, module)
    modules["homeassistant.components.number"].NumberEntity = type("NumberEntity", (), {})
    modules["homeassistant.components.number"].NumberMode = SimpleNamespace(BOX="box")
    modules["homeassistant.config_entries"].ConfigEntry = type("ConfigEntry", (), {})
    modules["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})
    modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    modules["homeassistant.helpers.entity"].EntityCategory = SimpleNamespace(CONFIG="config")
    modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object

    package_name = "_test_yunmu_polling"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)
    for name in ("const", "number"):
        full_name = f"{package_name}.{name}"
        spec = importlib.util.spec_from_file_location(full_name, INTEGRATION_DIR / f"{name}.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, mod)
        spec.loader.exec_module(mod)
    return sys.modules[f"{package_name}.number"]


class MockHass:
    def __init__(self):
        self.changes = []
        self.config_entries = SimpleNamespace(async_update_entry=self.update)

    def update(self, entry, *, options):
        self.changes.append(dict(options))
        entry.options = options


def make_number(number_module, options=None, entity_class=None):
    entry = SimpleNamespace(
        data={"address": "22:08:03:01:4C:54"},
        title="Yunmu test meter",
        options=options or {},
    )
    entity = (entity_class or number_module.YunmuPollInterval)(entry)
    hass = MockHass()
    entity.hass = hass
    return entity, entry, hass


def test_default_poll_interval_and_device_association(monkeypatch):
    module = load_number(monkeypatch)
    entity, _, hass = make_number(module)
    assert entity.native_value == 10
    assert entity._attr_native_min_value == 5
    assert entity._attr_native_max_value == 120
    assert entity._attr_unique_id == "22:08:03:01:4C:54_poll_interval"
    assert entity._attr_device_info["identifiers"] == {
        ("yunmu_ble", "22:08:03:01:4C:54")
    }
    assert hass.changes == []


def test_change_interval_persists_options_and_keeps_other_options(monkeypatch):
    module = load_number(monkeypatch)
    entity, entry, hass = make_number(module, {"poll_interval": 10, "other": True})
    asyncio.run(entity.async_set_native_value(30.0))
    assert hass.changes == [{"poll_interval": 30, "other": True}]
    assert entry.options["poll_interval"] == 30
    assert entity.native_value == 30
    asyncio.run(entity.async_set_native_value(30.0))
    assert len(hass.changes) == 1


@pytest.mark.parametrize("value", [4.0, 121.0, 5.5])
def test_reject_out_of_range_or_fractional_interval(monkeypatch, value):
    module = load_number(monkeypatch)
    entity, _, hass = make_number(module)
    with pytest.raises(ValueError):
        asyncio.run(entity.async_set_native_value(value))
    assert hass.changes == []


def test_change_to_minimum_interval(monkeypatch):
    module = load_number(monkeypatch)
    entity, _, _ = make_number(module)
    asyncio.run(entity.async_set_native_value(5.0))
    assert entity.native_value == 5


def test_low_energy_threshold_is_configurable_on_device_page(monkeypatch):
    module = load_number(monkeypatch)
    entity, entry, hass = make_number(
        module, {"poll_interval": 10, "other": True}, module.YunmuLowEnergyThreshold
    )
    assert entity.native_value == 10
    assert entity._attr_native_min_value == 0
    assert entity._attr_native_max_value == 1000
    assert entity._attr_native_unit_of_measurement == "kWh"
    assert entity._attr_unique_id == "22:08:03:01:4C:54_low_energy_threshold"
    assert entity._attr_entity_category == "config"

    asyncio.run(entity.async_set_native_value(25.0))
    assert entry.options == {
        "poll_interval": 10, "other": True, "low_energy_threshold": 25
    }
    assert entity.native_value == 25
    asyncio.run(entity.async_set_native_value(0.0))
    assert entity.native_value == 0
    assert len(hass.changes) == 2


@pytest.mark.parametrize("value", [-1.0, 1001.0, 2.5])
def test_low_energy_threshold_rejects_invalid_values(monkeypatch, value):
    module = load_number(monkeypatch)
    entity, _, hass = make_number(module, entity_class=module.YunmuLowEnergyThreshold)
    with pytest.raises(ValueError):
        asyncio.run(entity.async_set_native_value(value))
    assert hass.changes == []
