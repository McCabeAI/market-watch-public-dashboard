"""Scenario contribution bounds and classification sensitivity."""

from __future__ import annotations

from decimal import Decimal


def scenario_bounds(rows: list[dict]) -> dict:
    central = Decimal(0)
    low = Decimal(0)
    high = Decimal(0)
    for row in rows:
        weight = Decimal(row["weight_share"])
        central += weight * Decimal(row["mom_percent"])
        low += weight * Decimal(row["low_mom_percent"])
        high += weight * Decimal(row["high_mom_percent"])
    return {
        "central_mom_percent": format(central, "f"),
        "low_mom_percent": format(low, "f"),
        "high_mom_percent": format(high, "f"),
    }


def classification_sensitive(central: str, low: str, high: str) -> bool:
    return not (central == low == high)
