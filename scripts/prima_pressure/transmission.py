"""CPI transmission builder for Canada PRiMA (additive v2 output)."""

from __future__ import annotations

import calendar
import datetime as dt
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.prima_pressure import contract
from scripts.prima_pressure.contract import DISCLAIMER, iso_date
from scripts.prima_pressure.expiry import assess_stored_shock_inputs, validate_stored_oil_row
from scripts.prima_pressure.transmission_contract import (
    CRUDE_COST_SHARES,
    CRUDE_REFINING_DIVERGENCE_CPL,
    DISCLAIMER_TX,
    FUEL_OIL_COST_SHARES,
    FX_LOOKUP_MAX_CALENDAR_DAYS,
    IMPORTED_FX_MATERIAL_1M_PCT,
    IMPORTED_FX_MATERIAL_3M_PCT,
    LITRES_PER_BARREL,
    LITRES_PER_US_GALLON,
    PP_NEUTRAL_ABS,
    PUMP_PASS_THROUGH,
    TAX_PASS_THROUGH,
    TRANSMISSION_CHANNEL_ENERGY,
    TRANSMISSION_CHANNEL_FOOD,
    TRANSMISSION_CHANNEL_IMPORTED,
    TRANSMISSION_CHANNELS,
    TRANSMISSION_METHOD_VERSION,
    TRANSMISSION_PROVENANCE_LIVE,
    TRANSMISSION_PROVENANCE_RECON,
    TRANSMISSION_SCHEMA_VERSION,
    WEIGHT_BASIS,
    WEIGHT_FOOD_PCT,
    WEIGHT_FUEL_OIL_PCT,
    WEIGHT_GASOLINE_PCT,
)


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _month_end(period: str) -> dt.date | None:
    if not period or len(period) < 7:
        return None
    try:
        y, m = int(period[:4]), int(period[5:7])
        last = calendar.monthrange(y, m)[1]
        return dt.date(y, m, last)
    except (ValueError, TypeError):
        return None


def _horizon_block(
    *,
    basis: str,
    direction: str,
    pp_low: float | None = None,
    pp_mid: float | None = None,
    pp_high: float | None = None,
    reference_baseline: str = "",
    coverage: str = "full",
    uncovered_interval: str | None = None,
) -> dict[str, Any]:
    return {
        "basis": basis,
        "direction": direction,
        "pp_low": pp_low,
        "pp_mid": pp_mid,
        "pp_high": pp_high,
        "reference_baseline": reference_baseline,
        "coverage": coverage,
        "uncovered_interval": uncovered_interval,
    }


def _pp_direction(pp_mid: float | None) -> str:
    if pp_mid is None:
        return "unavailable"
    if abs(pp_mid) < PP_NEUTRAL_ABS:
        return "neutral"
    return "up" if pp_mid > 0 else "down"


def _nearest_fx_spot(
    target: dt.date,
    history: Sequence[tuple[dt.date, float]],
    *,
    max_days: int = FX_LOOKUP_MAX_CALENDAR_DAYS,
) -> tuple[float | None, dt.date | None]:
    best: tuple[int, float, dt.date] | None = None
    for obs_date, spot in history:
        if obs_date > target:
            continue
        gap = (target - obs_date).days
        if gap > max_days:
            continue
        if best is None or gap < best[0]:
            best = (gap, spot, obs_date)
    if best is None:
        return None, None
    return best[1], best[2]


def _fx_decimal_change(
    start: dt.date,
    end: dt.date,
    history: Sequence[tuple[dt.date, float]],
    *,
    ret_1m_pct: float | None = None,
) -> tuple[float | None, list[str], bool]:
    flags: list[str] = []
    spot_start, _ = _nearest_fx_spot(start, history)
    spot_end, _ = _nearest_fx_spot(end, history)
    if spot_start and spot_end and spot_start > 0:
        return spot_end / spot_start - 1.0, flags, False
    if ret_1m_pct is not None:
        flags.append("fx_window_approximate")
        return ret_1m_pct / 100.0, flags, True
    return None, ["fx_leg_missing"], False


