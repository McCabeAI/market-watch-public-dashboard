"""Paper rates executable catalog only.

Preflight and book admission both call ``assess_expression``; there is no second
checker. Marks come only from the frozen ``market_state`` — nothing is invented.
Distinct expressions (government yield, TU/FV/TY, USD SOFR OIS 2Y, USD SOFR OIS
1y1y, and the eight-quarter SOFR futures strip) are never substituted for one
another. The catalog does not rank or prefer a family.
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
_TWO_YEAR_STRIP_CONTRACTS = 8
_FOUR_QUARTER_STRIP_CONTRACTS = 4
_STRUCTURE_PROBE_NOTIONAL_USD = 5_000_000
_CURVE_ORDER = ("SOFR", "CORRA", "AONIA")
_TREASURY_PRODUCTS = ("TU", "FV", "TY")
_TREASURY_CANONICAL = {"TU": "TU", "ZT": "TU", "FV": "FV", "ZF": "FV", "TY": "TY", "ZN": "TY"}
_OIS_TENORS = ((0, 2, "USD_SOFR_OIS_2Y"), (1, 1, "USD_SOFR_OIS_1Y1Y"))

_RECIPE_NOTE = (
    "Parameterized recipe, not a ranked strategy and not a live trade. "
    "bookable is assess_expression on this example and assessed_notional_usd only. "
    "Another maturity or size is executable only after that user-selected expression passes assess_expression."
)


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
        if _parse_quarter_expiry(expiry) is None:
            continue
        expiries.append(expiry)
    return sorted(set(expiries))


def _parse_quarter_expiry(expiry: str | None) -> int | None:
    text = str(expiry or "").strip()
    if len(text) != 7 or text[4] != "-":
        return None
    try:
        year = int(text[:4])
        month = int(text[5:7])
    except ValueError:
        return None
    if month not in _QUARTERLY_MONTHS:
        return None
    return year * 4 + (month // 3 - 1)


def _format_quarter_index(index: int) -> str:
    year, quarter = divmod(index, 4)
    month = (quarter + 1) * 3
    return f"{year:04d}-{month:02d}"


def _consecutive_quarter_window(start_expiry: str, count: int) -> list[str] | None:
    start = _parse_quarter_expiry(start_expiry)
    if start is None or count < 1:
        return None
    return [_format_quarter_index(start + offset) for offset in range(count)]


def _listed_expiries(market_state: Mapping[str, Any] | None, curve_id: str) -> list[str]:
    found: list[str] = []
    for row in _curve_contract_rows(curve_id, market_state):
        expiry = str(row.get("expiry") or "")
        if expiry and expiry not in found:
            found.append(expiry)
    return sorted(found)


def _strip_probe_notional(curve_id: str, count: int) -> float:
    per_leg = 4_000_000.0 if str(curve_id).upper() == "AONIA" else 1_000_000.0
    return per_leg * max(1, count)


def _canonical_quarter_list(expiries: list[Any], count: int) -> list[str] | None:
    parsed: list[int] = []
    for raw in expiries:
        index = _parse_quarter_expiry(str(raw))
        if index is None:
            return None
        parsed.append(index)
    if len(parsed) != count or len(set(parsed)) != count:
        return None
    start = min(parsed)
    window = list(range(start, start + count))
    if sorted(parsed) != window:
        return None
    return [_format_quarter_index(index) for index in window]


def _sofr_strip_2y_incomplete(
    *,
    start: str | None,
    window: list[str],
    missing: list[str],
) -> dict[str, Any]:
    paths = [f"tradable_rate_curves.SOFR.contracts.{expiry}.implied_rate" for expiry in missing]
    paths.append("tradable_rate_curves.SOFR.quarterly_contracts")
    start_label = start or "the first listed SOFR quarterly"
    gap_label = ", ".join(missing) if missing else "the remaining quarterlies"
    reason = (
        f"SOFR_STRIP_2Y requires eight consecutive quarterly SR3 expiries starting at {start_label}; "
        f"missing required consecutive expiry {gap_label}. "
        "A missing quarter is not skipped and a later start is not substituted. "
        "four quarterlies are not a 2Y swap or a 2Y futures strip"
    )
    verdict = _verdict(
        status="missing_input",
        reason=reason,
        family="futures_strip",
        instrument="SOFR_STRIP_2Y",
        expression_type="futures_strip_average",
        missing_inputs=paths,
        mark_status="missing",
    )
    if window:
        verdict["expression"] = {
            "type": "futures_strip_average",
            "curve_id": "SOFR",
            "expiries": list(window),
        }
        verdict["expiries"] = list(window)
    return verdict


def _reject_sofr_strip_2y(expression: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Reject a SOFR_STRIP_2Y payload that is not exactly eight consecutive quarters."""
    if not isinstance(expression, Mapping):
        return _sofr_strip_2y_incomplete(start=None, window=[], missing=[])
    curve_id = str(expression.get("curve_id") or "SOFR").upper()
    if curve_id != "SOFR":
        return _verdict(
            status="unsupported",
            reason=(
                "refusing silent substitution: SOFR_STRIP_2Y is the SOFR eight-quarter strip, "
                f"not curve {curve_id}"
            ),
            family="futures_strip",
            instrument="SOFR_STRIP_2Y",
            expression_type="futures_strip_average",
            mark_status="not_applicable",
        )
    raw = expression.get("expiries")
    if not isinstance(raw, list) or len(raw) != _TWO_YEAR_STRIP_CONTRACTS:
        return _sofr_strip_2y_incomplete(start=None, window=[], missing=[])
    window = _canonical_quarter_list(raw, _TWO_YEAR_STRIP_CONTRACTS)
    if window is None:
        texts = [str(item) for item in raw]
        parsed = [idx for item in texts if (idx := _parse_quarter_expiry(item)) is not None]
        if parsed:
            start = _format_quarter_index(min(parsed))
            required = _consecutive_quarter_window(start, _TWO_YEAR_STRIP_CONTRACTS) or []
            have = set(texts)
            missing = [expiry for expiry in required if expiry not in have]
        else:
            start = None
            required = []
            missing = texts
        return _sofr_strip_2y_incomplete(start=start, window=required, missing=missing or texts[:1])
    return None


