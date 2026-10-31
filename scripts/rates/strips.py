"""Futures strip average: equal-direction STIR legs, package P&L = sum of leg P&L."""

from __future__ import annotations

from typing import Any, Mapping

from scripts.rates.contract_economics import (
    CURVE_SPEC,
    LOT_ROUNDING_POLICY,
    ParsedContract,
    contracts_from_face_usd,
    current_fx_quote,
    dv01_per_contract,
    parse_contract_id,
    whole_lots,
)
from scripts.rates.structures import (
    STRIP_TYPE,
    StructureError,
    structure_pnl_usd,
)

STRIP_TYPE = STRIP_TYPE  # noqa: F811 — re-export same constant as structures.STRIP_TYPE
FAMILY = "futures_strip"


def _curve_contract(curve_id: str, expiry: str) -> ParsedContract:
    curve = str(curve_id or "").upper()
    if curve not in CURVE_SPEC:
        raise StructureError(f"unsupported curve_id {curve_id!r}; supported curves are SOFR, CORRA, AONIA")
    parsed = parse_contract_id(f"{curve}_{expiry}")
    if parsed is None:
        raise StructureError(f"{curve} expiry {expiry!r} is not a contract month")
    return parsed


def _fx_for(parsed: ParsedContract, market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    quote = current_fx_quote(parsed.spec.currency, market_state)
    if quote.get("status") != "ok" or quote.get("usd_per_unit") is None:
        raise StructureError(
            f"{parsed.spec.currency} USD conversion is {quote.get('status') or 'unavailable'} for {parsed.alias}; "
            "refusing to reuse an older FX fixing or invent a rate"
        )
    return quote


def _implied_rate_path(curve_id: str, expiry: str) -> str:
    return f"tradable_rate_curves.{curve_id.upper()}.contracts.{expiry}.implied_rate"


def _read_implied_rate(
    curve_id: str,
    expiry: str,
    market_state: Mapping[str, Any] | None,
) -> tuple[float, str]:
    path = _implied_rate_path(curve_id, expiry)
    curves = market_state.get("tradable_rate_curves") if isinstance(market_state, Mapping) else None
    curve_map = curves.get("curves") if isinstance(curves, Mapping) else None
    block = curve_map.get(curve_id.upper()) if isinstance(curve_map, Mapping) else None
    if not isinstance(block, Mapping) or str(block.get("status") or "") != "ok":
        raise StructureError(f"missing or unavailable rate at {path}")
    target = str(expiry)
    for row in block.get("contracts") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("expiry") or "") != target:
            continue
        raw = row.get("implied_rate")
        if raw in (None, ""):
            raise StructureError(f"missing or unavailable rate at {path}")
        try:
            return float(raw), path
        except (TypeError, ValueError) as exc:
            raise StructureError(f"missing or unavailable rate at {path}") from exc
    raise StructureError(f"missing or unavailable rate at {path}")


