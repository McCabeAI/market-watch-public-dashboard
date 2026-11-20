"""Live-observed energy direct-fuel staging (PLAN §2.1)."""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Any, Mapping, Sequence

from scripts.prima_pressure import contract
from scripts.prima_pressure.contract import iso_date
from scripts.prima_pressure.expiry import contract_is_active, parse_listed_symbol
from scripts.prima_pressure.transmission_contract import (
    CRUDE_COST_SHARES,
    CRUDE_REFINING_DIVERGENCE_CPL,
    LITRES_PER_BARREL,
    LITRES_PER_US_GALLON,
    PP_NEUTRAL_ABS,
    TAX_PASS_THROUGH,
    TRANSMISSION_CHANNEL_ENERGY,
    WEIGHT_BASIS,
    WEIGHT_FUEL_OIL_PCT,
    WEIGHT_GASOLINE_PCT,
)


def _parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _period_cmp(a: str, b: str) -> int:
    return (a > b) - (a < b)


def _bars_for_period(bars: Sequence[dict], period: str) -> list[tuple[dt.date, float]]:
    out: list[tuple[dt.date, float]] = []
    for row in bars:
        d = _parse_date(row.get("date"))
        if d is None:
            continue
        if d.strftime("%Y-%m") != period:
            continue
        close = row.get("close")
        if isinstance(close, (int, float)):
            out.append((d, float(close)))
    return sorted(out)


def _nearest_fx(
    target: dt.date,
    history: Sequence[tuple[dt.date, float]],
    *,
    max_days: int = 5,
) -> float | None:
    best: tuple[int, float] | None = None
    for obs, spot in history:
        if obs > target:
            continue
        gap = (target - obs).days
        if gap > max_days:
            continue
        if best is None or gap < best[0]:
            best = (gap, spot)
    return best[1] if best else None


def _crude_cpl(usd_bbl: float, usdcad: float) -> float:
    return usd_bbl * usdcad / LITRES_PER_BARREL * 100.0


def _wholesale_cpl(usd_gal: float, usdcad: float) -> float:
    return usd_gal * usdcad / LITRES_PER_US_GALLON * 100.0


def _monthly_avg_cpl(
    bars: Sequence[dict],
    period: str,
    fx_history: Sequence[tuple[dt.date, float]],
    *,
    unit: str,
) -> tuple[float | None, int]:
    daily = _bars_for_period(bars, period)
    if len(daily) < 5:
        return None, len(daily)
    cpls: list[float] = []
    for d, price in daily:
        fx = _nearest_fx(d, fx_history)
        if fx is None:
            continue
        if unit == "crude":
            cpls.append(_crude_cpl(price, fx))
        else:
            cpls.append(_wholesale_cpl(price, fx))
    if len(cpls) < 5:
        return None, len(cpls)
    return sum(cpls) / len(cpls), len(cpls)


def _recon_pp_range(combined: float) -> tuple[float, float, float, str]:
    gas = [WEIGHT_GASOLINE_PCT * s * combined for s in CRUDE_COST_SHARES]
    fo = [WEIGHT_FUEL_OIL_PCT * s * combined for s in (0.5, 0.6, 0.7)]
    totals = sorted([g + f for g, f in zip(gas, fo)])
    return totals[0], totals[1], totals[2], "crude_cost_share 0.35/0.45/0.55"


def _pp_dir(pp: float | None) -> str:
    if pp is None:
        return "unavailable"
    if abs(pp) < PP_NEUTRAL_ABS:
        return "neutral"
    return "up" if pp > 0 else "down"


def _latest_nrcan_month(nrcan: Mapping[str, Any]) -> str | None:
    by = (nrcan or {}).get("gasoline_by_month") or {}
    if not by:
        return None
    through = (nrcan or {}).get("through_period")
    if through and through in by:
        return str(through)
    return max(by.keys())


def _pump(nrcan: Mapping[str, Any], period: str, *, fuel: str) -> float | None:
    key = "gasoline_by_month" if fuel == "gas" else "furnace_oil_by_month"
    row = (nrcan or {}).get(key) or {}
    val = row.get(period)
    return float(val) if isinstance(val, (int, float)) else None


def _front_active(front: Mapping[str, Any], as_of: dt.date) -> bool:
    sym = front.get("symbol")
    if not sym:
        return False
    try:
        root, year, month = parse_listed_symbol(str(sym))
    except Exception:
        return False
    try:
        return contract_is_active(root, year, month, as_of)
    except Exception:
        return False