def _combined_brent_cad(r_usd: float, r_fx: float | None) -> tuple[float | None, dict[str, Any] | None, list[str]]:
    flags: list[str] = []
    decomp: dict[str, Any] = {
        "usd_leg": r_usd,
        "fx_leg": r_fx,
        "interaction": (r_usd * r_fx) if r_fx is not None else None,
        "combined": None,
    }
    if r_fx is None:
        flags.append("fx_leg_missing")
        decomp["combined"] = r_usd
        return r_usd, decomp, flags
    combined = (1.0 + r_usd) * (1.0 + r_fx) - 1.0
    decomp["interaction"] = r_usd * r_fx
    decomp["combined"] = combined
    return combined, decomp, flags


def _recon_pp_range(combined: float) -> tuple[float, float, float]:
    gas_low = WEIGHT_GASOLINE_PCT * CRUDE_COST_SHARES[0] * combined
    gas_mid = WEIGHT_GASOLINE_PCT * CRUDE_COST_SHARES[1] * combined
    gas_high = WEIGHT_GASOLINE_PCT * CRUDE_COST_SHARES[2] * combined
    fo_low = WEIGHT_FUEL_OIL_PCT * FUEL_OIL_COST_SHARES[0] * combined
    fo_mid = WEIGHT_FUEL_OIL_PCT * FUEL_OIL_COST_SHARES[1] * combined
    fo_high = WEIGHT_FUEL_OIL_PCT * FUEL_OIL_COST_SHARES[2] * combined
    return gas_low + fo_low, gas_mid + fo_mid, gas_high + fo_high


def _find_shock_front(block: dict) -> dict | None:
    ce = block.get("channel_evidence") or {}
    shock = ce.get("shock_persistence") or {}
    for row in shock.get("inputs") or []:
        if not isinstance(row, dict):
            continue
        if row.get("maturity_months") == 0 or row.get("horizon_role_months") == 0:
            return row
        if row.get("selection") == "active_front":
            return row
    for row in shock.get("inputs") or []:
        if isinstance(row, dict) and row.get("actual_maturity_months") == 0:
            return row
    return None


def _find_shock_horizon(block: dict, months: int) -> dict | None:
    ce = block.get("channel_evidence") or {}
    shock = ce.get("shock_persistence") or {}
    for row in shock.get("inputs") or []:
        if not isinstance(row, dict):
            continue
        if row.get("maturity_months") == months or row.get("horizon_role_months") == months:
            return row
    return None


def _latest_cpi_period(block: dict) -> str | None:
    ce = block.get("channel_evidence") or {}
    for ch in ("consumer_price_breadth", "production_network_pressure", "imported_pressure"):
        for row in (ce.get(ch) or {}).get("inputs") or []:
            if isinstance(row, dict) and row.get("period"):
                return str(row["period"])
    shadow = block.get("shadow_sector_layer") or {}
    leg = (shadow.get("legacy_vs_shadow") or {}).get("legacy_scored") or {}
    for key in ("production_network_input",):
        pass
    direct = shadow.get("direct_energy") or {}
    for sub in (direct.get("monthly_ippi_energy"), direct.get("monthly_rmpi_crude_energy")):
        if isinstance(sub, dict) and sub.get("period"):
            return str(sub["period"])
    return None


def _producer_mom(block: dict, series_id: str) -> float | None:
    ce = block.get("channel_evidence") or {}
    for ch in ce.values():
        if not isinstance(ch, dict):
            continue
        for row in ch.get("inputs") or []:
            if isinstance(row, dict) and row.get("series_id") == series_id:
                mom = row.get("mom")
                if isinstance(mom, (int, float)):
                    return float(mom)
    shadow = block.get("shadow_sector_layer") or {}
    leg = (shadow.get("legacy_vs_shadow") or {}).get("legacy_scored") or {}
    if series_id == "rmpi_ex_crude_energy" and leg.get("raw_material_mom") is not None:
        return float(leg["raw_material_mom"])
    if series_id == "ippi_ex_energy" and leg.get("production_network_mom") is not None:
        return float(leg["production_network_mom"])
    return None


