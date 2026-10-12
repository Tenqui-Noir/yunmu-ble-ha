"""Track estimated electricity spending without repricing earlier usage.

Stored values are decimal strings so repeated small meter deltas do not
accumulate rounding errors. This is derived bookkeeping, never a meter write.
"""

from decimal import Decimal, InvalidOperation


class ConsumptionCostLedger:
    """Estimated meter-lifetime cost with fixed historical price segments."""

    def __init__(self, unit_price: float) -> None:
        self.price = Decimal(str(unit_price))
        self.last_total: Decimal | None = None
        self.total_cost: Decimal | None = None

    @staticmethod
    def _nonnegative_decimal(value: object) -> Decimal:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise ValueError("Invalid energy or monetary value") from err
        if not number.is_finite() or number < 0:
            raise ValueError("Energy and cost must be finite nonnegative numbers")
        return number

    def restore(self, data: object) -> None:
        """Load previously persisted baseline, ignoring malformed state."""
        if not isinstance(data, dict):
            return
        try:
            last_total = self._nonnegative_decimal(data["last_total_kwh"])
            total_cost = self._nonnegative_decimal(data["total_cost_cny"])
        except (KeyError, ValueError):
            return
        self.last_total = last_total
        self.total_cost = total_cost

    def observe(self, total_kwh: float) -> None:
        """Advance only by consumption delta, unaffected by prepaid recharge."""
        current = self._nonnegative_decimal(total_kwh)
        if self.last_total is None or self.total_cost is None:
            # First reading gives a meter-lifetime estimate as a baseline;
            # Home Assistant's total_increasing stats track future deltas.
            self.total_cost = current * self.price
        elif current >= self.last_total:
            self.total_cost += (current - self.last_total) * self.price
        # If the meter counter resets/decreases, keep the previous cost and
        # use the new counter as baseline; do not invent a consumption amount.
        self.last_total = current

    @property
    def value(self) -> float | None:
        """Rounded display value; full precision is kept in persistent storage."""
        return None if self.total_cost is None else round(float(self.total_cost), 2)

    def snapshot(self) -> dict[str, str] | None:
        """Serialize the latest successful checkpoint for HA Store."""
        if self.last_total is None or self.total_cost is None:
            return None
        return {
            "last_total_kwh": str(self.last_total),
            "total_cost_cny": str(self.total_cost),
        }