def build_energy_live(
    live: Mapping[str, Any],
    *,
    as_of: dt.date,
) -> tuple[dict[str, Any], list[dict], str]:
    missing: list[dict] = []
    flags: list[str] = []
    nrcan = live.get("nrcan") or {}
    mc = live.get("cpi_reference_period")
    mr = _latest_nrcan_month(nrcan)
    fx_hist: list[tuple[dt.date, float]] = list(live.get("usdcad_history") or [])
    latest_fx = live.get("usdcad_latest")
    if isinstance(latest_fx, tuple) and latest_fx[1]:
        fx_spot = float(latest_fx[1])
        fx_date = latest_fx[0]
    elif fx_hist:
        fx_date, fx_spot = fx_hist[-1]
    else:
        fx_date, fx_spot = None, None

    front = live.get("brent_front") or {}
    brent_bars = (live.get("daily_bars") or {}).get("brent_front") or []
    rbob = live.get("rbob_front")
    rbob_bars = (live.get("daily_bars") or {}).get("rbob") or []
    ulsd = live.get("ulsd_front")
    p3 = live.get("brent_3m")
    p6 = live.get("brent_6m")
    p12 = live.get("brent_12m")

    if not _front_active(front, as_of):
        flags.append("expired_or_invalid_front")
        un = {
            "basis": "unavailable",
            "direction": "unavailable",
            "pp_low": None,
            "pp_mid": None,
            "pp_high": None,
            "reference_baseline": "Listed Brent front",
            "coverage": "none",
            "uncovered_interval": None,
        }
        stages_early: dict[str, Any] = {}
        mr_early = _latest_nrcan_month(nrcan)
        pump_mr_early = _pump(nrcan, str(mr_early), fuel="gas") if mr_early else None
        _, wm = _attach_weekly_energy_stages(
            stages_early,
            live=live,
            as_of=as_of,
            mr=mr_early,
            pump_mr=pump_mr_early,
            stage_c_pp=None,
            fx_hist=fx_hist,
            fx_spot=fx_spot if isinstance(fx_spot, (int, float)) else None,
            brent_bars=brent_bars,
            rbob_bars=rbob_bars,
            ulsd=ulsd,
        )
        ch = {
            "id": TRANSMISSION_CHANNEL_ENERGY,
            "label": "Direct fuel (gasoline & fuel oil)",
            "status": "unavailable",
            "observed_change": None,
            "stages": stages_early,
            "remaining": {"h1_3m": un, "h3_6m": dict(un)},
            "cpi_components": [],
            "assumptions": [{"name": "tax_pass_through", "value": TAX_PASS_THROUGH}],
            "notes": ["Front contract not active as of collection date."],
        }
        missing_early = [{"input": "brent_front", "reason": "expired_or_inactive"}]
        missing_early.extend(wm)
        return ch, missing_early, "unavailable"

    pump_mc = _pump(nrcan, str(mc), fuel="gas") if mc else None
    pump_mr = _pump(nrcan, str(mr), fuel="gas") if mr else None

    stages: dict[str, Any] = {}

    # Stage B
    stage_b_pp: float | None = None
    stage_b_status = "unavailable"
    if mr is None or pump_mr is None:
        stages["B"] = {"status": "unavailable", "pp_gasoline": None, "reason": "nrcan_missing"}
        missing.append({"input": "nrcan_gasoline", "reason": "missing_pump_series"})
    elif mc and mr == mc:
        stage_b_pp = 0.0
        stage_b_status = "ok"
        stages["B"] = {
            "status": "ok",
            "label": "no retail month after CPI",
            "pp_gasoline": 0.0,
            "M_c": mc,
            "M_r": mr,
            "pump_M_c_cpl": pump_mc,
            "pump_M_r_cpl": pump_mr,
        }
    elif mc and pump_mc and _period_cmp(mr, mc) > 0:
        stage_b_pp = WEIGHT_GASOLINE_PCT * (pump_mr / pump_mc - 1.0)
        stage_b_status = "ok"
        stages["B"] = {
            "status": "ok",
            "pp_gasoline": stage_b_pp,
            "M_c": mc,
            "M_r": mr,
            "pump_M_c_cpl": pump_mc,
            "pump_M_r_cpl": pump_mr,
        }
    else:
        stages["B"] = {"status": "unavailable", "pp_gasoline": None, "reason": "pump_levels_missing"}

    # Stage C gasoline
    stage_c_pp = None
    uncovered = None
    coverage = "full"
    use_wholesale = bool(rbob and rbob.get("price_usd_gal") and rbob_bars)
    unit = "wholesale" if use_wholesale else "crude"
    product_bars = rbob_bars if use_wholesale else brent_bars
    product_price = (
        float(rbob["price_usd_gal"])
        if use_wholesale
        else float(front.get("price_usd_bbl") or 0)
    )

    cost_now = None
    if fx_spot and product_price:
        cost_now = (
            _wholesale_cpl(product_price, fx_spot)
            if use_wholesale
            else _crude_cpl(product_price, fx_spot)
        )

    avg_mr = None
    bar_count = 0
    if mr and product_bars:
        avg_mr, bar_count = _monthly_avg_cpl(product_bars, mr, fx_hist, unit=unit)

    crude_window_pp = None
    base_date = _parse_date(front.get("change_1m_base_date"))
    obs_date = _parse_date(front.get("observation_date"))

    if pump_mr and cost_now is not None and avg_mr is not None:
        stage_c_pp = (cost_now - avg_mr) * TAX_PASS_THROUGH / pump_mr * WEIGHT_GASOLINE_PCT
        stages["C"] = {
            "status": "ok",
            "pp_gasoline": stage_c_pp,
            "cost_now_cpl": cost_now,
            "cost_avg_M_r_cpl": avg_mr,
            "cost_basis": unit,
            "bars_in_M_r": bar_count,
            "tax_factor": TAX_PASS_THROUGH,
        }
    elif pump_mr and cost_now is not None and base_date:
        coverage = "partial"
        uncovered = f"end of {mr or mc} month avg unavailable → {obs_date.isoformat() if obs_date else as_of.isoformat()}"
        # Fallback: change since base on crude
        base_px = None
        for d, px in sorted(((_parse_date(b.get("date")), b.get("close")) for b in brent_bars), key=lambda x: x[0] or dt.date.min):
            if d and base_date and d <= base_date and isinstance(px, (int, float)):
                base_px = float(px)
        fx_base = _nearest_fx(base_date, fx_hist) if base_date else None
        if base_px and fx_base and fx_spot:
            c_base = _crude_cpl(base_px, fx_base)
            stage_c_pp = (cost_now - c_base) * TAX_PASS_THROUGH / pump_mr * WEIGHT_GASOLINE_PCT
            stages["C"] = {
                "status": "partial",
                "pp_gasoline": stage_c_pp,
                "cost_now_cpl": cost_now,
                "cost_base_cpl": c_base,
                "cost_basis": "crude_from_brent_base",
                "uncovered_interval": uncovered,
            }
        else:
            stages["C"] = {"status": "unavailable", "pp_gasoline": None, "reason": "cannot_form_stage_c"}
    else:
        stages["C"] = {"status": "unavailable", "pp_gasoline": None, "reason": "missing_cost_or_pump"}

    # Divergence
    if cost_now is not None and brent_bars and rbob_bars and base_date and fx_spot:
        base_crude = None
        base_wh = None
        for d, px in _bars_for_period(brent_bars, base_date.strftime("%Y-%m")):
            if d <= base_date:
                fx = _nearest_fx(d, fx_hist) or fx_spot
                base_crude = _crude_cpl(px, fx)
        for d, px in _bars_for_period(rbob_bars, base_date.strftime("%Y-%m")):
            if d <= base_date:
                fx = _nearest_fx(d, fx_hist) or fx_spot
                base_wh = _wholesale_cpl(px, fx)
        if base_crude is not None and base_wh is not None:
            d_crude = cost_now - base_crude if not use_wholesale else _crude_cpl(float(front.get("price_usd_bbl") or 0), fx_spot) - base_crude
            d_wh = cost_now - base_wh if use_wholesale else None
            if use_wholesale and d_wh is not None and abs(d_wh - d_crude) >= CRUDE_REFINING_DIVERGENCE_CPL:
                flags.append("crude_refining_divergence")
                stages["divergence"] = {
                    "wholesale_cpl_change": d_wh,
                    "crude_cpl_change": d_crude,
                    "threshold_cpl": CRUDE_REFINING_DIVERGENCE_CPL,
                }

    # Curve h1 adjustment
    curve_pp = 0.0
    fp = front.get("price_usd_bbl")
    p3p = (p3 or {}).get("price_usd_bbl")
    if pump_mr and fp and p3p and fx_spot:
        mean_f3 = (float(fp) + float(p3p)) / 2.0
        c_front = _crude_cpl(float(fp), fx_spot)
        c_mean = _crude_cpl(mean_f3, fx_spot)
        curve_pp = (c_mean - c_front) * TAX_PASS_THROUGH / pump_mr * WEIGHT_GASOLINE_PCT
        stages["curve"] = {
            "status": "ok",
            "pp_gasoline_h1": curve_pp,
            "mean_front_3m_usd_bbl": mean_f3,
            "fx_spot": fx_spot,
        }
    else:
        stages["curve"] = {"status": "unavailable", "pp_gasoline_h1": None}

    # Fuel oil (HO/ULSD wholesale c/L vs NRCan furnace pump month avg)
    fo_pp: float | None = None
    ho_bars = (live.get("daily_bars") or {}).get("ulsd") or (live.get("daily_bars") or {}).get("ho") or []
    pump_mr_fo = _pump(nrcan, str(mr), fuel="fo") if mr else None
    cost_ho_now: float | None = None
    if ulsd and ulsd.get("price_usd_gal") and fx_spot:
        cost_ho_now = _wholesale_cpl(float(ulsd["price_usd_gal"]), fx_spot)
    avg_ho_mr: float | None = None
    ho_bar_count = 0
    if mr and ho_bars:
        avg_ho_mr, ho_bar_count = _monthly_avg_cpl(ho_bars, mr, fx_hist, unit="wholesale")
    if pump_mr_fo and cost_ho_now is not None and avg_ho_mr is not None:
        fo_pp = (cost_ho_now - avg_ho_mr) * TAX_PASS_THROUGH / pump_mr_fo * WEIGHT_FUEL_OIL_PCT
        stages["fuel_oil"] = {
            "status": "ok",
            "pp": fo_pp,
            "pump_furnace_cpl": pump_mr_fo,
            "cost_now_cpl": cost_ho_now,
            "cost_avg_M_r_cpl": avg_ho_mr,
            "bars_in_M_r": ho_bar_count,
        }
    elif pump_mr_fo and cost_ho_now is not None and base_date and brent_bars and fp:
        avg_crude_mr, _ = (
            _monthly_avg_cpl(brent_bars, mr, fx_hist, unit="crude")
            if mr
            else (None, 0)
        )
        if avg_crude_mr is not None:
            fo_pp = (cost_ho_now - avg_crude_mr) * TAX_PASS_THROUGH / pump_mr_fo * WEIGHT_FUEL_OIL_PCT
            stages["fuel_oil"] = {
                "status": "partial",
                "pp": fo_pp,
                "basis": "crude_proxy",
                "cost_now_cpl": cost_ho_now,
                "crude_avg_M_r_cpl": avg_crude_mr,
            }
        else:
            stages["fuel_oil"] = {"status": "unavailable", "pp": None, "reason": "missing_ho_month_avg"}
    else:
        stages["fuel_oil"] = {
            "status": "unavailable",
            "pp": None,
            "reason": "missing_furnace_pump_or_ho_cost",
        }
        flags.append("fuel_oil_leg_unavailable")

    # Total h1
    pp_parts = [
        x
        for x in (stage_b_pp, stage_c_pp, curve_pp, fo_pp)
        if isinstance(x, (int, float))
    ]
    use_recon_fallback = pump_mr is None
    if use_recon_fallback:
        flags.append("pump_level_missing")
        from scripts.prima_pressure.transmission import _combined_brent_cad

        r_usd = front.get("change_1m_pct")
        r_usd_f = float(r_usd) if isinstance(r_usd, (int, float)) else None
        r_fx = None
        if base_date and obs_date:
            spot_s = _nearest_fx(base_date, fx_hist)
            spot_e = _nearest_fx(obs_date, fx_hist)
            if spot_s and spot_e:
                r_fx = spot_e / spot_s - 1.0
        if r_usd_f is not None and r_fx is not None:
            combined, _, _ = _combined_brent_cad(r_usd_f, r_fx)
            low, mid, high, rb = _recon_pp_range(combined)  # type: ignore[arg-type]
            h1_basis = "range"
            pp_low, pp_mid, pp_high = low, mid, high
            range_basis = rb
        elif r_usd_f is not None:
            flags.append("fx_leg_missing")
            h1_basis = "directional"
            pp_low = pp_mid = pp_high = None
            range_basis = None
        else:
            h1_basis = "unavailable"
            pp_low = pp_mid = pp_high = None
            range_basis = None
    elif pp_parts and stage_b_status != "unavailable":
        pp_mid = sum(pp_parts)
        pp_low = pp_mid
        pp_high = pp_mid
        h1_basis = "numerical"
        range_basis = None
    elif stage_b_status == "unavailable" and stage_c_pp is not None:
        pp_mid = stage_c_pp + curve_pp
        pp_low = pp_high = pp_mid
        h1_basis = "numerical"
        range_basis = None
    else:
        h1_basis = "unavailable"
        pp_low = pp_mid = pp_high = None
        range_basis = None

    # h3_6m
    p6p = (p6 or {}).get("price_usd_bbl")
    if pump_mr and p3p and p6p and fp and fx_spot:
        mean_f3 = (float(fp) + float(p3p)) / 2.0
        mean_36 = (float(p3p) + float(p6p)) / 2.0
        c_f3 = _crude_cpl(mean_f3, fx_spot)
        c_36 = _crude_cpl(mean_36, fx_spot)
        h3_pp = (c_36 - c_f3) * TAX_PASS_THROUGH / pump_mr * WEIGHT_GASOLINE_PCT
        h3 = {
            "basis": "numerical",
            "direction": _pp_dir(h3_pp),
            "pp_low": h3_pp,
            "pp_mid": h3_pp,
            "pp_high": h3_pp,
            "reference_baseline": "mean(front,3m)→mean(3m,6m); futures-implied if realised",
            "coverage": coverage,
            "uncovered_interval": uncovered,
            "note": "FX held at latest spot",
        }
    elif p12 and fp:
        fpf, p12p = float(fp), float(p12.get("price_usd_bbl") or 0)
        h3_dir = "neutral"
        if fpf > p12p + contract.STABLE_USD:
            h3_dir = "down"
        elif fpf < p12p - contract.STABLE_USD:
            h3_dir = "up"
        h3 = {
            "basis": "directional",
            "direction": h3_dir,
            "pp_low": None,
            "pp_mid": None,
            "pp_high": None,
            "reference_baseline": "Front vs 12m (3m/6m contracts missing)",
            "coverage": coverage,
            "uncovered_interval": uncovered,
        }
    else:
        h3 = {
            "basis": "unavailable",
            "direction": "unavailable",
            "pp_low": None,
            "pp_mid": None,
            "pp_high": None,
            "reference_baseline": "",
            "coverage": coverage,
            "uncovered_interval": uncovered,
        }

    h1 = {
        "basis": h1_basis,
        "direction": _pp_dir(pp_mid),
        "pp_low": pp_low,
        "pp_mid": pp_mid,
        "pp_high": pp_high,
        "coverage": coverage,
        "uncovered_interval": uncovered,
    }
    if range_basis:
        h1["range_basis"] = range_basis

    from scripts.prima_pressure.transmission import _combined_brent_cad

    r_usd_obs = front.get("change_1m_pct")
    r_usd_f = float(r_usd_obs) if isinstance(r_usd_obs, (int, float)) else None
    r_fx_obs = None
    if base_date and obs_date:
        spot_s = _nearest_fx(base_date, fx_hist)
        spot_e = _nearest_fx(obs_date, fx_hist)
        if spot_s and spot_e:
            r_fx_obs = spot_e / spot_s - 1.0
    combined_obs = None
    decomp_obs = None
    if r_usd_f is not None:
        combined_obs, decomp_obs, comb_flags = _combined_brent_cad(r_usd_f, r_fx_obs)
        flags.extend(comb_flags)

    observed = {
        "metric": "brent_in_cad_1m",
        "units": "pct",
        "value": combined_obs,
        "window": {
            "start": base_date.isoformat() if base_date else None,
            "end": obs_date.isoformat() if obs_date else None,
        },
        "decomposition": decomp_obs,
        "flags": sorted(set(flags)),
    }

    weekly_ref, live_missing = _attach_weekly_energy_stages(
        stages,
        live=live,
        as_of=as_of,
        mr=mr,
        pump_mr=pump_mr,
        stage_c_pp=stage_c_pp,
        fx_hist=fx_hist,
        fx_spot=fx_spot,
        brent_bars=brent_bars,
        rbob_bars=rbob_bars,
        ulsd=ulsd,
    )
    missing.extend(live_missing)

    live_notes = [
        "Live staging: Stage B retail gap, Stage C wholesale/crude to pump, curve adjustment.",
    ]
    if stages.get("fuel_oil", {}).get("status") == "unavailable":
        live_notes.append("Fuel oil leg unavailable; not summed in h1–3m.")

    ref_base = f"Staged live · CPI {mc or 'unknown'} · NRCan {mr or 'unavailable'}"
    if weekly_ref:
        ref_base += f" · {weekly_ref}"
    h1["reference_baseline"] = ref_base

    channel = {
        "id": TRANSMISSION_CHANNEL_ENERGY,
        "label": "Direct fuel (gasoline & fuel oil)",
        "status": "ok" if h1_basis in ("numerical", "range") else "partial",
        "observed_change": observed,
        "transmission_seen": [],
        "stages": stages,
        "remaining": {"h1_3m": h1, "h3_6m": h3},
        "cpi_components": [
            {"name": "Gasoline", "weight_pct": WEIGHT_GASOLINE_PCT, "basket": "2025", "weight_basis": WEIGHT_BASIS},
            {"name": "Fuel oil & other fuels", "weight_pct": WEIGHT_FUEL_OIL_PCT, "basket": "2025", "weight_basis": WEIGHT_BASIS},
        ],
        "assumptions": [
            {"name": "tax_pass_through", "value": TAX_PASS_THROUGH, "source": "GST/HST/QST approx."},
            {"name": "live_numerical_band", "value": "point", "source": "single tax factor 1.10; no ±tax band on live point"},
        ],
        "notes": live_notes,
    }
    tx_status = "ok" if channel["status"] == "ok" else "partial"
    return channel, missing, tx_status