def unavailable_transmission(reason: str) -> dict[str, Any]:
    unavail_h = _horizon_block(
        basis="unavailable",
        direction="unavailable",
        reference_baseline="",
        coverage="none",
    )
    empty_ch = {
        "id": "",
        "label": "",
        "status": "unavailable",
        "observed_change": None,
        "transmission_seen": [],
        "remaining": {"h1_3m": unavail_h, "h3_6m": dict(unavail_h)},
        "cpi_components": [],
        "assumptions": [],
        "notes": [reason],
    }
    channels = {
        TRANSMISSION_CHANNEL_ENERGY: {
            **empty_ch,
            "id": TRANSMISSION_CHANNEL_ENERGY,
            "label": "Direct fuel (gasoline & fuel oil)",
        },
        TRANSMISSION_CHANNEL_IMPORTED: {
            **empty_ch,
            "id": TRANSMISSION_CHANNEL_IMPORTED,
            "label": "Imported non-energy goods",
        },
        TRANSMISSION_CHANNEL_FOOD: {
            **empty_ch,
            "id": TRANSMISSION_CHANNEL_FOOD,
            "label": "Food & non-energy inputs",
        },
    }
    return {
        "schema_version": TRANSMISSION_SCHEMA_VERSION,
        "method_version": TRANSMISSION_METHOD_VERSION,
        "provenance": "unavailable",
        "as_of": None,
        "not_bank_of_canada_prima": True,
        "disclaimer": DISCLAIMER_TX,
        "cpi_reference_period": None,
        "status": "unavailable",
        "channels": channels,
        "underlying_core_evidence": {},
        "producer_stage": [],
        "policy_context": {"role": "context_only"},
        "summary": {
            "direct_fuel": {
                "h1_3m": unavail_h,
                "h3_6m": unavail_h,
                "direction": "unavailable",
            },
            "underlying_core": {
                "h1_3m": "unavailable",
                "h3_6m": "unavailable",
                "direction": "unavailable",
            },
        },
        "headline": {
            "what_changed": reason[:200],
            "where_transmitting": "",
            "what_remains": "",
        },
        "status_line": f"Transmission unavailable: {reason[:120]}",
        "missing_inputs": [{"input": "transmission", "reason": reason}],
    }


def collect_fx_history_points(root: Path) -> list[tuple[dt.date, float, str]]:
    from scripts.prima_pressure.presentation import _collect_observations

    observations, _ = _collect_observations(root)
    points: list[tuple[dt.date, float, str]] = []
    runs_root = root / "data" / "overnight" / "runs"
    for obs in observations:
        run_id = obs.get("run_id")
        review_id = obs.get("review_id")
        source_id = obs.get("source_id") or f"{run_id}/{review_id}"
        if not run_id or not review_id:
            continue
        snap_path = runs_root / str(run_id) / "reviews" / str(review_id) / "evidence_snapshot.json"
        if not snap_path.is_file():
            continue
        try:
            import json

            snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        families = snapshot.get("families") if isinstance(snapshot.get("families"), dict) else {}
        ms = families.get("market_state") if isinstance(families.get("market_state"), dict) else {}
        data = ms.get("data") if isinstance(ms.get("data"), dict) else {}
        fx = data.get("fx") if isinstance(data.get("fx"), dict) else {}
        pair = (fx.get("pairs") or {}).get("USDCAD")
        if not isinstance(pair, dict):
            continue
        spot = pair.get("spot")
        as_of = _parse_date(pair.get("as_of"))
        if as_of is None or not isinstance(spot, (int, float)):
            continue
        points.append((as_of, float(spot), str(source_id)))
    points.sort(key=lambda row: (row[0], row[2]))
    return points


