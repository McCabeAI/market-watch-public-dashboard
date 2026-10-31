"""Paper rates executable catalog only.

Preflight and book admission both call ``assess_expression``; there is no second
checker. Marks come only from the frozen ``market_state`` — nothing is invented.
Distinct 2Y expressions (government yield, TU/ZT, USD SOFR OIS, SOFR futures strip)
are never substituted for one another.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Mapping

from scripts.rates.contract_economics import (
    CURVE_SPEC,
    current_fx_quote,
    dv01_per_contract,
    is_sovereign_instrument,
    lots_from_face_usd,
    parse_contract_id,
)
from scripts.rates.structures import STRUCTURE_TYPES, StructureError, build_structure

FAMILIES = (
    "stir_outright",
    "futures_strip",
    "curve_structure",
    "usd_sofr_ois",
    "treasury_future",
    "government_yield",
    "other",
)

_QUARTERLY_MONTHS = frozenset({3, 6, 9, 12})
_TREASURY_ROOT = re.compile(r"^(TU|ZT|FV|ZF|TY|ZN)(?:[_-](20\d{2}-\d{2}))?$")
_STRIP_INSTRUMENT = re.compile(r"^[A-Z]+_STRIP_", re.I)
_OIS_INSTRUMENT = re.compile(r"^USD_SOFR_OIS_", re.I)
_SOVEREIGN_NORMALIZE = re.compile(
    r"^(US|CA|AU|NZ|EA|JP)[\s_-]+(2Y|5Y|10Y|30Y|LONG)$",
    re.IGNORECASE,
)

_EXPRESSION_FAMILY = {
    "calendar_spread": "curve_structure",
    "butterfly": "curve_structure",
    "outright_rv": "curve_structure",
    "curve_rv": "curve_structure",
    "futures_strip_average": "futures_strip",
    "usd_sofr_ois": "usd_sofr_ois",
    "treasury_future": "treasury_future",
    "forward_swap": "other",
    "outright": "stir_outright",
}

_ASSESSOR_PATHS = {
    "futures_strip": ("scripts.rates.strips", "assess_strip", "scripts.rates.strips.assess_strip"),
    "usd_sofr_ois": ("scripts.rates.ois", "assess_ois", "scripts.rates.ois.assess_ois"),
    "treasury_future": ("scripts.rates.treasury_futures", "assess_treasury", "scripts.rates.treasury_futures.assess_treasury"),
}

_TWO_YEAR_FAMILIES = frozenset({"government_yield", "treasury_future", "usd_sofr_ois", "futures_strip"})


def normalize_instrument(instrument: str | None) -> str | None:
    if not instrument or not isinstance(instrument, str):
        return None
    raw = instrument.strip()
    sovereign = _SOVEREIGN_NORMALIZE.fullmatch(raw)
    if sovereign:
        return f"{sovereign.group(1).upper()}_{sovereign.group(2).upper()}"
    return raw.upper()


def _expression_type(expression: Mapping[str, Any] | None) -> str | None:
    if not isinstance(expression, Mapping):
        return None
    kind = expression.get("type")
    if kind in (None, ""):
        return None
    return str(kind)


def _verdict(
    *,
    status: str,
    reason: str,
    family: str,
    instrument: str | None = None,
    expression_type: str | None = None,
    missing_inputs: list[str] | None = None,
    mark_status: str = "not_applicable",
    mark_source: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "bookable": status == "executable",
        "reason": reason,
        "missing_inputs": list(missing_inputs or []),
        "family": family,
        "instrument": instrument,
        "expression_type": expression_type,
        "mark_status": mark_status,
        "mark_source": mark_source,
    }


def _instrument_implied_family(instrument: str | None) -> str | None:
    if not instrument:
        return None
    normalized = normalize_instrument(instrument)
    if normalized and is_sovereign_instrument(normalized):
        return "government_yield"
    if normalized and _OIS_INSTRUMENT.match(normalized):
        return "usd_sofr_ois"
    if normalized and _STRIP_INSTRUMENT.match(normalized):
        return "futures_strip"
    if normalized and _TREASURY_ROOT.fullmatch(normalized.replace(" ", "")):
        return "treasury_future"
    if parse_contract_id(normalized or instrument):
        return "stir_outright"
    return None


def _substitution_conflict(instrument: str | None, expression: Mapping[str, Any] | None) -> dict[str, Any] | None:
    expr_type = _expression_type(expression)
    if expr_type in STRUCTURE_TYPES:
        return None
    expr_family = _EXPRESSION_FAMILY.get(expr_type) if expr_type else None
    inst_family = _instrument_implied_family(instrument)
    if expr_type == "outright" and inst_family == "stir_outright":
        return None
    if expr_family is None or inst_family is None:
        return None
    if expr_family == inst_family:
        return None
    if expr_family != inst_family:
        return _verdict(
            status="unsupported",
            reason=(
                f"refusing silent substitution: instrument {normalize_instrument(instrument)!r} "
                f"is {inst_family} but expression type {expr_type!r} is {expr_family}"
            ),
            family="other",
            instrument=normalize_instrument(instrument),
            expression_type=expr_type,
            mark_status="not_applicable",
        )
    return None


def _tradable_curves(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(market_state, Mapping):
        return {}
    block = market_state.get("tradable_rate_curves")
    if not isinstance(block, Mapping) or str(block.get("status") or "") != "ok":
        return {}
    curves = block.get("curves")
    return dict(curves) if isinstance(curves, Mapping) else {}


def _curve_contract_rows(curve_id: str, market_state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    block = _tradable_curves(market_state).get(curve_id.upper())
    if not isinstance(block, Mapping):
        return []
    rows = block.get("contracts")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        expiry = row.get("expiry")
        if not isinstance(expiry, str):
            continue
        out.append(dict(row))
    return out


def _contract_implied_rate(
    market_state: Mapping[str, Any] | None,
    curve_id: str,
    expiry: str,
) -> tuple[float | None, str | None, str | None]:
    """Return (rate, mark_source, missing_path)."""
    cid = curve_id.upper()
    for row in _curve_contract_rows(cid, market_state):
        if str(row.get("expiry")) == expiry:
            rate = row.get("implied_rate")
            if rate is None:
                path = f"tradable_rate_curves.{cid}.contracts.{expiry}.implied_rate"
                return None, None, path
            try:
                return float(rate), f"tradable_rate_curves.{cid}.contracts.{expiry}.implied_rate", None
            except (TypeError, ValueError):
                path = f"tradable_rate_curves.{cid}.contracts.{expiry}.implied_rate"
                return None, None, path
    path = f"tradable_rate_curves.{cid}.contracts.{expiry}.implied_rate"
    return None, None, path


def _quarterly_expiries(market_state: Mapping[str, Any] | None, curve_id: str) -> list[str]:
    expiries: list[str] = []
    for row in _curve_contract_rows(curve_id, market_state):
        expiry = str(row.get("expiry") or "")
        if not expiry or "-" not in expiry:
            continue
        try:
            month = int(expiry.split("-", 1)[1])
        except ValueError:
            continue
        if month in _QUARTERLY_MONTHS:
            expiries.append(expiry)
    return sorted(set(expiries))


def _sovereign_mark(
    market_state: Mapping[str, Any] | None,
    instrument: str,
) -> tuple[str, str | None]:
    normalized = normalize_instrument(instrument) or instrument
    match = re.fullmatch(r"([A-Z]{2})_(2Y|5Y|10Y|30Y|LONG)", normalized)
    if not match or not isinstance(market_state, Mapping):
        return "missing", None
    country, tenor = match.group(1), match.group(2)
    rates = market_state.get("rates")
    if not isinstance(rates, Mapping):
        return "missing", None
    block = rates.get(country)
    if not isinstance(block, Mapping):
        return "missing", None
    if str(block.get("status") or "") in {"stale", "missing", "invalid", "unavailable"}:
        return "unavailable", None
    tenors = block.get("tenors") if isinstance(block.get("tenors"), Mapping) else block
    row = tenors.get(tenor) if isinstance(tenors, Mapping) else None
    value = row.get("value") if isinstance(row, Mapping) else row
    if value is None:
        return "missing", None
    try:
        float(value)
    except (TypeError, ValueError):
        return "missing", None
    return "ok", f"market_state.rates.{country}.{tenor}"


def _assessor_missing(family: str) -> dict[str, Any]:
    _mod, _fn, path = _ASSESSOR_PATHS[family]
    return _verdict(
        status="missing_input",
        reason=f"assessor not installed for {family}",
        family=family,
        missing_inputs=[path],
        mark_status="not_applicable",
    )


def _delegate_assessor(
    family: str,
    instrument: str | None,
    expression: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
) -> dict[str, Any]:
    module_name, func_name, path = _ASSESSOR_PATHS[family]
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        missing = _assessor_missing(family)
        missing["instrument"] = normalize_instrument(instrument)
        missing["expression_type"] = _expression_type(expression)
        return missing
    assess = getattr(module, func_name, None)
    if assess is None:
        missing = _assessor_missing(family)
        missing["instrument"] = normalize_instrument(instrument)
        missing["expression_type"] = _expression_type(expression)
        return missing
    if family == "futures_strip":
        if not isinstance(expression, Mapping):
            return _verdict(
                status="missing_input",
                reason="futures_strip_average requires an expression payload",
                family=family,
                instrument=normalize_instrument(instrument),
                expression_type=_expression_type(expression),
                missing_inputs=["expression.type"],
            )
        if notional_usd is not None:
            probe_notional = float(notional_usd)
        else:
            expiries = expression.get("expiries")
            if not isinstance(expiries, list) or not expiries:
                return _verdict(
                    status="missing_input",
                    reason="futures_strip_average requires non-empty expiries",
                    family=family,
                    instrument=normalize_instrument(instrument),
                    expression_type=_expression_type(expression),
                    missing_inputs=["expression.expiries"],
                )
            probe_notional = max(1, len(expiries)) * 1_000_000
        result = assess(
            expression,
            notional_usd=probe_notional,
            market_state=market_state,
        )
    elif family == "usd_sofr_ois":
        if not isinstance(expression, Mapping):
            return _verdict(
                status="missing_input",
                reason="usd_sofr_ois requires an expression payload",
                family=family,
                instrument=normalize_instrument(instrument),
                expression_type=_expression_type(expression),
                missing_inputs=["expression.type"],
            )
        probe_notional = float(notional_usd) if notional_usd is not None else 1_000_000
        result = assess(expression, notional_usd=probe_notional, market_state=market_state)
    else:
        result = assess(instrument, expression, market_state, notional_usd)
    if result is None:
        return _verdict(
            status="unsupported",
            reason=f"assessor declined {family} for this instrument/expression pair",
            family=family,
            instrument=normalize_instrument(instrument),
            expression_type=_expression_type(expression),
        )
    return dict(result)


def _assess_stir_outright(
    instrument: str,
    expression: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
) -> dict[str, Any]:
    normalized = normalize_instrument(instrument) or instrument
    parsed = parse_contract_id(normalized)
    expr_type = _expression_type(expression)
    if parsed is None:
        return _verdict(
            status="unsupported",
            reason=f"instrument {normalized!r} is not a tradable STIR contract id",
            family="stir_outright",
            instrument=normalized,
            expression_type=expr_type,
        )
    alias = parsed.alias
    fx = current_fx_quote(parsed.spec.currency, market_state)
    pair = fx.get("pair")
    missing: list[str] = []
    if fx.get("status") != "ok" or fx.get("usd_per_unit") is None:
        if pair:
            missing.append(f"market_state.fx.pairs.{pair}")
        return _verdict(
            status="unavailable",
            reason=(
                f"{parsed.spec.currency} USD conversion is {fx.get('status') or 'unavailable'} "
                f"for {alias}; refusing to book without a frozen FX observation"
            ),
            family="stir_outright",
            instrument=alias,
            expression_type=expr_type,
            missing_inputs=missing,
            mark_status="not_applicable",
        )
    local_dv01 = dv01_per_contract(parsed.spec, year=parsed.year, month=parsed.month)
    if local_dv01 is None:
        return _verdict(
            status="missing_input",
            reason=f"verified DV01 unavailable for {alias}",
            family="stir_outright",
            instrument=alias,
            expression_type=expr_type,
            missing_inputs=[f"contract_economics.{parsed.spec.product_code}.dv01"],
            mark_status="not_applicable",
        )
    if notional_usd is not None:
        sized = lots_from_face_usd(parsed.spec, abs(float(notional_usd)), float(fx["usd_per_unit"]))
        if sized is None or int(sized["contracts"]) < 1:
            return _verdict(
                status="unavailable",
                reason=f"{alias} descriptive notional is below one exchange lot",
                family="stir_outright",
                instrument=alias,
                expression_type=expr_type,
                mark_status="not_applicable",
            )
    rate, mark_source, missing_path = _contract_implied_rate(market_state, parsed.spec.curve_id, parsed.expiry)
    if rate is None:
        return _verdict(
            status="missing_input",
            reason=f"implied rate missing for {alias} on frozen {parsed.spec.curve_id} curve",
            family="stir_outright",
            instrument=alias,
            expression_type=expr_type,
            missing_inputs=[missing_path or f"tradable_rate_curves.{parsed.spec.curve_id}.contracts.{parsed.expiry}.implied_rate"],
            mark_status="missing",
        )
    return _verdict(
        status="executable",
        reason=f"{alias} STIR outright is executable on frozen curve and FX marks",
        family="stir_outright",
        instrument=alias,
        expression_type=expr_type,
        mark_status="ok",
        mark_source=mark_source,
    )


def _structure_leg_expiries(kind: str, expression: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return list of (curve_id, expiry) required for marks."""
    legs: list[tuple[str, str]] = []
    if kind == "calendar_spread":
        curve = str(expression.get("curve_id") or "").upper()
        legs.append((curve, str(expression.get("near_expiry") or "")))
        legs.append((curve, str(expression.get("far_expiry") or "")))
    elif kind == "butterfly":
        curve = str(expression.get("curve_id") or "").upper()
        for key in ("wing1_expiry", "body_expiry", "wing2_expiry"):
            legs.append((curve, str(expression.get(key) or "")))
    elif kind == "outright_rv":
        receive = expression.get("receive") if isinstance(expression.get("receive"), Mapping) else {}
        pay = expression.get("pay") if isinstance(expression.get("pay"), Mapping) else {}
        legs.append((str(receive.get("curve_id") or "").upper(), str(receive.get("expiry") or "")))
        legs.append((str(pay.get("curve_id") or "").upper(), str(pay.get("expiry") or "")))
    elif kind == "curve_rv":
        for cal_key in ("long_calendar", "short_calendar"):
            cal = expression.get(cal_key) if isinstance(expression.get(cal_key), Mapping) else {}
            curve = str(cal.get("curve_id") or "").upper()
            legs.append((curve, str(cal.get("near_expiry") or "")))
            legs.append((curve, str(cal.get("far_expiry") or "")))
    return legs


