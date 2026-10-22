"""Regression checks for Home Assistant sensor device/state-class compatibility."""

import ast
from pathlib import Path

import pytest

SENSOR_FILE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "yunmu_ble" / "sensor.py"
)


def _sensor_descriptions() -> dict[str, dict[str, str]]:
    """Read declarative descriptions without importing Home Assistant."""
    tree = ast.parse(SENSOR_FILE.read_text(encoding="utf-8"))
    declaration = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SENSORS"
                for target in node.targets)
    )
    descriptions = {}
    for call in declaration.value.elts:
        fields = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        descriptions[ast.literal_eval(fields["key"])] = fields
    return descriptions


@pytest.mark.parametrize(
    ("key", "device_class", "state_class"),
    [
        ("remaining_energy", "SensorDeviceClass.ENERGY", "SensorStateClass.TOTAL"),
        ("total_energy", "SensorDeviceClass.ENERGY", "SensorStateClass.TOTAL_INCREASING"),
        ("estimated_balance", "SensorDeviceClass.MONETARY", "SensorStateClass.TOTAL"),
        ("total_spent", "SensorDeviceClass.MONETARY", "SensorStateClass.TOTAL"),
    ],
)
def test_supported_sensor_state_class(key, device_class, state_class):
    fields = _sensor_descriptions()[key]
    assert fields["device_class"] == device_class
    assert fields["state_class"] == state_class


def test_timestamp_has_no_state_class():
    assert "state_class" not in _sensor_descriptions()["last_read"]
