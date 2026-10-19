"""Air transportation shadow forecasts and ex-energy parent replacements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scripts.canadian_cpi_release.contract import (
    Snapshot,
    add_months,
    published_on_or_before,
)
from scripts.canadian_cpi_release.engine import ObsIndex
from scripts.canadian_cpi_release.ex_energy_interfaces import (
    AIRFARE_COMPARATORS,
    AIRFARE_ID,
    AIRFARE_INDEX_SPEC,
    AIRFARE_SEASONAL_N,
    AIRFARE_SEASONAL_PRIMARY,
    AIRFARE_WEIGHT_ID,
    AIRFARE_WEIGHT_SPEC,
    BACKTEST_END,
    BACKTEST_START,
    EVAL_PRIMARY_START,
    EVAL_RECENT_START,
    EX_ENERGY_ID,
    EX_FOOD_ENERGY_ID,
    ALL_ITEMS_ID,
    paired_abs_error_summary,
    price_updated_share,
    promotion_decision,
    replace_child_within_parent,
    same_month_mean,
)
from scripts.canadian_cpi_release.model import (
    baseline_carry_mean3_season5,
    compute_moms,
    forecast_model_a,
)
from scripts.canadian_cpi_release.sources.airfare_statcan import load_airfare_snapshot
from scripts.canadian_cpi_release.weights import select_basket_vintage

AIRFARE_LIMITATIONS = [
    "Airfare index values are latest-vintage StatCan WDS points in the separate airfare fixture.",
    "releaseTime gates as-of eligibility; historical index revisions are not reconstructed.",
    "NRCan is not used for air transportation.",
]


@dataclass
class AirfareObsIndex:
    snapshot: Snapshot
    as_of: str
    release: str
    _raw: dict[tuple[str, str], Any]

    @classmethod
    def build(cls, snapshot: Snapshot, as_of: str, release: str) -> AirfareObsIndex:
        raw: dict[tuple[str, str], Any] = {}
        for obs in snapshot.observations:
            key = (obs.canonical_id, obs.period)
            if key not in raw:
                raw[key] = obs
        return cls(snapshot=snapshot, as_of=as_of, release=release, _raw=raw)

    def eligible(self, obs) -> bool:
        return published_on_or_before(obs.published_at, self.as_of)

    def get_obs(self, canonical_id: str, period: str):
        obs = self._raw.get((canonical_id, period))
        if obs is None:
            return None
        return obs if self.eligible(obs) else None

    def level(
        self,
        canonical_id: str,
        period: str,
        *,
        input_for_forecast: bool = True,
        allow_actual_month: bool = False,
    ) -> float | None:
        if input_for_forecast and period >= self.release and not allow_actual_month:
            return None
        obs = self.get_obs(canonical_id, period)
        return obs.value if obs else None

    def levels_before(self, canonical_id: str, *, include_release_month: bool = False) -> dict[str, float]:
        out: dict[str, float] = {}
        for (cid, period), obs in self._raw.items():
            if cid != canonical_id:
                continue
            if not self.eligible(obs):
                continue
            if period >= self.release and not include_release_month:
                continue
            out[period] = obs.value
        return out


def _actual_mom(idx: AirfareObsIndex | ObsIndex, canonical_id: str, period: str) -> float | None:
    t1 = add_months(period, -1)
    lv = idx.level(canonical_id, period, input_for_forecast=False, allow_actual_month=True)
    l1 = idx.level(canonical_id, t1)
    if lv is None or l1 is None or l1 == 0:
        return None
    obs = idx.get_obs(canonical_id, period)
    if obs is None:
        return None
    return 100.0 * (lv / l1 - 1.0)


def _count_same_month_prior(moms: dict[str, float], target: str) -> int:
    month = target[5:7]
    return len([p for p in sorted(moms) if p < target and p[5:7] == month])


def _airfare_method_forecasts(moms: dict[str, float], target: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seasonal = same_month_mean(moms, target, n=AIRFARE_SEASONAL_N)
    n_same = _count_same_month_prior(moms, target)
    short = n_same < AIRFARE_SEASONAL_N
    out[AIRFARE_SEASONAL_PRIMARY] = {
        "mom": seasonal,
        "short_seasonal_sample": short,
        "promotion_eligible": seasonal is not None and not short,
    }
    _, _, season5 = baseline_carry_mean3_season5(moms, target)
    out["season5_engine"] = {"mom": season5, "comparator": True}
    ridge, method = forecast_model_a(moms, target)
    out["ridge_model_a"] = {"mom": ridge, "method": method, "comparator": True}
    return out


def _basket_weight_percent(air_idx: AirfareObsIndex, basket_year: int) -> float | None:
    return air_idx.level(AIRFARE_WEIGHT_ID, f"{basket_year}-01", input_for_forecast=False)


def _series_price_updated_share(
    *,
    release: str,
    basket_year: int,
    basket_link: str,
    basket_weight_percent: float,
    index_levels: dict[str, float],
    cpi_idx: ObsIndex,
) -> float | None:
    t_minus_1 = add_months(release, -1)
    all_levels = cpi_idx.levels_before(ALL_ITEMS_ID)
    if basket_link not in all_levels or t_minus_1 not in all_levels:
        return None
    if basket_link not in index_levels or t_minus_1 not in index_levels:
        return None
    return price_updated_share(
        basket_weight_percent=basket_weight_percent,
        index_link=index_levels[basket_link],
        index_tm1=index_levels[t_minus_1],
        all_items_link=all_levels[basket_link],
        all_items_tm1=all_levels[t_minus_1],
    )


def _parent_context(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    release: str,
    as_of: str,
) -> dict[str, Any]:
    cpi_idx = ObsIndex.build(cpi_snapshot, as_of, release)
    air_idx = AirfareObsIndex.build(airfare_snapshot, as_of, release)
    weight_pubs = cpi_idx.weight_publication_years()
    basket_year, basket_link, basket_status, blockers, assumptions = select_basket_vintage(
        release, as_of, weight_pubs
    )
    shares: dict[str, float | None] = {
        EX_ENERGY_ID: None,
        EX_FOOD_ENERGY_ID: None,
        AIRFARE_ID: None,
    }
    basket_weight_2025 = _basket_weight_percent(air_idx, 2025) if basket_year else None

    if basket_year and basket_link and basket_status != "blocked":
        for parent_id, weight_id in (
            (EX_ENERGY_ID, f"{EX_ENERGY_ID}__weight"),
            (EX_FOOD_ENERGY_ID, f"{EX_FOOD_ENERGY_ID}__weight"),
        ):
            w_pct = cpi_idx.level(weight_id, f"{basket_year}-01", input_for_forecast=False)
            idx_levels = cpi_idx.levels_before(parent_id)
            if w_pct is not None:
                shares[parent_id] = _series_price_updated_share(
                    release=release,
                    basket_year=basket_year,
                    basket_link=basket_link,
                    basket_weight_percent=w_pct,
                    index_levels=idx_levels,
                    cpi_idx=cpi_idx,
                )
        air_w = _basket_weight_percent(air_idx, basket_year)
        if air_w is not None:
            shares[AIRFARE_ID] = _series_price_updated_share(
                release=release,
                basket_year=basket_year,
                basket_link=basket_link,
                basket_weight_percent=air_w,
                index_levels=air_idx.levels_before(AIRFARE_ID),
                cpi_idx=cpi_idx,
            )

    ex_moms = compute_moms(cpi_idx.levels_before(EX_ENERGY_ID))
    exfe_moms = compute_moms(cpi_idx.levels_before(EX_FOOD_ENERGY_ID))
    air_moms = compute_moms(air_idx.levels_before(AIRFARE_ID))

    direct_ex, direct_method = forecast_model_a(ex_moms, release)
    direct_exfe, _ = forecast_model_a(exfe_moms, release)
    air_methods = _airfare_method_forecasts(air_moms, release)

    primary = air_methods[AIRFARE_SEASONAL_PRIMARY]["mom"]
    ridge_mom = air_methods["ridge_model_a"]["mom"]

    adjusted: dict[str, float | None] = {
        "adjusted_ex_food_energy_mom": None,
        "adjusted_direct_ex_energy_mom": None,
    }
    if (
        primary is not None
        and ridge_mom is not None
        and shares[EX_FOOD_ENERGY_ID] is not None
        and shares[AIRFARE_ID] is not None
    ):
        adjusted["adjusted_ex_food_energy_mom"] = replace_child_within_parent(
            direct_exfe,
            shares[EX_FOOD_ENERGY_ID],
            shares[AIRFARE_ID],
            ridge_mom,
            primary,
        )
    if (
        primary is not None
        and ridge_mom is not None
        and shares[EX_ENERGY_ID] is not None
        and shares[AIRFARE_ID] is not None
    ):
        adjusted["adjusted_direct_ex_energy_mom"] = replace_child_within_parent(
            direct_ex,
            shares[EX_ENERGY_ID],
            shares[AIRFARE_ID],
            ridge_mom,
            primary,
        )

    return {
        "cpi_idx": cpi_idx,
        "air_idx": air_idx,
        "basket_year": basket_year,
        "basket_link": basket_link,
        "basket_status": basket_status,
        "blockers": blockers,
        "assumptions": assumptions,
        "shares": shares,
        "basket_weight_2025": basket_weight_2025,
        "direct_ex_energy_mom": direct_ex,
        "direct_ex_energy_method": direct_method,
        "direct_ex_food_energy_mom": direct_exfe,
        "air_moms": air_moms,
        "air_methods": air_methods,
        "adjusted": adjusted,
    }


def airfare_shadow_month(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    release: str,
    as_of: str,
) -> dict[str, Any]:
    ctx = _parent_context(cpi_snapshot, airfare_snapshot, release, as_of)
    primary_info = ctx["air_methods"][AIRFARE_SEASONAL_PRIMARY]
    promotion_eligible = bool(primary_info.get("promotion_eligible"))
    blockers = list(ctx["blockers"])
    if ctx["air_idx"].get_obs(AIRFARE_ID, release) is not None:
        blockers.append("release_month_actual_present")

    provenance = {
        "index_vector_id": AIRFARE_INDEX_SPEC["vector_id"],
        "weight_vector_id": AIRFARE_WEIGHT_SPEC["vector_id"],
        "index_coordinate": AIRFARE_INDEX_SPEC["coordinate"],
        "weight_coordinate": AIRFARE_WEIGHT_SPEC["coordinate"],
        "source_records": airfare_snapshot.source_records,
        "basket_year": ctx["basket_year"],
        "basket_link": ctx["basket_link"],
        "basket_status": ctx["basket_status"],
        "vintage_note": (
            "Basket vintage from main CPI all-items weight publication timestamps via select_basket_vintage."
        ),
    }
    provenance["sha256"] = [rec["sha256"] for rec in airfare_snapshot.source_records if rec.get("sha256")]

    moms_out = {k: v.get("mom") for k, v in ctx["air_methods"].items()}
    return {
        "release": release,
        "as_of": as_of,
        "methods": ctx["air_methods"],
        "moms": moms_out,
        "airfare_model_a_baseline_mom": ctx["air_methods"]["ridge_model_a"]["mom"],
        "airfare_model_a_method": ctx["air_methods"]["ridge_model_a"].get("method"),
        "shares": ctx["shares"],
        "basket_weight_2025_percent": ctx["basket_weight_2025"],
        "direct_ex_energy_mom": ctx["direct_ex_energy_mom"],
        "direct_ex_food_energy_mom": ctx["direct_ex_food_energy_mom"],
        "adjusted_ex_food_energy_mom": ctx["adjusted"]["adjusted_ex_food_energy_mom"],
        "adjusted_direct_ex_energy_mom": ctx["adjusted"]["adjusted_direct_ex_energy_mom"],
        "provenance": provenance,
        "blockers": blockers,
        "assumptions": ctx["assumptions"],
        "promotion_eligible": promotion_eligible,
        "limitations": list(AIRFARE_LIMITATIONS),
    }


def _metrics_row(model: str, regime: str, forecasts: list[float], actuals: list[float]) -> dict[str, Any]:
    n = len(forecasts)
    if n == 0:
        return {"model": model, "regime": regime, "n": 0}
    err = np.array(forecasts) - np.array(actuals)
    def sgn(x: float) -> float:
        if x > 0:
            return 1.0
        if x < 0:
            return -1.0
        return 0.0

    direction = float(np.mean([sgn(f) == sgn(a) for f, a in zip(forecasts, actuals)]))
    return {
        "model": model,
        "regime": regime,
        "n": n,
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "bias": float(np.mean(err)),
        "direction": direction,
    }


def _regime_filter(regime: str, period: str) -> bool:
    if regime == "all":
        return True
    if regime == "from_2019":
        return period >= EVAL_PRIMARY_START
    if regime == "recent_2025_26":
        return period >= EVAL_RECENT_START
    if regime == "september":
        return period[5:7] == "09"
    return False


def _month_row(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    period: str,
    as_of: str,
) -> dict[str, Any] | None:
    cpi_idx = ObsIndex.build(cpi_snapshot, as_of, period)
    air_idx = AirfareObsIndex.build(airfare_snapshot, as_of, period)
    air_moms = compute_moms(air_idx.levels_before(AIRFARE_ID))
    if not air_moms:
        return None
    air_methods = _airfare_method_forecasts(air_moms, period)
    actual_air = _actual_mom(air_idx, AIRFARE_ID, period)

    ex_moms = compute_moms(cpi_idx.levels_before(EX_ENERGY_ID))
    if not ex_moms:
        return None
    direct_ex, _ = forecast_model_a(ex_moms, period)
    actual_ex = _actual_mom(cpi_idx, EX_ENERGY_ID, period)

    ctx = _parent_context(cpi_snapshot, airfare_snapshot, period, as_of)
    adjusted_direct = ctx["adjusted"]["adjusted_direct_ex_energy_mom"]

    comparators: dict[str, float | None] = {}
    for comp in AIRFARE_COMPARATORS:
        comp_mom = air_methods[comp]["mom"]
        ridge = air_methods["ridge_model_a"]["mom"]
        if (
            comp_mom is not None
            and ridge is not None
            and ctx["shares"][EX_ENERGY_ID] is not None
            and ctx["shares"][AIRFARE_ID] is not None
        ):
            comp_suffix = "season5" if comp == "season5_engine" else "ridge"
            comparators[f"airfare_on_direct_{comp_suffix}"] = replace_child_within_parent(
                direct_ex,
                ctx["shares"][EX_ENERGY_ID],
                ctx["shares"][AIRFARE_ID],
                ridge,
                comp_mom,
            )
        else:
            comp_suffix = "season5" if comp == "season5_engine" else "ridge"
            comparators[f"airfare_on_direct_{comp_suffix}"] = None

    return {
        "period": period,
        "actual_airfare_mom": actual_air,
        "air_methods": {k: v.get("mom") for k, v in air_methods.items()},
        "actual_ex_energy_mom": actual_ex,
        "direct_ex_energy_mom": direct_ex,
        "airfare_on_direct_ex_energy_mom": adjusted_direct,
        **comparators,
    }


def walk_forward_airfare(
    cpi_snapshot: Snapshot,
    airfare_snapshot: Snapshot,
    as_of: str,
    start: str = BACKTEST_START,
    end: str = BACKTEST_END,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    period = start
    while period <= end:
        row = _month_row(cpi_snapshot, airfare_snapshot, period, as_of)
        if row is not None:
            rows.append(row)
        period = add_months(period, 1)

    regimes = ("all", "from_2019", "recent_2025_26", "september")
    metrics: list[dict[str, Any]] = []
    air_models = (AIRFARE_SEASONAL_PRIMARY, "season5_engine", "ridge_model_a")
    ex_models = ("direct_ex_energy_mom", "airfare_on_direct_ex_energy_mom")

    for regime in regimes:
        sub = [r for r in rows if _regime_filter(regime, r["period"])]
        for model in air_models:
            pairs = [
                (r["air_methods"][model], r["actual_airfare_mom"])
                for r in sub
                if r["air_methods"].get(model) is not None and r["actual_airfare_mom"] is not None
            ]
            if pairs:
                metrics.append(
                    _metrics_row(model, regime, [p[0] for p in pairs], [p[1] for p in pairs])
                )
        for model in ex_models:
            key = model
            pairs = [
                (r[key], r["actual_ex_energy_mom"])
                for r in sub
                if r.get(key) is not None and r["actual_ex_energy_mom"] is not None
            ]
            if pairs:
                name = "direct" if model == "direct_ex_energy_mom" else "airfare_on_direct"
                metrics.append(_metrics_row(name, regime, [p[0] for p in pairs], [p[1] for p in pairs]))
        for comp_key in ("airfare_on_direct_season5", "airfare_on_direct_ridge"):
            pairs = [
                (r.get(comp_key), r["actual_ex_energy_mom"])
                for r in sub
                if r.get(comp_key) is not None and r["actual_ex_energy_mom"] is not None
            ]
            if pairs:
                metrics.append(
                    {
                        **_metrics_row(comp_key, regime, [p[0] for p in pairs], [p[1] for p in pairs]),
                        "comparator": True,
                    }
                )

    from19 = [r for r in rows if r["period"] >= EVAL_PRIMARY_START]
    direct_err: list[float] = []
    alt_err: list[float] = []
    for r in from19:
        if (
            r["direct_ex_energy_mom"] is None
            or r["airfare_on_direct_ex_energy_mom"] is None
            or r["actual_ex_energy_mom"] is None
        ):
            continue
        direct_err.append(r["direct_ex_energy_mom"] - r["actual_ex_energy_mom"])
        alt_err.append(r["airfare_on_direct_ex_energy_mom"] - r["actual_ex_energy_mom"])
    paired = paired_abs_error_summary(direct_err, alt_err) if direct_err else {"n": 0, "mae_delta": 0.0}

    def mae_for(model: str, regime: str) -> float | None:
        for m in metrics:
            if m.get("model") == model and m.get("regime") == regime and m.get("n", 0) > 0:
                return m.get("MAE")
        return None

    d_primary = mae_for("direct", "from_2019")
    d_recent = mae_for("direct", "recent_2025_26")
    a_primary = mae_for("airfare_on_direct", "from_2019")
    a_recent = mae_for("airfare_on_direct", "recent_2025_26")
    paired_delta = paired.get("mae_delta")
    promoted = False
    if (
        d_primary is not None
        and d_recent is not None
        and a_primary is not None
        and a_recent is not None
        and paired.get("n", 0) > 0
        and paired_delta is not None
    ):
        promoted = promotion_decision(
            direct_mae_primary=d_primary,
            direct_mae_recent=d_recent,
            alt_mae_primary=a_primary,
            alt_mae_recent=a_recent,
            paired_mae_delta_primary=float(paired_delta),
        )

    return {
        "rows": rows,
        "metrics": metrics,
        "paired_abs_error_from_2019": paired,
        "airfare_promoted": promoted,
        "limitations": list(AIRFARE_LIMITATIONS),
        "as_of": as_of,
        "start": start,
        "end": end,
    }


__all__ = [
    "airfare_shadow_month",
    "walk_forward_airfare",
    "load_airfare_snapshot",
]
