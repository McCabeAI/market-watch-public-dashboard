"""Deterministic PM funded-capital basis. Never guess from gross notional."""

from __future__ import annotations

from typing import Any, Mapping

from scripts.pm.curve_lock import expression_family

CASH_FUNDED = "cash_funded"
UNFUNDED_DERIVATIVE = "unfunded_derivative"
UNRESOLVED = "unresolved"

FUTURES_FAMILIES = {"sofr", "corra", "aonia"}
DERIVATIVE_EXPRESSION_TYPES = {
    "futures_strip_average",
    "forward_swap",
    "linear_combo",
}


def classify_funding_basis(
    position: Mapping[str, Any] | None = None,
    *,
    instrument: str | None = None,
    asset_class: str | None = None,
    expression: Mapping[str, Any] | None = None,
    locked_expression_family: str | None = None,
) -> dict[str, Any]:
    """Return a defensible funding basis from canonical instrument fields only."""
    pos = position or {}
    instrument = instrument if instrument is not None else pos.get("instrument")
    asset_class = asset_class if asset_class is not None else pos.get("asset_class")
    raw_expr = expression if expression is not None else pos.get("paper_expression")
    expr = raw_expr if isinstance(raw_expr, Mapping) else None
    family = locked_expression_family or pos.get("locked_expression_family")
    if not family:
        try:
            family = expression_family(instrument, asset_class, expr)
        except Exception:
            family = "other"

    notional = abs(float(pos.get("notional_usd") or 0.0))
    expr_type = str((expr or {}).get("type") or "")

    if family == "spot_fx" or asset_class == "spot_fx":
        return {
            "funding_basis": CASH_FUNDED,
            "funding_basis_status": CASH_FUNDED,
            "funding_draw_usd": round(notional, 2),
            "consumes_funded_capital": True,
            "reason": "spot cash FX exposure consumes funded capital",
        }
    if family in FUTURES_FAMILIES or expr_type == "futures_strip_average":
        return {
            "funding_basis": UNFUNDED_DERIVATIVE,
            "funding_basis_status": UNFUNDED_DERIVATIVE,
            "funding_draw_usd": 0.0,
            "consumes_funded_capital": False,
            "reason": "SR3/CORRA/AONIA futures notional is not a cash borrowing",
        }
    if family == "options" or asset_class == "options":
        return {
            "funding_basis": UNFUNDED_DERIVATIVE,
            "funding_basis_status": UNFUNDED_DERIVATIVE,
            "funding_draw_usd": 0.0,
            "consumes_funded_capital": False,
            "reason": "options notional is not charged full-notional SOFR funding",
        }
    if expr_type in DERIVATIVE_EXPRESSION_TYPES:
        return {
            "funding_basis": UNFUNDED_DERIVATIVE,
            "funding_basis_status": UNFUNDED_DERIVATIVE,
            "funding_draw_usd": 0.0,
            "consumes_funded_capital": False,
            "reason": "forward/future construction already embeds carry; notional is not drawn cash",
        }
    return {
        "funding_basis": UNRESOLVED,
        "funding_basis_status": UNRESOLVED,
        "funding_draw_usd": 0.0,
        "consumes_funded_capital": False,
        "reason": "canonical fields do not prove a cash-funded security; draw left unresolved",
    }


def apply_basis_to_position(position: dict[str, Any]) -> dict[str, Any]:
    basis = classify_funding_basis(position)
    position["funding_basis"] = basis["funding_basis"]
    position["funding_basis_status"] = basis["funding_basis_status"]
    position["funding_draw_usd"] = basis["funding_draw_usd"]
    position["funding_basis_reason"] = basis["reason"]
    return position


def funded_draw_for_book(book: dict[str, Any]) -> dict[str, Any]:
    draw = 0.0
    unresolved: list[str] = []
    statuses: set[str] = set()
    for position in book.get("positions") or []:
        apply_basis_to_position(position)
        draw += float(position.get("funding_draw_usd") or 0.0)
        status = str(position.get("funding_basis_status") or UNRESOLVED)
        statuses.add(status)
        if status == UNRESOLVED:
            unresolved.append(str(position.get("position_id") or position.get("instrument") or "unknown"))
    capital = float(book.get("cash_capital_usd") or book.get("gross_notional_limit_usd") or 0.0)
    funded = round(draw, 2)
    unused = round(max(0.0, capital - funded), 2)
    if unresolved:
        rollup = UNRESOLVED
    elif CASH_FUNDED in statuses and UNFUNDED_DERIVATIVE in statuses:
        rollup = "mixed"
    elif CASH_FUNDED in statuses:
        rollup = CASH_FUNDED
    elif UNFUNDED_DERIVATIVE in statuses:
        rollup = UNFUNDED_DERIVATIVE
    else:
        rollup = "none"
    return {
        "funded_draw_usd": funded,
        "unused_cash_usd": unused,
        "cash_capital_usd": capital,
        "funding_basis_status": rollup,
        "unresolved_funding_positions": unresolved,
    }