def _assess_curve_structure(
    instrument: str | None,
    expression: Mapping[str, Any],
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
) -> dict[str, Any]:
    kind = str(expression.get("type") or "")
    probe_notional = notional_usd if notional_usd is not None else 1_000_000
    try:
        built = build_structure(
            expression,
            side="long",
            notional_usd=probe_notional,
            market_state=market_state,
        )
    except StructureError as exc:
        text = str(exc)
        status = "unavailable" if "USD conversion" in text or "below one exchange" in text else "missing_input"
        return _verdict(
            status=status,
            reason=text,
            family="curve_structure",
            instrument=normalize_instrument(instrument),
            expression_type=kind,
            mark_status="not_applicable",
        )
    missing_paths: list[str] = []
    for leg in built.get("legs") or []:
        if not isinstance(leg, Mapping):
            continue
        curve_id = str(leg.get("curve_id") or "")
        expiry = str(leg.get("expiry") or "")
        _rate, _src, path = _contract_implied_rate(market_state, curve_id, expiry)
        if _rate is None and path:
            missing_paths.append(path)
    if missing_paths:
        return _verdict(
            status="missing_input",
            reason=f"{kind} is missing implied rates for one or more leg contracts",
            family="curve_structure",
            instrument=normalize_instrument(instrument),
            expression_type=kind,
            missing_inputs=sorted(set(missing_paths)),
            mark_status="missing",
        )
    return _verdict(
        status="executable",
        reason=f"{kind} structure builds and every leg has a frozen implied rate",
        family="curve_structure",
        instrument=normalize_instrument(instrument),
        expression_type=kind,
        mark_status="ok",
        mark_source="tradable_rate_curves",
    )


