"""Deterministic paper-mid resolver for Trader Room and overnight books.

Paper trading is allowed at the frozen packet's deterministic mid/reference level.
These marks are explicitly paper/reference marks, never executable broker quotes.

Derived expressions are recomputed from frozen source legs. Model-authored arithmetic is
not canonical. If a required leg cannot be resolved, the paper trade stays blocked.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Mapping

from scripts.overnight.errors import SchemaError


class PaperMarkError(SchemaError):
    """A requested paper expression cannot be marked from the frozen market state."""


def market_state_from_families(families: Mapping[str, Any]) -> dict[str, Any] | None:
    block = families.get("market_state") if isinstance(families, Mapping) else None
    if not isinstance(block, Mapping):
        return None
    data = block.get("data")
    return dict(data) if isinstance(data, Mapping) else None


def _number(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PaperMarkError(f"{label} is not numeric") from exc
    if not math.isfinite(out):
        raise PaperMarkError(f"{label} is not finite")
    return out


def _path_get(root: Mapping[str, Any], path: str) -> tuple[float, str | None]:
    node: Any = root
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise PaperMarkError(f"paper-mark source path missing: {path}")
        node = node[part]
    if isinstance(node, Mapping):
        as_of = node.get("as_of") or node.get("observation_date")
        for key in ("value", "rate", "bps", "spot", "discount_factor"):
            if node.get(key) is not None:
                return _number(node[key], path), str(as_of) if as_of else None
        raise PaperMarkError(f"paper-mark source path has no numeric value: {path}")
    return _number(node, path), None


def _fx_mark(state: Mapping[str, Any], pair: str) -> dict[str, Any]:
    fx = state.get("fx")
    if not isinstance(fx, Mapping):
        raise PaperMarkError("market_state.fx missing")
    pairs = fx.get("pairs") if isinstance(fx.get("pairs"), Mapping) else fx
    row = pairs.get(pair)
    if not isinstance(row, Mapping) or row.get("spot") is None:
        raise PaperMarkError(f"FX paper mid unavailable for {pair}")
    return {
        "value": _number(row["spot"], pair),
        "quote_unit": "spot",
        "source": f"market_state.fx.{pair}.spot",
        "as_of": row.get("as_of") or fx.get("source_observation"),
        "kind": "direct",
    }


_BLOCKING_RATE_STATUSES = frozenset({"stale", "missing", "invalid", "unavailable"})


def _require_rate_block_ok(state: Mapping[str, Any], country: str) -> None:
    rates = state.get("rates")
    if not isinstance(rates, Mapping) or not isinstance(rates.get(country), Mapping):
        raise PaperMarkError(f"rates block unavailable for {country}")
    block = rates[country]
    status = block.get("status")
    if status in _BLOCKING_RATE_STATUSES:
        raise PaperMarkError(
            f"{country} rates are {status} (latest_observation={block.get('latest_observation')})"
        )


def _rate_mark(state: Mapping[str, Any], country: str, tenor: str) -> dict[str, Any]:
    _require_rate_block_ok(state, country)
    rates = state.get("rates")
    block = rates[country]  # type: ignore[index]
    tenors = block.get("tenors") if isinstance(block.get("tenors"), Mapping) else block
    row = tenors.get(tenor)
    if isinstance(row, Mapping):
        value = row.get("value")
        as_of = row.get("as_of")
    else:
        value = row
        as_of = block.get("latest_observation")
    if value is None:
        raise PaperMarkError(f"paper mid unavailable for {country} {tenor}")
    return {
        "value": _number(value, f"{country} {tenor}"),
        "quote_unit": "percent",
        "source": f"market_state.rates.{country}.{tenor}",
        "as_of": as_of or block.get("latest_observation"),
        "kind": "direct",
    }


def _curve_mark(state: Mapping[str, Any], country: str, curve: str) -> dict[str, Any]:
    _require_rate_block_ok(state, country)
    rates = state.get("rates")
    block = rates.get(country) if isinstance(rates, Mapping) else None
    curves = block.get("curves") if isinstance(block, Mapping) else None
    row = curves.get(curve) if isinstance(curves, Mapping) else None
    if not isinstance(row, Mapping) or row.get("bps") is None:
        raise PaperMarkError(f"curve paper mid unavailable for {country} {curve}")
    return {
        "value": _number(row["bps"], f"{country} {curve}"),
        "quote_unit": "bps",
        "source": f"market_state.rates.{country}.curves.{curve}",
        "as_of": row.get("as_of"),
        "kind": "direct",
    }


def _rv_mark(state: Mapping[str, Any], instrument: str) -> dict[str, Any]:
    leg_match = re.fullmatch(r"([A-Z]{2})-([A-Z]{2})_[0-9A-Z]+", instrument.upper())
    if leg_match:
        for code in (leg_match.group(1), leg_match.group(2)):
            _require_rate_block_ok(state, code)
    block = state.get("rate_rv")
    row = block.get(instrument) if isinstance(block, Mapping) else None
    if not isinstance(row, Mapping) or row.get("bps") is None:
        raise PaperMarkError(f"rates-RV paper mid unavailable for {instrument}")
    return {
        "value": _number(row["bps"], instrument),
        "quote_unit": "bps",
        "source": f"market_state.rate_rv.{instrument}",
        "as_of": row.get("as_of"),
        "kind": "direct",
    }


def _tradable_curve_contract_mark(
    state: Mapping[str, Any],
    curve_id: str,
    contract_key: str,
) -> dict[str, Any]:
    curves = state.get("tradable_rate_curves")
    curve_map = curves.get("curves") if isinstance(curves, Mapping) else None
    block = curve_map.get(curve_id.upper()) if isinstance(curve_map, Mapping) else None
    if not isinstance(block, Mapping) or block.get("status") != "ok":
        raise PaperMarkError(f"tradable {curve_id} curve unavailable")
    target = contract_key.upper()
    for row in block.get("contracts") or []:
        if not isinstance(row, Mapping):
            continue
        code = str(row.get("code") or "").upper()
        expiry = str(row.get("expiry") or "").upper()
        if target not in {code, expiry}:
            continue
        if row.get("implied_rate") is None:
            raise PaperMarkError(f"{curve_id} contract {contract_key} missing implied rate")
        return {
            "value": _number(row["implied_rate"], f"{curve_id} {contract_key}"),
            "quote_unit": "percent",
            "source": f"market_state.tradable_rate_curves.{curve_id.upper()}.{expiry}.implied_rate",
            "as_of": (
                row.get("observation_date")
                or row.get("as_of")
                or state.get("generated_at")
                or row.get("expiry")
            ),
            "kind": "direct",
        }
    raise PaperMarkError(f"{curve_id} contract {contract_key} unavailable")


def _policy_contract_mark(state: Mapping[str, Any], code: str) -> dict[str, Any]:
    policy = state.get("policy_paths")
    countries = policy.get("countries") if isinstance(policy, Mapping) else None
    if not isinstance(countries, Mapping):
        raise PaperMarkError("market_state.policy_paths.countries missing")
    target = code.upper()
    for country, block in countries.items():
        if not isinstance(block, Mapping):
            continue
        for family in ("contracts_1m", "contracts_3m"):
            rows = block.get(family)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                if str(row.get("code") or "").upper() != target:
                    continue
                if row.get("implied_rate") is None:
                    raise PaperMarkError(f"policy contract {code} missing implied rate")
                return {
                    "value": _number(row["implied_rate"], code),
                    "quote_unit": "percent",
                    "source": f"market_state.policy_paths.{country}.{family}.{target}.implied_rate",
                    "as_of": row.get("as_of") or row.get("expiry"),
                    "kind": "direct",
                }
    raise PaperMarkError(f"policy-contract paper mid unavailable for {code}")


def _resolve_direct(state: Mapping[str, Any], instrument: str, asset_class: str | None) -> dict[str, Any]:
    raw = instrument.strip()
    upper = raw.upper().replace(" ", "_")

    fx_pair = upper.replace("_", "")
    if re.fullmatch(r"[A-Z]{6}", fx_pair):
        try:
            return _fx_mark(state, fx_pair)
        except PaperMarkError:
            pass

    m = re.fullmatch(r"(US|CA|AU|NZ|EA|JP)_(2Y|5Y|10Y|30Y|LONG)", upper)
    if m:
        return _rate_mark(state, m.group(1), m.group(2))

    m = re.fullmatch(r"(US|CA|AU|NZ|EA|JP)_(2S10S|5S10S)", upper)
    if m:
        return _curve_mark(state, m.group(1), m.group(2).lower())

    rv_key = raw.replace(" ", "_")
    rate_rv = state.get("rate_rv")
    if isinstance(rate_rv, Mapping):
        candidates = {str(k).upper(): str(k) for k in rate_rv}
        exact = candidates.get(rv_key.upper())
        if exact:
            return _rv_mark(state, exact)

    # Stable aliases for the three paper-tradable futures curves.
    # Examples: SOFR_2027-03, CORRA_2027-06, AONIA_2026-11.
    m = re.fullmatch(r"(SOFR|CORRA|AONIA|ESTR|TONA)_(20\d{2}-\d{2})", upper)
    if m:
        return _tradable_curve_contract_mark(state, m.group(1), m.group(2))

    # Exchange contract codes (SR1/SR3, COA/CRA, etc.) are marked in
    # implied-rate space so the rates P&L sign convention remains consistent.
    if re.fullmatch(r"[A-Z0-9]{4,12}", upper):
        try:
            return _policy_contract_mark(state, upper)
        except PaperMarkError:
            pass

    raise PaperMarkError(
        f"no deterministic paper mid for {instrument!r} asset_class={asset_class!r}"
    )


def _linear_combo(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    legs = expression.get("legs")
    if not isinstance(legs, list) or not legs:
        raise PaperMarkError("linear_combo requires non-empty legs")
    output_unit = expression.get("output_unit", "bps")
    if output_unit not in {"bps", "percent"}:
        raise PaperMarkError("linear_combo output_unit must be bps or percent")
    total = 0.0
    sources: list[str] = []
    dates: list[str] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            raise PaperMarkError("linear_combo leg must be an object")
        mark = resolve_paper_mid(
            state,
            str(leg.get("instrument") or ""),
            asset_class=leg.get("asset_class"),
            expression=leg.get("expression"),
        )
        weight = _number(leg.get("weight", 1.0), "linear_combo weight")
        value = float(mark["value"])
        if mark["quote_unit"] == "percent" and output_unit == "bps":
            value *= 100.0
        elif mark["quote_unit"] == "bps" and output_unit == "percent":
            value /= 100.0
        elif mark["quote_unit"] not in {"percent", "bps"}:
            raise PaperMarkError("linear_combo supports rates/curve legs only")
        total += weight * value
        sources.append(mark["source"])
        if mark.get("as_of"):
            dates.append(str(mark["as_of"]))
    return {
        "value": round(total, 8),
        "quote_unit": output_unit,
        "source": "derived:linear_combo[" + ",".join(sources) + "]",
        "as_of": min(dates) if dates else None,
        "kind": "derived",
        "expression": deepcopy(dict(expression)),
    }


def _futures_strip_average(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    """Average implied rate across explicit contracts from one locked curve family.

    This is intentionally simple paper math. A trader/subagent chooses the exact
    contracts defining the forward window; trusted code recomputes the same
    weighted average from that curve on every mark.
    """
    curve_id = str(expression.get("curve_id") or "").upper()
    if curve_id not in {"SOFR", "CORRA", "AONIA"}:
        raise PaperMarkError("futures_strip_average curve_id must be SOFR, CORRA or AONIA")
    expiries = expression.get("expiries")
    if not isinstance(expiries, list) or not expiries:
        raise PaperMarkError("futures_strip_average requires non-empty expiries")
    weights = expression.get("weights")
    if weights is None:
        weights = [1.0] * len(expiries)
    if not isinstance(weights, list) or len(weights) != len(expiries):
        raise PaperMarkError("futures_strip_average weights must match expiries")
    total_weight = 0.0
    weighted_rate = 0.0
    sources: list[str] = []
    dates: list[str] = []
    leg_rates: dict[str, float] = {}
    for expiry, raw_weight in zip(expiries, weights):
        weight = _number(raw_weight, "futures_strip_average weight")
        if weight <= 0:
            raise PaperMarkError("futures_strip_average weights must be positive")
        mark = _tradable_curve_contract_mark(state, curve_id, str(expiry))
        alias = f"{curve_id}_{expiry}"
        leg_rates[alias] = float(mark["value"])
        weighted_rate += weight * float(mark["value"])
        total_weight += weight
        sources.append(mark["source"])
        if mark.get("as_of"):
            dates.append(str(mark["as_of"]))
    return {
        "value": round(weighted_rate / total_weight, 8),
        "quote_unit": "percent",
        "source": f"derived:futures_strip_average:{curve_id}[" + ",".join(sources) + "]",
        "as_of": min(dates) if dates else state.get("generated_at"),
        "kind": "derived",
        "expression": deepcopy(dict(expression)),
        "leg_rates": leg_rates,
    }


def _structure_leg_specs(expression: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    kind = str(expression.get("type") or "")
    if kind == "calendar_spread":
        curve = str(expression.get("curve_id") or "")
        return [
            ("near", curve, str(expression.get("near_expiry") or "")),
            ("far", curve, str(expression.get("far_expiry") or "")),
        ]
    if kind == "butterfly":
        curve = str(expression.get("curve_id") or "")
        return [
            ("wing1", curve, str(expression.get("wing1_expiry") or "")),
            ("body", curve, str(expression.get("body_expiry") or "")),
            ("wing2", curve, str(expression.get("wing2_expiry") or "")),
        ]
    if kind == "outright_rv":
        receive = expression.get("receive") if isinstance(expression.get("receive"), Mapping) else {}
        pay = expression.get("pay") if isinstance(expression.get("pay"), Mapping) else {}
        return [
            ("receive", str(receive.get("curve_id") or ""), str(receive.get("expiry") or "")),
            ("pay", str(pay.get("curve_id") or ""), str(pay.get("expiry") or "")),
        ]
    if kind == "curve_rv":
        long_cal = expression.get("long_calendar") if isinstance(expression.get("long_calendar"), Mapping) else {}
        short_cal = expression.get("short_calendar") if isinstance(expression.get("short_calendar"), Mapping) else {}
        return [
            ("long_calendar_near", str(long_cal.get("curve_id") or ""), str(long_cal.get("near_expiry") or "")),
            ("long_calendar_far", str(long_cal.get("curve_id") or ""), str(long_cal.get("far_expiry") or "")),
            ("short_calendar_near", str(short_cal.get("curve_id") or ""), str(short_cal.get("near_expiry") or "")),
            ("short_calendar_far", str(short_cal.get("curve_id") or ""), str(short_cal.get("far_expiry") or "")),
        ]
    raise PaperMarkError(f"unsupported structure type {kind!r}")


def _usd_sofr_ois_mark(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    from scripts.rates.ois import OIS_TYPE, instrument_id

    if str(expression.get("type") or "") != OIS_TYPE:
        raise PaperMarkError("usd_sofr_ois expression required")
    try:
        start_years = float(expression.get("start_years"))
        tenor_years = float(expression.get("tenor_years"))
    except (TypeError, ValueError) as exc:
        raise PaperMarkError("usd_sofr_ois requires numeric start_years and tenor_years") from exc
    try:
        inst_id = instrument_id(start_years=start_years, tenor_years=tenor_years)
    except Exception as exc:
        raise PaperMarkError(str(exc)) from exc
    block = state.get("usd_sofr_ois")
    if not isinstance(block, Mapping):
        raise PaperMarkError("usd_sofr_ois block absent")
    instruments = block.get("instruments")
    if not isinstance(instruments, Mapping):
        raise PaperMarkError(f"usd_sofr_ois.instruments.{inst_id}")
    row = instruments.get(inst_id)
    if not isinstance(row, Mapping):
        raise PaperMarkError(f"usd_sofr_ois.instruments.{inst_id}")
    par = row.get("par_rate_percent")
    if par in (None, ""):
        raise PaperMarkError(f"usd_sofr_ois.instruments.{inst_id}.par_rate_percent")
    quote_type = str(row.get("quote_type") or "")
    source = str(row.get("source") or "")
    if quote_type == "observed_par":
        mark_source = source
        kind = "direct"
    else:
        mark_source = source if source.startswith("derived:usd_sofr_ois") else f"derived:usd_sofr_ois:{source}"
        kind = "derived"
    return {
        "value": round(float(par), 8),
        "quote_unit": "percent",
        "source": mark_source,
        "as_of": row.get("as_of") or block.get("as_of"),
        "kind": kind,
        "instrument_id": inst_id,
        "expression": deepcopy(dict(expression)),
    }


def _treasury_futures_mark(state: Mapping[str, Any], instrument: str) -> dict[str, Any]:
    from scripts.rates.treasury_futures import parse_treasury_id

    parsed = parse_treasury_id(instrument)
    if parsed is None or parsed.get("status") != "ok":
        raise PaperMarkError(f"treasury futures instrument unavailable for {instrument!r}")
    instrument_id = str(parsed["instrument"])
    block = state.get("treasury_futures")
    contracts = block.get("contracts") if isinstance(block, Mapping) else None
    row = contracts.get(instrument_id) if isinstance(contracts, Mapping) else None
    if not isinstance(row, Mapping):
        raise PaperMarkError(f"treasury_futures.contracts.{instrument_id}")
    price = row.get("futures_price")
    if price in (None, ""):
        raise PaperMarkError(f"treasury_futures.contracts.{instrument_id}.futures_price")
    source = row.get("price_source") if isinstance(row.get("price_source"), str) and row.get("price_source") else "treasury_futures"
    return {
        "value": round(float(price), 8),
        "quote_unit": "futures_points",
        "source": str(source),
        "as_of": row.get("price_as_of"),
        "kind": "direct",
        "expression": {"type": "treasury_future"},
    }


def _structure_mark(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    """Mark structure legs from the frozen curves without resizing contracts."""
    from scripts.rates.contract_economics import parse_contract_id
    from scripts.rates.structures import package_mark_bp

    sources: list[str] = []
    dates: list[str] = []
    rates: dict[str, float] = {}
    preview: list[dict[str, Any]] = []
    for role, curve_id, expiry in _structure_leg_specs(expression):
        parsed = parse_contract_id(f"{curve_id}_{expiry}")
        if parsed is None:
            raise PaperMarkError(f"structure leg {curve_id} {expiry} is not a supported contract")
        mark = _tradable_curve_contract_mark(state, curve_id, expiry)
        rates[parsed.alias] = float(mark["value"])
        rates[role] = float(mark["value"])
        preview.append({"role": role, "mark_rate": float(mark["value"]), "entry_rate": float(mark["value"])})
        sources.append(str(mark["source"]))
        if mark.get("as_of"):
            dates.append(str(mark["as_of"]))
    value = package_mark_bp(str(expression.get("type") or ""), preview)
    if value is None:
        raise PaperMarkError("structure mark unavailable")
    return {
        "value": round(value, 8),
        "quote_unit": "bps",
        "source": f"derived:{expression.get('type')}[" + ",".join(sources) + "]",
        "as_of": min(dates) if dates else state.get("generated_at"),
        "kind": "derived",
        "expression": deepcopy(dict(expression)),
        "leg_rates": rates,
        "structure_label": expression.get("type"),
    }


def _official_curve_df(
    state: Mapping[str, Any],
    country: str,
    years: float,
) -> tuple[float, str | None, str]:
    curves = state.get("official_curves")
    countries = curves.get("countries") if isinstance(curves, Mapping) else None
    block = countries.get(country) if isinstance(countries, Mapping) else None
    if not isinstance(block, Mapping) or block.get("status") != "ok":
        raise PaperMarkError(f"official curve unavailable for {country}")
    raw = block.get("discount_factors")
    if not isinstance(raw, Mapping):
        raise PaperMarkError(f"official curve discount factors unavailable for {country}")

    points: list[tuple[float, float, str | None, str]] = []
    for label, row in raw.items():
        if not isinstance(row, Mapping):
            continue
        maturity = row.get("maturity_years")
        value = row.get("value")
        if maturity is None or value is None:
            continue
        t = _number(maturity, f"{country} curve maturity")
        df = _number(value, f"{country} {label} discount factor")
        if t < 0 or df <= 0:
            continue
        points.append((t, df, row.get("as_of") or block.get("as_of"), str(row.get("source") or label)))
    if not points:
        raise PaperMarkError(f"official curve contains no discount factors for {country}")
    points.sort(key=lambda item: item[0])
    target = float(years)
    for t, df, as_of, source in points:
        if abs(t - target) < 1e-9:
            return df, str(as_of) if as_of else None, f"official_curves.{country}.{source}@{t:g}Y"

    lower = next((p for p in reversed(points) if p[0] < target), None)
    upper = next((p for p in points if p[0] > target), None)
    if lower is None or upper is None:
        raise PaperMarkError(
            f"{country} official curve cannot interpolate {target:g}Y outside "
            f"{points[0][0]:g}Y..{points[-1][0]:g}Y"
        )
    t0, df0, d0, s0 = lower
    t1, df1, d1, s1 = upper
    # Log-linear interpolation preserves positive discount factors and corresponds
    # to a constant continuously-compounded forward between the source nodes.
    w = (target - t0) / (t1 - t0)
    log_df = math.log(df0) + w * (math.log(df1) - math.log(df0))
    df = math.exp(log_df)
    dates = [str(d) for d in (d0, d1) if d]
    as_of = min(dates) if dates else str(block.get("as_of") or "") or None
    source = f"official_curves.{country}.loglinear[{s0}@{t0:g}Y,{s1}@{t1:g}Y]"
    return df, as_of, source


def _forward_swap(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    """Forward par-swap proxy from deterministic discount factors.

    Compact paper syntax:
      {"type":"forward_swap","curve_country":"US","start_years":2,
       "tenor_years":2,"payment_frequency":1}

    For an annual-pay 2y2y:
      rate = (P(0,2) - P(0,4)) / (P(0,3) + P(0,4))

    Explicit source refs remain supported for fixtures and bespoke curves.
    """
    country = expression.get("curve_country")
    if isinstance(country, str):
        country = country.upper()
        if country not in {"US", "CA", "AU"}:
            raise PaperMarkError("forward_swap curve_country must be US, CA or AU")
        start_years = _number(expression.get("start_years"), "forward_swap start_years")
        tenor_years = _number(expression.get("tenor_years"), "forward_swap tenor_years")
        frequency = int(_number(expression.get("payment_frequency", 1), "forward_swap payment_frequency"))
        if start_years < 0 or tenor_years <= 0:
            raise PaperMarkError("forward_swap start_years must be >=0 and tenor_years >0")
        if frequency not in {1, 2, 4}:
            raise PaperMarkError("forward_swap payment_frequency must be 1, 2 or 4")
        end_years = start_years + tenor_years
        periods_float = tenor_years * frequency
        periods = int(round(periods_float))
        if periods <= 0 or abs(periods_float - periods) > 1e-8:
            raise PaperMarkError("forward_swap tenor_years must align to payment_frequency")

        start_df, start_asof, start_source = _official_curve_df(state, country, start_years)
        end_df, end_asof, end_source = _official_curve_df(state, country, end_years)
        accrual = 1.0 / frequency
        denom = 0.0
        dates = [d for d in (start_asof, end_asof) if d]
        refs = [start_source, end_source]
        for i in range(1, periods + 1):
            payment_t = start_years + i * accrual
            df, as_of, source = _official_curve_df(state, country, payment_t)
            denom += accrual * df
            refs.append(source)
            if as_of:
                dates.append(as_of)
    else:
        start_ref = expression.get("start_discount_ref")
        end_ref = expression.get("end_discount_ref")
        payments = expression.get("payment_discount_refs")
        if not isinstance(start_ref, str) or not isinstance(end_ref, str):
            raise PaperMarkError(
                "forward_swap requires curve_country/start_years/tenor_years "
                "or explicit start_discount_ref/end_discount_ref"
            )
        if not isinstance(payments, list) or not payments:
            raise PaperMarkError("forward_swap requires payment_discount_refs")
        start_df, start_asof = _path_get(state, start_ref)
        end_df, end_asof = _path_get(state, end_ref)
        denom = 0.0
        dates = [d for d in (start_asof, end_asof) if d]
        refs = [start_ref, end_ref]
        for payment in payments:
            if not isinstance(payment, Mapping) or not isinstance(payment.get("ref"), str):
                raise PaperMarkError("forward_swap payment requires ref")
            df, as_of = _path_get(state, payment["ref"])
            accrual = _number(payment.get("accrual", 1.0), "forward_swap accrual")
            if df <= 0 or accrual <= 0:
                raise PaperMarkError("forward_swap payment inputs must be positive")
            denom += accrual * df
            refs.append(payment["ref"])
            if as_of:
                dates.append(as_of)

    if not (0 < start_df < 1.5 and 0 < end_df < 1.5):
        raise PaperMarkError("forward_swap discount factors are implausible")
    if denom <= 0:
        raise PaperMarkError("forward_swap annuity is non-positive")
    rate_percent = 100.0 * (start_df - end_df) / denom
    return {
        "value": round(rate_percent, 8),
        "quote_unit": "percent",
        "source": "derived:forward_swap_proxy[" + ",".join(refs) + "]",
        "as_of": min(dates) if dates else None,
        "kind": "derived",
        "expression": deepcopy(dict(expression)),
    }


def resolve_paper_mid(
    market_state: Mapping[str, Any],
    instrument: str,
    *,
    asset_class: str | None = None,
    expression: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a canonical paper mid from the frozen market-state packet."""
    if not isinstance(market_state, Mapping):
        raise PaperMarkError("market_state is required for deterministic paper marks")
    if expression:
        kind = expression.get("type")
        if kind == "linear_combo":
            return _linear_combo(market_state, expression)
        if kind == "forward_swap":
            return _forward_swap(market_state, expression)
        if kind == "futures_strip_average":
            if asset_class == "curve":
                raise PaperMarkError(
                    "futures_strip_average is a strip average, not a curve spread"
                )
            return _futures_strip_average(market_state, expression)
        if kind == "usd_sofr_ois":
            return _usd_sofr_ois_mark(market_state, expression)
        if kind == "treasury_future":
            if not instrument:
                raise PaperMarkError("treasury_future mark requires instrument")
            return _treasury_futures_mark(market_state, instrument)
        if kind in {"calendar_spread", "butterfly", "outright_rv", "curve_rv"}:
            return _structure_mark(market_state, expression)
        raise PaperMarkError(f"unsupported paper expression type {kind!r}")
    if not instrument:
        raise PaperMarkError("instrument is required for a paper mid")
    return _resolve_direct(market_state, instrument, asset_class)


