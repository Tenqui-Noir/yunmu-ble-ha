"""Offline tests for existing Recorder-based usage aggregation."""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest


def load_analytics(monkeypatch, statistic):
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.recorder",
        "homeassistant.components.recorder.statistics",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["homeassistant.components.recorder.statistics"].statistic_during_period = statistic
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "yunmu_ble"
        / "analytics.py"
    )
    spec = importlib.util.spec_from_file_location("_test_yunmu_analytics", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_period_starts_are_calendar_boundaries(monkeypatch):
    module = load_analytics(monkeypatch, lambda *args: {"change": 1.0})
    tz = timezone(timedelta(hours=8))
    now = datetime(2026, 10, 12, 14, 35, tzinfo=tz)
    starts = module.period_starts(now)
    assert starts["daily_usage"] == datetime(2026, 10, 12, tzinfo=tz)
    assert starts["weekly_usage"] == datetime(2026, 10, 12, tzinfo=tz)
    assert starts["monthly_usage"] == datetime(2026, 10, 1, tzinfo=tz)
    assert starts["yearly_usage"] == datetime(2026, 1, 1, tzinfo=tz)


def test_recorder_change_uses_existing_history_without_ble(monkeypatch):
    calls = []

    def statistic(hass, start, end, statistic_id, types, units):
        calls.append((start, end, statistic_id, types, units))
        return {"change": len(calls) * 1.235}

    module = load_analytics(monkeypatch, statistic)
    now = datetime(2026, 10, 12, 14, 35, tzinfo=timezone(timedelta(hours=8)))
    result = module.calculate_period_usage(object(), "sensor.yunmu_total_energy", now)
    assert result == {
        "daily_usage": 1.24,
        "weekly_usage": 2.47,
        "monthly_usage": 3.71,
        "yearly_usage": 4.94,
    }
    assert len(calls) == 4
    assert all(call[2] == "sensor.yunmu_total_energy" for call in calls)
    assert all(call[3] == {"change"} for call in calls)
    assert all(call[4] == {"energy": "kWh"} for call in calls)
    assert all(call[0].tzinfo == UTC for call in calls)


def test_missing_statistics_are_unknown_not_zero(monkeypatch):
    module = load_analytics(monkeypatch, lambda *args: {"change": None})
    now = datetime(2026, 10, 12, tzinfo=UTC)
    result = module.calculate_period_usage(object(), "sensor.energy", now)
    assert all(value is None for value in result.values())


@pytest.mark.parametrize("change,expected", [(-2.0, 0.0), (float("nan"), None)])
def test_bad_statistics_never_show_negative_or_nan(monkeypatch, change, expected):
    module = load_analytics(monkeypatch, lambda *args: {"change": change})
    now = datetime(2026, 10, 12, tzinfo=UTC)
    result = module.calculate_period_usage(object(), "sensor.energy", now)
    assert all(value == expected for value in result.values())
