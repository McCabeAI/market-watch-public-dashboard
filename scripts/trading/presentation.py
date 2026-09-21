"""Trader/PM human-facing presentation contract.

Machine identifiers remain valid in canonical execution fields.  This module
governs only the desk-facing narrative shown to a human.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.overnight.errors import SchemaError

_NORMALIZED_ID_RE = re.compile(
    r"\b(?:CORRA|SOFR|AONIA)_20\d{2}(?:-\d{2}|[FGHJKMNQUVXZ]-[FGHJKMNQUVXZ])\b",
    re.I,
)
_POSITION_ID_RE = re.compile(r"\b(?:pos|pm-[a-z0-9-]+)-[a-z0-9]+\b", re.I)
_ROBOT_LABEL_RE = re.compile(r"\b(?:FACT|INFERENCE|UNKNOWN):", re.I)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _desk_text(value: Any, field: str) -> str:
    text = _text(value, field)
    if _NORMALIZED_ID_RE.search(text):
        raise SchemaError(
            f"{field} must use market shorthand (for example H7 CORRA), not normalized internal IDs"
        )
    if _POSITION_ID_RE.search(text):
        raise SchemaError(f"{field} must not expose internal position IDs")
    if _ROBOT_LABEL_RE.search(text):
        raise SchemaError(f"{field} must use natural desk prose, not FACT:/INFERENCE:/UNKNOWN: labels")
    return text


def validate_trade_presentation(
    value: Any,
    *,
    label: str,
    required: bool = True,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise SchemaError(f"{label}.presentation is required")
        return None
    if not isinstance(value, dict):
        raise SchemaError(f"{label}.presentation must be an object")

    market_expression = _desk_text(
        value.get("market_expression"), f"{label}.presentation.market_expression"
    )
    punchline = _desk_text(value.get("punchline"), f"{label}.presentation.punchline")
    if len(punchline) > 320:
        raise SchemaError(f"{label}.presentation.punchline must be <= 320 characters")

    support = value.get("support")
    if not isinstance(support, list) or not 1 <= len(support) <= 6:
        raise SchemaError(f"{label}.presentation.support must contain 1..6 desk-readable bullets")
    cleaned_support = [
        _desk_text(item, f"{label}.presentation.support[{idx}]")
        for idx, item in enumerate(support)
    ]

    take_profit = value.get("take_profit")
    if not isinstance(take_profit, dict):
        raise SchemaError(f"{label}.presentation.take_profit must be an object")
    objective = _desk_text(
        take_profit.get("objective"), f"{label}.presentation.take_profit.objective"
    )
    basis = _desk_text(take_profit.get("basis"), f"{label}.presentation.take_profit.basis")
    pnl_target = take_profit.get("pnl_target_usd")
    if pnl_target is not None:
        if isinstance(pnl_target, bool) or not isinstance(pnl_target, (int, float)):
            raise SchemaError(
                f"{label}.presentation.take_profit.pnl_target_usd must be numeric or null"
            )
        if float(pnl_target) <= 0:
            raise SchemaError(
                f"{label}.presentation.take_profit.pnl_target_usd must be positive when supplied"
            )

    invalidation = value.get("invalidation")
    if invalidation is not None:
        _desk_text(invalidation, f"{label}.presentation.invalidation")

    return {
        **value,
        "market_expression": market_expression,
        "punchline": punchline,
        "support": cleaned_support,
        "take_profit": {
            **take_profit,
            "objective": objective,
            "basis": basis,
        },
    }
