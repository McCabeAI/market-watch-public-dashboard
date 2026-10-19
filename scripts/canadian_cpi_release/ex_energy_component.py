"""Canadian ex-energy component nowcast and walk-forward backtest (C1)."""

from __future__ import annotations

from typing import Any

import numpy as np

from scripts.canadian_cpi_release.contract import Snapshot, add_months
from scripts.canadian_cpi_release.engine import ObsIndex
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    ALL_ITEMS_ID,
    BACKTEST_SCHEMA,
    EVAL_PRIMARY_START,
    EVAL_RECENT_START,
    EX_ENERGY_ID,
    EX_FOOD_ENERGY_ID,
    FOOD_ID,
    IDENTITY_NOTE,
    combine_partition_mom,
    equal_blend,
    index_from_mom,
    paired_abs_error_summary,
    price_updated_share,
    yoy_from_index,
)
from scripts.canadian_cpi_release.model import compute_moms, forecast_model_a
from scripts.canadian_cpi_release.weights import select_basket_vintage

MODEL_A_LABEL = "forecast_model_a"

LIMITATIONS_NOWCAST = [
    "Latest-vintage snapshot: published_at gates eligibility; this is not a full real-time vintage replay.",
    "NSA CPI is mostly unrevised but basket weights can revise.",
    "NRCan is not used in this ex-energy component path.",
    IDENTITY_NOTE,
]

LIMITATIONS_BACKTEST = [
    "Pseudo-OOS latest vintage, not a full real-time vintage backtest.",
    "NSA CPI is mostly unrevised but basket weights can revise.",
    "NRCan is not used here.",
    IDENTITY_NOTE,
]


def _weight_period(basket_year: int) -> str:
    return f"{basket_year}-01"


def _weight_id(index_id: str) -> str:
    return f"{index_id}__weight"


def _sign_match(forecast: float, actual: float) -> bool:
    def sgn(x: float) -> float:
        if x > 0:
            return 1.0
        if x < 0:
            return -1.0
        return 0.0

    return sgn(forecast) == sgn(actual)


def _metrics_row(
    model: str, regime: str, forecasts: list[float], actuals: list[float]
) -> dict[str, Any]:
    n = len(forecasts)
    if n == 0:
        return {"model": model, "regime": regime, "n": 0}
    err = np.array(forecasts) - np.array(actuals)
    return {
        "model": model,
        "regime": regime,
        "n": n,
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "bias": float(np.mean(err)),
        "direction": float(
            np.mean([_sign_match(f, a) for f, a in zip(forecasts, actuals)])
        ),
    }


def _mom_from_levels(level_now: float, level_prev: float) -> float:
    if level_prev == 0:
        raise ValueError("zero_prev_level")
    return 100.0 * (level_now / level_prev - 1.0)


def month_actual_ex_energy_mom(snapshot: Snapshot, as_of: str, period: str) -> float | None:
    """Official ex-energy NSA MoM for ``period`` if eligible at ``as_of``."""
    idx = ObsIndex.build(snapshot, as_of, period)
    t1 = add_months(period, -1)
    lv = idx.level(
        EX_ENERGY_ID, period, input_for_forecast=False, allow_actual_month=True
    )
    l1 = idx.level(EX_ENERGY_ID, t1)
    if lv is None or l1 is None:
        return None
    if idx.get_obs(EX_ENERGY_ID, period) is None:
        return None
    return _mom_from_levels(lv, l1)


def _actual_mom(idx: ObsIndex, canonical_id: str, period: str) -> float | None:
    t1 = add_months(period, -1)
    lv = idx.level(canonical_id, period, input_for_forecast=False, allow_actual_month=True)
    l1 = idx.level(canonical_id, t1)
    if lv is None or l1 is None:
        return None
    if idx.get_obs(canonical_id, period) is None:
        return None
    return _mom_from_levels(lv, l1)


def _forecast_yoy(idx: ObsIndex, mom: float) -> float | None:
    release = idx.release
    t1 = add_months(release, -1)
    t12 = add_months(release, -12)
    prev = idx.level(EX_ENERGY_ID, t1)
    base = idx.level(EX_ENERGY_ID, t12)
    if prev is None or base is None or base <= 0:
        return None
    forecast_index = index_from_mom(prev, mom)
    return yoy_from_index(forecast_index, base)


