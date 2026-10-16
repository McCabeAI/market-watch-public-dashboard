"""Paper-mark admission and unmarkable-seat isolation.

Numeric snapshot values never grant new risk. Traders and PMs share this
contract. A sovereign curve is enterable only when the country registry says
``paper_sovereign_admission`` is ``approved``. NZ sovereign yields and any
rates expression that uses them, including structured legs, are research-only
until a separate NZ rates certification. NZD spot FX is not that exposure:
fresh ECB FX does not depend on NZ rates.

Valuation of an already accepted position still uses the canonical paper-mid
resolver. This module does not invent marks, exits, or HOLD decisions.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from scripts.country_registry import economies, paper_sovereign_admission

REASON_UNSUPPORTED_MARK_SOURCE = "unsupported_mark_source"
REASON_ENTRY_NOT_APPROVED = "entry_not_approved"
DETAIL_SEAT_VALUATION_UNAVAILABLE = "seat_valuation_unavailable"

NEW_RISK_ACTIONS = ("OPEN", "ADD", "HEDGE")
_RESEARCH_ONLY = "research_only"
_APPROVED = "approved"

_G10 = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "NOK", "SEK", "JPY")
_CURRENCY_COUNTRY = {
    "USD": "US",
    "CAD": "CA",
    "AUD": "AU",
    "NZD": "NZ",
    "EUR": "EA",
    "JPY": "JP",
}
# Spot FX whose sovereign curve is research-only must not inherit that rates
# dependency. Approved FX/rates couplings (CAD, JPY) stay as they are.
_SPOT_RATE_DEPS_TO_IGNORE = ("NZ_rates",)

_SOVEREIGN_TENOR = re.compile(r"^([A-Z]{2})_(2Y|5Y|10Y|30Y|LONG|2S10S|5S10S)$")
_RV = re.compile(r"^([A-Z]{2})-([A-Z]{2})_([0-9]+Y|LONG)$")
_FX = re.compile(r"^[A-Z]{6}$")


def _norm_instrument(instrument: Any) -> str:
    return re.sub(r"\s+", "_", str(instrument or "").strip()).upper()


def _country_permission(code: str) -> str:
    return paper_sovereign_admission(code)


def _add_country(bucket: set[str], code: str) -> None:
    cleaned = str(code or "").upper()
    if re.fullmatch(r"[A-Z]{2}", cleaned):
        bucket.add(cleaned)


def _consume_instrument(instrument: Any, *, asset_class: str | None, found: dict[str, Any]) -> None:
    upper = _norm_instrument(instrument)
    if not upper:
        return
    asset = str(asset_class or "").lower()
    fx_pair = upper.replace("_", "")
    if _FX.fullmatch(fx_pair) and fx_pair[:3] in _G10 and fx_pair[3:] in _G10:
        if asset not in {"curve", "rates_rv"}:
            found["fx_pairs"].add(fx_pair)
            for currency in (fx_pair[:3], fx_pair[3:]):
                country = _CURRENCY_COUNTRY.get(currency)
                if country:
                    found["fx_countries"].add(country)
            return
    sovereign = _SOVEREIGN_TENOR.fullmatch(upper)
    if sovereign:
        _add_country(found["sovereign_countries"], sovereign.group(1))
        return
    rv = _RV.fullmatch(upper)
    if rv:
        _add_country(found["sovereign_countries"], rv.group(1))
        _add_country(found["sovereign_countries"], rv.group(2))
        return


def _walk_expression(expression: Any, found: dict[str, Any]) -> None:
    if isinstance(expression, list):
        for item in expression:
            _walk_expression(item, found)
        return
    if not isinstance(expression, Mapping):
        return
    _consume_instrument(
        expression.get("instrument"),
        asset_class=expression.get("asset_class") if isinstance(expression.get("asset_class"), str) else None,
        found=found,
    )
    curve_country = expression.get("curve_country")
    if isinstance(curve_country, str):
        _add_country(found["sovereign_countries"], curve_country)
    country = expression.get("country")
    if isinstance(country, str) and expression.get("type") in {"forward_swap", "linear_combo", "sovereign"}:
        _add_country(found["sovereign_countries"], country)
    for key in ("start_discount_ref", "end_discount_ref", "ref"):
        _countries_in_ref(expression.get(key), found)
    payments = expression.get("payment_discount_refs")
    if isinstance(payments, list):
        for payment in payments:
            if isinstance(payment, Mapping):
                _countries_in_ref(payment.get("ref"), found)
            else:
                _countries_in_ref(payment, found)
    legs = expression.get("legs")
    if isinstance(legs, list):
        for leg in legs:
            if isinstance(leg, Mapping):
                _consume_instrument(
                    leg.get("instrument"),
                    asset_class=leg.get("asset_class") if isinstance(leg.get("asset_class"), str) else None,
                    found=found,
                )
                nested = leg.get("expression")
                if nested is not None:
                    _walk_expression(nested, found)
            else:
                _walk_expression(leg, found)
    nested_expression = expression.get("expression")
    if nested_expression is not None and nested_expression is not expression:
        _walk_expression(nested_expression, found)


def _countries_in_ref(ref: Any, found: dict[str, Any]) -> None:
    if not isinstance(ref, str):
        return
    known = set(economies())
    for part in re.split(r"[./]", ref):
        token = part.upper()
        if token in known:
            _add_country(found["sovereign_countries"], token)


def classify_exposure(
    instrument: Any = None,
    *,
    asset_class: str | None = None,
    expression: Any = None,
) -> dict[str, Any]:
    """Classify an instrument without reading snapshot numbers.

    ``research_only`` is true when any sovereign leg is registry research-only.
    ``pure_spot_fx`` is a G10 spot pair with no sovereign leg. Those pairs do
    not inherit research-only rates dependencies.
    """
    found: dict[str, set[str]] = {
        "sovereign_countries": set(),
        "fx_pairs": set(),
        "fx_countries": set(),
    }
    _consume_instrument(instrument, asset_class=asset_class, found=found)
    _walk_expression(expression, found)

    sovereign = tuple(sorted(found["sovereign_countries"]))
    permissions = {code: _country_permission(code) for code in sovereign}
    research_countries = tuple(code for code, permission in permissions.items() if permission == _RESEARCH_ONLY)
    unknown_countries = tuple(code for code, permission in permissions.items() if permission == "unknown")
    research_only = bool(research_countries)
    pure_spot_fx = bool(found["fx_pairs"]) and not sovereign

    if research_only:
        admission = _RESEARCH_ONLY
        reason = REASON_UNSUPPORTED_MARK_SOURCE
        entry_permitted = False
    elif unknown_countries:
        admission = "unknown"
        reason = REASON_ENTRY_NOT_APPROVED
        entry_permitted = False
    else:
        admission = _APPROVED
        reason = None
        entry_permitted = True

    research_rate_dependencies = tuple(f"{code}_rates" for code in research_countries)
    return {
        "admission": admission,
        "entry_permitted": entry_permitted,
        "reason": reason,
        "research_only": research_only,
        "pure_spot_fx": pure_spot_fx,
        "sovereign_countries": sovereign,
        "research_countries": research_countries,
        "unknown_countries": unknown_countries,
        "fx_pairs": tuple(sorted(found["fx_pairs"])),
        "research_rate_dependencies": research_rate_dependencies,
        "spot_rate_deps_to_ignore": _SPOT_RATE_DEPS_TO_IGNORE if pure_spot_fx else (),
    }


def _rejection(
    *,
    reason: str,
    message: str,
    instrument: Any = None,
    detail: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    out = {
        "reason": reason,
        "message": message,
        "instrument": instrument,
        "action": action,
        "live_marked": False,
        "synthetic_hold": False,
    }
    if detail:
        out["detail"] = detail
    return out


def entry_rejection(
    instrument: Any = None,
    *,
    asset_class: str | None = None,
    expression: Any = None,
    action: str = "OPEN",
) -> dict[str, Any] | None:
    """Return a fail-closed rejection for new risk, or None when entry is allowed.

    The decision ignores mark values. A finite research print does not admit
    a research-only sovereign or rates-RV expression.
    """
    if action not in NEW_RISK_ACTIONS:
        return None
    info = classify_exposure(instrument, asset_class=asset_class, expression=expression)
    if info["entry_permitted"]:
        return None
    label = _norm_instrument(instrument) or "expression"
    if info["reason"] == REASON_UNSUPPORTED_MARK_SOURCE:
        countries = ",".join(info["research_countries"])
        message = (
            f"{label} uses research-only sovereign rates ({countries}) and is not an "
            "approved paper-mark source"
        )
        return _rejection(reason=REASON_UNSUPPORTED_MARK_SOURCE, message=message, instrument=instrument, action=action)
    countries = ",".join(info["unknown_countries"])
    message = f"{label} sovereign exposure ({countries}) has no approved paper-mark permission"
    return _rejection(reason=REASON_ENTRY_NOT_APPROVED, message=message, instrument=instrument, action=action)


def action_exposure(
    action: Mapping[str, Any],
    positions: list[Any] | None = None,
    *,
    selected_candidate: Mapping[str, Any] | None = None,
) -> tuple[Any, Any, Any]:
    """Instrument the admission gate must judge for this action.

    ADD follows the open position. A HEDGE with no instrument of its own
    follows the target position. The selected memo candidate is only a fallback.
    """
    kind = action.get("action")
    instrument = action.get("instrument")
    asset_class = action.get("asset_class")
    expression = action.get("paper_expression")
    position = None
    if kind in {"ADD", "REDUCE", "CLOSE"}:
        position = _position_by_id(positions, action.get("position_id"))
    elif kind == "HEDGE" and not instrument:
        position = _position_by_id(positions, action.get("hedge_of") or action.get("position_id"))
    if isinstance(position, Mapping):
        instrument = position.get("instrument") if kind != "HEDGE" or not action.get("instrument") else instrument
        if kind != "HEDGE":
            asset_class = position.get("asset_class")
            expression = position.get("paper_expression")
        else:
            asset_class = asset_class or position.get("asset_class")
            if expression is None:
                expression = position.get("paper_expression")
            if not instrument:
                instrument = position.get("instrument")
    if not instrument and isinstance(selected_candidate, Mapping):
        instrument = selected_candidate.get("instrument")
        asset_class = asset_class or selected_candidate.get("asset_class")
        if expression is None:
            expression = selected_candidate.get("paper_expression")
    return instrument, asset_class, expression


def _position_by_id(positions: list[Any] | None, position_id: Any) -> Mapping[str, Any] | None:
    wanted = str(position_id or "")
    if not wanted:
        return None
    for position in positions or []:
        if isinstance(position, Mapping) and str(position.get("position_id") or "") == wanted:
            return position
    return None


def research_only_position(position: Mapping[str, Any]) -> bool:
    return bool(
        classify_exposure(
            position.get("instrument"),
            asset_class=position.get("asset_class") if isinstance(position.get("asset_class"), str) else None,
            expression=position.get("paper_expression") or position.get("expression"),
        )["research_only"]
    )


def seat_valuation_block(
    positions: list[Any] | None,
    unresolved_position_ids: set[str],
) -> dict[str, Any] | None:
    """Block every new-risk action on a seat while a research-only position has no verified mark."""
    for position in positions or []:
        if not isinstance(position, Mapping) or not research_only_position(position):
            continue
        position_id = str(position.get("position_id") or "")
        if position_id not in unresolved_position_ids:
            continue
        instrument = position.get("instrument")
        message = (
            f"new risk blocked while {position_id} {instrument} has no verified mark "
            f"({DETAIL_SEAT_VALUATION_UNAVAILABLE})"
        )
        return _rejection(
            reason=REASON_ENTRY_NOT_APPROVED,
            message=message,
            instrument=instrument,
            detail=DETAIL_SEAT_VALUATION_UNAVAILABLE,
        )
    return None


def unresolved_research_position_ids(
    positions: list[Any] | None,
    *,
    market_state: Mapping[str, Any] | None,
    resolve_mark,
) -> set[str]:
    """Ids of research-only positions whose current mark cannot be resolved.

    ``resolve_mark`` is the canonical paper-mid function. Missing market state
    fails closed: an unverified research position restricts the seat.
    """
    unresolved: set[str] = set()
    for position in positions or []:
        if not isinstance(position, Mapping) or not research_only_position(position):
            continue
        position_id = str(position.get("position_id") or "")
        if market_state is None:
            if position_id:
                unresolved.add(position_id)
            continue
        try:
            resolve_mark(
                market_state,
                str(position.get("instrument") or ""),
                asset_class=position.get("asset_class"),
                expression=position.get("paper_expression"),
            )
        except Exception:
            if position_id:
                unresolved.add(position_id)
    return unresolved


def scan_new_risk(
    actions: list[Any] | None,
    *,
    seat: str,
    positions: list[Any] | None = None,
    unresolved_position_ids: set[str] | None = None,
    selected_candidate: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Machine-readable rejections for OPEN/ADD/HEDGE. Does not rewrite actions."""
    findings: list[dict[str, Any]] = []
    unresolved = unresolved_position_ids or set()
    for action in actions or []:
        if not isinstance(action, Mapping):
            continue
        kind = str(action.get("action") or "")
        if kind not in NEW_RISK_ACTIONS:
            continue
        instrument, asset_class, expression = action_exposure(
            action,
            positions,
            selected_candidate=selected_candidate,
        )
        rejection = entry_rejection(
            instrument,
            asset_class=asset_class if isinstance(asset_class, str) else None,
            expression=expression if isinstance(expression, Mapping) else None,
            action=kind,
        )
        if rejection is None:
            rejection = seat_valuation_block(positions, unresolved)
        if rejection is None:
            continue
        row = dict(rejection)
        row["seat"] = seat
        row["action"] = kind
        row["instrument"] = instrument
        findings.append(row)
    return findings