def find_position(positions: list[Any] | None, position_id: str, *, owner: str | None = None) -> Mapping[str, Any]:
    for position in positions or []:
        if isinstance(position, Mapping) and position.get("position_id") == position_id:
            return position
    label = f" for {owner}" if owner else ""
    raise PaperMarkError(f"unknown position_id {position_id}{label}")


def _position_lookup(books: Mapping[str, Any], seat: str, position_id: str) -> Mapping[str, Any]:
    seat_block = (books.get("seats") or {}).get(seat) if isinstance(books, Mapping) else None
    positions = seat_block.get("positions") if isinstance(seat_block, Mapping) else None
    return find_position(list(positions or []), position_id, owner=seat)


def hydrate_structure_rates(position: dict[str, Any], market_state: Mapping[str, Any] | None) -> None:
    """Fill missing leg rates from the frozen curve. Does not invent a level."""
    if not position.get("legs"):
        return
    if not isinstance(market_state, Mapping):
        if any(leg.get("entry_rate") is None for leg in position["legs"]):
            raise PaperMarkError("structure leg rates are missing and market_state was not supplied")
        return
    mark = resolve_paper_mid(
        market_state,
        str(position.get("instrument") or ""),
        asset_class=position.get("asset_class"),
        expression=position.get("paper_expression"),
    )
    from scripts.rates.structures import package_mark_bp, update_leg_marks

    rates = mark.get("leg_rates") or {}
    update_leg_marks(position["legs"], rates)
    from scripts.rates.structures import apply_mark_fx

    if not apply_mark_fx(position["legs"], market_state):
        raise PaperMarkError("current FX fixing missing or stale for a structure leg")
    for leg in position["legs"]:
        leg["mark_status"] = "ok"
        if leg.get("entry_rate") is None:
            if leg.get("mark_rate") is None:
                raise PaperMarkError(f"structure leg {leg.get('instrument')} has no implied rate")
            leg["entry_rate"] = leg["mark_rate"]
    kind = None
    expression = position.get("paper_expression")
    if isinstance(expression, Mapping):
        kind = expression.get("type")
    kind = kind or position.get("structure_label")
    package = package_mark_bp(str(kind or ""), position["legs"])
    if package is None:
        raise PaperMarkError("structure package mark unavailable")
    position["entry_price"] = package
    position["mark_price"] = package
    position["mark_price_source"] = mark.get("source")
    position["entry_price_source"] = mark.get("source")
    position["mark_price_as_of"] = mark.get("as_of")
    position["entry_price_as_of"] = mark.get("as_of")


