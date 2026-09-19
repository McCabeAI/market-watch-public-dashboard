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

    # Exchange contract codes (SR1Z26, COAZ26, CRA..., etc.) are marked in
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


def _forward_swap(state: Mapping[str, Any], expression: Mapping[str, Any]) -> dict[str, Any]:
    """Forward par swap from deterministic discount factors.

    For a 2y2y annual-pay forward swap:
      rate = (P(0,2) - P(0,4)) / (P(0,3) + P(0,4))

    More generally the denominator is sum(alpha_i * P(0,t_i)).
    """
    start_ref = expression.get("start_discount_ref")
    end_ref = expression.get("end_discount_ref")
    payments = expression.get("payment_discount_refs")
    if not isinstance(start_ref, str) or not isinstance(end_ref, str):
        raise PaperMarkError("forward_swap requires start_discount_ref and end_discount_ref")
    if not isinstance(payments, list) or not payments:
        raise PaperMarkError("forward_swap requires payment_discount_refs")
    start_df, start_asof = _path_get(state, start_ref)
    end_df, end_asof = _path_get(state, end_ref)
    if not (0 < end_df <= start_df <= 1.5):
        raise PaperMarkError("forward_swap discount factors are implausible")
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
    if denom <= 0:
        raise PaperMarkError("forward_swap annuity is non-positive")
    rate_percent = 100.0 * (start_df - end_df) / denom
    return {
        "value": round(rate_percent, 8),
        "quote_unit": "percent",
        "source": "derived:forward_swap[" + ",".join(refs) + "]",
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