def _assess_futures_strip(
    instrument: str | None,
    expression: Mapping[str, Any] | None,
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
) -> dict[str, Any]:
    normalized = normalize_instrument(instrument) if instrument else None
    if normalized == "SOFR_STRIP_2Y":
        rejected = _reject_sofr_strip_2y(expression if isinstance(expression, Mapping) else None)
        if rejected is not None:
            return rejected
    verdict = _delegate_assessor(
        "futures_strip",
        normalized,
        expression if isinstance(expression, Mapping) else None,
        market_state,
        notional_usd,
    )
    if normalized == "SOFR_STRIP_2Y" and verdict.get("family") == "futures_strip":
        verdict = dict(verdict)
        verdict["instrument"] = "SOFR_STRIP_2Y"
        if isinstance(expression, Mapping) and isinstance(expression.get("expiries"), list):
            window = _canonical_quarter_list(list(expression.get("expiries") or []), _TWO_YEAR_STRIP_CONTRACTS)
            expiries = window if window is not None else [str(item) for item in expression.get("expiries") or []]
            verdict["expression"] = {
                "type": "futures_strip_average",
                "curve_id": "SOFR",
                "expiries": expiries,
            }
            verdict["expiries"] = expiries
    return verdict


def _sofr_strip_2y_choice(
    market_state: Mapping[str, Any] | None,
    notional_usd: float | None,
    start_expiry: str | None = None,
) -> dict[str, Any]:
    available = _quarterly_expiries(market_state, "SOFR")
    if start_expiry is not None:
        start = str(start_expiry).strip()
        if _parse_quarter_expiry(start) is None:
            verdict = _verdict(
                status="missing_input",
                reason=(
                    f"SOFR_STRIP_2Y start {start_expiry!r} is not a quarterly SR3 expiry; "
                    "eight consecutive calendar quarters are required. "
                    "four quarterlies are not a 2Y swap or a 2Y futures strip"
                ),
                family="futures_strip",
                instrument="SOFR_STRIP_2Y",
                expression_type="futures_strip_average",
                missing_inputs=["tradable_rate_curves.SOFR.quarterly_contracts"],
                mark_status="missing",
            )
            return verdict
    elif available:
        start = available[0]
    else:
        return _sofr_strip_2y_incomplete(start=None, window=[], missing=[])

    window = _consecutive_quarter_window(start, _TWO_YEAR_STRIP_CONTRACTS) or []
    have = set(available)
    missing = [expiry for expiry in window if expiry not in have]
    if missing:
        return _sofr_strip_2y_incomplete(start=start, window=window, missing=missing)
    expression = {
        "type": "futures_strip_average",
        "curve_id": "SOFR",
        "expiries": window,
    }
    return _assess_futures_strip("SOFR_STRIP_2Y", expression, market_state, notional_usd)