def _is_strip_position(position: Mapping[str, Any]) -> bool:
    expression = position.get("paper_expression")
    if isinstance(expression, Mapping) and expression.get("type") == "futures_strip_average":
        return True
    return position.get("structure_label") == "futures_strip_average"


def _ois_position(position: Mapping[str, Any]) -> bool:
    family = position.get("family") or position.get("structure_label")
    expression = position.get("paper_expression")
    expr_type = expression.get("type") if isinstance(expression, Mapping) else None
    return family == "usd_sofr_ois" or expr_type == "usd_sofr_ois"


def _treasury_position(position: Mapping[str, Any]) -> bool:
    return position.get("family") == "treasury_future" or position.get("price_unit") == "futures_points"


def marks_are_current(position: Mapping[str, Any]) -> bool:
    if position.get("mark_status") == "unavailable":
        return False
    if (
        not position.get("legs")
        and position.get("valuation_method") == "instrument_dv01"
        and position.get("contract_currency") not in (None, "USD")
        and (
            position.get("mark_fx_usd_per_unit") in (None, "")
            or position.get("mark_fx_status") not in (None, "ok")
        )
    ):
        return False
    legs = position.get("legs")
    if not legs:
        return position.get("mark_price") not in (None, "")
    for leg in legs:
        if not isinstance(leg, Mapping):
            return False
        if leg.get("mark_status") == "unavailable" or leg.get("mark_rate") is None:
            return False
        if leg.get("currency") not in (None, "USD") and (
            leg.get("mark_fx_usd_per_unit") is None or leg.get("mark_fx_status") not in (None, "ok")
        ):
            return False
    return position.get("mark_price") not in (None, "")