def inputs_from_frozen(
    block: Mapping[str, Any],
    *,
    usdcad_pair: Mapping[str, Any] | None,
    fx_history_points: Sequence[tuple[dt.date, float, str]] = (),
    as_of: dt.date,
) -> dict[str, Any]:
    history: list[tuple[dt.date, float]] = [
        (d, spot) for d, spot, _sid in fx_history_points
    ]
    if usdcad_pair:
        as_of_fx = _parse_date(usdcad_pair.get("as_of"))
        spot = usdcad_pair.get("spot")
        if as_of_fx and isinstance(spot, (int, float)):
            history.append((as_of_fx, float(spot)))
    history = sorted(set(history))

    pair_metrics = dict(usdcad_pair) if isinstance(usdcad_pair, dict) else {}
    return {
        "provenance": TRANSMISSION_PROVENANCE_RECON,
        "mode": "reconstructed",
        "as_of": as_of,
        "legacy_block": dict(block),
        "usdcad_pair": pair_metrics,
        "usdcad_history": history,
        "cpi_reference_period": _latest_cpi_period(dict(block)),
    }


def _point_from_bundle(bundle: dict, maturity: int) -> dict | None:
    oil = bundle.get("oil_curves") or bundle.get("oil_curve") or {}
    brent = oil.get("brent_last_day") or {}
    for pt in brent.get("points") or []:
        if pt.get("maturity_months") == maturity:
            return pt
    return None


def _change_pct_from_point(pt: dict) -> tuple[float | None, dt.date | None, dt.date | None]:
    ch = (pt.get("changes") or {}).get("1m") or {}
    pct = ch.get("pct")
    if pct is None:
        pct = pt.get("change_1m_pct")
    base = _parse_date(ch.get("prior_date") or pt.get("change_1m_base_date"))
    obs = _parse_date(pt.get("observation_date"))
    if isinstance(pct, (int, float)):
        return float(pct), base, obs
    return None, base, obs


def inputs_from_live(
    bundle: Mapping[str, Any],
    *,
    usdcad_history: Sequence[tuple[dt.date, float]] | None,
    nrcan: Mapping[str, Any] | None,
    as_of: dt.date,
) -> dict[str, Any]:
    b = dict(bundle)
    history = list(usdcad_history or [])
    prod = b.get("producer_prices") or {}
    cpi_period = None
    for row in prod.get("series") or []:
        if isinstance(row, dict) and row.get("period"):
            cpi_period = str(row["period"])
            break
    cpi_in = b.get("cpi_breadth_inputs") or {}
    for row in cpi_in.get("series") or []:
        if isinstance(row, dict) and row.get("period"):
            cpi_period = cpi_period or str(row["period"])

    return {
        "provenance": TRANSMISSION_PROVENANCE_LIVE,
        "mode": "live",
        "as_of": as_of,
        "bundle": b,
        "usdcad_history": history,
        "nrcan": dict(nrcan) if isinstance(nrcan, dict) else None,
        "cpi_reference_period": cpi_period,
    }


def _oil_guard_ok(block: dict, as_of: dt.date) -> tuple[bool, str | None]:
    review = assess_stored_shock_inputs(block, as_of)
    status = review.get("status")
    if status not in ("ok", "valid") and not review.get("valid"):
        return False, str(status or "stored_oil_rejected")
    front = _find_shock_front(block)
    if front:
        finding = validate_stored_oil_row(front, as_of)
        if not finding.get("valid"):
            return False, str(finding.get("reason") or "invalid_front")
    return True, None