def _month_end_from_period(period: str | None) -> dt.date | None:
    if not period or len(period) < 7:
        return None
    try:
        y, m = int(period[:4]), int(period[5:7])
        last = calendar.monthrange(y, m)[1]
        return dt.date(y, m, last)
    except ValueError:
        return None


def _weekly_block_status(block: Mapping[str, Any] | None) -> str:
    if not isinstance(block, Mapping):
        return "unavailable"
    return str(block.get("status") or "unavailable")


def _eligible_weekly_latest(
    observations: Sequence[dict],
    *,
    as_of: dt.date,
    max_stale_days: int = 14,
) -> tuple[dict | None, str | None]:
    if not observations:
        return None, "no_observations"
    eligible = []
    floor = as_of - dt.timedelta(days=max_stale_days)
    for row in observations:
        we = _parse_date(row.get("week_ending"))
        if we is None or we > as_of or we < floor:
            continue
        eligible.append(row)
    if not eligible:
        latest_we = _parse_date(observations[-1].get("week_ending"))
        if latest_we and latest_we < floor:
            return None, "stale"
        return None, "no_eligible_week"
    return eligible[-1], None


def _obs_at_index(observations: Sequence[dict], index_back: int) -> dict | None:
    if len(observations) <= index_back:
        return None
    return observations[-1 - index_back]