def apply_resolved_mark(position: dict[str, Any], mark: Mapping[str, Any]) -> None:
    legs = position.get("legs")
    if legs:
        rates = mark.get("leg_rates") if isinstance(mark.get("leg_rates"), Mapping) else {}
        missing = [str(leg.get("instrument")) for leg in legs if str(leg.get("instrument")) not in rates]
        if missing:
            clear_unresolved_mark(position, reason=f"partial leg marks missing: {missing}")
            return
        from scripts.rates.structures import apply_mark_fx, package_mark_bp, update_leg_marks

        update_leg_marks(position["legs"], rates)
        for leg in position["legs"]:
            leg["mark_status"] = "ok"
            leg["mark_as_of"] = mark.get("as_of")
            leg["mark_source"] = mark.get("source")
        live_state = mark.get("market_state") if isinstance(mark.get("market_state"), Mapping) else None
        if live_state is not None and not apply_mark_fx(position["legs"], live_state):
            clear_unresolved_mark(position, reason="current FX fixing missing or stale")
            return
        if _is_strip_position(position):
            position["mark_status"] = "ok"
            position.pop("mark_unavailable_reason", None)
            position["mark_price"] = mark.get("value")
            dv01_sum = round(sum(abs(float(leg.get("dv01_usd") or 0.0)) for leg in position["legs"]), 8)
            position["spread_dv01_usd"] = dv01_sum
            position["shock_dv01_usd"] = dv01_sum
        else:
            kind = None
            expression = position.get("paper_expression")
            if isinstance(expression, Mapping):
                kind = expression.get("type")
            package = package_mark_bp(str(kind or position.get("structure_label") or ""), position["legs"])
            if package is None:
                clear_unresolved_mark(position, reason="structure package or FX mark incomplete")
                return
            position["mark_price"] = package
            position["mark_status"] = "ok"
            position.pop("mark_unavailable_reason", None)
            position.pop("pnl_unavailable", None)
            if not marks_are_current(position):
                clear_unresolved_mark(position, reason="structure package or FX mark incomplete")
                return
    else:
        position["mark_price"] = mark["value"]
        if _ois_position(position):
            position["mark_rate"] = mark["value"]
    position["mark_price_source"] = mark["source"]
    position["mark_price_as_of"] = mark.get("as_of")
    position["mark_status"] = "ok"
    position.pop("mark_unavailable_reason", None)


