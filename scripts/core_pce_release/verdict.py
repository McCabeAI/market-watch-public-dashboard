"""Multi-horizon HOT / NEUTRAL / COLD (nowcast_repair_v1)."""

from __future__ import annotations

from decimal import Decimal

TARGET_ANNUALIZED = Decimal("2")


def classify_momentum(deltas: dict[int, Decimal], post_3m: Decimal | None = None) -> str:
    """HOT when 3- and 6-month deltas are strictly positive; COLD when both negative."""
    d3 = deltas[3]
    d6 = deltas[6]
    if d3 > 0 and d6 > 0:
        return "HOT"
    if d3 < 0 and d6 < 0:
        return "COLD"
    return "NEUTRAL"


def nine_month_direction(delta_9: Decimal) -> str:
    if delta_9 > 0:
        return "accelerating"
    if delta_9 < 0:
        return "decelerating"
    return "unchanged"


def gap_to_two(post_rates: dict[int, Decimal]) -> dict[int, Decimal]:
    two = Decimal("2")
    return {months: post_rates[months] - two for months in (3, 6, 9)}