def _build_energy_reconstructed(inputs: dict, as_of: dt.date) -> tuple[dict, list[dict], str]:
    block = inputs["legacy_block"]
    missing: list[dict] = []
    guard_ok, guard_reason = _oil_guard_ok(block, as_of)
    front = _find_shock_front(block)
    p12 = _find_shock_horizon(block, 12)

    cpi_period = inputs.get("cpi_reference_period") or _latest_cpi_period(block)
    cpi_end = _month_end(cpi_period) if cpi_period else None

    flags: list[str] = []
    r_usd = None
    base_date = None
    obs_date = None
    if front:
        r_usd = front.get("change_1m_pct")
        if isinstance(r_usd, (int, float)):
            r_usd = float(r_usd)
        else:
            r_usd = None
        base_date = _parse_date(front.get("change_1m_base_date"))
        obs_date = _parse_date(front.get("observation_date"))

    pair = inputs.get("usdcad_pair") or {}
    ret_1m = pair.get("ret_1m")
    history: list[tuple[dt.date, float]] = list(inputs.get("usdcad_history") or [])

    r_fx = None
    fx_approx = False
    if base_date and obs_date and history:
        r_fx, fx_flags, fx_approx = _fx_decimal_change(
            base_date, obs_date, history, ret_1m_pct=float(ret_1m) if ret_1m is not None else None
        )
        flags.extend(fx_flags)
    elif ret_1m is not None:
        r_fx = float(ret_1m) / 100.0
        flags.append("fx_window_approximate")
        fx_approx = True
    else:
        flags.append("fx_leg_missing")

    combined, decomp, comb_flags = _combined_brent_cad(r_usd or 0.0, r_fx)
    flags.extend(comb_flags)
    if r_usd is None:
        combined = None

    uncovered = None
    coverage = "full"
    numeric_allowed = True
    if cpi_end and base_date:
        if base_date <= cpi_end:
            numeric_allowed = False
            flags.append("cpi_overlap")
        else:
            coverage = "partial"
            uncovered = f"{cpi_end.isoformat()} → {base_date.isoformat()}"

    basis = "range"
    direction = "unavailable"
    pp_low = pp_mid = pp_high = None
    if not guard_ok:
        basis = "unavailable"
        missing.append({"input": "brent_front", "reason": guard_reason or "oil_guard"})
    elif combined is None:
        basis = "unavailable"
        missing.append({"input": "brent_1m", "reason": "missing_usd_leg"})
    elif "fx_leg_missing" in flags and numeric_allowed:
        basis = "directional"
        direction = _pp_direction(combined * WEIGHT_GASOLINE_PCT * CRUDE_COST_SHARES[1])
    elif not numeric_allowed:
        basis = "directional"
        direction = _pp_direction(combined * WEIGHT_GASOLINE_PCT * CRUDE_COST_SHARES[1] if combined else None)
    else:
        pp_low, pp_mid, pp_high = _recon_pp_range(combined)
        direction = _pp_direction(pp_mid)

    h1 = _horizon_block(
        basis=basis,
        direction=direction,
        pp_low=pp_low,
        pp_mid=pp_mid,
        pp_high=pp_high,
        reference_baseline=f"Brent-in-CAD 1m · CPI through {cpi_period or 'unknown'}",
        coverage=coverage if basis == "range" else ("none" if basis == "unavailable" else "partial"),
        uncovered_interval=uncovered,
    )

    h3_basis = "directional"
    h3_dir = "neutral"
    if front and p12:
        fp = front.get("price")
        p12p = p12.get("price")
        if isinstance(fp, (int, float)) and isinstance(p12p, (int, float)):
            if fp > p12p + contract.STABLE_USD:
                h3_dir = "down"
            elif fp < p12p - contract.STABLE_USD:
                h3_dir = "up"
    h3 = _horizon_block(
        basis=h3_basis,
        direction=h3_dir,
        reference_baseline="Front vs 12m listed Brent (if curve realised)",
        coverage="partial" if coverage == "partial" else "full",
        uncovered_interval=uncovered,
    )
    if h3_dir == "down" and basis == "directional":
        h3["notes"] = ["Backwardation: down if curve realised"]

    metric_value = combined
    if metric_value is not None and basis == "directional" and "fx_leg_missing" in flags:
        metric_value = r_usd

    observed = {
        "metric": "brent_in_cad_1m",
        "units": "decimal_change",
        "value": metric_value,
        "window": {
            "start": base_date.isoformat() if base_date else None,
            "end": obs_date.isoformat() if obs_date else None,
        },
        "decomposition": decomp,
        "flags": sorted(set(flags)),
    }

    channel = {
        "id": TRANSMISSION_CHANNEL_ENERGY,
        "label": "Direct fuel (gasoline & fuel oil)",
        "status": "ok" if guard_ok and combined is not None else "partial",
        "observed_change": observed,
        "transmission_seen": [],
        "remaining": {"h1_3m": h1, "h3_6m": h3},
        "cpi_components": [
            {
                "name": "Gasoline",
                "weight_pct": WEIGHT_GASOLINE_PCT,
                "basket": "2025",
                "weight_basis": WEIGHT_BASIS,
            },
            {
                "name": "Fuel oil & other fuels",
                "weight_pct": WEIGHT_FUEL_OIL_PCT,
                "basket": "2025",
                "weight_basis": WEIGHT_BASIS,
            },
        ],
        "assumptions": [
            {"name": "tax_pass_through", "value": TAX_PASS_THROUGH, "source": "GST/HST/QST approx."},
            {"name": "crude_cost_share", "value": list(CRUDE_COST_SHARES), "source": "NRCan pump breakdown"},
        ],
        "notes": [
            "CAD move counted once via Brent-in-CAD decomposition.",
            "Reconstructed path: crude-cost elasticity range; no live pump/NRCan staging.",
        ],
    }
    if fx_approx:
        channel["notes"].append("FX 1m from ECB window approximation when dated spots absent.")
    status = "ok" if channel["status"] == "ok" else "partial"
    return channel, missing, status


