"""Lock SOFR / CORRA / AONIA / bond expression families from OPEN through CLOSE."""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.pm.errors import CurveLockError, SchemaError


def expression_family(
    instrument: str | None,
    asset_class: str | None = None,
    expression: Mapping[str, Any] | None = None,
) -> str:
    if isinstance(expression, Mapping) and expression:
        kind = expression.get("type")
        if kind == "futures_strip_average":
            curve_id = str(expression.get("curve_id") or "").lower()
            if curve_id not in {"sofr", "corra", "aonia"}:
                raise CurveLockError("futures_strip_average curve_id must be SOFR, CORRA or AONIA")
            return curve_id
        if kind == "forward_swap":
            return "bond"
        if kind == "linear_combo":
            families = {
                expression_family(
                    str(leg.get("instrument") or "") if isinstance(leg, Mapping) else "",
                    leg.get("asset_class") if isinstance(leg, Mapping) else None,
                    leg.get("expression") if isinstance(leg, Mapping) else None,
                )
                for leg in (expression.get("legs") or [])
                if isinstance(leg, Mapping)
            }
            families.discard("other")
            if len(families) == 1:
                return next(iter(families))
            if len(families) > 1:
                raise CurveLockError(
                    "linear_combo mixes expression families "
                    + ",".join(sorted(families))
                    + "; family must stay locked"
                )
    raw = str(instrument or "").strip()
    upper = raw.upper().replace(" ", "_")
    if re.fullmatch(r"(SOFR|SR3)[_-].+", upper) or upper.startswith("SOFR") or upper.startswith("SR3"):
        return "sofr"
    if re.fullmatch(r"(CORRA|CRA)[_-].+", upper) or upper.startswith("CORRA") or upper.startswith("CRA"):
        return "corra"
    if re.fullmatch(r"(AONIA|IB)[_-].+", upper) or upper.startswith("AONIA"):
        return "aonia"
    if asset_class in {"rates", "curve", "rates_rv"}:
        return "bond"
    if asset_class == "spot_fx" or re.fullmatch(r"[A-Z]{6}", upper.replace("_", "")):
        return "spot_fx"
    if asset_class == "options":
        return "options"
    return "other"


def assert_family_locked(position: Mapping[str, Any], *, instrument: str | None, asset_class: str | None, expression: Mapping[str, Any] | None) -> str:
    locked = position.get("locked_expression_family") or expression_family(
        position.get("instrument"),
        position.get("asset_class"),
        position.get("paper_expression") if isinstance(position.get("paper_expression"), Mapping) else None,
    )
    incoming = expression_family(instrument or position.get("instrument"), asset_class or position.get("asset_class"), expression)
    if incoming != locked and incoming != "other":
        raise CurveLockError(
            f"{position.get('position_id')} is locked to {locked}; refusing silent switch to {incoming}"
        )
    if expression and position.get("paper_expression") and expression != position.get("paper_expression"):
        if incoming in {"sofr", "corra", "aonia", "bond"} and incoming == locked:
            # Same family but a different construction still counts as a silent switch.
            raise CurveLockError(
                f"{position.get('position_id')} paper_expression is locked from OPEN through CLOSE"
            )
    return str(locked)


def locked_fields(instrument: str | None, asset_class: str | None, expression: Mapping[str, Any] | None) -> dict[str, Any]:
    family = expression_family(instrument, asset_class, expression)
    if family in {"sofr", "corra", "aonia", "bond"} and not instrument and not expression:
        raise SchemaError("curve-family lock requires an instrument or paper_expression")
    return {
        "locked_expression_family": family,
        "paper_expression": dict(expression) if isinstance(expression, Mapping) else None,
    }