def _row_expression(row: Mapping[str, Any]) -> Any:
    expression = row.get("paper_expression")
    if expression is None:
        expression = row.get("expression")
    return expression


def _isolatable(row: Mapping[str, Any]) -> bool:
    if not row.get("seat"):
        return False
    info = classify_exposure(
        row.get("instrument"),
        asset_class=row.get("asset_class") if isinstance(row.get("asset_class"), str) else None,
        expression=_row_expression(row),
    )
    if not info["research_only"]:
        return False
    return str(row.get("dependency") or "") in set(info["research_rate_dependencies"])


def _quarantined_copy(row: Mapping[str, Any]) -> dict[str, Any]:
    instrument = row.get("instrument")
    dependency = row.get("dependency")
    status = row.get("dependency_status")
    return {
        "position_id": row.get("position_id"),
        "seat": row.get("seat"),
        "instrument": instrument,
        "asset_class": row.get("asset_class"),
        "dependency": dependency,
        "dependency_status": status,
        "observation_date": row.get("observation_date"),
        "reason_code": REASON_UNSUPPORTED_MARK_SOURCE,
        "reason": (
            f"position {instrument!r} is research-only and unmarkable on {dependency} ({status}); "
            "valuation unavailable, new risk blocked for this seat"
        ),
        "quarantined": True,
        "live_marked": False,
        "pnl_available": False,
        "scoring": False,
    }


