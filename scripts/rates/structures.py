"""Native domestic calendars, butterflies, and cross-market relative structures.

Leg P&L is the source of truth. The package mark is the observed level of the
structure. A futures strip average is not a curve spread and cannot be built here.

Package side follows the rates book convention: long profits when the canonical
mark falls. No structure is a recommended trade.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.overnight.errors import SchemaError
from scripts.rates.contract_economics import (
    CURVE_SPEC,
    ParsedContract,
    contracts_from_face_usd,
    dv01_per_contract,
    fx_usd_per_unit,
    parse_contract_id,
)

STRUCTURE_TYPES = ("calendar_spread", "butterfly", "outright_rv", "curve_rv")
STRIP_TYPE = "futures_strip_average"


class StructureError(SchemaError):
    """A multi-leg rates structure cannot be built without inventing inputs."""


def _curve_contract(curve_id: str, expiry: str) -> ParsedContract:
    curve = str(curve_id or "").upper()
    if curve not in CURVE_SPEC:
        raise StructureError(f"unsupported curve_id {curve_id!r}; supported curves are SOFR, CORRA, AONIA")
    parsed = parse_contract_id(f"{curve}_{expiry}")
    if parsed is None:
        raise StructureError(f"{curve} expiry {expiry!r} is not a contract month")
    return parsed


def _fx_for(parsed: ParsedContract, market_state: Mapping[str, Any] | None, explicit: Mapping[str, Any] | None) -> tuple[float, str | None]:
    if isinstance(explicit, Mapping) and parsed.spec.currency in explicit:
        try:
            rate = float(explicit[parsed.spec.currency])
        except (TypeError, ValueError) as exc:
            raise StructureError(f"fx for {parsed.spec.currency} is not numeric") from exc
        if rate <= 0:
            raise StructureError(f"fx for {parsed.spec.currency} must be positive")
        return rate, "expression.fx_usd_per_unit"
    rate, pair = fx_usd_per_unit(parsed.spec.currency, market_state)
    if rate is None:
        raise StructureError(
            f"{parsed.spec.currency} USD conversion is unavailable for {parsed.alias}; "
            "refusing to invent an FX rate"
        )
    return rate, pair


def _leg(
    parsed: ParsedContract,
    *,
    role: str,
    template_side: str,
    contracts: float,
    fx_rate: float,
    fx_pair: str | None,
    entry_rate: float | None,
) -> dict[str, Any]:
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None:
        raise StructureError(f"DV01 unavailable for {parsed.alias}")
    return {
        "role": role,
        "instrument": parsed.alias,
        "curve_id": parsed.spec.curve_id,
        "product_code": parsed.spec.product_code,
        "venue": parsed.spec.venue,
        "expiry": parsed.expiry,
        "side": template_side,
        "contracts": contracts,
        "currency": parsed.spec.currency,
        "face_notional": parsed.spec.face_notional,
        "dv01_per_contract_local": local,
        "dv01_local": local * contracts,
        "fx_usd_per_unit": fx_rate,
        "fx_pair": fx_pair,
        "dv01_usd": local * contracts * fx_rate,
        "entry_rate": entry_rate,
        "mark_rate": entry_rate,
        "quote_unit": "implied_rate_percent",
        "economics_source": parsed.spec.source,
    }


def _apply_package_side(legs: list[dict[str, Any]], side: str) -> None:
    if side not in {"long", "short"}:
        raise StructureError("structure side must be long or short")
    if side == "long":
        return
    for leg in legs:
        leg["side"] = "short" if leg["side"] == "long" else "long"


def _balance_to(target_dv01_usd: float, parsed: ParsedContract, fx_rate: float) -> float:
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None or fx_rate <= 0:
        raise StructureError(f"cannot size {parsed.alias}")
    per_contract = local * fx_rate
    if per_contract <= 0:
        raise StructureError(f"cannot size {parsed.alias}")
    return target_dv01_usd / per_contract


def _anchor_contracts(
    parsed: ParsedContract,
    *,
    notional_usd: float | None,
    target_dv01_usd: float | None,
    fx_rate: float,
) -> tuple[float, float]:
    """Return (contracts, usd dv01 of that leg)."""
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None:
        raise StructureError(f"DV01 unavailable for {parsed.alias}")
    if target_dv01_usd is not None:
        if target_dv01_usd <= 0:
            raise StructureError("target_dv01_usd must be positive")
        contracts = _balance_to(float(target_dv01_usd), parsed, fx_rate)
        return contracts, float(target_dv01_usd)
    if notional_usd is None or notional_usd <= 0:
        raise StructureError("structure sizing needs target_dv01_usd or a positive notional_usd face")
    contracts = contracts_from_face_usd(parsed.spec, float(notional_usd), fx_rate)
    if contracts is None:
        raise StructureError(f"cannot convert face for {parsed.alias}")
    return contracts, local * contracts * fx_rate


def _rate_from_expression(expression: Mapping[str, Any], key: str) -> float | None:
    raw = expression.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise StructureError(f"{key} is not numeric") from exc


def build_structure(
    expression: Mapping[str, Any],
    *,
    side: str = "long",
    notional_usd: float | None = None,
    target_dv01_usd: float | None = None,
    market_state: Mapping[str, Any] | None = None,
    entry_rates: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build auditable legs. ``notional_usd`` is the anchor-leg face in USD."""
    kind = str(expression.get("type") or "")
    if kind == STRIP_TYPE:
        raise StructureError(
            "futures_strip_average is a strip average, not a curve spread and not a single contract"
        )
    if kind not in STRUCTURE_TYPES:
        raise StructureError(f"unsupported structure type {kind!r}")
    explicit_fx = expression.get("fx_usd_per_unit") if isinstance(expression.get("fx_usd_per_unit"), Mapping) else None
    if target_dv01_usd is None and expression.get("target_dv01_usd") not in (None, ""):
        target_dv01_usd = float(expression["target_dv01_usd"])
    target_dv01 = target_dv01_usd
    rates = dict(entry_rates or {})

    if kind == "calendar_spread":
        near = _curve_contract(str(expression.get("curve_id") or ""), str(expression.get("near_expiry") or ""))
        far = _curve_contract(str(expression.get("curve_id") or ""), str(expression.get("far_expiry") or ""))
        if near.expiry == far.expiry:
            raise StructureError("calendar near and far expiries must differ")
        if near.expiry > far.expiry:
            raise StructureError("calendar near_expiry must be earlier than far_expiry")
        near_fx, near_pair = _fx_for(near, market_state, explicit_fx)
        far_fx, far_pair = _fx_for(far, market_state, explicit_fx)
        contracts, dv01 = _anchor_contracts(near, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=near_fx)
        far_contracts = _balance_to(dv01, far, far_fx)
        legs = [
            _leg(near, role="near", template_side="short", contracts=contracts, fx_rate=near_fx, fx_pair=near_pair, entry_rate=rates.get(near.alias) or _rate_from_expression(expression, "near_rate")),
            _leg(far, role="far", template_side="long", contracts=far_contracts, fx_rate=far_fx, fx_pair=far_pair, entry_rate=rates.get(far.alias) or _rate_from_expression(expression, "far_rate")),
        ]
        mark_definition = "far implied rate minus near implied rate, in basis points"
        quote = "bps"
    elif kind == "butterfly":
        wing1 = _curve_contract(str(expression.get("curve_id") or ""), str(expression.get("wing1_expiry") or ""))
        body = _curve_contract(str(expression.get("curve_id") or ""), str(expression.get("body_expiry") or ""))
        wing2 = _curve_contract(str(expression.get("curve_id") or ""), str(expression.get("wing2_expiry") or ""))
        order = [wing1.expiry, body.expiry, wing2.expiry]
        if order != sorted(order) or len(set(order)) != 3:
            raise StructureError("butterfly expiries must be three distinct dates in wing1 < body < wing2 order")
        w1_fx, w1_pair = _fx_for(wing1, market_state, explicit_fx)
        body_fx, body_pair = _fx_for(body, market_state, explicit_fx)
        w2_fx, w2_pair = _fx_for(wing2, market_state, explicit_fx)
        contracts, dv01 = _anchor_contracts(wing1, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=w1_fx)
        # Long the canonical mark (2*body - wing1 - wing2) profits when that mark falls:
        # short the wings, long twice the body, in futures space.
        legs = [
            _leg(wing1, role="wing1", template_side="short", contracts=contracts, fx_rate=w1_fx, fx_pair=w1_pair, entry_rate=rates.get(wing1.alias) or _rate_from_expression(expression, "wing1_rate")),
            _leg(body, role="body", template_side="long", contracts=_balance_to(2.0 * dv01, body, body_fx), fx_rate=body_fx, fx_pair=body_pair, entry_rate=rates.get(body.alias) or _rate_from_expression(expression, "body_rate")),
            _leg(wing2, role="wing2", template_side="short", contracts=_balance_to(dv01, wing2, w2_fx), fx_rate=w2_fx, fx_pair=w2_pair, entry_rate=rates.get(wing2.alias) or _rate_from_expression(expression, "wing2_rate")),
        ]
        mark_definition = "(2 × body implied rate − wing1 − wing2), in basis points"
        quote = "bps"
    elif kind == "outright_rv":
        receive = expression.get("receive") if isinstance(expression.get("receive"), Mapping) else {}
        pay = expression.get("pay") if isinstance(expression.get("pay"), Mapping) else {}
        long_leg = _curve_contract(str(receive.get("curve_id") or ""), str(receive.get("expiry") or ""))
        short_leg = _curve_contract(str(pay.get("curve_id") or ""), str(pay.get("expiry") or ""))
        if long_leg.spec.curve_id == short_leg.spec.curve_id and long_leg.expiry == short_leg.expiry:
            raise StructureError("outright RV legs must not be the same contract")
        long_fx, long_pair = _fx_for(long_leg, market_state, explicit_fx)
        short_fx, short_pair = _fx_for(short_leg, market_state, explicit_fx)
        contracts, dv01 = _anchor_contracts(long_leg, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=long_fx)
        legs = [
            _leg(long_leg, role="receive", template_side="long", contracts=contracts, fx_rate=long_fx, fx_pair=long_pair, entry_rate=rates.get(long_leg.alias) or _rate_from_expression(receive, "rate")),
            _leg(short_leg, role="pay", template_side="short", contracts=_balance_to(dv01, short_leg, short_fx), fx_rate=short_fx, fx_pair=short_pair, entry_rate=rates.get(short_leg.alias) or _rate_from_expression(pay, "rate")),
        ]
        mark_definition = "receive implied rate minus pay implied rate, in basis points"
        quote = "bps"
    else:
        long_cal = expression.get("long_calendar") if isinstance(expression.get("long_calendar"), Mapping) else None
        short_cal = expression.get("short_calendar") if isinstance(expression.get("short_calendar"), Mapping) else None
        if not long_cal or not short_cal:
            raise StructureError("curve_rv requires long_calendar and short_calendar")
        built_long = build_structure(
            {"type": "calendar_spread", **dict(long_cal), "fx_usd_per_unit": explicit_fx, "target_dv01_usd": target_dv01},
            side="long",
            notional_usd=None if target_dv01 is not None else notional_usd,
            market_state=market_state,
            entry_rates=rates,
        )
        unit = built_long["spread_dv01_usd"]
        built_short = build_structure(
            {"type": "calendar_spread", **dict(short_cal), "fx_usd_per_unit": explicit_fx, "target_dv01_usd": unit},
            side="short",
            market_state=market_state,
            entry_rates=rates,
        )
        legs = []
        for leg in built_long["legs"]:
            row = dict(leg)
            row["role"] = f"long_calendar_{leg['role']}"
            legs.append(row)
        for leg in built_short["legs"]:
            row = dict(leg)
            row["role"] = f"short_calendar_{leg['role']}"
            legs.append(row)
        mark_definition = "long calendar spread minus short calendar spread, both in basis points"
        quote = "bps"
        _apply_package_side(legs, side)
        return _package(kind, legs, side=side, mark_definition=mark_definition, quote=quote, expression=expression)

    _apply_package_side(legs, side)
    return _package(kind, legs, side=side, mark_definition=mark_definition, quote=quote, expression=expression)


