"""Deterministic funding basis: official SOFR charged on shocked risk capital."""

from __future__ import annotations

from typing import Any, Mapping

from scripts.pm.curve_lock import expression_family
from scripts.risk_capital import (
    RISK_CAPITAL_METHOD,
    attach_position_risk,
    book_risk_capital,
    position_risk_capital,
)

# Legacy labels remain import-compatible, but canonical funding is now risk-capital based.
CASH_FUNDED = "cash_funded"
UNFUNDED_DERIVATIVE = "unfunded_derivative"
UNRESOLVED = "unresolved"
RISK_CAPITAL_FUNDED = "risk_capital_1pct_shock"

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
    """Return the shocked-risk funding base from canonical position fields."""
    pos = dict(position or {})
    if instrument is not None:
        pos["instrument"] = instrument
    if asset_class is not None:
        pos["asset_class"] = asset_class
    if expression is not None:
        pos["paper_expression"] = expression
    if locked_expression_family is not None:
        pos["locked_expression_family"] = locked_expression_family

    # Preserve family derivation as metadata only; it no longer changes the funding rate.
    family = pos.get("locked_expression_family")
    if not family:
        try:
            family = expression_family(pos.get("instrument"), pos.get("asset_class"), pos.get("paper_expression"))
        except Exception:
            family = "other"

    capital = position_risk_capital(pos)
    if capital is None:
        return {
            "funding_basis": UNRESOLVED,
            "funding_basis_status": UNRESOLVED,
            "funding_draw_usd": 0.0,
            "risk_capital_usd": None,
            "risk_capital_method": RISK_CAPITAL_METHOD,
            "consumes_funded_capital": False,
            "expression_family": family,
            "reason": "deterministic mark/risk fields are insufficient to compute 1% shocked MTM",
        }
    return {
        "funding_basis": RISK_CAPITAL_FUNDED,
        "funding_basis_status": RISK_CAPITAL_FUNDED,
        "funding_draw_usd": capital,
        "risk_capital_usd": capital,
        "risk_capital_method": RISK_CAPITAL_METHOD,
        "consumes_funded_capital": capital > 0,
        "expression_family": family,
        "reason": "official SOFR is charged on absolute MTM loss from a 1% adverse risk-factor shock",
    }


def apply_basis_to_position(position: dict[str, Any]) -> dict[str, Any]:
    attach_position_risk(position)
    basis = classify_funding_basis(position)
    position["funding_basis"] = basis["funding_basis"]
    position["funding_basis_status"] = basis["funding_basis_status"]
    position["funding_draw_usd"] = basis["funding_draw_usd"]
    position["funding_basis_reason"] = basis["reason"]
    return position


def funded_draw_for_book(book: dict[str, Any]) -> dict[str, Any]:
    metrics = book_risk_capital(book)
    unresolved: list[str] = []
    for position in book.get("positions") or []:
        apply_basis_to_position(position)
        if position.get("funding_basis_status") == UNRESOLVED:
            unresolved.append(str(position.get("position_id") or position.get("instrument") or "unknown"))

    capital = float(book.get("cash_capital_usd") or book.get("gross_notional_limit_usd") or 0.0)
    risk_capital = round(float(metrics["risk_capital_usd"]), 2)
    return {
        "funded_draw_usd": risk_capital,  # compatibility alias: funding base is shocked risk capital.
        "risk_capital_usd": risk_capital,
        "risk_capital_method": metrics["risk_capital_method"],
        "risk_shock": metrics["risk_shock"],
        "risk_capital_status": metrics["risk_capital_status"],
        "risk_capital_unavailable_positions": metrics["risk_capital_unavailable_positions"],
        # Risk capital is a financing hurdle, not a cash purchase; paper NAV cash remains available.
        "unused_cash_usd": round(capital, 2),
        "cash_capital_usd": capital,
        "funding_basis_status": UNRESOLVED if unresolved else RISK_CAPITAL_FUNDED,
        "unresolved_funding_positions": unresolved,
    }