def _levels_dict(idx: ObsIndex, canonical_id: str) -> dict[str, float]:
    return idx.levels_before(canonical_id)


def _basket_weight_percent(idx: ObsIndex, index_id: str, basket_year: int) -> float | None:
    w_key = _weight_period(basket_year)
    obs = idx.get_obs(_weight_id(index_id), w_key)
    return obs.value if obs is not None else None


def _price_updated_shares_for_release(
    idx: ObsIndex,
    release: str,
    basket_year: int,
    basket_link: str,
) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """Return partition shares, basket weight percents, blockers."""
    blockers: list[str] = []
    t_minus_1 = add_months(release, -1)
    all_link = idx.level(ALL_ITEMS_ID, basket_link)
    all_tm1 = idx.level(ALL_ITEMS_ID, t_minus_1)
    if all_link is None or all_tm1 is None:
        blockers.append("missing_all_items_levels_for_weights")
        return {}, {}, blockers

    basket_weights: dict[str, float] = {}
    shares: dict[str, float] = {}
    for key, index_id in (
        ("food", FOOD_ID),
        ("ex_food_energy", EX_FOOD_ENERGY_ID),
        ("ex_energy", EX_ENERGY_ID),
    ):
        w_pct = _basket_weight_percent(idx, index_id, basket_year)
        if w_pct is None:
            blockers.append(f"missing_weight_{index_id}")
            continue
        basket_weights[key] = w_pct
        i_link = idx.level(index_id, basket_link)
        i_tm1 = idx.level(index_id, t_minus_1)
        if i_link is None or i_tm1 is None:
            blockers.append(f"missing_index_levels_{index_id}")
            continue
        try:
            shares[key] = price_updated_share(
                basket_weight_percent=w_pct,
                index_link=i_link,
                index_tm1=i_tm1,
                all_items_link=all_link,
                all_items_tm1=all_tm1,
            )
        except ValueError:
            blockers.append(f"invalid_share_{index_id}")

    return shares, basket_weights, blockers


def _forecast_mom_model_a(idx: ObsIndex, canonical_id: str, release: str) -> tuple[float, str]:
    levels = _levels_dict(idx, canonical_id)
    moms = compute_moms(levels)
    mom, method = forecast_model_a(moms, release)
    label = MODEL_A_LABEL if method == "modeled" else f"{MODEL_A_LABEL}_{method}"
    return mom, label


def _identity_history(
    snapshot: Snapshot,
    as_of: str,
    before: str,
    *,
    start: str = EVAL_PRIMARY_START,
) -> tuple[float | None, int]:
    residuals: list[float] = []
    period = start
    while period < before:
        idx = ObsIndex.build(snapshot, as_of, period)
        official = month_actual_ex_energy_mom(snapshot, as_of, period)
        if official is None:
            period = add_months(period, 1)
            continue
        mom_food = _actual_mom(idx, FOOD_ID, period)
        mom_exfe = _actual_mom(idx, EX_FOOD_ENERGY_ID, period)
        if mom_food is None or mom_exfe is None:
            period = add_months(period, 1)
            continue
        weight_pubs = idx.weight_publication_years()
        basket_year, basket_link, basket_status, _, _ = select_basket_vintage(
            period, as_of, weight_pubs
        )
        if basket_status == "blocked":
            period = add_months(period, 1)
            continue
        shares, _, blockers = _price_updated_shares_for_release(
            idx, period, basket_year, basket_link
        )
        if blockers or "food" not in shares or "ex_food_energy" not in shares:
            period = add_months(period, 1)
            continue
        approx = combine_partition_mom(
            shares["food"],
            mom_food,
            shares["ex_food_energy"],
            mom_exfe,
        )
        residuals.append(official - approx)
        period = add_months(period, 1)

    if not residuals:
        return None, 0
    return float(np.mean(np.abs(residuals))), len(residuals)


