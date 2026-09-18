"""Kevin's Market Watch Operating Hub expression mandate.

Standing remits, grok-4.6 seat models, and orchestration level stay unchanged.
This module only classifies existing seats and validates the expression rule.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.trader_room.constants import (
    CHOSEN_EXPRESSION_FAMILIES,
    COMPARISON_AGENTS,
    COMPARISON_EXPRESSION_FAMILIES,
    NO_TRADE_AGENT,
    RATES_EXPRESSION_FAMILIES,
    SPOT_EXPRESSION_FAMILY,
    SPOT_SPECIALIST_AGENTS,
    VOL_EXPRESSION_FAMILY,
    VOL_SPECIALIST_AGENT,
)
from scripts.trader_room.errors import SchemaError

VOL_HINTS = (
    "straddle",
    "strangle",
    "risk reversal",
    "risk-reversal",
    "option",
    "implied vol",
    "variance swap",
    "vanna",
    "call spread",
    "put spread",
    "butterfly",
    "calendar spread",
    "seagull",
    "knock-in",
    "knock-out",
    "vol overlay",
)

RATES_INSTRUMENT_HINTS = (
    "ust",
    "treasury",
    "gilt",
    "bund",
    "oga",
    "acgb",
    "can ",
    "can2",
    "can5",
    "can10",
    "us 2y",
    "us 5y",
    "us 10y",
    "us 30y",
    "2s10s",
    "5s10s",
    "2s5s",
    "5s30s",
    "duration",
    "curve",
    "swap",
    "ois",
    "spread",
    "rv",
)


def seat_class(agent: str) -> str:
    if agent in SPOT_SPECIALIST_AGENTS:
        return "spot_specialist"
    if agent == VOL_SPECIALIST_AGENT:
        return "vol_specialist"
    if agent in COMPARISON_AGENTS:
        return "comparison"
    raise SchemaError(f"unknown standing seat {agent}")


def looks_like_vol(trade: dict[str, Any] | None) -> bool:
    if not trade:
        return False
    blob = " ".join(str(trade.get(key) or "") for key in ("instrument", "structure", "direction")).lower()
    if "volume" in blob:
        blob = blob.replace("volume", "")
    return any(hint in blob for hint in VOL_HINTS)


def looks_like_rates(trade: dict[str, Any] | None) -> bool:
    if not trade:
        return False
    blob = " ".join(str(trade.get(key) or "") for key in ("instrument", "structure", "direction")).lower()
    return any(hint in blob for hint in RATES_INSTRUMENT_HINTS)


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _require_rates_consideration(considered: Any, agent: str) -> list[dict[str, Any]]:
    if not isinstance(considered, list) or len(considered) < 3:
        raise SchemaError(f"{agent} must consider outright duration, curve, and cross-market rates RV")
    by_family = {}
    for item in considered:
        if not isinstance(item, dict):
            raise SchemaError(f"{agent} considered_rates entries must be objects")
        family = item.get("family")
        if family not in RATES_EXPRESSION_FAMILIES:
            raise SchemaError(f"{agent} unknown rates family {family!r}")
        _non_empty(item.get("instrument"), f"{agent}.considered_rates.{family}.instrument")
        _non_empty(item.get("assessment"), f"{agent}.considered_rates.{family}.assessment")
        by_family[family] = item
    missing = [family for family in RATES_EXPRESSION_FAMILIES if family not in by_family]
    if missing:
        raise SchemaError(f"{agent} missing required rates families: {missing}")
    return [by_family[family] for family in RATES_EXPRESSION_FAMILIES]


def _require_spot_consideration(considered: Any, agent: str) -> dict[str, Any]:
    if not isinstance(considered, dict):
        raise SchemaError(f"{agent} considered_spot must be an object")
    _non_empty(considered.get("instrument"), f"{agent}.considered_spot.instrument")
    _non_empty(considered.get("assessment"), f"{agent}.considered_spot.assessment")
    return considered


def validate_expression_comparison(
    contribution: dict[str, Any],
    *,
    agent: str,
) -> dict[str, Any] | None:
    """Apply the Operating Hub expression rule without changing remits."""
    comparison = contribution.get("expression_comparison")
    trade = contribution.get("trade")
    klass = seat_class(agent)

    if klass == "vol_specialist":
        if comparison is not None:
            raise SchemaError("vol-convexity remit/comparison surface is unchanged; omit expression_comparison")
        return None

    if comparison is None:
        raise SchemaError(f"{agent} must include expression_comparison")
    if not isinstance(comparison, dict):
        raise SchemaError(f"{agent} expression_comparison must be an object")
    if comparison.get("seat_class") != klass:
        raise SchemaError(f"{agent} expression_comparison.seat_class must be {klass}")

    if klass == "spot_specialist":
        if comparison.get("spot_dedicated") is not True:
            raise SchemaError(f"{agent} must remain spot-dedicated")
        if comparison.get("chosen_expression") != SPOT_EXPRESSION_FAMILY:
            raise SchemaError(f"{agent} must choose spot_fx")
        if looks_like_vol(trade):
            raise SchemaError(f"{agent} is spot-dedicated and must not default to vol")
        if looks_like_rates(trade):
            raise SchemaError(f"{agent} is spot-dedicated and must not substitute a rates expression")
        return comparison

    considered_rates = _require_rates_consideration(comparison.get("considered_rates"), agent)
    considered_spot = _require_spot_consideration(comparison.get("considered_spot"), agent)
    chosen = comparison.get("chosen_expression")
    if chosen not in CHOSEN_EXPRESSION_FAMILIES:
        raise SchemaError(f"{agent} chosen_expression must be a recognized family")
    _non_empty(comparison.get("chosen_because"), f"{agent}.expression_comparison.chosen_because")

    if trade is None:
        if agent != NO_TRADE_AGENT:
            raise SchemaError(f"{agent} cannot choose no-trade")
        if chosen != "no_trade":
            raise SchemaError("no-trade-skeptic must set chosen_expression=no_trade when trade is null")
        return comparison

    if chosen == "no_trade":
        raise SchemaError(f"{agent} chose no_trade but submitted a trade")
    if chosen == VOL_EXPRESSION_FAMILY:
        if comparison.get("unusually_compelling_vol") is not True:
            raise SchemaError(
                f"{agent} may surface vol only when unusually compelling; do not default to options"
            )
        _non_empty(
            comparison.get("vol_reason"),
            f"{agent}.expression_comparison.vol_reason",
        )
        if not looks_like_vol(trade):
            raise SchemaError(f"{agent} chose vol_options but trade is not a vol expression")
    else:
        if looks_like_vol(trade) and comparison.get("unusually_compelling_vol") is not True:
            raise SchemaError(
                f"{agent} must not default to vol/options; retain vol-convexity for that remit"
            )
        if chosen == SPOT_EXPRESSION_FAMILY and looks_like_rates(trade) and not re.search(
            r"(EUR|GBP|AUD|NZD|USD|CAD|CHF|NOK|SEK|JPY){2}",
            str(trade.get("instrument") or "").replace("/", "").upper(),
        ):
            raise SchemaError(f"{agent} chose spot_fx but trade looks like a rates expression")
        if chosen in RATES_EXPRESSION_FAMILIES and chosen not in {item["family"] for item in considered_rates}:
            raise SchemaError(f"{agent} chose a rates family it did not consider")

    # Spot remains an allowed winner; rates are considered first, not forced.
    if chosen == SPOT_EXPRESSION_FAMILY and not str(considered_spot.get("assessment") or "").strip():
        raise SchemaError(f"{agent} must explain the spot alternative")
    return comparison


def compact_comparison(comparison: dict[str, Any] | None) -> dict[str, Any] | None:
    if not comparison:
        return None
    return {
        "seat_class": comparison.get("seat_class"),
        "chosen_expression": comparison.get("chosen_expression"),
        "chosen_because": comparison.get("chosen_because"),
        "spot_dedicated": comparison.get("spot_dedicated"),
        "unusually_compelling_vol": comparison.get("unusually_compelling_vol"),
    }


def comparison_required_families() -> tuple[str, ...]:
    return COMPARISON_EXPRESSION_FAMILIES