def _ois_choice(
    market_state: Mapping[str, Any] | None,
    start_years: int,
    tenor_years: int,
    instrument: str,
    notional_usd: float | None,
) -> dict[str, Any]:
    expression = {"type": "usd_sofr_ois", "start_years": start_years, "tenor_years": tenor_years}
    verdict = dict(
        assess_expression(
            instrument,
            expression=expression,
            market_state=market_state,
            notional_usd=notional_usd,
        )
    )
    verdict["expression"] = expression
    return verdict


def _sourced_treasury_ids(market_state: Mapping[str, Any] | None, product: str) -> list[str]:
    if not isinstance(market_state, Mapping):
        return []
    block = market_state.get("treasury_futures")
    if not isinstance(block, Mapping):
        return []
    contracts = block.get("contracts")
    if not isinstance(contracts, Mapping):
        return []
    found: list[str] = []
    for contract_id, row in contracts.items():
        if not isinstance(row, Mapping):
            continue
        if not str(row.get("price_source") or row.get("source") or "").strip():
            continue
        normalized = normalize_instrument(str(contract_id)) or str(contract_id).upper()
        match = _TREASURY_ROOT.fullmatch(normalized.replace(" ", ""))
        if match is None:
            continue
        if _TREASURY_CANONICAL.get(match.group(1)) != product:
            continue
        if match.group(2) is None:
            continue
        found.append(normalized)
    return sorted(set(found))


def _treasury_choice(market_state: Mapping[str, Any] | None, instrument: str, notional_usd: float | None) -> dict[str, Any]:
    expression = {"type": "treasury_future"}
    verdict = dict(
        assess_expression(
            instrument,
            expression=expression,
            market_state=market_state,
            notional_usd=notional_usd,
        )
    )
    verdict["expression"] = expression
    return verdict


def _treasury_product_rows(
    market_state: Mapping[str, Any] | None,
    products: tuple[str, ...],
    notional_usd: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in products:
        verdict = _treasury_choice(market_state, product, notional_usd)
        ident = str(verdict.get("instrument") or product)
        if ident not in seen:
            rows.append(verdict)
            seen.add(ident)
        for contract_id in _sourced_treasury_ids(market_state, product):
            dated = _treasury_choice(market_state, contract_id, notional_usd)
            dated_id = str(dated.get("instrument") or contract_id)
            if dated_id in seen:
                continue
            rows.append(dated)
            seen.add(dated_id)
    return rows


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
        return _assess_futures_strip(normalized, expression, market_state, notional_usd)

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
        return _assess_futures_strip(normalized, expression, market_state, notional_usd)

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


_CALENDAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "curve_id", "near_expiry", "far_expiry"],
    "properties": {
        "type": {"const": "calendar_spread"},
        "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
        "near_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$", "description": "YYYY-MM earlier than far_expiry"},
        "far_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$", "description": "YYYY-MM"},
    },
    "optional": ["near_rate", "far_rate", "target_dv01_usd", "fx_usd_per_unit"],
}
_BUTTERFLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "curve_id", "wing1_expiry", "body_expiry", "wing2_expiry"],
    "properties": {
        "type": {"const": "butterfly"},
        "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
        "wing1_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
        "body_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
        "wing2_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$", "description": "wing1 < body < wing2"},
    },
    "optional": ["wing1_rate", "body_rate", "wing2_rate", "target_dv01_usd", "fx_usd_per_unit"],
}
_OUTRIGHT_RV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "receive", "pay"],
    "properties": {
        "type": {"const": "outright_rv"},
        "receive": {
            "type": "object",
            "required": ["curve_id", "expiry"],
            "properties": {
                "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
                "expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            },
        },
        "pay": {
            "type": "object",
            "required": ["curve_id", "expiry"],
            "properties": {
                "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
                "expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            },
        },
    },
    "description": "Cross-country when receive.curve_id and pay.curve_id differ. Legs must not be the same contract.",
    "optional": ["target_dv01_usd", "fx_usd_per_unit"],
}
_CURVE_RV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "long_calendar", "short_calendar"],
    "properties": {
        "type": {"const": "curve_rv"},
        "long_calendar": {
            "type": "object",
            "required": ["curve_id", "near_expiry", "far_expiry"],
            "properties": {
                "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
                "near_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
                "far_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            },
        },
        "short_calendar": {
            "type": "object",
            "required": ["curve_id", "near_expiry", "far_expiry"],
            "properties": {
                "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
                "near_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
                "far_expiry": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            },
        },
    },
    "description": "Four legs: long calendar near/far and short calendar near/far.",
    "optional": ["target_dv01_usd", "fx_usd_per_unit"],
}
_FOUR_QUARTER_STRIP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["type", "curve_id", "expiries"],
    "properties": {
        "type": {"const": "futures_strip_average"},
        "curve_id": {"enum": ["SOFR", "CORRA", "AONIA"]},
        "expiries": {
            "type": "array",
            "minItems": 4,
            "maxItems": 4,
            "description": "Exactly four consecutive quarter-year expiries. Instrument is {curve_id}_STRIP, never SOFR_STRIP_2Y.",
        },
    },
    "optional": ["weights", "target_dv01_usd"],
}


