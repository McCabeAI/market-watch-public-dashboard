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
    HEDGE_LOT_ROUNDING_POLICY,
    LOT_ROUNDING_POLICY,
    ParsedContract,
    contracts_from_face_usd,
    current_fx_quote,
    dv01_per_contract,
    parse_contract_id,
    whole_lots,
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


def _fx_for(parsed: ParsedContract, market_state: Mapping[str, Any] | None, explicit: Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(explicit, Mapping) and parsed.spec.currency in explicit:
        try:
            rate = float(explicit[parsed.spec.currency])
        except (TypeError, ValueError) as exc:
            raise StructureError(f"fx for {parsed.spec.currency} is not numeric") from exc
        if rate <= 0:
            raise StructureError(f"fx for {parsed.spec.currency} must be positive")
        return {
            "status": "ok",
            "usd_per_unit": rate,
            "pair": None,
            "as_of": None,
            "source": "expression.fx_usd_per_unit",
        }
    quote = current_fx_quote(parsed.spec.currency, market_state)
    if quote.get("status") != "ok" or quote.get("usd_per_unit") is None:
        raise StructureError(
            f"{parsed.spec.currency} USD conversion is {quote.get('status') or 'unavailable'} for {parsed.alias}; "
            "refusing to reuse an older FX fixing or invent a rate"
        )
    return quote


def _leg(
    parsed: ParsedContract,
    *,
    role: str,
    template_side: str,
    contracts: int,
    contracts_unrounded: float,
    fx_quote: Mapping[str, Any],
    entry_rate: float | None,
    rounding_policy: str,
) -> dict[str, Any]:
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None:
        raise StructureError(f"DV01 unavailable for {parsed.alias}")
    if int(contracts) != contracts or contracts < 0:
        raise StructureError(f"{parsed.alias} contracts must be a whole lot count")
    fx_rate = float(fx_quote["usd_per_unit"])
    residual_contracts = float(contracts_unrounded) - int(contracts)
    return {
        "role": role,
        "instrument": parsed.alias,
        "curve_id": parsed.spec.curve_id,
        "product_code": parsed.spec.product_code,
        "venue": parsed.spec.venue,
        "expiry": parsed.expiry,
        "side": template_side,
        "contracts": int(contracts),
        "contracts_unrounded": contracts_unrounded,
        "residual_contracts": residual_contracts,
        "rounding_policy": rounding_policy,
        "currency": parsed.spec.currency,
        "face_notional": parsed.spec.face_notional,
        "dv01_per_contract_local": local,
        "dv01_local": local * int(contracts),
        "entry_fx_usd_per_unit": fx_rate,
        "entry_fx_pair": fx_quote.get("pair"),
        "entry_fx_as_of": fx_quote.get("as_of"),
        "entry_fx_source": fx_quote.get("source"),
        "mark_fx_usd_per_unit": fx_rate,
        "mark_fx_pair": fx_quote.get("pair"),
        "mark_fx_as_of": fx_quote.get("as_of"),
        "mark_fx_source": fx_quote.get("source"),
        "mark_fx_status": "ok",
        "dv01_usd": local * int(contracts) * fx_rate,
        "entry_rate": entry_rate,
        "mark_rate": entry_rate,
        "mark_status": "ok" if entry_rate is not None else "pending",
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


def _lots_for_target(target_dv01_usd: float, parsed: ParsedContract, fx_rate: float, *, policy: str) -> tuple[int, float, float]:
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None or fx_rate <= 0:
        raise StructureError(f"cannot size {parsed.alias}")
    per_contract = local * fx_rate
    if per_contract <= 0:
        raise StructureError(f"cannot size {parsed.alias}")
    raw = target_dv01_usd / per_contract
    lots = whole_lots(raw, policy=policy)
    if lots < 1:
        raise StructureError(
            f"{parsed.alias} target is {raw:.4f} lots, below one exchange contract; "
            "refusing a fractional booking"
        )
    return lots, raw, lots * per_contract


def _anchor_contracts(
    parsed: ParsedContract,
    *,
    notional_usd: float | None,
    target_dv01_usd: float | None,
    fx_rate: float,
) -> tuple[int, float, float]:
    """Return (whole lots, unrounded lots, achieved USD DV01)."""
    local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local is None:
        raise StructureError(f"DV01 unavailable for {parsed.alias}")
    if target_dv01_usd is not None:
        if target_dv01_usd <= 0:
            raise StructureError("target_dv01_usd must be positive")
        return _lots_for_target(float(target_dv01_usd), parsed, fx_rate, policy=LOT_ROUNDING_POLICY)
    if notional_usd is None or notional_usd <= 0:
        raise StructureError("structure sizing needs target_dv01_usd or a positive notional_usd face")
    raw = contracts_from_face_usd(parsed.spec, float(notional_usd), fx_rate)
    if raw is None:
        raise StructureError(f"cannot convert face for {parsed.alias}")
    lots = whole_lots(raw, policy=LOT_ROUNDING_POLICY)
    if lots < 1:
        raise StructureError(
            f"{parsed.alias} descriptive notional is {raw:.4f} lots, below one exchange contract"
        )
    return lots, raw, lots * local * fx_rate


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
        near_fx = _fx_for(near, market_state, explicit_fx)
        far_fx = _fx_for(far, market_state, explicit_fx)
        contracts, raw_near, dv01 = _anchor_contracts(
            near, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=float(near_fx["usd_per_unit"])
        )
        far_lots, raw_far, _far_dv01 = _lots_for_target(
            dv01, far, float(far_fx["usd_per_unit"]), policy=HEDGE_LOT_ROUNDING_POLICY
        )
        legs = [
            _leg(near, role="near", template_side="short", contracts=contracts, contracts_unrounded=raw_near, fx_quote=near_fx, rounding_policy=LOT_ROUNDING_POLICY, entry_rate=rates.get(near.alias) or _rate_from_expression(expression, "near_rate")),
            _leg(far, role="far", template_side="long", contracts=far_lots, contracts_unrounded=raw_far, fx_quote=far_fx, rounding_policy=HEDGE_LOT_ROUNDING_POLICY, entry_rate=rates.get(far.alias) or _rate_from_expression(expression, "far_rate")),
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
        w1_fx = _fx_for(wing1, market_state, explicit_fx)
        body_fx = _fx_for(body, market_state, explicit_fx)
        w2_fx = _fx_for(wing2, market_state, explicit_fx)
        contracts, raw_wing, dv01 = _anchor_contracts(
            wing1, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=float(w1_fx["usd_per_unit"])
        )
        # Long the canonical mark (2*body - wing1 - wing2) profits when that mark falls:
        # short the wings, long twice the body, in futures space.
        body_lots, raw_body, _body_dv01 = _lots_for_target(
            2.0 * dv01, body, float(body_fx["usd_per_unit"]), policy=HEDGE_LOT_ROUNDING_POLICY
        )
        wing2_lots, raw_wing2, _wing2_dv01 = _lots_for_target(
            dv01, wing2, float(w2_fx["usd_per_unit"]), policy=HEDGE_LOT_ROUNDING_POLICY
        )
        legs = [
            _leg(wing1, role="wing1", template_side="short", contracts=contracts, contracts_unrounded=raw_wing, fx_quote=w1_fx, rounding_policy=LOT_ROUNDING_POLICY, entry_rate=rates.get(wing1.alias) or _rate_from_expression(expression, "wing1_rate")),
            _leg(body, role="body", template_side="long", contracts=body_lots, contracts_unrounded=raw_body, fx_quote=body_fx, rounding_policy=HEDGE_LOT_ROUNDING_POLICY, entry_rate=rates.get(body.alias) or _rate_from_expression(expression, "body_rate")),
            _leg(wing2, role="wing2", template_side="short", contracts=wing2_lots, contracts_unrounded=raw_wing2, fx_quote=w2_fx, rounding_policy=HEDGE_LOT_ROUNDING_POLICY, entry_rate=rates.get(wing2.alias) or _rate_from_expression(expression, "wing2_rate")),
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
        long_fx = _fx_for(long_leg, market_state, explicit_fx)
        short_fx = _fx_for(short_leg, market_state, explicit_fx)
        contracts, raw_long, dv01 = _anchor_contracts(
            long_leg, notional_usd=notional_usd, target_dv01_usd=target_dv01, fx_rate=float(long_fx["usd_per_unit"])
        )
        short_lots, raw_short, _short_dv01 = _lots_for_target(
            dv01, short_leg, float(short_fx["usd_per_unit"]), policy=HEDGE_LOT_ROUNDING_POLICY
        )
        legs = [
            _leg(long_leg, role="receive", template_side="long", contracts=contracts, contracts_unrounded=raw_long, fx_quote=long_fx, rounding_policy=LOT_ROUNDING_POLICY, entry_rate=rates.get(long_leg.alias) or _rate_from_expression(receive, "rate")),
            _leg(short_leg, role="pay", template_side="short", contracts=short_lots, contracts_unrounded=raw_short, fx_quote=short_fx, rounding_policy=HEDGE_LOT_ROUNDING_POLICY, entry_rate=rates.get(short_leg.alias) or _rate_from_expression(pay, "rate")),
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


def leg_pnl_for_contracts(leg: Mapping[str, Any], contracts: int) -> float | None:
    """USD P&L for an explicit whole-lot slice at the leg's current mark and FX."""
    if contracts < 0:
        return None
    if contracts == 0:
        return 0.0
    if leg.get("mark_status") == "unavailable":
        return None
    entry = leg.get("entry_rate")
    mark = leg.get("mark_rate")
    fx = leg.get("mark_fx_usd_per_unit")
    if leg.get("mark_fx_status") not in (None, "ok"):
        return None
    local = leg.get("dv01_per_contract_local")
    if entry is None or mark is None or fx is None or local is None:
        return None
    bp = (float(mark) - float(entry)) * 100.0
    sign = 1.0 if leg.get("side") == "long" else -1.0
    return -sign * int(contracts) * float(local) * bp * float(fx)


def leg_pnl_usd(leg: Mapping[str, Any]) -> float | None:
    """Current USD P&L. Uses the mark FX vintage only, never the entry fixing."""
    contracts = leg.get("contracts")
    if contracts is None:
        return None
    return leg_pnl_for_contracts(leg, int(contracts))


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


def recompute_leg_dv01(leg: dict[str, Any]) -> None:
    contracts = int(leg.get("contracts") or 0)
    leg["contracts"] = contracts
    local = float(leg["dv01_per_contract_local"])
    leg["dv01_local"] = local * contracts
    fx = leg.get("mark_fx_usd_per_unit")
    leg["dv01_usd"] = None if fx in (None, "") else local * contracts * float(fx)


def scale_legs(legs: list[dict[str, Any]], ratio: float, *, average_entries: bool = False) -> None:
    """Resize to whole lots. The descriptive notional is not written back onto contracts."""
    if ratio < 0:
        raise StructureError("leg scale cannot be negative")
    for leg in legs:
        old = int(leg.get("contracts") or 0)
        new_lots = whole_lots(old * ratio, policy=LOT_ROUNDING_POLICY)
        if average_entries and new_lots > old and leg.get("entry_rate") is not None and leg.get("mark_rate") is not None and old > 0:
            added = new_lots - old
            leg["entry_rate"] = (float(leg["entry_rate"]) * old + float(leg["mark_rate"]) * added) / new_lots
        leg["contracts"] = new_lots
        leg["rounding_policy"] = LOT_ROUNDING_POLICY
        recompute_leg_dv01(leg)


def apply_mark_fx(legs: list[dict[str, Any]], market_state: Mapping[str, Any] | None) -> bool:
    """Write the current frozen FX onto every leg. Returns False if any fixing is unusable."""
    ok = True
    for leg in legs:
        quote = current_fx_quote(str(leg.get("currency") or ""), market_state)
        if quote.get("status") != "ok" or quote.get("usd_per_unit") is None:
            leg["mark_fx_usd_per_unit"] = None
            leg["mark_fx_status"] = quote.get("status") or "unavailable"
            leg["mark_fx_as_of"] = quote.get("as_of")
            leg["mark_fx_source"] = quote.get("source")
            leg["mark_fx_pair"] = quote.get("pair")
            leg["dv01_usd"] = None
            ok = False
            continue
        leg["mark_fx_usd_per_unit"] = quote["usd_per_unit"]
        leg["mark_fx_pair"] = quote.get("pair")
        leg["mark_fx_as_of"] = quote.get("as_of")
        leg["mark_fx_source"] = quote.get("source")
        leg["mark_fx_status"] = "ok"
        recompute_leg_dv01(leg)
    return ok
