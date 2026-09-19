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


def _rate_mark(state: Mapping[str, Any], country: str, tenor: str) -> dict[str, Any]:
    rates = state.get("rates")
    if not isinstance(rates, Mapping) or not isinstance(rates.get(country), Mapping):
        raise PaperMarkError(f"rates block unavailable for {country}")
    block = rates[country]
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
            "as_of": state.get("generated_at") or row.get("as_of") or row.get("expiry"),
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

    m = re.fullmatch(r"(US|CA|AU|NZ)_(2Y|5Y|10Y|30Y|LONG)", upper)
    if m:
        return _rate_mark(state, m.group(1), m.group(2))

    m = re.fullmatch(r"(US|CA|AU|NZ)_(2S10S|5S10S)", upper)
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
    m = re.fullmatch(r"(SOFR|CORRA|AONIA)_(20\d{2}-\d{2})", upper)
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
    for expiry, raw_weight in zip(expiries, weights):
        weight = _number(raw_weight, "futures_strip_average weight")
        if weight <= 0:
            raise PaperMarkError("futures_strip_average weights must be positive")
        mark = _tradable_curve_contract_mark(state, curve_id, str(expiry))
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
            return _futures_strip_average(market_state, expression)
        raise PaperMarkError(f"unsupported paper expression type {kind!r}")
    if not instrument:
        raise PaperMarkError("instrument is required for a paper mid")
    return _resolve_direct(market_state, instrument, asset_class)


def _position_lookup(books: Mapping[str, Any], seat: str, position_id: str) -> Mapping[str, Any]:
    seat_block = (books.get("seats") or {}).get(seat) if isinstance(books, Mapping) else None
    positions = seat_block.get("positions") if isinstance(seat_block, Mapping) else None
    for position in positions or []:
        if position.get("position_id") == position_id:
            return position
    raise PaperMarkError(f"unknown position_id {position_id} for {seat}")


def refresh_book_marks(books: dict[str, Any], market_state: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh every open position to the current deterministic packet mid."""
    for seat, seat_book in (books.get("seats") or {}).items():
        for position in seat_book.get("positions") or []:
            try:
                mark = resolve_paper_mid(
                    market_state,
                    str(position.get("instrument") or ""),
                    asset_class=position.get("asset_class"),
                    expression=position.get("paper_expression"),
                )
            except PaperMarkError as exc:
                position["mark_price"] = None
                position["mark_price_source"] = None
                position["mark_price_as_of"] = None
                seat_book.setdefault("alerts", []).append(
                    f"Paper mark unavailable for {position.get('instrument')}: {exc}"
                )
                continue
            position["mark_price"] = mark["value"]
            position["mark_price_source"] = mark["source"]
            position["mark_price_as_of"] = mark.get("as_of")
    return books


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
        for action in payload.get("actions") or []:
            kind = action.get("action")
            if kind not in {"OPEN", "ADD", "REDUCE", "CLOSE", "HEDGE"}:
                continue
            instrument = action.get("instrument")
            asset_class = action.get("asset_class")
            expression = action.get("paper_expression")
            if kind in {"ADD", "REDUCE", "CLOSE"}:
                pos = _position_lookup(books, seat, str(action.get("position_id") or ""))
                instrument = pos.get("instrument")
                asset_class = pos.get("asset_class")
                expression = pos.get("paper_expression")
            elif kind == "HEDGE" and not instrument:
                target_id = str(action.get("hedge_of") or action.get("position_id") or "")
                pos = _position_lookup(books, seat, target_id)
                instrument = pos.get("instrument")
                asset_class = pos.get("asset_class")
                expression = action.get("paper_expression") or pos.get("paper_expression")
            mark = resolve_paper_mid(
                market_state,
                str(instrument or ""),
                asset_class=asset_class,
                expression=expression,
            )
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
    return out