def _package(
    kind: str,
    legs: list[dict[str, Any]],
    *,
    side: str,
    mark_definition: str,
    quote: str,
    expression: Mapping[str, Any],
) -> dict[str, Any]:
    spread_dv01 = _spread_dv01_usd(kind, legs)
    return {
        "type": kind,
        "side": side,
        "legs": legs,
        "spread_dv01_usd": round(spread_dv01, 8),
        "quote_unit": quote,
        "mark_definition": mark_definition,
        "package_mark_bp": package_mark_bp(kind, legs),
        "structure_label": kind,
        "not_a_strip": True,
        "expression": {k: expression.get(k) for k in expression if k != "fx_usd_per_unit"},
    }


def _spread_dv01_usd(kind: str, legs: list[dict[str, Any]]) -> float:
    by_role = {leg["role"]: abs(float(leg["dv01_usd"])) for leg in legs}
    if kind == "calendar_spread":
        return by_role.get("near") or by_role.get("far") or 0.0
    if kind == "butterfly":
        return by_role.get("wing1") or 0.0
    if kind == "outright_rv":
        return by_role.get("receive") or by_role.get("pay") or 0.0
    if kind == "curve_rv":
        return by_role.get("long_calendar_near") or 0.0
    return 0.0


def package_mark_bp(kind: str, legs: list[dict[str, Any]]) -> float | None:
    rates = {}
    for leg in legs:
        rate = leg.get("mark_rate")
        if rate is None:
            rate = leg.get("entry_rate")
        if rate is None:
            return None
        rates[leg["role"]] = float(rate)
    if kind == "calendar_spread":
        if "near" not in rates or "far" not in rates:
            return None
        return (rates["far"] - rates["near"]) * 100.0
    if kind == "butterfly":
        needed = ("wing1", "body", "wing2")
        if any(role not in rates for role in needed):
            return None
        return (2.0 * rates["body"] - rates["wing1"] - rates["wing2"]) * 100.0
    if kind == "outright_rv":
        if "receive" not in rates or "pay" not in rates:
            return None
        return (rates["receive"] - rates["pay"]) * 100.0
    if kind == "curve_rv":
        keys = ("long_calendar_near", "long_calendar_far", "short_calendar_near", "short_calendar_far")
        if any(role not in rates for role in keys):
            return None
        long_spread = (rates["long_calendar_far"] - rates["long_calendar_near"]) * 100.0
        short_spread = (rates["short_calendar_far"] - rates["short_calendar_near"]) * 100.0
        return long_spread - short_spread
    return None