def clear_unresolved_mark(position: dict[str, Any], *, reason: str | None = None) -> None:
    """Drop the package mark and every leg mark together. Stale legs cannot keep a P&L."""
    position["mark_price"] = None
    position["mark_price_source"] = None
    position["mark_price_as_of"] = None
    position["mark_status"] = "unavailable"
    position["pnl_unavailable"] = True
    if reason:
        position["mark_unavailable_reason"] = reason
    for leg in position.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        leg["mark_rate"] = None
        leg["mark_status"] = "unavailable"
        leg["mark_as_of"] = None
        leg["mark_source"] = None
        leg["mark_fx_usd_per_unit"] = None
        leg["mark_fx_status"] = "unavailable"
        leg["dv01_usd"] = None
    if not position.get("legs") and position.get("valuation_method") == "instrument_dv01":
        position["mark_fx_usd_per_unit"] = None
        position["mark_fx_status"] = "unavailable"


def refresh_positions(
    positions: list[dict[str, Any]],
    market_state: Mapping[str, Any],
    *,
    alerts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Re-mark a position list. Missing marks isolate to that position; nothing is invented."""
    for position in positions:
        try:
            mark = resolve_paper_mid(
                market_state,
                str(position.get("instrument") or ""),
                asset_class=position.get("asset_class"),
                expression=position.get("paper_expression"),
            )
        except PaperMarkError as exc:
            clear_unresolved_mark(position, reason=str(exc))
            if alerts is not None:
                alerts.append(f"Paper mark unavailable for {position.get('instrument')}: {exc}")
            continue
        mark = dict(mark)
        mark["market_state"] = market_state
        apply_resolved_mark(position, mark)
        if position.get("valuation_method") == "instrument_dv01" and not position.get("legs"):
            from scripts.rates.lifecycle import refresh_outright_fx

            if _treasury_position(position):
                continue
            if not refresh_outright_fx(position, market_state):
                if alerts is not None:
                    alerts.append(f"FX mark unavailable for {position.get('instrument')}")
                continue
        if position.get("legs") and not _is_strip_position(position):
            from scripts.rates.structures import apply_mark_fx, package_mark_bp

            if not apply_mark_fx(position["legs"], market_state):
                clear_unresolved_mark(position, reason="current FX fixing missing or stale")
                if alerts is not None:
                    alerts.append(f"FX mark unavailable for {position.get('instrument')}")
                continue
            kind = None
            expression = position.get("paper_expression")
            if isinstance(expression, Mapping):
                kind = expression.get("type")
            package = package_mark_bp(str(kind or position.get("structure_label") or ""), position["legs"])
            if package is None:
                clear_unresolved_mark(position, reason="structure package mark incomplete after FX")
                continue
            position["mark_price"] = package
            position["spread_dv01_usd"] = max(abs(float(leg.get("dv01_usd") or 0.0)) for leg in position["legs"])
    return positions


def refresh_book_marks(books: dict[str, Any], market_state: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh every open position to the current deterministic packet mid."""
    for _seat, seat_book in (books.get("seats") or {}).items():
        alerts = seat_book.setdefault("alerts", [])
        refresh_positions(list(seat_book.get("positions") or []), market_state, alerts=alerts)
    return books


def hydrate_action_mids(
    actions: list[dict[str, Any]],
    market_state: Mapping[str, Any],
    *,
    positions: list[Any] | None = None,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    """Replace model-supplied transaction prices with deterministic paper mids.

    OPEN/ADD/HEDGE enter at the current frozen mid. REDUCE/CLOSE exit at that same
    review mid. Missing marks fail closed; they are never invented.
    """
    for action in actions:
        kind = action.get("action")
        if kind not in {"OPEN", "ADD", "REDUCE", "CLOSE", "HEDGE"}:
            continue
        instrument = action.get("instrument")
        asset_class = action.get("asset_class")
        expression = action.get("paper_expression")
        if kind in {"ADD", "REDUCE", "CLOSE"}:
            pos = find_position(positions, str(action.get("position_id") or ""), owner=owner)
            instrument = pos.get("instrument")
            asset_class = pos.get("asset_class")
            expression = pos.get("paper_expression")
        elif kind == "HEDGE" and not instrument:
            target_id = str(action.get("hedge_of") or action.get("position_id") or "")
            pos = find_position(positions, target_id, owner=owner)
            instrument = pos.get("instrument")
            asset_class = pos.get("asset_class")
            expression = action.get("paper_expression") or pos.get("paper_expression")
        if kind in {"OPEN", "ADD", "HEDGE"}:
            from scripts.overnight.mark_admission import entry_rejection

            rejection = entry_rejection(
                instrument,
                asset_class=asset_class if isinstance(asset_class, str) else None,
                expression=expression if isinstance(expression, Mapping) else None,
                action=kind,
            )
            if rejection:
                action["_admission_rejection"] = rejection
                action["_paper_mark_error"] = f"{rejection['reason']}: {rejection['message']}"
                for key in ("price", "mark_price", "paper_mid_source", "paper_mid_as_of", "paper_mid_kind"):
                    action.pop(key, None)
                continue
        try:
            mark = resolve_paper_mid(
                market_state,
                str(instrument or ""),
                asset_class=asset_class,
                expression=expression,
            )
        except PaperMarkError as exc:
            if kind in {"OPEN", "ADD", "HEDGE"}:
                action["_paper_mark_error"] = str(exc)
            continue
        action["instrument"] = instrument
        if asset_class:
            action["asset_class"] = asset_class
        action["price"] = mark["value"]
        action["mark_price"] = mark["value"]
        action["paper_mid_source"] = mark["source"]
        action["paper_mid_as_of"] = mark.get("as_of")
        action["paper_mid_kind"] = mark["kind"]
        if expression:
            action["paper_expression"] = deepcopy(expression)
    return actions


def hydrate_review_mids(
    books: Mapping[str, Any],
    reviews: Mapping[str, Any],
    market_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace model-supplied transaction prices with deterministic paper mids.

    OPEN/ADD/HEDGE enter at the current frozen mid. REDUCE/CLOSE exit at that same
    review mid. The model chooses the expression and size; deterministic code owns
    the transaction mark and provenance.
    """
    out = deepcopy(dict(reviews))
    for seat, payload in out.items():
        if not isinstance(payload, Mapping):
            continue
        seat_block = (books.get("seats") or {}).get(seat) if isinstance(books, Mapping) else None
        positions = list((seat_block or {}).get("positions") or [])
        hydrate_action_mids(
            list(payload.get("actions") or []),
            market_state,
            positions=positions,
            owner=seat,
        )
    return out
