"""Multi-horizon HOT / NEUTRAL / COLD. There is no single-month HOT cutoff."""

from __future__ import annotations

from decimal import Decimal

DEADBAND_ANNUALIZED_PP = Decimal("0.05")
TARGET_ANNUALIZED = Decimal("2")


def _sign(delta: Decimal) -> int:
    if delta > DEADBAND_ANNUALIZED_PP:
        return 1
    if delta < -DEADBAND_ANNUALIZED_PP:
        return -1
    return 0


def classify_momentum(deltas: dict[int, Decimal], post_3m: Decimal) -> str:
    """Classify from 3/6/9 deltas versus the pre-release windows.

    HOT requires the 3-month and at least one other horizon to accelerate,
    with the post 3-month rate above 2%. A lone 0.28% month is not HOT when
    the 6- and 9-month moves stay inside the deadband. COLD requires at least
    two horizons to decelerate and the 3-month window itself not to accelerate.
    """
    signs = {months: _sign(deltas[months]) for months in (3, 6, 9)}
    up = sum(1 for value in signs.values() if value == 1)
    down = sum(1 for value in signs.values() if value == -1)
    if up >= 2 and signs[3] == 1 and post_3m > TARGET_ANNUALIZED:
        return "HOT"
    if down >= 2 and signs[3] != 1:
        return "COLD"
    return "NEUTRAL"
