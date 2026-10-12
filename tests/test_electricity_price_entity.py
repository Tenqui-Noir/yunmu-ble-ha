"""Tests for the device-level electricity price configuration entity."""

import asyncio
import importlib.util
import math
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

    package_name = "_test_yunmu_price"
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


def make_entry(price=None):
    options = {"poll_interval": 10, "low_energy_threshold": 30}
    if price is not None:
        options["electricity_price"] = price
    return SimpleNamespace(
        data={"address": "22:08:03:01:4C:54"},
        title="Yunmu test meter",
        options=options,
    )


def test_price_is_registered_on_device_page(monkeypatch):
    mod = load_number(monkeypatch)
    entry = make_entry()
    entities = []
    asyncio.run(mod.async_setup_entry(None, entry, entities.extend))
    assert len(entities) == 3
    price = next(entity for entity in entities if isinstance(entity, mod.YunmuElectricityPrice))
    assert price.native_value == 0.7
    assert price._attr_entity_category == "config"
    assert price._attr_unique_id == "22:08:03:01:4C:54_electricity_price"
    assert price._attr_device_info["identifiers"] == {
        ("yunmu_ble", "22:08:03:01:4C:54")
    }
    assert price._attr_native_unit_of_measurement == "CNY/kWh"
    assert price._attr_native_min_value == 0
    assert price._attr_native_max_value == 10


def test_existing_price_persists_and_other_options_remain(monkeypatch):
    mod = load_number(monkeypatch)
    entry = make_entry(0.93)
    changes = []

    def update(e, *, options):
        changes.append(options)
        e.options = options

    price = mod.YunmuElectricityPrice(entry)
    price.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update))
    assert price.native_value == 0.93
    asyncio.run(price.async_set_native_value(0.815))
    assert entry.options == {
        "poll_interval": 10,
        "low_energy_threshold": 30,
        "electricity_price": 0.815,
    }
    asyncio.run(price.async_set_native_value(0.815))
    assert len(changes) == 1


@pytest.mark.parametrize("invalid", [-0.01, 10.001, math.nan, math.inf, -math.inf])
def test_reject_invalid_electricity_price(monkeypatch, invalid):
    mod = load_number(monkeypatch)
    price = mod.YunmuElectricityPrice(make_entry())
    price.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=None))
    with pytest.raises(ValueError):
        asyncio.run(price.async_set_native_value(invalid))


def test_integration_dialog_excludes_price_without_discarding_saved_value(monkeypatch):
    """The old options dialog must not silently revert the device-level price."""
    for name in (
        "homeassistant", "homeassistant.config_entries", "homeassistant.components",
        "homeassistant.components.bluetooth", "homeassistant.const",
        "homeassistant.data_entry_flow", "voluptuous",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))

    ha_entries = sys.modules["homeassistant.config_entries"]

    class FakeConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    class FakeOptionsFlow:
        def async_create_entry(self, **kwargs):
            return kwargs

        def async_show_form(self, **kwargs):
            return kwargs

    ha_entries.ConfigFlow = FakeConfigFlow
    ha_entries.OptionsFlow = FakeOptionsFlow
    ha_entries.ConfigEntry = object
    sys.modules["homeassistant"].config_entries = ha_entries
    sys.modules["homeassistant.const"].CONF_ADDRESS = "address"
    sys.modules["homeassistant.data_entry_flow"].FlowResult = dict
    vol = sys.modules["voluptuous"]
    vol.Required = lambda key, **kwargs: key
    vol.All = lambda *args: args
    vol.Coerce = lambda kind: kind
    vol.Range = lambda **kwargs: kwargs
    vol.Schema = lambda schema: schema

    package_name = "_test_yunmu_price_options"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION_DIR)]
    monkeypatch.setitem(sys.modules, package_name, package)
    for name in ("const", "config_flow"):
        full_name = f"{package_name}.{name}"
        spec = importlib.util.spec_from_file_location(full_name, INTEGRATION_DIR / f"{name}.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, full_name, mod)
        spec.loader.exec_module(mod)

    flow_class = sys.modules[f"{package_name}.config_flow"].YunmuOptionsFlow
    flow = flow_class(make_entry(0.93))
    form = asyncio.run(flow.async_step_init())
    assert "electricity_price" not in form["data_schema"]
    assert set(form["data_schema"]) == {"poll_interval", "low_energy_threshold"}

    result = asyncio.run(
        flow.async_step_init({"poll_interval": 20, "low_energy_threshold": 40})
    )
    assert result["data"] == {
        "poll_interval": 20,
        "low_energy_threshold": 40,
        "electricity_price": 0.93,
    }
