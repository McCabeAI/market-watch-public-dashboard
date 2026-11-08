"""CME 30-day Federal Funds (ZQ) and one-month SOFR (SR1) month-count value.

Contract unit is interest on USD 5,000,000. A one-basis-point index move is
worth ``5_000_000 * 0.0001 * days_in_contract_month / 360``. For a 30-day
month that identity is 41.6666... USD, which the exchange quotes as $41.67.
PnL uses the month's actual calendar length and rounds the lot result to
cents, half up. The quoted $41.67 figure is not applied to 28-, 29-, or
31-day months.

Long the futures profits when the index rises (the implied rate falls).
"""

from __future__ import annotations

from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP

FACE_NOTIONAL_USD = 5_000_000
QUOTED_30_DAY_BP_USD = Decimal("41.67")


def days_in_contract_month(year: int | None, month: int | None) -> int | None:
    if year is None or month is None:
        return None
    if month < 1 or month > 12:
        return None
    return monthrange(int(year), int(month))[1]


def monthly_bp_value_usd(year: int | None, month: int | None) -> dict[str, float | int | None]:
    """Unrounded and cent-quoted USD value of a 0.01 index-point move."""
    days = days_in_contract_month(year, month)
    if days is None:
        return {
            "days": None,
            "unrounded_usd_per_bp": None,
            "quoted_usd_per_bp": None,
        }
    unrounded = Decimal(FACE_NOTIONAL_USD) * Decimal("0.0001") * Decimal(days) / Decimal(360)
    quoted = unrounded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "days": days,
        "unrounded_usd_per_bp": float(unrounded),
        "quoted_usd_per_bp": float(quoted),
    }


def _cents(amount: Decimal) -> float:
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def monthly_index_pnl_usd(
    entry_index: float,
    exit_index: float,
    lots: int,
    side: str,
    *,
    year: int,
    month: int,
) -> float | None:
    """USD PnL from IMM index levels. ``side`` is long or short."""
    if lots < 0:
        return None
    if lots == 0:
        return 0.0
    value = monthly_bp_value_usd(year, month)
    if value["unrounded_usd_per_bp"] is None:
        return None
    per_bp = Decimal(str(value["unrounded_usd_per_bp"]))
    index_move_bp = (Decimal(str(exit_index)) - Decimal(str(entry_index))) * Decimal(100)
    raw = index_move_bp * per_bp * Decimal(int(lots))
    if str(side).lower() == "short":
        raw = -raw
    elif str(side).lower() != "long":
        return None
    return _cents(raw)


def monthly_rate_pnl_usd(
    entry_rate: float,
    exit_rate: float,
    lots: int,
    side: str,
    *,
    year: int,
    month: int,
) -> float | None:
    """USD PnL from implied rates in percentage points (index = 100 - rate)."""
    return monthly_index_pnl_usd(
        100.0 - float(entry_rate),
        100.0 - float(exit_rate),
        lots,
        side,
        year=year,
        month=month,
    )