def leg_pnl_usd(leg: Mapping[str, Any]) -> float | None:
    entry = leg.get("entry_rate")
    mark = leg.get("mark_rate")
    fx = leg.get("fx_usd_per_unit")
    local = leg.get("dv01_per_contract_local")
    contracts = leg.get("contracts")
    if entry is None or mark is None or fx is None or local is None or contracts is None:
        return None
    bp = (float(mark) - float(entry)) * 100.0
    sign = 1.0 if leg.get("side") == "long" else -1.0
    # Long futures: profit when the implied rate falls.
    return -sign * float(contracts) * float(local) * bp * float(fx)


def structure_pnl_usd(legs: list[Mapping[str, Any]] | None) -> float | None:
    if not legs:
        return None
    total = 0.0
    for leg in legs:
        pnl = leg_pnl_usd(leg)
        if pnl is None:
            return None
        total += pnl
    return total


def update_leg_marks(legs: list[dict[str, Any]], rates: Mapping[str, float]) -> None:
    for leg in legs:
        key = str(leg.get("instrument") or "")
        if key in rates:
            leg["mark_rate"] = float(rates[key])
            continue
        role = str(leg.get("role") or "")
        if role in rates:
            leg["mark_rate"] = float(rates[role])


def scale_legs(legs: list[dict[str, Any]], ratio: float, *, average_entries: bool = False) -> None:
    if ratio < 0:
        raise StructureError("leg scale cannot be negative")
    for leg in legs:
        if average_entries and ratio > 1 and leg.get("entry_rate") is not None and leg.get("mark_rate") is not None:
            added = ratio - 1.0
            leg["entry_rate"] = (float(leg["entry_rate"]) + added * float(leg["mark_rate"])) / ratio
        leg["contracts"] = float(leg["contracts"]) * ratio
        local = float(leg["dv01_per_contract_local"])
        fx = float(leg["fx_usd_per_unit"])
        leg["dv01_local"] = local * float(leg["contracts"])
        leg["dv01_usd"] = leg["dv01_local"] * fx
