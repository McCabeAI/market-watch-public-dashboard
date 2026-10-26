"""Explainable Canada Prima-pressure monitoring proxy (dict bundle in, dict out)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from scripts.prima_pressure import contract
from scripts.prima_pressure.sector_shadow import build_sector_shadow

CHANNELS = contract.CHANNELS


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _point_at_maturity(points: list[dict] | None, maturity_months: int) -> dict | None:
    for point in points or []:
        if point.get("maturity_months") == maturity_months:
            return point
    return None


def _change_1m(point: dict | None) -> tuple[float | None, float | None]:
    if not point:
        return None, None
    bucket = (point.get("changes") or {}).get("1m") or {}
    return _safe_float(bucket.get("abs")), _safe_float(bucket.get("pct"))


def _series_map(producer: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (producer or {}).get("series") or []:
        sid = row.get("series_id")
        if sid:
            out[str(sid)] = row
    return out


def _cpi_series_map(cpi: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in (cpi or {}).get("series") or []:
        sid = row.get("series_id")
        if sid:
            out[str(sid)] = row
    return out


def _as_of_date(bundle: dict) -> date | None:
    raw = bundle.get("as_of")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _release_age_days(as_of: date | None, release_time: Any) -> int | None:
    if as_of is None or not release_time:
        return None
    text = str(release_time)
    try:
        released = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            released = date.fromisoformat(text[:10])
        except ValueError:
            return None
    return (as_of - released).days


def _mom_direction(mom: float | None, band: float) -> str:
    if mom is None:
        return "UNAVAILABLE"
    if mom >= band:
        return "RISING"
    if mom <= -band:
        return "FALLING"
    return "STABLE"


def _curve_driver(point: dict, label: str) -> dict:
    abs_chg, pct_chg = _change_1m(point)
    bucket = (point.get("changes") or {}).get("1m") or {}
    obs_date = point.get("observation_date") or point.get("as_of")
    return {
        "label": label,
        "symbol": point.get("symbol"),
        "contract_month": point.get("contract_month"),
        "maturity_months": point.get("maturity_months"),
        "price": _safe_float(point.get("price")),
        "change_1m_abs": abs_chg,
        "change_1m_pct": pct_chg,
        "observation_date": obs_date,
        "change_1m_base_date": bucket.get("prior_date"),
    }


def _format_pct_driver(point: dict, prefix: str = "Brent last-day") -> str:
    pct = _safe_float(point.get("change_1m_pct"))
    if pct is None:
        _, pct = _change_1m(point)
    month = point.get("contract_month") or "unknown"
    if pct is None:
        return f"{prefix} {month} 1m change unavailable"
    sign = "+" if pct >= 0 else ""
    return f"{prefix} {month} 1m change {sign}{pct * 100:.1f} percent"


def _channel_shell(
    direction: str,
    *,
    stale: bool = False,
    drivers: list[dict] | None = None,
    note: str | None = None,
) -> dict:
    return {
        "direction": direction,
        "coverage": 0 if direction == "UNAVAILABLE" else 1,
        "stale": stale,
        "drivers": drivers or [],
        "note": note,
    }


def _shock_persistence(bundle: dict) -> tuple[dict, str, list[dict], bool]:
    oil = bundle.get("oil_curve") or bundle.get("oil_curves") or {}
    brent = oil.get("brent_last_day") or {}
    wti = oil.get("wti") or {}
    brent_points = brent.get("points") or []
    wti_points = wti.get("points") or []

    front = _point_at_maturity(brent_points, 0)
    m12 = _point_at_maturity(brent_points, 12)
    m24 = _point_at_maturity(brent_points, 24)

    front_pct = _change_1m(front)[1]
    m12_pct = _change_1m(m12)[1]
    m24_pct = _change_1m(m24)[1]

    oil_stale = any(
        (p or {}).get("staleness") == "stale"
        for p in (front, m12, m24)
        if p
    )

    drivers: list[dict] = []
    context_drivers: list[dict] = []
    for pt in (front, m12, m24):
        if pt:
            drivers.append(_curve_driver(pt, "brent_last_day"))
    for pt in wti_points:
        context_drivers.append(_curve_driver(pt, "wti_context"))

    classification = "unavailable"
    direction = "UNAVAILABLE"
    note: str | None = None

    if m12 is None or m24 is None or m12_pct is None or m24_pct is None:
        note = "12m and 24m Brent last-day quotes are required; the front contract alone is not persistence."
    else:
        has_front = front is not None and front_pct is not None
        if m12_pct >= contract.PATH_PERSISTENCE_PCT and m24_pct >= contract.PATH_PERSISTENCE_PCT:
            classification = "parallel_upward_repricing"
            direction = "RISING"
        elif m12_pct <= -contract.PATH_PERSISTENCE_PCT and m24_pct <= -contract.PATH_PERSISTENCE_PCT:
            classification = "parallel_downward_repricing"
            direction = "FALLING"
        elif (
            has_front
            and front_pct >= contract.MATERIAL_PCT
            and m12_pct < contract.PATH_PERSISTENCE_PCT
            and m24_pct < contract.PATH_PERSISTENCE_PCT
        ):
            classification = "front_loaded_temporary"
            direction = "STABLE"
            note = (
                "Front-month move is material but 12m/24m repricing is below the persistence band; "
                "the front shock is not treated as persistent inflation pressure."
            )
        elif has_front or True:
            classification = "mixed"
            direction = "STABLE"

    if context_drivers:
        drivers = drivers + [{"context": "wti", "points": context_drivers}]

    sub = _channel_shell(direction, stale=oil_stale, drivers=drivers, note=note)
    attribution = []
    if direction != "UNAVAILABLE" and m12:
        attribution.append(
            {
                "channel": "shock_persistence",
                "series_id": m12.get("symbol") or "brent_last_day_12m",
                "detail": classification,
            }
        )
    return sub, classification, attribution, oil_stale


def _production_network(bundle: dict) -> tuple[dict, list[dict], bool, str | None]:
    """Scored channel stays on monthly IPPI excluding energy.

    Quarterly sector PPI is shadow-only, including when that layer reports status ok.
    """
    producer = bundle.get("producer_prices") or {}
    series = _series_map(producer)
    as_of = _as_of_date(bundle)

    source: str | None = None
    mom: float | None = None
    stale = False
    series_id: str | None = None
    note = (
        "Scored on monthly IPPI excluding energy and petroleum products. "
        "The quarterly sector PPI layer is shadow-only and is not an input to this channel."
    )

    fallback = series.get("ippi_ex_energy")
    if fallback and fallback.get("status") in ("ok", "stale"):
        mom = _safe_float(fallback.get("mom"))
        if mom is not None:
            source = "ippi_ex_energy"
            series_id = "ippi_ex_energy"
            stale = bool(fallback.get("stale"))

    direction = _mom_direction(mom, contract.IPPI_EX_ENERGY_MOM_BAND) if source else "UNAVAILABLE"
    drivers: list[dict] = []
    if source and series_id:
        row_meta = series.get(series_id) or {}
        drivers.append(
            {
                "input": source,
                "series_id": series_id,
                "frequency": "monthly",
                "mom": mom,
                "band": contract.IPPI_EX_ENERGY_MOM_BAND,
                "table": row_meta.get("table"),
                "vector_id": row_meta.get("vector_id"),
                "units": row_meta.get("units"),
                "seasonal_status": row_meta.get("seasonal_status"),
                "period": row_meta.get("period"),
                "value": row_meta.get("value"),
                "prior_period": row_meta.get("prior_period"),
                "prior_value": row_meta.get("prior_value"),
                "release_time": row_meta.get("release_time"),
                "release_age_days": _release_age_days(as_of, row_meta.get("release_time")),
                "status": row_meta.get("status"),
                "stale": row_meta.get("stale"),
                "sector_ppi_not_used": True,
            }
        )

    sub = _channel_shell(direction, stale=stale, drivers=drivers, note=note)
    attribution = []
    if source and series_id:
        attribution.append(
            {
                "channel": "production_network_pressure",
                "series_id": series_id,
                "detail": f"input={source} mom={mom}",
            }
        )
    return sub, attribution, stale, source


def _imported_pressure(bundle: dict) -> tuple[dict, list[dict], bool]:
    """Stored id stays imported_pressure. The series is not an import price index."""
    producer = bundle.get("producer_prices") or {}
    series = _series_map(producer)
    row = series.get("rmpi_ex_crude_energy")
    as_of = _as_of_date(bundle)
    mom: float | None = None
    stale = False
    if row:
        mom = _safe_float(row.get("mom"))
        stale = bool(row.get("stale"))
        if row.get("status") not in ("ok", "stale"):
            mom = None

    direction = _mom_direction(mom, contract.RMPI_EX_ENERGY_MOM_BAND) if mom is not None else "UNAVAILABLE"
    note = (
        "RMPI excluding crude energy prices raw materials purchased by Canadian manufacturers, "
        "including domestically produced materials. It is not an import-price index. "
        "No import-price series is pinned, so this channel is not imported cost pressure. "
        "The stored id imported_pressure is unchanged so earlier runs stay comparable."
    )
    drivers: list[dict] = []
    if mom is not None and row:
        drivers.append(
            {
                "series_id": "rmpi_ex_crude_energy",
                "frequency": "monthly",
                "mom": mom,
                "band": contract.RMPI_EX_ENERGY_MOM_BAND,
                "table": row.get("table"),
                "vector_id": row.get("vector_id"),
                "units": row.get("units"),
                "seasonal_status": row.get("seasonal_status"),
                "period": row.get("period"),
                "value": row.get("value"),
                "prior_period": row.get("prior_period"),
                "prior_value": row.get("prior_value"),
                "release_time": row.get("release_time"),
                "release_age_days": _release_age_days(as_of, row.get("release_time")),
                "status": row.get("status"),
                "stale": row.get("stale"),
                "interpretation": "raw_material_purchase_prices_not_import_prices",
                "import_price_supported": False,
                "display_label": contract.CHANNEL_DISPLAY_LABELS["imported_pressure"],
                "legacy_channel_id": "imported_pressure",
            }
        )
    sub = _channel_shell(direction, stale=stale, drivers=drivers, note=note)
    sub["display_label"] = contract.CHANNEL_DISPLAY_LABELS["imported_pressure"]
    sub["legacy_channel_id"] = "imported_pressure"
    sub["import_price_supported"] = False
    attribution = []
    if mom is not None:
        attribution.append(
            {
                "channel": "imported_pressure",
                "series_id": "rmpi_ex_crude_energy",
                "detail": f"mom={mom}",
            }
        )
    return sub, attribution, stale


def _trim_acceleration(points: list[dict]) -> float | None:
    sorted_pts = sorted(points, key=lambda p: str(p.get("period") or ""))
    if len(sorted_pts) < 5:
        return None
    levels = [_safe_float(p.get("value")) for p in sorted_pts]
    if any(v is None or v <= 0 for v in levels[-5:]):
        return None
    t = len(levels) - 1

    def ann_at(end: int) -> float | None:
        if end < 3:
            return None
        base = levels[end - 3]
        if base is None or base <= 0:
            return None
        ratio = levels[end] / base
        return ratio**4 - 1

    ann_t = ann_at(t)
    ann_prev = ann_at(t - 1)
    if ann_t is None or ann_prev is None:
        return None
    return (ann_t - ann_prev) * 100


def _consumer_breadth(bundle: dict) -> tuple[dict, list[dict], bool]:
    cpi = bundle.get("cpi_breadth_inputs") or {}
    series = _cpi_series_map(cpi)

    majors_ok = True
    positive = 0
    with_mom = 0
    any_stale = False
    for major_id in contract.CPI_MAJOR_IDS:
        row = series.get(major_id)
        if not row or row.get("status") == "unavailable":
            majors_ok = False
            break
        mom = _safe_float(row.get("latest_mom"))
        if mom is None:
            majors_ok = False
            break
        with_mom += 1
        if mom > 0:
            positive += 1
        if row.get("status") == "stale" or row.get("stale"):
            any_stale = True

    breadth_share: float | None = None
    if majors_ok and with_mom == len(contract.CPI_MAJOR_IDS):
        breadth_share = positive / with_mom

    trim_row = series.get("core_trim_index")
    accel_pp: float | None = None
    if trim_row:
        accel_pp = _trim_acceleration(trim_row.get("points") or [])
        if trim_row.get("status") == "stale" or trim_row.get("stale"):
            any_stale = True

    direction = "UNAVAILABLE"
    drivers: list[dict] = []
    note: str | None = None

    if breadth_share is None or accel_pp is None:
        note = "Requires all eight CPI majors with month-over-month readings and at least five trim index levels."
    else:
        major_details: list[dict] = []
        for major_id in contract.CPI_MAJOR_IDS:
            major_row = series.get(major_id) or {}
            pts = major_row.get("points") or []
            latest_period = pts[-1].get("period") if pts else None
            major_details.append(
                {
                    "series_id": major_id,
                    "latest_mom": _safe_float(major_row.get("latest_mom")),
                    "period": latest_period,
                }
            )
        drivers.append(
            {
                "breadth_share": breadth_share,
                "breadth_positive_majors": positive,
                "breadth_majors_with_mom": with_mom,
                "trim_accel_pp": accel_pp,
                "majors": major_details,
            }
        )
        rising = (
            breadth_share >= contract.BREADTH_RISING_SHARE
            and accel_pp > contract.TRIM_ACCEL_PP
        )
        falling = (
            breadth_share <= contract.BREADTH_FALLING_SHARE
            and accel_pp < -contract.TRIM_ACCEL_PP
        )
        if rising:
            direction = "RISING"
        elif falling:
            direction = "FALLING"
        else:
            direction = "STABLE"

    sub = _channel_shell(direction, stale=any_stale, drivers=drivers, note=note)
    attribution = []
    if direction != "UNAVAILABLE":
        attribution.append(
            {
                "channel": "consumer_price_breadth",
                "series_id": "cpi_majors_and_core_trim_index",
                "detail": f"breadth_share={breadth_share} trim_accel_pp={accel_pp}",
            }
        )
    return sub, attribution, any_stale


def _demand_constraint(bundle: dict) -> tuple[dict, list[dict]]:
    demand = bundle.get("demand_inputs") or {}
    corra = demand.get("corra") or {}
    neutral = demand.get("neutral_midpoint") or {}
    midpoint = _safe_float(neutral.get("midpoint"))
    if midpoint is None:
        midpoint = contract.NEUTRAL_MIDPOINT

    rate = _safe_float(corra.get("rate"))
    status = corra.get("status")
    direction = "UNAVAILABLE"
    drivers: list[dict] = []
    note = "CORRA is the observed overnight benchmark, not a Governing Council vote."

    if status == "ok" and rate is not None:
        gap = rate - midpoint
        drivers.append(
            {
                "corra_rate": rate,
                "neutral_midpoint": midpoint,
                "gap": gap,
                "as_of": corra.get("as_of"),
            }
        )
        if gap >= contract.POLICY_GAP_FALLING:
            direction = "FALLING"
        elif gap <= contract.POLICY_GAP_RISING:
            direction = "RISING"
        else:
            direction = "STABLE"

    sub = _channel_shell(direction, drivers=drivers, note=note)
    attribution = []
    if direction != "UNAVAILABLE":
        attribution.append(
            {
                "channel": "demand_pass_through_constraint",
                "series_id": "CORRA",
                "detail": f"gap={drivers[0]['gap'] if drivers else None}",
            }
        )
    return sub, attribution


def _vote(direction: str) -> int | None:
    if direction == "RISING":
        return 1
    if direction == "FALLING":
        return -1
    if direction == "STABLE":
        return 0
    return None


def _aggregate(
    channel_dirs: dict[str, str],
    *,
    shock_dir: str,
    producer_stale: bool,
    cpi_stale: bool,
) -> tuple[str, str | None, str, float, int]:
    votes: list[int] = []
    for ch, d in channel_dirs.items():
        v = _vote(d)
        if v is not None:
            votes.append(v)
    available = len(votes)
    net = sum(votes)
    coverage = available / len(CHANNELS)

    if available < 2:
        return "UNAVAILABLE", None, "low", coverage, net

    if net >= 2:
        direction = "RISING"
    elif net <= -2:
        direction = "FALLING"
    else:
        direction = "STABLE"

    abs_net = abs(net)
    if abs_net >= 3:
        strength = "high"
    elif abs_net == 2:
        strength = "moderate"
    else:
        strength = "low"

    confidence = "low"
    if coverage >= 0.6:
        confidence = "medium"
    if (
        coverage >= 0.8
        and shock_dir != "UNAVAILABLE"
        and not producer_stale
        and not cpi_stale
    ):
        confidence = "high"

    return direction, strength, confidence, coverage, net


def _largest_driver_labels(
    shock_pts: list[dict],
    subcomponents: dict[str, dict],
) -> list[str]:
    labels: list[str] = []
    shock = subcomponents.get("shock_persistence") or {}
    for drv in shock.get("drivers") or []:
        if drv.get("context") == "wti":
            continue
        if drv.get("maturity_months") in (12, 24) and drv.get("change_1m_pct") is not None:
            labels.append(_format_pct_driver(drv))
    prod = subcomponents.get("production_network_pressure") or {}
    for drv in prod.get("drivers") or []:
        mom = drv.get("mom")
        if mom is not None:
            labels.append(f"IPPI ex-energy mom {mom * 100:+.2f} percent")
    imp = subcomponents.get("imported_pressure") or {}
    for drv in imp.get("drivers") or []:
        mom = drv.get("mom")
        if mom is not None:
            labels.append(f"RMPI ex-crude-energy mom {mom * 100:+.2f} percent")
    demand = subcomponents.get("demand_pass_through_constraint") or {}
    for drv in demand.get("drivers") or []:
        gap = drv.get("gap")
        if gap is not None:
            labels.append(f"CORRA gap versus neutral midpoint {gap:+.2f} percentage points")
    return labels[:3]


def _mpr_comparison(bundle: dict) -> dict:
    anchor = bundle.get("mpr_anchor")
    if not isinstance(anchor, dict) or not anchor:
        anchor = bundle.get("mpr_comparison")
    if isinstance(anchor, dict) and anchor:
        return dict(anchor)
    return {"status": "unavailable"}


def _change_since_last_mpr_sentence(mpr: dict) -> str:
    legs = mpr.get("legs") or mpr.get("comparison_legs") or []
    preferred = None
    for leg in legs:
        if leg.get("leg") == "brent_end_2027_vs_prose" and leg.get("status") == "ok":
            preferred = leg
            break
    if preferred is None:
        for leg in legs:
            if leg.get("status") in ("ok", "partial") and leg.get("delta_usd_bbl") is not None:
                preferred = leg
                break
    if preferred is None:
        return "unavailable"
    delta = preferred.get("delta_usd_bbl")
    assumption = preferred.get("assumption_usd_bbl")
    if assumption is None:
        assumption = preferred.get("conditioning_chart_level_usd_bbl")
    leg_name = preferred.get("leg") or "oil"
    assumption_text = f" versus {assumption}" if assumption is not None else ""
    conditioning = mpr.get("conditioning_date") or "the July 2026 conditioning date"
    return (
        f"Versus the July 2026 MPR conditioning assumptions as of {conditioning}, "
        f"{leg_name} is {delta:+.2f} USD per barrel{assumption_text}. "
        "Observable monitoring only; not a reproduction of the Bank of Canada's Prima model."
    )


def _oil_status(bundle: dict, oil_stale: bool) -> str:
    oil = bundle.get("oil_curve") or bundle.get("oil_curves") or {}
    brent = oil.get("brent_last_day") or {}
    points = brent.get("points") or []
    has_path = any(p.get("maturity_months") in (12, 24) for p in points)
    if brent.get("status") == "unavailable" or not has_path:
        return "unavailable"
    if oil_stale or any(p.get("staleness") == "stale" for p in points):
        return "stale"
    return "fresh"


def _staleness_summary(producer_stale: bool, oil_status: str) -> str:
    producer = "producer inputs stale" if producer_stale else "producer inputs fresh"
    oil = {
        "stale": "oil curve stale",
        "unavailable": "oil curve unavailable",
    }.get(oil_status, "oil curve fresh")
    return f"{producer}; {oil}"


def compute_prima_proxy(bundle: dict) -> dict:
    bundle = bundle or {}

    shock_sub, front_class, shock_attr, oil_stale = _shock_persistence(bundle)
    prod_sub, prod_attr, prod_stale, _prod_source = _production_network(bundle)
    imp_sub, imp_attr, imp_stale = _imported_pressure(bundle)
    cpi_sub, cpi_attr, cpi_stale = _consumer_breadth(bundle)
    demand_sub, demand_attr = _demand_constraint(bundle)

    subcomponents = {
        "shock_persistence": shock_sub,
        "production_network_pressure": prod_sub,
        "imported_pressure": imp_sub,
        "consumer_price_breadth": cpi_sub,
        "demand_pass_through_constraint": demand_sub,
    }
    channel_dirs = {ch: subcomponents[ch]["direction"] for ch in CHANNELS}

    direction, strength, confidence, coverage, net = _aggregate(
        channel_dirs,
        shock_dir=shock_sub["direction"],
        producer_stale=prod_stale or imp_stale,
        cpi_stale=cpi_stale,
    )

    attribution = shock_attr + prod_attr + imp_attr + cpi_attr + demand_attr
    largest = _largest_driver_labels([], subcomponents)

    available = sum(1 for d in channel_dirs.values() if d != "UNAVAILABLE")
    mpr_comparison = _mpr_comparison(bundle)
    oil_status = _oil_status(bundle, oil_stale)
    shadow = build_sector_shadow(
        bundle,
        {
            "direction": direction,
            "strength": strength,
            "internal_net_vote": net,
            "production_direction": prod_sub["direction"],
            "raw_material_direction": imp_sub["direction"],
        },
    )

    return {
        "schema_version": contract.SCHEMA_VERSION,
        "kind": "canada_prima_pressure_proxy",
        "disclaimer": contract.DISCLAIMER,
        "as_of": bundle.get("as_of"),
        "direction": direction,
        "strength": strength,
        "confidence": confidence,
        "coverage": coverage,
        "channels_available": available,
        "channels_required": 5,
        "internal_net_vote": net,
        "front_shock_classification": front_class,
        "subcomponents": subcomponents,
        "attribution": attribution,
        "largest_drivers": largest,
        "mpr_comparison": mpr_comparison,
        "staleness": {
            "producer": bool(prod_stale or imp_stale),
            "oil": oil_status != "fresh",
            "oil_status": oil_status,
        },
        "shadow_sector_layer": shadow,
    }


_CHANNEL_RULE_IDS = {
    "shock_persistence": "brent_12m_24m_1m_persistence",
    "production_network_pressure": "ippi_ex_energy_mom_band",
    "imported_pressure": "rmpi_ex_crude_energy_mom_band",
    "consumer_price_breadth": "cpi_major_share_trim_accel",
    "demand_pass_through_constraint": "corra_neutral_gap",
}


def _flatten_channel_inputs(drivers: list[dict]) -> list[dict]:
    out: list[dict] = []
    for drv in drivers:
        if drv.get("context") == "wti":
            continue
        nested = drv.get("points")
        if isinstance(nested, list):
            for pt in nested:
                if isinstance(pt, dict):
                    out.append(dict(pt))
            continue
        out.append({k: v for k, v in drv.items() if k not in ("label", "input")})
    return out


def _build_channel_evidence(subcomponents: dict[str, dict]) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    for ch in CHANNELS:
        sub = subcomponents.get(ch) or {}
        note = sub.get("note")
        evidence[ch] = {
            "direction": sub.get("direction", "UNAVAILABLE"),
            "rule": _CHANNEL_RULE_IDS[ch],
            "inputs": _flatten_channel_inputs(sub.get("drivers") or []),
            "stale": bool(sub.get("stale")),
            "note": str(note) if note is not None else None,
        }
    return evidence


def compact_block(proxy: dict) -> dict:
    proxy = proxy or {}
    mpr = proxy.get("mpr_comparison") or {}
    subs = proxy.get("subcomponents") or {}
    staleness = proxy.get("staleness") or {}

    mpr_status = mpr.get("status") or mpr.get("path_status") or "unavailable"
    conditioning_date = mpr.get("conditioning_date")

    block = {
        "title": "Canada Prima-pressure proxy",
        "direction": proxy.get("direction"),
        "strength": proxy.get("strength"),
        "confidence": proxy.get("confidence"),
        "coverage": proxy.get("coverage"),
        "subcomponent_directions": {
            ch: (subs.get(ch) or {}).get("direction", "UNAVAILABLE") for ch in CHANNELS
        },
        "front_shock_classification": proxy.get("front_shock_classification"),
        "largest_drivers": list(proxy.get("largest_drivers") or [])[:3],
        "mpr_status": mpr_status,
        "conditioning_date": conditioning_date,
        "change_since_last_mpr": _change_since_last_mpr_sentence(mpr),
        "disclaimer": proxy.get("disclaimer") or contract.DISCLAIMER,
        "staleness": _staleness_summary(
            bool(staleness.get("producer")),
            str(staleness.get("oil_status") or ("stale" if staleness.get("oil") else "fresh")),
        ),
        "channel_evidence": _build_channel_evidence(subs),
    }
    shadow = proxy.get("shadow_sector_layer")
    if isinstance(shadow, dict):
        block["shadow_sector_layer"] = shadow
    return block