def _build_imported(inputs: dict) -> dict:
    pair = inputs.get("usdcad_pair") or {}
    r1 = pair.get("ret_1m")
    r3 = pair.get("ret_3m")
    material = False
    if isinstance(r3, (int, float)) and abs(float(r3)) >= IMPORTED_FX_MATERIAL_3M_PCT:
        material = True
    if isinstance(r1, (int, float)) and abs(float(r1)) >= IMPORTED_FX_MATERIAL_1M_PCT:
        material = True
    if material and isinstance(r3, (int, float)):
        direction = "up" if float(r3) > 0 else "down"
    elif material and isinstance(r1, (int, float)):
        direction = "up" if float(r1) > 0 else "down"
    else:
        direction = "neutral"

    h1 = _horizon_block(
        basis="directional",
        direction=direction if direction != "neutral" else "neutral",
        reference_baseline="USDCAD (CAD per USD); not additive with fuel FX leg",
    )
    h3 = dict(h1)
    return {
        "id": TRANSMISSION_CHANNEL_IMPORTED,
        "label": "Imported non-energy goods",
        "status": "ok",
        "observed_change": {
            "metric": "usdcad",
            "units": "percent",
            "value": {"ret_1m": r1, "ret_3m": r3},
            "window": {"start": None, "end": pair.get("as_of")},
            "decomposition": None,
            "flags": [] if material else ["not_material"],
        },
        "transmission_seen": [],
        "remaining": {"h1_3m": h1, "h3_6m": h3},
        "cpi_components": [],
        "assumptions": [],
        "notes": [
            "Import price index not pinned (IMPORT_PRICE_MEASURE unavailable).",
            "FX also appears in energy decomposition for a different CPI weight set.",
        ],
    }


def _build_food(block: dict) -> dict:
    rmpi = _producer_mom(block, "rmpi_ex_crude_energy")
    ippi = _producer_mom(block, "ippi_ex_energy")
    rmpi_band = contract.RMPI_EX_ENERGY_MOM_BAND
    ippi_band = contract.IPPI_EX_ENERGY_MOM_BAND

    def band_dir(mom: float | None, band: float) -> str:
        if mom is None:
            return "neutral"
        if mom > band:
            return "up"
        if mom < -band:
            return "down"
        return "neutral"

    d3 = band_dir(rmpi, rmpi_band)
    if d3 == "neutral":
        d3 = band_dir(ippi, ippi_band)
    d1 = "neutral" if d3 == "neutral" else d3
    if rmpi is not None and abs(rmpi) > rmpi_band:
        d1 = band_dir(rmpi, rmpi_band)

    return {
        "id": TRANSMISSION_CHANNEL_FOOD,
        "label": "Food & non-energy inputs",
        "status": "ok",
        "observed_change": {
            "metric": "producer_inputs",
            "units": "mom_decimal",
            "value": {"rmpi_ex_crude_energy": rmpi, "ippi_ex_energy": ippi},
            "window": None,
            "decomposition": None,
            "flags": [],
        },
        "transmission_seen": [],
        "remaining": {
            "h1_3m": _horizon_block(basis="directional", direction=d1, reference_baseline="RMPI/IPPI bands"),
            "h3_6m": _horizon_block(basis="directional", direction=d3, reference_baseline="Input costs 3–9m lag"),
        },
        "cpi_components": [
            {
                "name": "Food",
                "weight_pct": WEIGHT_FOOD_PCT,
                "basket": "2025",
                "weight_basis": WEIGHT_BASIS,
            }
        ],
        "assumptions": [],
        "notes": ["BoC BCPI weekly series not wired in this build."],
    }