def _blocked_nowcast(
    snapshot: Snapshot,
    release: str,
    as_of: str,
    *,
    basket_year: int | None = None,
    basket_link: str | None = None,
    basket_status: str = "blocked",
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    recent_mae, recent_n = _identity_history(snapshot, as_of, release)
    return {
        "status": "blocked",
        "release": release,
        "as_of": as_of,
        "basket_year": basket_year,
        "basket_link": basket_link,
        "basket_status": basket_status,
        "blockers": blockers or [],
        "shares": {
            "food": None,
            "ex_food_energy": None,
            "ex_energy": None,
            "partition_sum": None,
        },
        "basket_weight_percent": {
            "food": None,
            "ex_food_energy": None,
            "ex_energy": None,
            "weight_gap": None,
        },
        "forecasts": {
            "direct": {"nsa_mom": None, "method": None, "yoy": None},
            "component": {"nsa_mom": None, "method": None, "yoy": None},
            "blend_equal": {"nsa_mom": None, "method": None, "yoy": None},
        },
        "methods": {"food": None, "ex_food_energy": None, "direct": None},
        "identity": {
            "note": IDENTITY_NOTE,
            "residual_mom": None,
            "recent_mae": recent_mae,
            "recent_n": recent_n,
        },
        "limitations": list(LIMITATIONS_NOWCAST),
    }


def component_ex_energy_nowcast(snapshot: Snapshot, release: str, as_of: str) -> dict[str, Any]:
    idx = ObsIndex.build(snapshot, as_of, release)
    weight_pubs = idx.weight_publication_years()
    basket_year, basket_link, basket_status, blockers, assumptions = select_basket_vintage(
        release, as_of, weight_pubs
    )
    if basket_status == "blocked":
        out = _blocked_nowcast(
            snapshot,
            release,
            as_of,
            basket_year=None,
            basket_link=None,
            basket_status=basket_status,
            blockers=blockers,
        )
        out["assumptions"] = assumptions
        return out

    shares, basket_weights, share_blockers = _price_updated_shares_for_release(
        idx, release, basket_year, basket_link
    )
    t_minus_1 = add_months(release, -1)
    if idx.level(EX_ENERGY_ID, t_minus_1) is None:
        share_blockers.append("missing_ex_energy_t_minus_1")

    if share_blockers:
        out = _blocked_nowcast(
            snapshot,
            release,
            as_of,
            basket_year=basket_year,
            basket_link=basket_link,
            basket_status="blocked",
            blockers=share_blockers + blockers,
        )
        out["assumptions"] = assumptions
        return out

    weight_gap = (
        basket_weights["food"]
        + basket_weights["ex_food_energy"]
        - basket_weights["ex_energy"]
    )
    partition_sum = shares["food"] + shares["ex_food_energy"]

    mom_food, method_food = _forecast_mom_model_a(idx, FOOD_ID, release)
    mom_exfe, method_exfe = _forecast_mom_model_a(idx, EX_FOOD_ENERGY_ID, release)
    mom_direct, method_direct = _forecast_mom_model_a(idx, EX_ENERGY_ID, release)

    mom_component = combine_partition_mom(
        shares["food"], mom_food, shares["ex_food_energy"], mom_exfe
    )
    mom_blend = equal_blend(mom_direct, mom_component)

    yoy_direct = _forecast_yoy(idx, mom_direct)
    yoy_component = _forecast_yoy(idx, mom_component)
    yoy_blend = _forecast_yoy(idx, mom_blend)

    residual_mom: float | None = None
    official_target = month_actual_ex_energy_mom(snapshot, as_of, release)
    if official_target is not None:
        mom_food_act = _actual_mom(idx, FOOD_ID, release)
        mom_exfe_act = _actual_mom(idx, EX_FOOD_ENERGY_ID, release)
        if mom_food_act is not None and mom_exfe_act is not None:
            approx_act = combine_partition_mom(
                shares["food"],
                mom_food_act,
                shares["ex_food_energy"],
                mom_exfe_act,
            )
            residual_mom = official_target - approx_act

    recent_mae, recent_n = _identity_history(snapshot, as_of, release)

    return {
        "status": "ok",
        "release": release,
        "as_of": as_of,
        "basket_year": basket_year,
        "basket_link": basket_link,
        "basket_status": basket_status,
        "assumptions": assumptions,
        "blockers": blockers,
        "shares": {
            "food": shares["food"],
            "ex_food_energy": shares["ex_food_energy"],
            "ex_energy": shares["ex_energy"],
            "partition_sum": partition_sum,
        },
        "basket_weight_percent": {
            "food": basket_weights["food"],
            "ex_food_energy": basket_weights["ex_food_energy"],
            "ex_energy": basket_weights["ex_energy"],
            "weight_gap": weight_gap,
        },
        "forecasts": {
            "direct": {
                "nsa_mom": mom_direct,
                "method": method_direct,
                "yoy": yoy_direct,
            },
            "component": {
                "nsa_mom": mom_component,
                "method": "partition_food_ex_food_energy",
                "yoy": yoy_component,
            },
            "blend_equal": {
                "nsa_mom": mom_blend,
                "method": "equal_blend_predeclared",
                "yoy": yoy_blend,
            },
        },
        "methods": {
            "food": method_food,
            "ex_food_energy": method_exfe,
            "direct": method_direct,
        },
        "identity": {
            "note": IDENTITY_NOTE,
            "residual_mom": residual_mom,
            "recent_mae": recent_mae,
            "recent_n": recent_n,
        },
        "limitations": list(LIMITATIONS_NOWCAST),
    }


def walk_forward_ex_energy(
    snapshot: Snapshot,
    as_of: str,
    start: str = "2017-01",
    end: str = "2026-08",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    blocked_months = 0
    period = start
    while period <= end:
        fc = component_ex_energy_nowcast(snapshot, period, as_of)
        actual = month_actual_ex_energy_mom(snapshot, as_of, period)
        basket_year = fc.get("basket_year")

        if fc["status"] != "ok":
            blocked_months += 1
            period = add_months(period, 1)
            continue

        for model_key in ("direct", "component", "blend_equal"):
            forecast_val = fc["forecasts"][model_key]["nsa_mom"]
            rows.append(
                {
                    "period": period,
                    "model": model_key,
                    "forecast": forecast_val,
                    "actual": actual,
                    "basket_year": basket_year,
                }
            )
        period = add_months(period, 1)

    models = ("direct", "component", "blend_equal")
    regimes: list[tuple[str, Any]] = [
        ("all", lambda p: True),
        ("from_2019", lambda p: p >= EVAL_PRIMARY_START),
        ("recent_2025_26", lambda p: p >= EVAL_RECENT_START),
        ("september", lambda p: p[5:7] == "09"),
    ]

    metrics: list[dict[str, Any]] = []
    for model in models:
        model_rows = [r for r in rows if r["model"] == model]
        for regime_name, pred in regimes:
            sub = [
                r
                for r in model_rows
                if pred(r["period"]) and r["actual"] is not None and r["forecast"] is not None
            ]
            if not sub:
                continue
            metrics.append(
                _metrics_row(
                    model,
                    regime_name,
                    [r["forecast"] for r in sub],
                    [r["actual"] for r in sub],
                )
            )

    paired_vs_direct: dict[str, dict[str, Any]] = {}
    for alt in ("component", "blend_equal"):
        for regime_name, pred in (
            ("from_2019", lambda p: p >= EVAL_PRIMARY_START),
            ("recent_2025_26", lambda p: p >= EVAL_RECENT_START),
        ):
            direct_errs: list[float] = []
            alt_errs: list[float] = []
            periods = sorted(
                {
                    r["period"]
                    for r in rows
                    if r["model"] == "direct"
                    and pred(r["period"])
                    and r["actual"] is not None
                    and r["forecast"] is not None
                }
            )
            for p in periods:
                d_row = next(
                    r
                    for r in rows
                    if r["period"] == p and r["model"] == "direct"
                )
                a_row = next(
                    r for r in rows if r["period"] == p and r["model"] == alt
                )
                if a_row["forecast"] is None:
                    continue
                actual = d_row["actual"]
                if actual is None:
                    continue
                direct_errs.append(d_row["forecast"] - actual)
                alt_errs.append(a_row["forecast"] - actual)
            key = f"{alt}_{regime_name}"
            paired_vs_direct[key] = paired_abs_error_summary(direct_errs, alt_errs)

    return {
        "schema_version": BACKTEST_SCHEMA,
        "as_of": as_of,
        "start": start,
        "end": end,
        "blocked_months": blocked_months,
        "rows": rows,
        "metrics": metrics,
        "paired_vs_direct": paired_vs_direct,
        "limitations": list(LIMITATIONS_BACKTEST),
    }