def _assess_government_yield(
    instrument: str,
    expression: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = normalize_instrument(instrument) or instrument
    mark_status, mark_source = _sovereign_mark(market_state, normalized)
    return _verdict(
        status="missing_input",
        reason=(
            f"{normalized} has no verified modified duration or DV01 in this repo; "
            "sovereign yield prints are not exchange contract economics"
        ),
        family="government_yield",
        instrument=normalized,
        expression_type=_expression_type(expression),
        missing_inputs=[f"sovereign.{normalized}.modified_duration"],
        mark_status=mark_status,
        mark_source=mark_source,
    )


def _assess_forward_swap(expression: Mapping[str, Any]) -> dict[str, Any]:
    return _verdict(
        status="unsupported",
        reason=(
            "forward_swap is a government-curve proxy derived from official yield inputs; "
            "it is not an observed USD SOFR OIS quote and cannot be booked as SOFR OIS"
        ),
        family="other",
        instrument=None,
        expression_type="forward_swap",
        mark_status="not_applicable",
    )


def assess_expression(
    instrument: str | None,
    *,
    asset_class: str | None = None,
    expression: Mapping[str, Any] | None = None,
    market_state: Mapping[str, Any] | None = None,
    notional_usd: float | None = None,
) -> dict[str, Any]:
    del asset_class
    blocked = _substitution_conflict(instrument, expression)
    if blocked is not None:
        return blocked

    normalized = normalize_instrument(instrument) if instrument else None
    expr_type = _expression_type(expression)

    if isinstance(expression, Mapping) and expr_type == "forward_swap":
        return _assess_forward_swap(expression)

    if expr_type in STRUCTURE_TYPES:
        return _assess_curve_structure(normalized, expression, market_state, notional_usd)

    if expr_type == "futures_strip_average":
        return _delegate_assessor("futures_strip", normalized, expression, market_state, notional_usd)

    if expr_type == "usd_sofr_ois":
        return _delegate_assessor("usd_sofr_ois", normalized, expression, market_state, notional_usd)

    if expr_type == "treasury_future":
        return _delegate_assessor("treasury_future", normalized, expression, market_state, notional_usd)

    if normalized and is_sovereign_instrument(normalized):
        return _assess_government_yield(normalized, expression, market_state)

    if normalized and _OIS_INSTRUMENT.match(normalized):
        expr = expression if isinstance(expression, Mapping) else {"type": "usd_sofr_ois"}
        return _delegate_assessor("usd_sofr_ois", normalized, expr, market_state, notional_usd)

    if normalized and _STRIP_INSTRUMENT.match(normalized):
        expr = expression if isinstance(expression, Mapping) else None
        return _delegate_assessor("futures_strip", normalized, expr, market_state, notional_usd)

    if normalized and _TREASURY_ROOT.fullmatch(normalized.replace(" ", "")):
        expr = expression if isinstance(expression, Mapping) else {"type": "treasury_future"}
        return _delegate_assessor("treasury_future", normalized, expr, market_state, notional_usd)

    parsed = parse_contract_id(normalized or instrument or "")
    if parsed is not None and expr_type in (None, "outright"):
        return _assess_stir_outright(normalized or instrument or "", expression, market_state, notional_usd)

    if expr_type and expr_type not in _EXPRESSION_FAMILY:
        return _verdict(
            status="unsupported",
            reason=f"unsupported expression type {expr_type!r}",
            family="other",
            instrument=normalized,
            expression_type=expr_type,
            mark_status="not_applicable",
        )

    if normalized:
        return _verdict(
            status="unsupported",
            reason=f"instrument {normalized!r} is not supported by the paper executable catalog",
            family="other",
            instrument=normalized,
            expression_type=expr_type,
            mark_status="not_applicable",
        )

    return _verdict(
        status="unsupported",
        reason="instrument and expression are insufficient to assess a rates booking",
        family="other",
        instrument=None,
        expression_type=expr_type,
        mark_status="not_applicable",
    )


def two_year_choices(market_state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []

    choices.append(
        assess_expression("US_2Y", market_state=market_state, notional_usd=None)
    )

    choices.append(
        assess_expression("TU", expression={"type": "treasury_future"}, market_state=market_state, notional_usd=None)
    )

    choices.append(
        assess_expression(
            "USD_SOFR_OIS_2Y",
            expression={"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2},
            market_state=market_state,
            notional_usd=None,
        )
    )

    quarterlies = _quarterly_expiries(market_state, "SOFR")
    strip_expression: dict[str, Any] = {
        "type": "futures_strip_average",
        "curve_id": "SOFR",
        "expiries": quarterlies[:4],
    }
    if len(quarterlies) < 4:
        strip_verdict = _verdict(
            status="missing_input",
            reason="SOFR 2Y futures strip needs four quarterly contracts on the frozen SOFR curve",
            family="futures_strip",
            instrument="SOFR_STRIP_2Y",
            expression_type="futures_strip_average",
            missing_inputs=["tradable_rate_curves.SOFR.quarterly_contracts"],
            mark_status="missing",
        )
    else:
        strip_verdict = assess_expression(
            "SOFR_STRIP_2Y",
            expression=strip_expression,
            market_state=market_state,
            notional_usd=None,
        )
    choices.append(strip_verdict)

    return choices


def select_two_year(
    market_state: Mapping[str, Any] | None,
    *,
    family: str,
    notional_usd: float | None = None,
) -> dict[str, Any]:
    fam = str(family or "").strip().lower()
    if fam not in _TWO_YEAR_FAMILIES:
        allowed = ", ".join(sorted(_TWO_YEAR_FAMILIES))
        return _verdict(
            status="unsupported",
            reason=f"unknown 2Y family {family!r}; allowed families are {allowed}",
            family="other",
            instrument=None,
            expression_type=None,
            mark_status="not_applicable",
        )
    if fam == "government_yield":
        return assess_expression("US_2Y", market_state=market_state, notional_usd=notional_usd)
    if fam == "treasury_future":
        return assess_expression(
            "TU",
            expression={"type": "treasury_future"},
            market_state=market_state,
            notional_usd=notional_usd,
        )
    if fam == "usd_sofr_ois":
        return assess_expression(
            "USD_SOFR_OIS_2Y",
            expression={"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2},
            market_state=market_state,
            notional_usd=notional_usd,
        )
    quarterlies = _quarterly_expiries(market_state, "SOFR")
    if len(quarterlies) < 4:
        return _verdict(
            status="missing_input",
            reason="SOFR 2Y futures strip needs four quarterly contracts on the frozen SOFR curve",
            family="futures_strip",
            instrument="SOFR_STRIP_2Y",
            expression_type="futures_strip_average",
            missing_inputs=["tradable_rate_curves.SOFR.quarterly_contracts"],
            mark_status="missing",
        )
    return assess_expression(
        "SOFR_STRIP_2Y",
        expression={
            "type": "futures_strip_average",
            "curve_id": "SOFR",
            "expiries": quarterlies[:4],
        },
        market_state=market_state,
        notional_usd=notional_usd,
    )


def build_executable_catalog(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for curve_id in ("SOFR", "CORRA", "AONIA"):
        if curve_id not in CURVE_SPEC:
            continue
        for contract in _curve_contract_rows(curve_id, market_state):
            expiry = str(contract.get("expiry") or "")
            if not expiry:
                continue
            instrument = f"{curve_id}_{expiry}"
            rows.append(assess_expression(instrument, market_state=market_state))
    rows.extend(two_year_choices(market_state))
    return {
        "rows": rows,
        "advisory": (
            "Paper catalog only: each row is assess_expression on the frozen market_state. "
            "Domestic calendar/butterfly/RV structures are bookable when build_structure succeeds "
            "and leg marks exist; this table lists STIR outrights and the four distinct 2Y families."
        ),
        "substitution_policy": (
            "Refusing silent substitution: US_2Y, TU/ZT, USD_SOFR_OIS_2Y, and SOFR_STRIP_2Y "
            "are separate families. Instrument tokens must match expression types; the catalog never "
            "rewrites one 2Y expression into another."
        ),
    }