def two_year_choices(market_state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [
        assess_expression("US_2Y", market_state=market_state, notional_usd=None),
        _treasury_choice(market_state, "TU", None),
        _ois_choice(market_state, 0, 2, "USD_SOFR_OIS_2Y", None),
        _sofr_strip_2y_choice(market_state, None, None),
    ]


def select_two_year(
    market_state: Mapping[str, Any] | None,
    *,
    family: str,
    notional_usd: float | None = None,
    start_expiry: str | None = None,
) -> dict[str, Any]:
    """Select one 2Y family. ``start_expiry`` applies only to the SOFR futures strip.

    The futures-strip default starts at the earliest listed SOFR quarterly and
    requires the next seven calendar quarters. A missing quarter is not skipped.
    Pass ``start_expiry`` only when the user explicitly chooses a different 2Y start.
    """
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
        return _treasury_choice(market_state, "TU", notional_usd)
    if fam == "usd_sofr_ois":
        return _ois_choice(market_state, 0, 2, "USD_SOFR_OIS_2Y", notional_usd)
    return _sofr_strip_2y_choice(market_state, notional_usd, start_expiry)


def _stamp_concrete(
    verdict: Mapping[str, Any],
    expression: Mapping[str, Any],
    notional_usd: float | None,
) -> dict[str, Any]:
    stamped = dict(verdict)
    stamped["expression"] = dict(expression)
    if notional_usd is not None:
        stamped["assessed_notional_usd"] = notional_usd
    stamped["representative"] = True
    stamped["ranked"] = False
    return stamped


def _calendar_candidates(market_state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for curve in _CURVE_ORDER:
        expiries = _listed_expiries(market_state, curve)
        if len(expiries) < 2:
            continue
        found.append(
            (
                f"{curve}_{expiries[0]}",
                {
                    "type": "calendar_spread",
                    "curve_id": curve,
                    "near_expiry": expiries[0],
                    "far_expiry": expiries[1],
                },
            )
        )
    return found


def _butterfly_candidates(market_state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    for curve in _CURVE_ORDER:
        expiries = _listed_expiries(market_state, curve)
        if len(expiries) < 3:
            continue
        found.append(
            (
                f"{curve}_{expiries[0]}",
                {
                    "type": "butterfly",
                    "curve_id": curve,
                    "wing1_expiry": expiries[0],
                    "body_expiry": expiries[1],
                    "wing2_expiry": expiries[2],
                },
            )
        )
    return found


def _outright_rv_candidates(market_state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    fronts: list[tuple[str, str]] = []
    for curve in _CURVE_ORDER:
        expiries = _listed_expiries(market_state, curve)
        if expiries:
            fronts.append((curve, expiries[0]))
    found: list[tuple[str, dict[str, Any]]] = []
    for index, (curve_a, expiry_a) in enumerate(fronts):
        for curve_b, expiry_b in fronts[index + 1 :]:
            found.append(
                (
                    f"{curve_a}_{expiry_a}",
                    {
                        "type": "outright_rv",
                        "receive": {"curve_id": curve_a, "expiry": expiry_a},
                        "pay": {"curve_id": curve_b, "expiry": expiry_b},
                    },
                )
            )
    return found


def _curve_rv_candidates(market_state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    calendars: list[tuple[str, str, str]] = []
    for curve in _CURVE_ORDER:
        expiries = _listed_expiries(market_state, curve)
        if len(expiries) >= 2:
            calendars.append((curve, expiries[0], expiries[1]))
    found: list[tuple[str, dict[str, Any]]] = []
    for index, (curve_a, near_a, far_a) in enumerate(calendars):
        for curve_b, near_b, far_b in calendars[index + 1 :]:
            found.append(
                (
                    f"{curve_a}_{near_a}",
                    {
                        "type": "curve_rv",
                        "long_calendar": {
                            "curve_id": curve_a,
                            "near_expiry": near_a,
                            "far_expiry": far_a,
                        },
                        "short_calendar": {
                            "curve_id": curve_b,
                            "near_expiry": near_b,
                            "far_expiry": far_b,
                        },
                    },
                )
            )
    return found


def _first_representative(
    candidates: list[tuple[str, dict[str, Any]]],
    market_state: Mapping[str, Any] | None,
    notional_usd: float,
    placeholder: tuple[str, dict[str, Any]],
) -> dict[str, Any]:
    chosen: dict[str, Any] | None = None
    for instrument, expression in candidates:
        verdict = _stamp_concrete(
            assess_expression(
                instrument,
                expression=expression,
                market_state=market_state,
                notional_usd=notional_usd,
            ),
            expression,
            notional_usd,
        )
        if chosen is None:
            chosen = verdict
        if verdict.get("bookable"):
            return verdict
    if chosen is not None:
        return chosen
    instrument, expression = placeholder
    return _stamp_concrete(
        assess_expression(
            instrument,
            expression=expression,
            market_state=market_state,
            notional_usd=notional_usd,
        ),
        expression,
        notional_usd,
    )


def _four_quarter_representative(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for curve in _CURVE_ORDER:
        available = _quarterly_expiries(market_state, curve)
        if not available:
            continue
        window = _consecutive_quarter_window(available[0], _FOUR_QUARTER_STRIP_CONTRACTS) or []
        if any(expiry not in set(available) for expiry in window):
            continue
        expression = {
            "type": "futures_strip_average",
            "curve_id": curve,
            "expiries": window,
        }
        instrument = f"{curve}_STRIP"
        notional = _strip_probe_notional(curve, _FOUR_QUARTER_STRIP_CONTRACTS)
        verdict = dict(
            _assess_futures_strip(instrument, expression, market_state, notional)
        )
        verdict["instrument"] = instrument
        verdict["expression"] = expression
        verdict["expiries"] = list(window)
        verdict["assessed_notional_usd"] = notional
        verdict["not_a_two_year_strip"] = True
        verdict["representative"] = True
        verdict["ranked"] = False
        if fallback is None:
            fallback = verdict
        if verdict.get("bookable"):
            return verdict
    if fallback is not None:
        return fallback
    window = ["2026-12", "2027-03", "2027-06", "2027-09"]
    expression = {"type": "futures_strip_average", "curve_id": "SOFR", "expiries": window}
    notional = _strip_probe_notional("SOFR", _FOUR_QUARTER_STRIP_CONTRACTS)
    verdict = dict(_assess_futures_strip("SOFR_STRIP", expression, market_state, notional))
    verdict["instrument"] = "SOFR_STRIP"
    verdict["expression"] = expression
    verdict["expiries"] = list(window)
    verdict["assessed_notional_usd"] = notional
    verdict["not_a_two_year_strip"] = True
    verdict["representative"] = True
    verdict["ranked"] = False
    return verdict


def _recipe(expression_type: str, schema: Mapping[str, Any], verdict: Mapping[str, Any]) -> dict[str, Any]:
    example = dict(verdict.get("expression") or {})
    return {
        "role": "parameterized_recipe",
        "expression_type": expression_type,
        "family": verdict.get("family"),
        "schema": dict(schema),
        "example": example,
        "example_instrument": verdict.get("instrument"),
        "assessed_notional_usd": verdict.get("assessed_notional_usd"),
        "example_verdict": dict(verdict),
        "example_bookable": bool(verdict.get("bookable")),
        "bookable": bool(verdict.get("bookable")),
        "executable_template": False,
        "ranked": False,
        "note": _RECIPE_NOTE,
    }


def build_executable_catalog(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for curve_id in _CURVE_ORDER:
        if curve_id not in CURVE_SPEC:
            continue
        for contract in _curve_contract_rows(curve_id, market_state):
            expiry = str(contract.get("expiry") or "")
            if not expiry:
                continue
            instrument = f"{curve_id}_{expiry}"
            rows.append(assess_expression(instrument, market_state=market_state))
    rows.extend(two_year_choices(market_state))
    rows.append(_ois_choice(market_state, 1, 1, "USD_SOFR_OIS_1Y1Y", None))
    present = {str(row.get("instrument")) for row in rows}
    for verdict in _treasury_product_rows(market_state, _TREASURY_PRODUCTS, None):
        ident = str(verdict.get("instrument"))
        if ident in present:
            continue
        rows.append(verdict)
        present.add(ident)

    calendar = _first_representative(
        _calendar_candidates(market_state),
        market_state,
        _STRUCTURE_PROBE_NOTIONAL_USD,
        (
            "SOFR_2026-12",
            {
                "type": "calendar_spread",
                "curve_id": "SOFR",
                "near_expiry": "2026-12",
                "far_expiry": "2027-03",
            },
        ),
    )
    butterfly = _first_representative(
        _butterfly_candidates(market_state),
        market_state,
        _STRUCTURE_PROBE_NOTIONAL_USD,
        (
            "SOFR_2026-12",
            {
                "type": "butterfly",
                "curve_id": "SOFR",
                "wing1_expiry": "2026-12",
                "body_expiry": "2027-03",
                "wing2_expiry": "2027-06",
            },
        ),
    )
    outright_rv = _first_representative(
        _outright_rv_candidates(market_state),
        market_state,
        _STRUCTURE_PROBE_NOTIONAL_USD,
        (
            "SOFR_2026-12",
            {
                "type": "outright_rv",
                "receive": {"curve_id": "SOFR", "expiry": "2026-12"},
                "pay": {"curve_id": "CORRA", "expiry": "2026-12"},
            },
        ),
    )
    curve_rv = _first_representative(
        _curve_rv_candidates(market_state),
        market_state,
        _STRUCTURE_PROBE_NOTIONAL_USD,
        (
            "SOFR_2026-12",
            {
                "type": "curve_rv",
                "long_calendar": {
                    "curve_id": "SOFR",
                    "near_expiry": "2026-12",
                    "far_expiry": "2027-03",
                },
                "short_calendar": {
                    "curve_id": "CORRA",
                    "near_expiry": "2026-12",
                    "far_expiry": "2027-03",
                },
            },
        ),
    )
    four_quarter = _four_quarter_representative(market_state)
    recipes = [
        _recipe("calendar_spread", _CALENDAR_SCHEMA, calendar),
        _recipe("butterfly", _BUTTERFLY_SCHEMA, butterfly),
        _recipe("outright_rv", _OUTRIGHT_RV_SCHEMA, outright_rv),
        _recipe("curve_rv", _CURVE_RV_SCHEMA, curve_rv),
        _recipe("futures_strip_average", _FOUR_QUARTER_STRIP_SCHEMA, four_quarter),
    ]
    for verdict in (calendar, butterfly, outright_rv, curve_rv, four_quarter):
        if verdict.get("bookable"):
            rows.append(dict(verdict))
    return {
        "rows": rows,
        "recipes": recipes,
        "ranking": None,
        "preference": None,
        "advisory": (
            "Paper catalog only. Each concrete row is assess_expression on the frozen market_state "
            "and the catalog does not rank, recommend, or choose a strategy. Representative bookable "
            "rows are included only when that expression and assessed notional are executable. "
            "Parameterized recipes describe other calendar, butterfly, outright cross-country RV, and "
            "four-leg curve RV combinations; a recipe is not a live trade until the user-selected "
            "expression and size pass assess_expression. USD_SOFR_OIS_2Y and USD_SOFR_OIS_1Y1Y are "
            "separate. SOFR_STRIP_2Y is eight consecutive quarterly SR3 expiries; a four-contract "
            "strip uses {curve}_STRIP and is not a 2Y strip."
        ),
        "substitution_policy": (
            "Refusing silent substitution: US_2Y, TU/ZT, FV/ZF, TY/ZN, USD_SOFR_OIS_2Y, "
            "USD_SOFR_OIS_1Y1Y, and SOFR_STRIP_2Y are separate. Instrument tokens must match "
            "expression types; the catalog never rewrites one expression into another and does not "
            "rank or prefer a family."
        ),
    }
