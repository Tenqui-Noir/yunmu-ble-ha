"""Period electricity usage from Home Assistant's existing Recorder statistics.

Recorder handles counter resets and combines hourly and recent 5-minute
statistics. Never write directly to its database or call BLE here.
"""

from datetime import UTC, datetime, timedelta
from math import isfinite

from homeassistant.components.recorder.statistics import statistic_during_period


def period_starts(now: datetime) -> dict[str, datetime]:
    """Find start of local calendar periods, not rolling 24h/7d windows."""
    if now.tzinfo is None:
        raise ValueError("A timezone-aware local datetime is required")
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "daily_usage": midnight,
        "weekly_usage": midnight - timedelta(days=midnight.weekday()),
        "monthly_usage": midnight.replace(day=1),
        "yearly_usage": midnight.replace(month=1, day=1),
    }


def calculate_period_usage(
    hass: object, statistic_id: str, now: datetime
) -> dict[str, float | None]:
    """Retrieve each current period's accumulated change in kWh.

    The results reflect the latest processed Recorder statistics, which may
    trail the most recent BLE poll. Missing or corrupt data is not interpreted
    as zero. Incomplete recorded history gives incomplete period totals.
    """
    end_utc = now.astimezone(UTC)
    results: dict[str, float | None] = {}
    for key, start_local in period_starts(now).items():
        point = statistic_during_period(
            hass,
            start_local.astimezone(UTC),
            end_utc,
            statistic_id,
            {"change"},
            {"energy": "kWh"},
        )
        change = point.get("change")
        if change is None:
            results[key] = None
        else:
            value = float(change)
            results[key] = round(max(0.0, value), 2) if isfinite(value) else None
    return results
