"""Trusted shocked-risk capital used for sizing and funding.

Risk capital is the absolute paper MTM loss from the agreed standard shock:
- spot FX: 1% adverse price move;
- outright rates: 1 percentage-point / 100bp adverse rate move;
- curve and rates-RV: 100bp adverse spread move.

That is deliberately a common risk unit. Equal shocked P&L receives equal SOFR
funding treatment regardless of asset class. Notional itself is descriptive.
"""

from __future__ import annotations

from typing import Any, Mapping

SPOT_SHOCK_FRACTION = 0.01
RATE_SHOCK_PERCENTAGE_POINTS = 1.0
CURVE_SHOCK_BPS = 100.0
RISK_CAPITAL_METHOD = "mtm_standard_1pct_move"


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
    mark = _number(position.get("mark_price"))
    if mark is not None:
        return mark
    return _number(position.get("entry_price"))


def position_risk_capital(position: Mapping[str, Any]) -> float | None:
    """Absolute P&L from the standard 1%/100bp adverse move."""
    notional = _number(position.get("notional_usd"))
    if notional is None:
        return None
    notional = abs(notional)
    if notional == 0:
        return 0.0

    asset = str(position.get("asset_class") or "")
    if asset == "spot_fx":
        return round(notional * SPOT_SHOCK_FRACTION, 2)
    if asset == "rates":
        return round(notional * RATE_SHOCK_PERCENTAGE_POINTS / 100.0, 2)
    if asset in {"curve", "rates_rv"}:
        return round(notional * CURVE_SHOCK_BPS / 10_000.0, 2)
    if asset == "options":
        # Options need an actual deterministic shocked MTM rather than a notional proxy.
        explicit = _number(position.get("shock_1pct_pnl_usd"))
        return None if explicit is None else round(abs(explicit), 2)
    return None


def position_can_force_exit(position: Mapping[str, Any]) -> bool:
    """True when trusted code can flatten without inventing a price."""
    return _number(position.get("mark_price")) is not None and _number(position.get("entry_price")) is not None


def partition_force_exit_positions(
    positions: list[Mapping[str, Any]] | None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    markable: list[Mapping[str, Any]] = []
    blocked: list[Mapping[str, Any]] = []
    for position in positions or []:
        if position_can_force_exit(position):
            markable.append(position)
        else:
            blocked.append(position)
    return markable, blocked


def already_force_flattened_ids(book: Mapping[str, Any]) -> set[str]:
    """Position ids recorded on prior RISK_STOP flatten events."""
    ids: set[str] = set()
    for row in book.get("history") or []:
        if row.get("action") != "RISK_STOP":
            continue
        for position_id in row.get("flattened_position_ids") or []:
            if position_id:
                ids.add(str(position_id))
    return ids


def attach_position_risk(position: dict[str, Any]) -> dict[str, Any]:
    capital = position_risk_capital(position)
    position["risk_capital_usd"] = capital
    position["risk_capital_method"] = RISK_CAPITAL_METHOD
    position["risk_shock"] = {
        "spot_fraction": SPOT_SHOCK_FRACTION,
        "rates_percentage_points": RATE_SHOCK_PERCENTAGE_POINTS,
        "curve_bps": CURVE_SHOCK_BPS,
    }
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
        "risk_shock": {
            "spot_fraction": SPOT_SHOCK_FRACTION,
            "rates_percentage_points": RATE_SHOCK_PERCENTAGE_POINTS,
            "curve_bps": CURVE_SHOCK_BPS,
        },
        "risk_capital_unavailable_positions": unavailable,
        "risk_capital_status": "unavailable" if unavailable else "ok",
    }
