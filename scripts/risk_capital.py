"""Trusted shocked-risk capital used for sizing and funding.

Risk capital is the absolute paper MTM loss from a 1% adverse move in the
quoted risk factor.  Rates marks are quoted in percentage points, curves/RV in
basis points, and spot/options in relative price terms.  A one-basis-point
minimum shock prevents a near-zero rate/spread mark from manufacturing zero
risk capital.
"""

from __future__ import annotations

from typing import Any, Mapping

SHOCK_FRACTION = 0.01
RATE_MIN_SHOCK_MARK = 0.01  # 1bp when rates are stored in percentage points.
CURVE_MIN_SHOCK_BP = 1.0    # 1bp when curve/RV marks are stored in basis points.
RISK_CAPITAL_METHOD = "mtm_1pct_relative_shock"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def risk_factor_mark(position: Mapping[str, Any]) -> float | None:
    """Use the current deterministic mark, falling back to entry only if needed."""
    mark = _number(position.get("mark_price"))
    if mark is not None:
        return mark
    return _number(position.get("entry_price"))


def position_risk_capital(position: Mapping[str, Any]) -> float | None:
    """Absolute P&L from a 1% adverse move in the position's quoted risk factor."""
    notional = _number(position.get("notional_usd"))
    if notional is None:
        return None
    notional = abs(notional)
    if notional == 0:
        return 0.0

    asset = str(position.get("asset_class") or "")
    if asset in {"spot_fx", "options"}:
        return round(notional * SHOCK_FRACTION, 2)

    mark = risk_factor_mark(position)
    if mark is None:
        return None

    if asset == "rates":
        shock_mark = max(abs(mark) * SHOCK_FRACTION, RATE_MIN_SHOCK_MARK)
        return round(notional * shock_mark / 100.0, 2)

    if asset in {"curve", "rates_rv"}:
        shock_bp = max(abs(mark) * SHOCK_FRACTION, CURVE_MIN_SHOCK_BP)
        return round(notional * shock_bp / 10_000.0, 2)

    return None


def attach_position_risk(position: dict[str, Any]) -> dict[str, Any]:
    capital = position_risk_capital(position)
    position["risk_capital_usd"] = capital
    position["risk_capital_method"] = RISK_CAPITAL_METHOD
    position["risk_shock_fraction"] = SHOCK_FRACTION
    position["risk_capital_unavailable"] = capital is None
    return position


def book_risk_capital(book: Mapping[str, Any]) -> dict[str, Any]:
    total = 0.0
    unavailable: list[str] = []
    for position in book.get("positions") or []:
        capital = position_risk_capital(position)
        if capital is None:
            unavailable.append(str(position.get("position_id") or position.get("instrument") or "unknown"))
            continue
        total += capital
    return {
        "risk_capital_usd": round(total, 2),
        "risk_capital_method": RISK_CAPITAL_METHOD,
        "risk_shock_fraction": SHOCK_FRACTION,
        "risk_capital_unavailable_positions": unavailable,
        "risk_capital_status": "unavailable" if unavailable else "ok",
    }