def _bar_close_on_or_before(bars: Sequence[dict], target: dt.date) -> float | None:
    best: tuple[dt.date, float] | None = None
    for row in bars:
        d = _parse_date(row.get("date"))
        close = row.get("close")
        if d is None or not isinstance(close, (int, float)):
            continue
        if d > target:
            continue
        if best is None or d > best[0]:
            best = (d, float(close))
    return best[1] if best else None


def _classify_pump_gap(delta_pump: float, implied: float) -> str:
    if abs(delta_pump) >= 1e-9 and abs(implied) >= 1e-9:
        if (delta_pump > 0) != (implied > 0):
            return "opposite_sign"
    gap = delta_pump - implied
    if abs(gap) < CRUDE_REFINING_DIVERGENCE_CPL:
        return "consistent"
    if abs(delta_pump) < abs(implied):
        return "pump_lagging"
    return "pump_leading"


def _weekly_four_week_pair(
    observations: Sequence[dict],
    *,
    as_of: dt.date,
) -> tuple[dict | None, dict | None, str | None]:
    tail = [
        row
        for row in observations
        if _parse_date(row.get("week_ending")) and _parse_date(row["week_ending"]) <= as_of
    ]
    if len(tail) < 5:
        return None, None, "insufficient_weekly_history"
    latest = tail[-1]
    prior = tail[-5]
    d_latest = _parse_date(latest.get("week_ending"))
    d_prior = _parse_date(prior.get("week_ending"))
    if d_latest is None or d_prior is None:
        return None, None, "malformed_dates"
    span = (d_latest - d_prior).days
    if span < 21 or span > 35:
        return None, None, "weekly_spacing_not_4w"
    return latest, prior, None