def _leg(
    parsed: ParsedContract,
    *,
    role: str,
    template_side: str,
    contracts: int,
    contracts_unrounded: float,
    fx_quote: Mapping[str, Any],
    entry_rate: float,
    mark_rate: float,
    mark_status: str,
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
        "rounding_policy": LOT_ROUNDING_POLICY,
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
        "mark_rate": mark_rate,
        "mark_status": mark_status,
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


def _normalize_weights(expiries: list[str], weights: Any) -> list[float]:
    if weights is None:
        return [1.0] * len(expiries)
    if not isinstance(weights, list) or len(weights) != len(expiries):
        raise StructureError("futures_strip_average weights must match expiries")
    out: list[float] = []
    for raw in weights:
        try:
            w = float(raw)
        except (TypeError, ValueError) as exc:
            raise StructureError("futures_strip_average weights must be positive") from exc
        if w <= 0:
            raise StructureError("futures_strip_average weights must be positive")
        out.append(w)
    return out


def build_strip(
    expression: Mapping[str, Any],
    *,
    side: str = "long",
    notional_usd: float | None = None,
    target_dv01_usd: float | None = None,
    market_state: Mapping[str, Any] | None = None,
    entry_rates: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    kind = str(expression.get("type") or "")
    if kind != STRIP_TYPE:
        raise StructureError(f"expected expression type {STRIP_TYPE!r}, got {kind!r}")
    curve_id = str(expression.get("curve_id") or "")
    expiries = expression.get("expiries")
    if not isinstance(expiries, list) or not expiries:
        raise StructureError("futures_strip_average requires non-empty expiries")
    weights = _normalize_weights(expiries, expression.get("weights"))
    weight_sum = sum(weights)

    if target_dv01_usd is None and expression.get("target_dv01_usd") not in (None, ""):
        target_dv01_usd = float(expression["target_dv01_usd"])

    use_notional = notional_usd is not None
    use_target = not use_notional and target_dv01_usd is not None
    if use_notional:
        if float(notional_usd) <= 0:
            raise StructureError("notional_usd must be positive")
    elif use_target:
        if float(target_dv01_usd) <= 0:
            raise StructureError("target_dv01_usd must be positive")
    else:
        raise StructureError("structure sizing needs target_dv01_usd or a positive notional_usd face")

    rates = dict(entry_rates or {})
    legs: list[dict[str, Any]] = []
    mark_sources: list[str] = []
    weighted_mark = 0.0

    for expiry, weight in zip(expiries, weights):
        parsed = _curve_contract(curve_id, str(expiry))
        mark_rate, rate_path = _read_implied_rate(parsed.spec.curve_id, parsed.expiry, market_state)
        mark_sources.append(rate_path)
        entry_rate = float(rates[parsed.alias]) if parsed.alias in rates else mark_rate
        fx_quote = _fx_for(parsed, market_state)
        fx_rate = float(fx_quote["usd_per_unit"])
        local = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
        if local is None:
            raise StructureError(f"DV01 unavailable for {parsed.alias}")

        share = weight / weight_sum
        if use_notional:
            face_i = float(notional_usd) * share
            raw = contracts_from_face_usd(parsed.spec, face_i, fx_rate)
            if raw is None:
                raise StructureError(f"cannot convert face for {parsed.alias}")
            lots = whole_lots(raw, policy=LOT_ROUNDING_POLICY)
            if lots < 1:
                raise StructureError(
                    f"{parsed.alias} descriptive notional is {raw:.4f} lots, below one exchange contract"
                )
        else:
            target_i = float(target_dv01_usd) * share
            per_contract = local * fx_rate
            if per_contract <= 0:
                raise StructureError(f"cannot size {parsed.alias}")
            raw = target_i / per_contract
            lots = whole_lots(raw, policy=LOT_ROUNDING_POLICY)
            if lots < 1:
                raise StructureError(
                    f"{parsed.alias} target is {raw:.4f} lots, below one exchange contract; "
                    "refusing a fractional booking"
                )

        role = f"strip_{parsed.expiry}"
        legs.append(
            _leg(
                parsed,
                role=role,
                template_side="long",
                contracts=lots,
                contracts_unrounded=raw,
                fx_quote=fx_quote,
                entry_rate=entry_rate,
                mark_rate=mark_rate,
                mark_status="ok",
            )
        )
        weighted_mark += weight * mark_rate

    _apply_package_side(legs, side)
    spread_dv01 = sum(float(leg["dv01_usd"]) for leg in legs)
    package_mark = weighted_mark / weight_sum

    return {
        "type": STRIP_TYPE,
        "side": side,
        "legs": legs,
        "spread_dv01_usd": round(spread_dv01, 8),
        "shock_dv01_usd": round(spread_dv01, 8),
        "shock_policy": "sum_leg_dv01",
        "quote_unit": "percent",
        "package_mark_percent": round(package_mark, 8),
        "mark_definition": "weighted average implied rate, percent; not a curve spread",
        "structure_label": STRIP_TYPE,
        "not_a_strip": False,
        "not_a_curve_spread": True,
        "valuation_method": "instrument_dv01",
        "isolated": False,
        "expression": {k: v for k, v in expression.items() if k != "fx_usd_per_unit"},
        "mark_sources": mark_sources,
    }


def strip_pnl_usd(legs: list[Mapping[str, Any]] | None) -> float | None:
    return structure_pnl_usd(legs)


def _strip_verdict_base(expression: Mapping[str, Any]) -> dict[str, Any]:
    curve = str(expression.get("curve_id") or "").upper()
    expiries = expression.get("expiries") if isinstance(expression.get("expiries"), list) else []
    instrument = f"{curve}_strip" if curve else None
    if expiries:
        instrument = f"{curve}_{expiries[0]}" if curve else str(expiries[0])
    return {
        "family": FAMILY,
        "instrument": instrument,
        "expression_type": STRIP_TYPE,
        "missing_inputs": [],
    }


def _classify_strip_error(exc: StructureError) -> tuple[str, list[str]]:
    msg = str(exc)
    missing: list[str] = []
    if "tradable_rate_curves." in msg and "implied_rate" in msg:
        for token in msg.split():
            if token.startswith("tradable_rate_curves."):
                missing.append(token.rstrip("."))
        if not missing and " at " in msg:
            missing.append(msg.split(" at ", 1)[-1])
        return "missing_input", missing
    if "unsupported curve_id" in msg:
        return "unsupported", missing
    if "USD conversion" in msg or "unavailable" in msg.lower():
        if "tradable_rate_curves" in msg:
            return "missing_input", missing
        return "unavailable", missing
    if "below one exchange contract" in msg or "fractional booking" in msg:
        return "unavailable", missing
    if "requires non-empty" in msg or "must be positive" in msg or "sizing needs" in msg:
        return "missing_input", missing
    return "missing_input", missing


def assess_strip(
    expression: Mapping[str, Any],
    *,
    side: str = "long",
    notional_usd: float | None = None,
    target_dv01_usd: float | None = None,
    market_state: Mapping[str, Any] | None = None,
    entry_rates: Mapping[str, float] | None = None,
) -> dict[str, Any] | None:
    if str(expression.get("type") or "") != STRIP_TYPE:
        return None
    base = _strip_verdict_base(expression)
    try:
        built = build_strip(
            expression,
            side=side,
            notional_usd=notional_usd,
            target_dv01_usd=target_dv01_usd,
            market_state=market_state,
            entry_rates=entry_rates,
        )
    except StructureError as exc:
        status, missing = _classify_strip_error(exc)
        return {
            **base,
            "status": status,
            "bookable": False,
            "reason": str(exc),
            "missing_inputs": missing,
            "mark_status": "missing" if status == "missing_input" else "unavailable",
            "mark_source": None,
        }
    mark_source = "; ".join(built.get("mark_sources") or [])
    return {
        **base,
        "status": "executable",
        "bookable": True,
        "reason": "strip legs sized and marked from tradable_rate_curves",
        "missing_inputs": [],
        "mark_status": "ok",
        "mark_source": mark_source,
    }