def quarantine_decision(
    unmarkable_positions: list[Any],
    *,
    trade_eligible_countries: list[str] | None,
) -> dict[str, Any]:
    """Decide whether unmarkable positions halt the book or isolate their seats.

    Approved-instrument failures (a live mark source that is stale or missing)
    keep the global ``existing_book_unmarkable`` halt. Research-only sovereign
    positions isolate the named seats when some other country is independently
    trade-eligible. No HOLD is synthesized.
    """
    rows = [row for row in unmarkable_positions if isinstance(row, Mapping)]
    eligible = [code for code in (trade_eligible_countries or []) if code]
    isolatable = [row for row in rows if _isolatable(row)]
    blocking = [row for row in rows if row not in isolatable]
    base_fields = {
        "hold_decisions_emitted": 0,
        "synthetic_holds": False,
    }
    if not rows:
        return {
            "mode": "clear",
            "why": None,
            "gate_fields": {
                **base_fields,
                "quarantined_positions": [],
                "restricted_seats": [],
                "seat_risk": {},
                "quarantine_reason": None,
                "quarantine_mode": "clear",
            },
        }
    if blocking or not eligible:
        if blocking:
            sample = blocking[0]
            why = (
                "approved mark dependency prevents safe partial continuation: "
                f"{sample.get('instrument')} on {sample.get('seat')} depends on "
                f"{sample.get('dependency')} ({sample.get('dependency_status')})"
            )
        else:
            why = "no independently trade-eligible country; partial continuation would have no markable book"
        return {
            "mode": "block",
            "why": why,
            "gate_fields": {
                **base_fields,
                "quarantined_positions": [],
                "restricted_seats": [],
                "seat_risk": {},
                "quarantine_reason": None,
                "quarantine_mode": "block",
                "block_why": why,
            },
        }
    restricted = sorted({str(row.get("seat")) for row in isolatable})
    quarantined = [_quarantined_copy(row) for row in isolatable]
    return {
        "mode": "isolate",
        "why": None,
        "gate_fields": {
            **base_fields,
            "quarantined_positions": quarantined,
            "restricted_seats": restricted,
            "seat_risk": {seat: "unavailable_new_risk" for seat in restricted},
            "quarantine_reason": REASON_UNSUPPORTED_MARK_SOURCE,
            "quarantine_mode": "isolate",
        },
    }


def frozen_permission_fields(gate: Mapping[str, Any]) -> dict[str, Any]:
    """Subset of the quality-gate artifact copied onto the frozen packet."""
    return {
        "restricted_seats": list(gate.get("restricted_seats") or []),
        "quarantined_positions": list(gate.get("quarantined_positions") or []),
        "seat_risk": dict(gate.get("seat_risk") or {}),
        "hold_decisions_emitted": int(gate.get("hold_decisions_emitted") or 0),
        "synthetic_holds": bool(gate.get("synthetic_holds") or False),
        "quarantine_reason": gate.get("quarantine_reason"),
        "quarantine_mode": gate.get("quarantine_mode"),
        "block_why": gate.get("block_why"),
    }