def _nrcan_series_block(
    nrcan_w: Any,
    series_key: str,
) -> tuple[Mapping[str, Any] | None, dict[str, Any] | None, str | None]:
    """Return (block, series_entry, malformed_reason)."""
    if not isinstance(nrcan_w, Mapping):
        return None, None, "malformed_feed"
    raw_series = nrcan_w.get("series")
    if raw_series is not None and not isinstance(raw_series, Mapping):
        return nrcan_w, None, "malformed_feed"
    series_map: Mapping[str, Any] = raw_series or {}
    entry = series_map.get(series_key)
    if entry is not None and not isinstance(entry, Mapping):
        return nrcan_w, None, "malformed_feed"
    return nrcan_w, dict(entry) if isinstance(entry, Mapping) else {}, None


def _attach_weekly_energy_stages(
    stages: dict[str, Any],
    *,
    live: Mapping[str, Any],
    as_of: dt.date,
    mr: str | None,
    pump_mr: float | None,
    stage_c_pp: float | None,
    fx_hist: Sequence[tuple[dt.date, float]],
    fx_spot: float | None,
    brent_bars: Sequence[dict],
    rbob_bars: Sequence[dict],
    ulsd: Mapping[str, Any] | None,
) -> tuple[str | None, list[dict]]:
    missing: list[dict] = []
    weekly_ref: str | None = None
    nrcan_w = live.get("nrcan_weekly")
    if _weekly_block_status(nrcan_w) == "not_in_frozen_snapshot":
        for key in ("weekly_pump", "pump_vs_wholesale", "diesel_weekly"):
            stages[key] = {"status": "not_in_frozen_snapshot"}
        return None, missing

    nrcan_w_map, gas_series, nrcan_malformed = _nrcan_series_block(nrcan_w, "gasoline_regular")
    if nrcan_malformed:
        for key in ("weekly_pump", "pump_vs_wholesale", "diesel_weekly"):
            stages[key] = {
                "status": "unavailable",
                "reason": nrcan_malformed,
                "role": "informational" if key != "weekly_pump" else None,
            }
            stages[key] = {k: v for k, v in stages[key].items() if v is not None}
        return None, missing
    nrcan_w = nrcan_w_map or {}
    gas_series = gas_series or {}
    gas_obs = gas_series.get("observations") if isinstance(gas_series.get("observations"), list) else []

    # weekly_pump
    wp: dict[str, Any]
    if _weekly_block_status(nrcan_w) != "ok" and _weekly_block_status(nrcan_w) != "partial":
        wp = {
            "status": "unavailable",
            "reason": (nrcan_w or {}).get("reason") if isinstance(nrcan_w, Mapping) else "feed_missing",
            "frequency": "weekly",
        }
        if gas_series.get("status") == "unavailable":
            missing.append({"input": "nrcan_weekly_gasoline", "reason": str(gas_series.get("reason") or "unavailable")})
    else:
        latest_row, inelig = _eligible_weekly_latest(gas_obs, as_of=as_of)
        mr_end = _month_end_from_period(mr)
        if latest_row is None:
            wp = {
                "status": "stale" if inelig == "stale" else "unavailable",
                "reason": inelig or "no_weekly",
                "frequency": "weekly",
            }
            missing.append({"input": "nrcan_weekly_gasoline", "reason": inelig or "unavailable"})
        elif pump_mr is None or mr is None:
            wp = {"status": "unavailable", "reason": "pump_M_r_missing", "frequency": "weekly"}
        else:
            week_end = _parse_date(latest_row.get("week_ending"))
            price_cpl = latest_row.get("price_cpl")
            if week_end is None or not isinstance(price_cpl, (int, float)):
                wp = {"status": "unavailable", "reason": "malformed_weekly", "frequency": "weekly"}
            elif mr_end and week_end <= mr_end:
                wp = {
                    "status": "no_week_after_M_r",
                    "frequency": "weekly",
                    "week_ending": week_end.isoformat(),
                    "M_r": mr,
                    "pump_M_r_cpl": pump_mr,
                }
            else:
                observed_pp = WEIGHT_GASOLINE_PCT * (float(price_cpl) / pump_mr - 1.0)
                residual = None
                if isinstance(stage_c_pp, (int, float)):
                    residual = float(stage_c_pp) - observed_pp
                wp = {
                    "status": "ok",
                    "frequency": "weekly",
                    "week_ending": week_end.isoformat(),
                    "price_cpl": float(price_cpl),
                    "M_r": mr,
                    "pump_M_r_cpl": pump_mr,
                    "observed_at_pump_pp": observed_pp,
                    "residual_unpriced_pp": residual,
                    "split_note": "split of Stage C (cost→pump), not additive; both not yet in CPI",
                    "source": "nrcan_weekly_gasoline_regular",
                    "product_id": gas_series.get("product_id"),
                    "retrieved_at": (nrcan_w or {}).get("retrieved_at") if isinstance(nrcan_w, Mapping) else None,
                    "published_at": (nrcan_w or {}).get("published_at") if isinstance(nrcan_w, Mapping) else None,
                }
                weekly_ref = f"NRCan weekly to {week_end.isoformat()}"
    stages["weekly_pump"] = wp

    # pump_vs_wholesale
    pvw: dict[str, Any]
    if not gas_obs or _weekly_block_status(nrcan_w) not in ("ok", "partial"):
        pvw = {"status": "unavailable", "reason": "nrcan_weekly_missing", "role": "informational"}
    else:
        latest, prior, pair_reason = _weekly_four_week_pair(gas_obs, as_of=as_of)
        if pair_reason or latest is None or prior is None:
            pvw = {
                "status": "unavailable",
                "reason": pair_reason or "insufficient_weekly_history",
                "role": "informational",
            }
        else:
            d_latest = _parse_date(latest.get("week_ending"))
            d_prior = _parse_date(prior.get("week_ending"))
            p_latest = latest.get("price_cpl")
            p_prior = prior.get("price_cpl")
            if d_latest is None or d_prior is None:
                pvw = {"status": "unavailable", "reason": "malformed_dates", "role": "informational"}
            elif not isinstance(p_latest, (int, float)) or not isinstance(p_prior, (int, float)):
                pvw = {"status": "unavailable", "reason": "missing_prices", "role": "informational"}
            else:
                delta_pump = float(p_latest) - float(p_prior)
                use_rbob = bool(rbob_bars)
                product_bars = rbob_bars if use_rbob else brent_bars
                unit = "wholesale" if use_rbob else "crude"
                if not product_bars:
                    pvw = {"status": "unavailable", "reason": "missing_futures_bars", "role": "informational"}
                else:
                    px_l = _bar_close_on_or_before(product_bars, d_latest)
                    px_p = _bar_close_on_or_before(product_bars, d_prior)
                    fx_l = _nearest_fx(d_latest, fx_hist) or fx_spot
                    fx_p = _nearest_fx(d_prior, fx_hist) or fx_spot
                    if px_l is None or px_p is None or fx_l is None or fx_p is None:
                        pvw = {"status": "unavailable", "reason": "missing_price_or_fx_leg", "role": "informational"}
                    else:
                        if unit == "wholesale":
                            cpl_l = _wholesale_cpl(px_l, fx_l)
                            cpl_p = _wholesale_cpl(px_p, fx_p)
                        else:
                            cpl_l = _crude_cpl(px_l, fx_l)
                            cpl_p = _crude_cpl(px_p, fx_p)
                        delta_cost = cpl_l - cpl_p
                        implied = delta_cost * TAX_PASS_THROUGH
                        classification = _classify_pump_gap(delta_pump, implied)
                        pvw = {
                            "status": "ok",
                            "role": "informational",
                            "classification": classification,
                            "delta_pump_cpl": delta_pump,
                            "delta_wholesale_cpl": delta_cost,
                            "delta_crude_cpl": delta_cost if unit == "crude" else None,
                            "implied_pump_change_cpl": implied,
                            "gap_cpl": delta_pump - implied,
                            "cost_basis": unit,
                            "window": {
                                "start": d_prior.isoformat(),
                                "end": d_latest.isoformat(),
                            },
                            "cpi_contribution": None,
                        }
    stages["pump_vs_wholesale"] = pvw

    # diesel_weekly
    _, diesel_series, diesel_malformed = _nrcan_series_block(nrcan_w, "diesel")
    diesel_obs = (
        diesel_series.get("observations")
        if isinstance(diesel_series, Mapping) and isinstance(diesel_series.get("observations"), list)
        else []
    )
    dw: dict[str, Any]
    if diesel_malformed:
        dw = {
            "status": "unavailable",
            "reason": "malformed_feed",
            "role": "transport_and_producer_cost_context",
        }
    elif _weekly_block_status(nrcan_w) not in ("ok", "partial"):
        dw = {"status": "unavailable", "reason": "nrcan_weekly_missing", "role": "transport_and_producer_cost_context"}
    elif not diesel_obs:
        dw = {"status": "unavailable", "reason": "no_diesel_observations", "role": "transport_and_producer_cost_context"}
    else:
        latest_d, prior_d, diesel_pair_reason = _weekly_four_week_pair(diesel_obs, as_of=as_of)
        change_pct = None
        if diesel_pair_reason or latest_d is None or prior_d is None:
            dw = {
                "status": "unavailable",
                "reason": diesel_pair_reason or "insufficient_weekly_history",
                "role": "transport_and_producer_cost_context",
            }
        else:
            a, b = latest_d.get("price_cpl"), prior_d.get("price_cpl")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b != 0:
                change_pct = float(a) / float(b) - 1.0
            ulsd_chg = None
            if ulsd and isinstance(ulsd, Mapping):
                ho_bars = (live.get("daily_bars") or {}).get("ulsd") or (live.get("daily_bars") or {}).get("ho") or []
                d_end = _parse_date(latest_d.get("week_ending"))
                d_start = _parse_date(prior_d.get("week_ending"))
                if d_end and d_start and ho_bars:
                    p_end = _bar_close_on_or_before(ho_bars, d_end)
                    p_start = _bar_close_on_or_before(ho_bars, d_start)
                    fx_e = _nearest_fx(d_end, fx_hist) or fx_spot
                    fx_s = _nearest_fx(d_start, fx_hist) or fx_spot
                    if p_end and p_start and fx_e and fx_s:
                        ulsd_chg = _wholesale_cpl(p_end, fx_e) / _wholesale_cpl(p_start, fx_s) - 1.0
            dw = {
                "status": "ok",
                "role": "transport_and_producer_cost_context",
                "frequency": "weekly",
                "latest_week_ending": latest_d.get("week_ending"),
                "price_cpl": latest_d.get("price_cpl"),
                "change_4w_pct_decimal": change_pct,
                "ulsd_futures_4w_pct_decimal": ulsd_chg,
                "cpi_contribution": None,
                "note": "not added to household gasoline/fuel-oil pp",
            }
    stages["diesel_weekly"] = dw
    return weekly_ref, missing
