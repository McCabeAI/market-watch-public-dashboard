"""Rates-first vs dedicated-spot expression rules."""

from __future__ import annotations

from typing import Any

from scripts.overnight.constants import (
    ASSET_CLASSES,
    EXPRESSION_CHOICES,
    NO_TRADE_SEAT,
    RATES_FIRST_SEATS,
    SEAT_REMITS,
    SPOT_SEATS,
    STANDING_SEATS,
    VOL_LAST_RESORT_SEAT,
)
from scripts.overnight.errors import SchemaError


def expression_rule(seat: str) -> str:
    if seat not in STANDING_SEATS:
        raise SchemaError(f"unknown seat {seat}")
    if seat in SPOT_SEATS:
        return "spot_only"
    return "rates_first"


def remit(seat: str) -> str:
    if seat not in SEAT_REMITS:
        raise SchemaError(f"unknown seat remit {seat}")
    return SEAT_REMITS[seat]


def _optional_candidate(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise SchemaError(f"{field} must be an object or null")
    for key in ("instrument", "asset_class", "rationale"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise SchemaError(f"{field}.{key} must be a non-empty string")
    if value["asset_class"] not in ASSET_CLASSES:
        raise SchemaError(f"{field}.asset_class must be one of {ASSET_CLASSES}")


def validate_expression_memo(memo: dict[str, Any] | None, *, seat: str, action: str) -> dict[str, Any]:
    if memo is None:
        raise SchemaError(f"{seat} must supply an expression_memo")
    if not isinstance(memo, dict):
        raise SchemaError(f"{seat} expression_memo must be an object")
    for key in ("rates_candidate", "spot_candidate", "options_candidate", "selected", "rationale"):
        if key not in memo:
            raise SchemaError(f"{seat} expression_memo missing {key}")
    if memo["selected"] not in EXPRESSION_CHOICES:
        raise SchemaError(f"{seat} selected expression must be one of {EXPRESSION_CHOICES}")
    if not isinstance(memo["rationale"], str) or not memo["rationale"].strip():
        raise SchemaError(f"{seat} expression_memo.rationale must be non-empty")
    _optional_candidate(memo["rates_candidate"], f"{seat}.rates_candidate")
    _optional_candidate(memo["spot_candidate"], f"{seat}.spot_candidate")
    _optional_candidate(memo["options_candidate"], f"{seat}.options_candidate")

    rule = expression_rule(seat)
    selected = memo["selected"]

    if action == "HOLD" and selected == "none" and not memo["spot_candidate"] and not memo["rates_candidate"]:
        return memo

    if rule == "spot_only":
        if selected not in {"spot", "none"}:
            raise SchemaError(f"{seat} is a dedicated spot-FX seat and may not select {selected}")
        if memo["rates_candidate"] is not None:
            raise SchemaError(f"{seat} must stay spot-oriented; rates_candidate must be null")
        if memo["options_candidate"] is not None and selected != "none":
            raise SchemaError(f"{seat} may not put on options; options are last-resort for other seats")
        if selected == "spot" and memo["spot_candidate"] is None:
            raise SchemaError(f"{seat} selected spot without a spot_candidate")
        if selected == "spot" and memo["spot_candidate"]["asset_class"] != "spot_fx":
            raise SchemaError(f"{seat} spot_candidate.asset_class must be spot_fx")
        return memo

    # rates-first seats, including vol-convexity and the skeptic
    if selected in {"rates", "spot", "options"} and action in {"OPEN", "ADD", "HEDGE"}:
        if memo["rates_candidate"] is None:
            raise SchemaError(f"{seat} must evaluate a rates candidate before selecting {selected}")
        if memo["spot_candidate"] is None:
            raise SchemaError(f"{seat} must compare a spot candidate before selecting {selected}")
        if memo["rates_candidate"]["asset_class"] not in {"rates", "curve", "rates_rv"}:
            raise SchemaError(f"{seat} rates_candidate.asset_class must be rates, curve, or rates_rv")
    if selected == "options":
        if seat != VOL_LAST_RESORT_SEAT and action in {"OPEN", "ADD"}:
            raise SchemaError(f"{seat} may use options only as an explicit last resort; default seats must not OPEN options")
        if memo["options_candidate"] is None:
            raise SchemaError(f"{seat} selected options without an options_candidate")
        if "last resort" not in memo["rationale"].lower() and "last-resort" not in memo["rationale"].lower():
            raise SchemaError(f"{seat} options selection must justify last-resort use")
    if selected == "none" and seat != NO_TRADE_SEAT and action in {"OPEN", "ADD"}:
        raise SchemaError(f"{seat} cannot OPEN/ADD with selected=none")
    if selected == "rates" and memo["rates_candidate"] is None:
        raise SchemaError(f"{seat} selected rates without a rates_candidate")
    if selected == "spot" and memo["spot_candidate"] is None:
        raise SchemaError(f"{seat} selected spot without a spot_candidate")
    return memo


def selected_asset_class(memo: dict[str, Any]) -> str | None:
    choice = memo["selected"]
    if choice == "none":
        return None
    candidate = {
        "rates": memo.get("rates_candidate"),
        "spot": memo.get("spot_candidate"),
        "options": memo.get("options_candidate"),
    }[choice]
    return None if candidate is None else candidate["asset_class"]


def assert_rates_first_roster() -> None:
    if set(SPOT_SEATS) | set(RATES_FIRST_SEATS) != set(STANDING_SEATS):
        raise SchemaError("spot and rates-first seats do not partition the standing 14")
