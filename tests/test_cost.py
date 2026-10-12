"""Tests for monetary estimate tracking across recharges and price changes."""

import importlib.util
import sys
from pathlib import Path

import pytest

PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble" / "cost.py"
)
spec = importlib.util.spec_from_file_location("_test_yunmu_cost", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ConsumptionCostLedger = module.ConsumptionCostLedger


def test_recharge_changes_no_cost_when_cumulative_consumption_is_constant():
    ledger = ConsumptionCostLedger(0.7)
    ledger.observe(7000.0)
    original = ledger.value
    ledger.observe(7000.0)  # In reality, remaining balance may jump after recharge.
    assert ledger.value == original
    ledger.observe(7003.0)
    assert ledger.value == pytest.approx(original + 2.1)


def test_price_change_preserves_spending_and_counts_new_usage_at_new_rate():
    first = ConsumptionCostLedger(0.7)
    first.observe(7000.0)
    first.observe(7002.0)
    saved = first.snapshot()

    updated = ConsumptionCostLedger(0.9)
    updated.restore(saved)
    assert updated.value == pytest.approx(4901.4)
    updated.observe(7004.0)
    assert updated.value == pytest.approx(4903.2)
    assert updated.snapshot()["last_total_kwh"] == "7004.0"


def test_persisted_cost_keeps_sub_cent_precision_across_small_reads():
    ledger = ConsumptionCostLedger(0.7)
    ledger.observe(1.0)
    for reading in (1.01, 1.02, 1.03):
        ledger.observe(reading)
    assert ledger.snapshot()["total_cost_cny"] == "0.721"
    restored = ConsumptionCostLedger(0.7)
    restored.restore(ledger.snapshot())
    restored.observe(1.04)
    assert restored.snapshot()["total_cost_cny"] == "0.728"


def test_counter_reset_keeps_spending_instead_of_going_backwards():
    ledger = ConsumptionCostLedger(0.7)
    ledger.observe(7000)
    ledger.observe(7002)
    old_cost = ledger.value
    ledger.observe(1)
    assert ledger.value == old_cost
    ledger.observe(3)
    assert ledger.value == pytest.approx(old_cost + 1.4)


@pytest.mark.parametrize(
    "value", [-1, float("nan"), float("inf"), "invalid"]
)
def test_invalid_values_do_not_change_last_checkpoint(value):
    ledger = ConsumptionCostLedger(0.7)
    ledger.observe(10.0)
    saved = ledger.snapshot()
    with pytest.raises(ValueError):
        ledger.observe(value)
    assert ledger.snapshot() == saved


def test_invalid_saved_state_is_ignored():
    ledger = ConsumptionCostLedger(0.7)
    ledger.restore({"last_total_kwh": "NaN", "total_cost_cny": "2"})
    assert ledger.value is None