def _underlying_core(imported: dict, food: dict, block: dict) -> dict[str, Any]:
    dirs = []
    for ch in (imported, food):
        for horizon in ("h1_3m", "h3_6m"):
            d = (ch.get("remaining") or {}).get(horizon, {}).get("direction")
            if d and d not in ("neutral", "unavailable"):
                dirs.append(d)
    shadow = block.get("shadow_sector_layer") or {}
    ippi_e = (shadow.get("direct_energy") or {}).get("monthly_ippi_energy") or {}
    chg = ippi_e.get("change")
    if isinstance(chg, (int, float)) and abs(chg) > 0.01:
        dirs.append("up" if chg > 0 else "down")

    if not dirs:
        direction = "neutral"
    elif len(set(dirs)) == 1:
        direction = dirs[0]
    else:
        direction = "mixed"

    return {
        "direction_h1_3m": direction,
        "direction_h3_6m": direction,
        "drivers": ["imported_non_energy_goods", "food_and_non_energy_inputs", "indirect_energy"],
        "never_numeric": True,
    }


def _producer_stage(block: dict) -> list[dict]:
    shadow = block.get("shadow_sector_layer") or {}
    out: list[dict] = []
    direct = shadow.get("direct_energy") or {}
    for key in ("monthly_ippi_energy", "monthly_rmpi_crude_energy"):
        row = direct.get(key)
        if isinstance(row, dict):
            out.append(row)
    for sec in shadow.get("other_sectors") or []:
        if isinstance(sec, dict):
            out.append(sec)
    return out


def _policy_context(block: dict) -> dict:
    ce = block.get("channel_evidence") or {}
    demand = ce.get("demand_pass_through_constraint") or {}
    inputs = demand.get("inputs") or []
    row = inputs[0] if inputs else {}
    return {
        "corra_rate": row.get("corra_rate"),
        "neutral_midpoint": row.get("neutral_midpoint"),
        "gap": row.get("gap"),
        "role": "context_only",
        "note": "CORRA is legacy-proxy context only; not used in transmission determination.",
    }


