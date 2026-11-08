"""ASX 90 Day Bank Bill (IR) cash-settled futures valuation.

Price in AUD is the discounted bill formula from the ASX contract spec; yield
is implied rate percent (100 minus the futures index). Settlements may quote the
index to three decimals (e.g. 95.050); valuation keeps that precision on yield.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

_FACE_AUD = Decimal("1000000")
_YEAR_DAYS = Decimal("365")
_BILL_DAYS = Decimal("90")
_CENT = Decimal("0.01")
_ONE_BP = Decimal("0.01")


def _as_decimal(yield_percent: float | Decimal | str) -> Decimal:
    if isinstance(yield_percent, Decimal):
        return yield_percent
    if isinstance(yield_percent, float):
        return Decimal(str(yield_percent))
    return Decimal(str(yield_percent))


def yield_from_index(futures_index: float | Decimal | str) -> Decimal:
    """Implied annual yield percent = 100 minus the futures index.

    Prefer ``str`` or ``Decimal`` inputs so values such as ``95.050`` map to
    ``Decimal('4.950')`` exactly. A short-decimal ``float`` is accepted via
    ``Decimal(str(futures_index))`` only.
    """
    if isinstance(futures_index, Decimal):
        index = futures_index
    elif isinstance(futures_index, float):
        index = Decimal(str(futures_index))
    else:
        index = Decimal(str(futures_index))
    return Decimal("100") - index


def contract_value_aud_unrounded(yield_percent: float | Decimal | str) -> Decimal:
    """Contract AUD value before cent rounding."""
    y = _as_decimal(yield_percent)
    denom = _YEAR_DAYS + y * _BILL_DAYS / Decimal("100")
    return _FACE_AUD * _YEAR_DAYS / denom


def contract_value_aud(yield_percent: float | Decimal | str) -> Decimal:
    """Cent-rounded contract value (ROUND_HALF_UP)."""
    return contract_value_aud_unrounded(yield_percent).quantize(_CENT, rounding=ROUND_HALF_UP)


def _analytic_dp_per_yield_percent(yield_percent: Decimal) -> Decimal:
    y = _as_decimal(yield_percent)
    inner = _YEAR_DAYS + Decimal("0.9") * y
    return -_FACE_AUD * _YEAR_DAYS * Decimal("0.9") / (inner * inner)


def variable_bp_value_aud(yield_percent: float | Decimal | str) -> dict[str, Any]:
    """1bp (0.01 yield percent) convexity-aware tick metrics at ``yield_percent``."""
    y = _as_decimal(yield_percent)
    value = contract_value_aud(y)
    y_down = y - _ONE_BP
    y_up = y + _ONE_BP
    value_down = contract_value_aud(y_down)
    value_up = contract_value_aud(y_up)
    long_down = value_down - value
    long_up = value_up - value
    analytic = -_analytic_dp_per_yield_percent(y) * _ONE_BP
    return {
        "yield_percent": float(y),
        "contract_value_aud": value,
        "value_yield_minus_1bp": value_down,
        "value_yield_plus_1bp": value_up,
        "long_pnl_yield_down_1bp_aud": long_down,
        "long_pnl_yield_up_1bp_aud": long_up,
        "analytic_dp_per_bp_aud": analytic,
        "convexity_note": (
            "Realized 1bp P&L uses cent-rounded prices; equal up/down tick P&L after "
            "rounding does not imply zero convexity on multi-bp moves."
        ),
    }


def ir_pnl_aud(
    entry_yield: float | Decimal | str,
    mark_yield: float | Decimal | str,
    contracts: int,
    side: str,
) -> Decimal:
    """Realized AUD P&L from rounded contract values only."""
    if contracts < 0:
        raise ValueError("contracts must be non-negative")
    if contracts == 0:
        return Decimal("0")
    entry_v = contract_value_aud(entry_yield)
    mark_v = contract_value_aud(mark_yield)
    delta = mark_v - entry_v
    if side == "long":
        return delta * contracts
    if side == "short":
        return -delta * contracts
    raise ValueError(f"side must be long or short, not {side!r}")


def ir_pnl_usd(
    entry_yield: float | Decimal | str,
    mark_yield: float | Decimal | str,
    contracts: int,
    side: str,
    fx_usd_per_unit: Decimal | float,
) -> Decimal:
    """AUD P&L converted with AUDUSD (USD per 1 AUD)."""
    aud = ir_pnl_aud(entry_yield, mark_yield, contracts, side)
    fx = fx_usd_per_unit if isinstance(fx_usd_per_unit, Decimal) else Decimal(str(fx_usd_per_unit))
    return (aud * fx).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
