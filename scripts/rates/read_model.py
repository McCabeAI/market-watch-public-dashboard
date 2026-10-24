"""Strategy-neutral relative-rate analytics.

Every row is an observed level with units, freshness, and an explicit empty
recommendation. Nothing here is a preferred trade, a quota, or an edge.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.rates.contract_economics import CURVE_SPEC, fx_usd_per_unit
from scripts.trader_room.constants import STANDING_ADVOCATES

SUPPORTED_CURVES = ("SOFR", "CORRA", "AONIA")
ADVISORY = (
    "Observed spreads and flies are market levels with contract units. "
    "They are not trade recommendations, disclosed edges, or default preferences. "
    "No trade is required."
)


def _contracts(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in block.get("contracts") or []:
        if not isinstance(row, Mapping):
            continue
        expiry = str(row.get("expiry") or "")
        rate = row.get("implied_rate")
        if not expiry or rate is None:
            continue
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "expiry": expiry,
                "code": row.get("code"),
                "implied_rate_percent": rate_f,
                "as_of": row.get("observation_date") or row.get("as_of"),
            }
        )
    rows.sort(key=lambda item: item["expiry"])
    return rows


def _row(**fields: Any) -> dict[str, Any]:
    base = {
        "recommendation": None,
        "preferred_side": None,
        "edge": None,
        "optional_no_trade": True,
        "strategy_neutral": True,
    }
    base.update(fields)
    return base


def build_relative_analytics(market_state: Mapping[str, Any] | None) -> dict[str, Any]:
    state = market_state if isinstance(market_state, Mapping) else {}
    curves = state.get("tradable_rate_curves")
    curve_map = curves.get("curves") if isinstance(curves, Mapping) else None
    if not isinstance(curve_map, Mapping):
        curve_map = {}
    loaded: dict[str, list[dict[str, Any]]] = {}
    missing: list[dict[str, Any]] = []
    for curve_id in SUPPORTED_CURVES:
        block = curve_map.get(curve_id)
        spec = CURVE_SPEC[curve_id]
        fx, pair = fx_usd_per_unit(spec.currency, state)
        if not isinstance(block, Mapping) or block.get("status") != "ok":
            missing.append(
                {
                    "curve_id": curve_id,
                    "status": "unavailable",
                    "reason": (block or {}).get("error") if isinstance(block, Mapping) else "tradable curve missing",
                }
            )
            continue
        contracts = _contracts(block)
        if not contracts:
            missing.append({"curve_id": curve_id, "status": "unavailable", "reason": "no contracts with implied rates"})
            continue
        loaded[curve_id] = contracts
        if fx is None:
            missing.append(
                {
                    "curve_id": curve_id,
                    "status": "fx_unavailable",
                    "reason": f"{spec.currency} USD conversion missing ({pair}); levels are still listed in local rate space",
                }
            )

    rows: list[dict[str, Any]] = []
    for curve_id, contracts in loaded.items():
        spec = CURVE_SPEC[curve_id]
        fx, pair = fx_usd_per_unit(spec.currency, state)
        for contract in contracts:
            rows.append(
                _row(
                    kind="outright",
                    curve_id=curve_id,
                    product_code=spec.product_code,
                    currency=spec.currency,
                    expiry=contract["expiry"],
                    code=contract["code"],
                    implied_rate_percent=contract["implied_rate_percent"],
                    price_unit="implied_rate_percent",
                    dv01_note=spec.source,
                    fx_usd_per_unit=fx,
                    fx_pair=pair,
                    fx_status="ok" if fx is not None else "unavailable",
                    as_of=contract["as_of"],
                    as_of_missing=contract["as_of"] in (None, ""),
                    status="ok",
                )
            )
        for i, near in enumerate(contracts):
            for far in contracts[i + 1 :]:
                spread = (far["implied_rate_percent"] - near["implied_rate_percent"]) * 100.0
                rows.append(
                    _row(
                        kind="domestic_calendar",
                        curve_id=curve_id,
                        product_code=spec.product_code,
                        currency=spec.currency,
                        near_expiry=near["expiry"],
                        far_expiry=far["expiry"],
                        observed_spread_bp=round(spread, 6),
                        mark_definition="far implied rate minus near implied rate, in basis points",
                        price_unit="bps",
                        structure_label="calendar_spread",
                        not_a_strip=True,
                        fx_status="ok" if fx is not None else "unavailable",
                        as_of=_older(near.get("as_of"), far.get("as_of")),
                        as_of_missing=near.get("as_of") in (None, "") or far.get("as_of") in (None, ""),
                        status="ok",
                    )
                )
        for i in range(len(contracts) - 2):
            wing1, body, wing2 = contracts[i], contracts[i + 1], contracts[i + 2]
            fly = (2.0 * body["implied_rate_percent"] - wing1["implied_rate_percent"] - wing2["implied_rate_percent"]) * 100.0
            rows.append(
                _row(
                    kind="domestic_butterfly",
                    curve_id=curve_id,
                    product_code=spec.product_code,
                    currency=spec.currency,
                    wing1_expiry=wing1["expiry"],
                    body_expiry=body["expiry"],
                    wing2_expiry=wing2["expiry"],
                    observed_fly_bp=round(fly, 6),
                    mark_definition="(2 × body − wing1 − wing2) implied rates, in basis points",
                    price_unit="bps",
                    structure_label="butterfly",
                    not_a_strip=True,
                    fx_status="ok" if fx is not None else "unavailable",
                    as_of=_older(wing1.get("as_of"), body.get("as_of"), wing2.get("as_of")),
                    as_of_missing=any(item.get("as_of") in (None, "") for item in (wing1, body, wing2)),
                    status="ok",
                )
            )

    curve_ids = list(loaded)
    for i, left in enumerate(curve_ids):
        for right in curve_ids[i + 1 :]:
            left_by = {row["expiry"]: row for row in loaded[left]}
            right_by = {row["expiry"]: row for row in loaded[right]}
            shared = sorted(set(left_by) & set(right_by))
            for expiry in shared:
                a, b = left_by[expiry], right_by[expiry]
                rows.append(
                    _row(
                        kind="cross_market_outright",
                        receive_curve=left,
                        pay_curve=right,
                        expiry=expiry,
                        observed_spread_bp=round((a["implied_rate_percent"] - b["implied_rate_percent"]) * 100.0, 6),
                        mark_definition=f"{left} implied rate minus {right} implied rate, in basis points",
                        price_unit="bps",
                        structure_label="outright_rv",
                        not_a_strip=True,
                        fx_status=_pair_fx_status(state, left, right),
                        as_of=_older(a.get("as_of"), b.get("as_of")),
                        as_of_missing=a.get("as_of") in (None, "") or b.get("as_of") in (None, ""),
                        status="ok",
                    )
                )
            left_pairs = {(near["expiry"], far["expiry"]) for i, near in enumerate(loaded[left]) for far in loaded[left][i + 1 :]}
            right_pairs = {(near["expiry"], far["expiry"]) for i, near in enumerate(loaded[right]) for far in loaded[right][i + 1 :]}
            for near_expiry, far_expiry in sorted(left_pairs & right_pairs):
                l_near, l_far = left_by[near_expiry], left_by[far_expiry]
                r_near, r_far = right_by[near_expiry], right_by[far_expiry]
                long_spread = (l_far["implied_rate_percent"] - l_near["implied_rate_percent"]) * 100.0
                short_spread = (r_far["implied_rate_percent"] - r_near["implied_rate_percent"]) * 100.0
                rows.append(
                    _row(
                        kind="cross_market_curve",
                        long_curve=left,
                        short_curve=right,
                        near_expiry=near_expiry,
                        far_expiry=far_expiry,
                        observed_spread_bp=round(long_spread - short_spread, 6),
                        long_calendar_bp=round(long_spread, 6),
                        short_calendar_bp=round(short_spread, 6),
                        mark_definition="long-curve calendar spread minus short-curve calendar spread, in basis points",
                        price_unit="bps",
                        structure_label="curve_rv",
                        not_a_strip=True,
                        fx_status=_pair_fx_status(state, left, right),
                        as_of=_older(l_near.get("as_of"), l_far.get("as_of"), r_near.get("as_of"), r_far.get("as_of")),
                        as_of_missing=any(
                            item.get("as_of") in (None, "") for item in (l_near, l_far, r_near, r_far)
                        ),
                        status="ok",
                    )
                )

    return {
        "version": 1,
        "advisory": ADVISORY,
        "optional_no_trade": True,
        "strategy_neutral": True,
        "recommendation": None,
        "available_to": list(STANDING_ADVOCATES),
        "same_analytics_for_every_eligible_seat": True,
        "rows": rows,
        "missing": missing,
        "strip_is_not_a_curve_spread": True,
    }


def analytics_for_seat(market_state: Mapping[str, Any] | None, seat: str) -> dict[str, Any]:
    """Same observations for every eligible seat. The seat id is not a preference."""
    payload = build_relative_analytics(market_state)
    payload["seat"] = seat
    payload["eligible"] = seat in STANDING_ADVOCATES
    return payload


def _older(*values: Any) -> str | None:
    present = [str(value) for value in values if value not in (None, "")]
    if not present:
        return None
    return min(present)


def _pair_fx_status(state: Mapping[str, Any], left: str, right: str) -> str:
    ok = True
    for curve_id in (left, right):
        fx, _pair = fx_usd_per_unit(CURVE_SPEC[curve_id].currency, state)
        if fx is None:
            ok = False
    return "ok" if ok else "unavailable"