def build_transmission(inputs: Mapping[str, Any], *, as_of: dt.date) -> dict[str, Any]:
    inputs = dict(inputs)
    provenance = inputs.get("provenance", TRANSMISSION_PROVENANCE_RECON)
    block = inputs.get("legacy_block") or {}

    if inputs.get("mode") == "live":
        block = {}
        proxy_bundle = inputs.get("bundle") or {}
        # Synthesize minimal block from live bundle for shared channel builders
        from scripts.prima_pressure.proxy import compute_prima_proxy, compact_block

        proxy = compute_prima_proxy(proxy_bundle)
        block = compact_block(proxy)

    energy, missing, tx_status = _build_energy_reconstructed(
        {**inputs, "legacy_block": block}, as_of
    )
    imported = _build_imported(inputs)
    food = _build_food(block)

    cpi_ref = inputs.get("cpi_reference_period") or _latest_cpi_period(block)
    core = _underlying_core(imported, food, block)
    fuel_h1 = energy["remaining"]["h1_3m"]
    fuel_h3 = energy["remaining"]["h3_6m"]

    headline_changed = ""
    obs = energy.get("observed_change") or {}
    if obs.get("value") is not None:
        headline_changed = (
            f"Brent-in-CAD 1m {float(obs['value']):+.1%} "
            f"({obs.get('window', {}).get('start')}→{obs.get('window', {}).get('end')})"
        )[:200]

    status_line = (
        f"{'Live' if provenance == TRANSMISSION_PROVENANCE_LIVE else 'Reconstructed'} inputs "
        f"{as_of.isoformat()} · CPI {cpi_ref or 'unknown'} · "
        f"fuel h1_3m {fuel_h1.get('direction')} ({fuel_h1.get('basis')})"
    )
    if missing:
        status_line += f" · missing: {missing[0].get('input')}"

    out = {
        "schema_version": TRANSMISSION_SCHEMA_VERSION,
        "method_version": TRANSMISSION_METHOD_VERSION,
        "provenance": provenance,
        "as_of": iso_date(as_of),
        "not_bank_of_canada_prima": True,
        "disclaimer": DISCLAIMER_TX,
        "cpi_reference_period": cpi_ref,
        "status": tx_status,
        "channels": {
            TRANSMISSION_CHANNEL_ENERGY: energy,
            TRANSMISSION_CHANNEL_IMPORTED: imported,
            TRANSMISSION_CHANNEL_FOOD: food,
        },
        "underlying_core_evidence": core,
        "producer_stage": _producer_stage(block),
        "policy_context": _policy_context(block),
        "summary": {
            "direct_fuel": {
                "h1_3m": fuel_h1,
                "h3_6m": fuel_h3,
                "direction_h1_3m": fuel_h1.get("direction"),
                "direction_h3_6m": fuel_h3.get("direction"),
                "weight_sum_pct": WEIGHT_GASOLINE_PCT + WEIGHT_FUEL_OIL_PCT,
            },
            "underlying_core": core,
        },
        "headline": {
            "what_changed": headline_changed or "Observable input moves in energy and FX.",
            "where_transmitting": "Direct fuel numerical/range where supported; core channels directional.",
            "what_remains": (
                f"Fuel 1–3m {fuel_h1.get('direction')} ({fuel_h1.get('basis')}); "
                f"3–6m {fuel_h3.get('direction')} ({fuel_h3.get('basis')})"
            )[:200],
        },
        "status_line": status_line[:300],
        "missing_inputs": missing,
    }
    return out


def transmission_for_snapshot(
    snapshot: Mapping[str, Any],
    *,
    fx_history_points: Sequence[tuple[dt.date, float, str]] = (),
    root: Path | None = None,
) -> dict[str, Any]:
    block = snapshot.get("canada_prima_pressure")
    if not isinstance(block, dict):
        families = snapshot.get("families") if isinstance(snapshot.get("families"), dict) else {}
        ms = families.get("market_state") if isinstance(families.get("market_state"), dict) else {}
        data = ms.get("data") if isinstance(ms.get("data"), dict) else {}
        block = data.get("canada_prima_pressure")
    if not isinstance(block, dict):
        return unavailable_transmission("no_prima_block")

    frozen_tx = block.get("transmission")
    if (
        isinstance(frozen_tx, dict)
        and frozen_tx.get("provenance") == TRANSMISSION_PROVENANCE_LIVE
        and frozen_tx.get("status") != "unavailable"
    ):
        return frozen_tx

    as_of = _parse_date(snapshot.get("as_of")) or _parse_date(block.get("as_of"))
    if as_of is None:
        return unavailable_transmission("missing_as_of")

    pair = None
    families = snapshot.get("families") if isinstance(snapshot.get("families"), dict) else {}
    ms = families.get("market_state") if isinstance(families.get("market_state"), dict) else {}
    data = ms.get("data") if isinstance(ms.get("data"), dict) else {}
    fx = data.get("fx") if isinstance(data.get("fx"), dict) else {}
    pair = (fx.get("pairs") or {}).get("USDCAD")

    pts = list(fx_history_points)
    if not pts and root is not None:
        pts = collect_fx_history_points(root)

    inputs = inputs_from_frozen(
        block,
        usdcad_pair=pair if isinstance(pair, dict) else None,
        fx_history_points=pts,
        as_of=as_of,
    )
    return build_transmission(inputs, as_of=as_of)
