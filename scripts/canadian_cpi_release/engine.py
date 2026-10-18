"""Canadian CPI B2 nowcast engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.canadian_cpi_release import MODEL_VERSION, SCHEMA_VERSION
from scripts.canadian_cpi_release.aggregate import (
    ComponentForecast,
    build_contribution_leaves,
    headline_from_components,
    weighted_baseline_headline,
)
from scripts.canadian_cpi_release.contract import (
    BRIDGE_CHILDREN,
    MAJOR_IDS,
    SERIES,
    SERIES_BY_ID,
    UNAVAILABLE_SA,
    Snapshot,
    NowcastResult,
    Observation,
    add_months,
    month_end,
    parse_as_of,
    published_on_or_before,
)
from scripts.canadian_cpi_release.core_measures import build_core_block
from scripts.canadian_cpi_release.model import (
    baseline_carry_mean3_season5,
    compute_moms,
    forecast_bridge,
    forecast_model_a,
)
from scripts.canadian_cpi_release.uncertainty import uncertainty_from_errors
from scripts.canadian_cpi_release.weights import (
    ALL_ITEMS_ID,
    WeightResult,
    compute_shares,
    eligible_basket_years,
    select_basket_vintage,
)
GASOLINE_ID = "cpi_nsa_gasoline"
FUEL_OIL_ID = "cpi_nsa_fuel_oil"
REPLACEMENT_ID = "cpi_nsa_replacement_cost"

BRIDGE_EXTRA: dict[str, tuple[str, str]] = {
    "nrcan_gasoline": ("nrcan_gasoline", "pump"),
    "nrcan_furnace_oil": ("nrcan_furnace_oil", "furnace"),
    "nhpi_lag": ("nhpi_house_only", "nhpi"),
}

MANDATORY_INDEX_IDS: tuple[str, ...] = tuple(
    s.canonical_id for s in SERIES if s.mandatory
) + tuple(
    f"{s.canonical_id}__weight"
    for s in SERIES
    if s.weight_vector_id is not None and s.role in ("headline", "major", "bridge_child")
)

SPECIAL_AGG_IDS = (
    "cpi_nsa_ex_energy",
    "cpi_nsa_ex_food_energy",
    "cpi_nsa_ex_gasoline",
)

SA_PAIRS = (
    ("cpi_nsa_all_items", "cpi_sa_all_items"),
    ("cpi_nsa_ex_food_energy", "cpi_sa_ex_food_energy"),
)

BACKTEST_LIMITATIONS = [
    "NSA CPI is mostly unrevised but SA, NHPI, and basket weights can revise.",
    "NRCan historical availability is assumed at month-end rather than proven by archived timestamps.",
    "This is not a full real-time vintage backtest.",
    "No consensus panel is scored.",
]

NRCAN_ASSUMPTION = (
    "NRCan fuel observations without published_at are treated as eligible when "
    "reference month <= forecast month and month-end(period) <= as_of civil date."
)


@dataclass
class ObsIndex:
    snapshot: Snapshot
    as_of: str
    release: str
    _raw: dict[tuple[str, str], Observation]

    @classmethod
    def build(cls, snapshot: Snapshot, as_of: str, release: str) -> ObsIndex:
        raw: dict[tuple[str, str], Observation] = {}
        for obs in snapshot.observations:
            key = (obs.canonical_id, obs.period)
            if key not in raw:
                raw[key] = obs
        return cls(snapshot=snapshot, as_of=as_of, release=release, _raw=raw)

    def _is_nrcan(self, canonical_id: str) -> bool:
        spec = SERIES_BY_ID.get(canonical_id)
        return spec is not None and spec.source == "nrcan_html"

    def eligible(self, obs: Observation) -> bool:
        if self._is_nrcan(obs.canonical_id):
            as_of_date = parse_as_of(self.as_of).date()
            return obs.period <= self.release and month_end(obs.period) <= as_of_date
        return published_on_or_before(obs.published_at, self.as_of)

    def get_obs(self, canonical_id: str, period: str) -> Observation | None:
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

    def levels_before(
        self, canonical_id: str, *, include_release_month: bool = False
    ) -> dict[str, float]:
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

    def weight_publication_years(self) -> dict[int, str | None]:
        years = eligible_basket_years(self.release)
        pubs: dict[int, str | None] = {}
        w_id = f"{ALL_ITEMS_ID}__weight"
        for y in years:
            period = f"{y}-01"
            obs = self._raw.get((w_id, period))
            if obs is None:
                pubs[y] = None
            else:
                pubs[y] = obs.published_at
        return pubs


def _check_mandatory_levels(
    idx: ObsIndex, release: str, blockers: list[str]
) -> bool:
    t1 = add_months(release, -1)
    need = [ALL_ITEMS_ID, *MAJOR_IDS]
    need.extend(child for child, _, _ in BRIDGE_CHILDREN)
    ok = True
    for cid in need:
        if idx.level(cid, t1) is None:
            blockers.append(f"missing_{cid}_t_minus_1")
            ok = False
    return ok


def _check_mandatory_feeds(idx: ObsIndex, release: str, blockers: list[str]) -> None:
    """NRCan/NHPI required for bridge months."""
    for child_id, _, kind in BRIDGE_CHILDREN:
        feed_id, _ = BRIDGE_EXTRA[kind]
        if kind == "nhpi_lag":
            lag_period = add_months(release, -1)
            levels = idx.levels_before(feed_id)
            moms = compute_moms(levels)
            if lag_period not in moms and idx.level(feed_id, lag_period) is None:
                blockers.append(f"mandatory_missing_{feed_id}_for_{release}")
        else:
            lv = idx.level(feed_id, release, input_for_forecast=False)
            t1 = add_months(release, -1)
            if lv is None or idx.level(feed_id, t1) is None:
                blockers.append(f"mandatory_missing_{feed_id}_for_{release}")


def _extra_series_for_bridge(
    idx: ObsIndex,
    child_id: str,
    kind: str,
    moms: dict[str, float],
    target: str,
) -> tuple[dict[str, dict[str, float | None]], list[str], str | None]:
    feed_id, col_name = BRIDGE_EXTRA[kind]
    extra_names = [col_name]
    feed_levels = dict(idx.levels_before(feed_id))
    if kind != "nhpi_lag":
        v_release = idx.level(feed_id, target, input_for_forecast=False)
        if v_release is not None:
            feed_levels[target] = v_release
    feed_moms = compute_moms(feed_levels)
    extra_by_period: dict[str, dict[str, float | None]] = {}

    if kind == "nhpi_lag":
        for p in moms:
            if p >= target:
                continue
            lag_p = add_months(p, -1)
            extra_by_period.setdefault(p, {})[col_name] = feed_moms.get(lag_p)
        lag_t = add_months(target, -1)
        if lag_t not in feed_moms:
            return extra_by_period, extra_names, f"mandatory_missing_nhpi_mom_{lag_t}"
        extra_by_period.setdefault(target, {})[col_name] = feed_moms[lag_t]
        return extra_by_period, extra_names, None

    for p in list(moms.keys()) + [target]:
        if p > target:
            continue
        if p == target and p >= idx.release:
            val = feed_moms.get(p)
        else:
            val = feed_moms.get(p)
        extra_by_period.setdefault(p, {})[col_name] = val
    if target not in feed_moms:
        return extra_by_period, extra_names, f"mandatory_missing_{feed_id}_mom_{target}"
    return extra_by_period, extra_names, None


def _forecast_component(
    idx: ObsIndex,
    canonical_id: str,
    release: str,
    *,
    bridge_kind: str | None = None,
) -> tuple[ComponentForecast, list[str]]:
    blockers: list[str] = []
    levels = idx.levels_before(canonical_id)
    moms = compute_moms(levels)
    mom_a, method_a = forecast_model_a(moms, release)
    mom_used = mom_a
    method = method_a
    bridge_applied = False

    if bridge_kind:
        extra_by, names, err = _extra_series_for_bridge(
            idx, canonical_id, bridge_kind, moms, release
        )
        if err:
            blockers.append(err)
        else:
            bridge_val, bridge_method = forecast_bridge(
                moms, release, extra_by, names
            )
            if bridge_val is not None:
                mom_used = bridge_val
                bridge_applied = True
                if bridge_kind == "nhpi_lag":
                    method = "lagged_official_bridge"
                else:
                    method = "observed_bridge"
            else:
                method = "fallback_baseline"

    delta_pp = 0.0
    cf = ComponentForecast(
        canonical_id=canonical_id,
        mom_a=mom_a,
        mom_used=mom_used,
        method=method,
        bridge_applied=bridge_applied,
        bridge_delta_pp=delta_pp,
    )
    return cf, blockers


def _seasonal_gap_bridge(
    idx: ObsIndex,
    release: str,
    nsa_id: str,
    sa_id: str,
) -> tuple[float | None, str]:
    nsa_levels = idx.levels_before(nsa_id)
    sa_levels = idx.levels_before(sa_id)
    nsa_moms = compute_moms(nsa_levels)
    sa_moms = compute_moms(sa_levels)
    gaps: dict[str, float] = {}
    for p in nsa_moms:
        if p in sa_moms:
            gaps[p] = sa_moms[p] - nsa_moms[p]
    tgt_m = int(release[5:7])
    prior = sorted(p for p in gaps if p < release and int(p[5:7]) == tgt_m)
    if not prior:
        return None, "unavailable"
    bridge = float(np.median([gaps[p] for p in prior[-5:]]))
    return bridge, "seasonal_median_bridge"


def _special_aggregate(idx: ObsIndex, release: str, agg_id: str) -> dict[str, Any]:
    levels = idx.levels_before(agg_id)
    moms = compute_moms(levels)
    mom, method = forecast_model_a(moms, release)
    sa_mom = None
    sa_method = "unavailable_no_official_sa" if agg_id in UNAVAILABLE_SA else None
    t1 = add_months(release, -1)
    t12 = add_months(release, -12)
    prev = idx.level(agg_id, t1)
    base = idx.level(agg_id, t12)
    yoy = None
    if prev is not None and base is not None and base > 0:
        idx_forecast = prev * (1.0 + mom / 100.0)
        yoy = 100.0 * (idx_forecast / base - 1.0)
    if agg_id == "cpi_nsa_ex_food_energy":
        bridge, sa_method = _seasonal_gap_bridge(
            idx, release, "cpi_nsa_ex_food_energy", "cpi_sa_ex_food_energy"
        )
        if bridge is not None:
            sa_mom = mom + bridge
    elif agg_id == "cpi_nsa_all_items":
        bridge, sa_method = _seasonal_gap_bridge(idx, release, ALL_ITEMS_ID, "cpi_sa_all_items")
        if bridge is not None:
            sa_mom = mom + bridge
    return {
        "canonical_id": agg_id,
        "nsa_mom": mom,
        "nsa_method": method,
        "yoy": yoy,
        "sa_mom": sa_mom,
        "sa_method": sa_method,
    }


def _collect_level_series(idx: ObsIndex) -> dict[str, dict[str, float]]:
    ids = set(MANDATORY_INDEX_IDS)
    ids.update(MAJOR_IDS)
    ids.update(SPECIAL_AGG_IDS)
    ids.update(("core_trim_index", "core_median_index"))
    ids.update(f"{i}__weight" for i in MAJOR_IDS)
    ids.update(
        f"{c}__weight" for c, _, _ in BRIDGE_CHILDREN
    )
    ids.add(f"{ALL_ITEMS_ID}__weight")
    for cid in (
        "nrcan_gasoline",
        "nrcan_furnace_oil",
        "nhpi_house_only",
        "cpi_sa_all_items",
        "cpi_sa_ex_food_energy",
    ):
        ids.add(cid)
    out: dict[str, dict[str, float]] = {}
    for cid in ids:
        if cid.endswith("__weight"):
            series: dict[str, float] = {}
            for (c, period), obs in idx._raw.items():
                if c != cid or not idx.eligible(obs):
                    continue
                series[period] = obs.value
            out[cid] = series
        else:
            out[cid] = idx.levels_before(cid)
    return out


def _month_forecast(
    snapshot: Snapshot,
    release: str,
    as_of: str,
    *,
    for_backtest: bool = False,
) -> tuple[NowcastResult | None, str | None]:
    """Internal single-month forecast. Returns None if month should be skipped in backtest."""
    idx = ObsIndex.build(snapshot, as_of, release)
    blockers: list[str] = []
    assumptions: list[str] = [NRCAN_ASSUMPTION]

    if not _check_mandatory_levels(idx, release, blockers):
        if for_backtest:
            return None, "skip"
        res = NowcastResult(release=release, as_of=as_of, status="blocked", blockers=blockers)
        return res, None

    _check_mandatory_feeds(idx, release, blockers)
    if blockers and not for_backtest:
        res = NowcastResult(release=release, as_of=as_of, status="blocked", blockers=blockers)
        return res, None

    weight_pubs = idx.weight_publication_years()
    basket_year, basket_link, basket_status, b_block, b_assump = select_basket_vintage(
        release, as_of, weight_pubs
    )
    blockers.extend(b_block)
    assumptions.extend(b_assump)
    if basket_status == "blocked" or not basket_year:
        if for_backtest:
            return None, "skip"
        return (
            NowcastResult(
                release=release,
                as_of=as_of,
                status="blocked",
                blockers=blockers,
                assumptions=assumptions,
            ),
            None,
        )

    level_series = _collect_level_series(idx)
    w_result: WeightResult = compute_shares(
        release=release,
        basket_year=basket_year,
        basket_link=basket_link,
        levels=level_series,
    )
    if w_result.shares is None:
        blockers.extend(w_result.blockers)
        if for_backtest:
            return None, "skip"
        return (
            NowcastResult(
                release=release,
                as_of=as_of,
                status="blocked",
                blockers=blockers,
                assumptions=assumptions,
                basket_year=basket_year,
                basket_link=basket_link,
                basket_status=basket_status,
            ),
            None,
        )

    shares = w_result.shares
    components: dict[str, ComponentForecast] = {}
    comp_blockers: list[str] = []

    for mid in MAJOR_IDS:
        cf, bl = _forecast_component(idx, mid, release)
        components[mid] = cf
        comp_blockers.extend(bl)

    for child_id, _, kind in BRIDGE_CHILDREN:
        cf, bl = _forecast_component(idx, child_id, release, bridge_kind=kind)
        components[child_id] = cf
        comp_blockers.extend(bl)

    if comp_blockers and not for_backtest:
        blockers.extend(comp_blockers)
        return (
            NowcastResult(
                release=release,
                as_of=as_of,
                status="blocked",
                blockers=blockers,
                assumptions=assumptions,
            ),
            None,
        )

    headline_a, headline_b2, _ = headline_from_components(shares, components)

    major_moms_a = {m: components[m].mom_a for m in MAJOR_IDS}
    carry_moms: dict[str, float] = {}
    mean3_moms: dict[str, float] = {}
    season5_moms: dict[str, float] = {}
    for m in MAJOR_IDS:
        moms = compute_moms(idx.levels_before(m))
        c, m3, s5 = baseline_carry_mean3_season5(moms, release)
        if c is not None:
            carry_moms[m] = c
        if m3 is not None:
            mean3_moms[m] = m3
        if s5 is not None:
            season5_moms[m] = s5

    baselines = {
        "carry": weighted_baseline_headline(shares, carry_moms),
        "mean3": weighted_baseline_headline(shares, mean3_moms),
        "season5": weighted_baseline_headline(shares, season5_moms),
        "A": headline_a,
        "B2": headline_b2,
    }

    leaves, leaf_blockers = build_contribution_leaves(shares, components, headline_b2)
    if leaf_blockers:
        blockers.extend(leaf_blockers)
        if not for_backtest:
            return (
                NowcastResult(
                    release=release,
                    as_of=as_of,
                    status="blocked",
                    blockers=blockers,
                    assumptions=assumptions,
                ),
                None,
            )

    t1 = add_months(release, -1)
    t12 = add_months(release, -12)
    previous_index = idx.level(ALL_ITEMS_ID, t1)
    base_index = idx.level(ALL_ITEMS_ID, t12)
    headline_index = None
    headline_yoy = None
    yoy_blockers: list[str] = []
    if previous_index is not None:
        headline_index = previous_index * (1.0 + headline_b2 / 100.0)
    if base_index is None:
        yoy_blockers.append("missing_all_items_t_minus_12")
    elif headline_index is not None and base_index > 0:
        headline_yoy = 100.0 * (headline_index / base_index - 1.0)

    fatal = list(blockers)
    sa_bridge, sa_method = _seasonal_gap_bridge(idx, release, ALL_ITEMS_ID, "cpi_sa_all_items")
    headline_sa_mom = None
    if sa_bridge is not None and not fatal:
        headline_sa_mom = headline_b2 + sa_bridge

    special = {aid: _special_aggregate(idx, release, aid) for aid in SPECIAL_AGG_IDS}
    core = build_core_block(level_series, release)

    component_rows = []
    for cid, cf in components.items():
        component_rows.append(
            {
                "canonical_id": cid,
                "mom_a": cf.mom_a,
                "mom_forecast": cf.mom_used,
                "method": cf.method,
                "bridge_applied": cf.bridge_applied,
            }
        )

    all_blockers = fatal + yoy_blockers
    status = "blocked" if fatal else "ok"

    result = NowcastResult(
        schema_version=SCHEMA_VERSION,
        model_version=MODEL_VERSION,
        release=release,
        as_of=as_of,
        status=status,
        headline_nsa_mom=headline_b2 if not fatal else None,
        headline_index=headline_index if not fatal else None,
        headline_yoy=headline_yoy if not fatal and not yoy_blockers else None,
        headline_sa_mom=headline_sa_mom if not fatal else None,
        previous_index=previous_index,
        base_index=base_index,
        basket_year=basket_year,
        basket_link=basket_link,
        basket_status=basket_status,
        components=component_rows,
        contributions=leaves,
        special_aggregates=special,
        core=core,
        baselines=baselines,
        blockers=all_blockers,
        assumptions=assumptions,
    )
    return result, None


def forecast_release(snapshot: Snapshot, release: str, as_of: str) -> NowcastResult:
    """Pre-release nowcast for CPI reference month `release` (YYYY-MM)."""
    result, _ = _month_forecast(snapshot, release, as_of, for_backtest=False)
    if result is None:
        return NowcastResult(release=release, as_of=as_of, status="blocked", blockers=["internal_error"])
    errors = _b2_backtest_errors(snapshot, as_of, release)
    result.uncertainty = uncertainty_from_errors(errors, result.headline_nsa_mom)
    return result


def _actual_headline_mom(idx: ObsIndex, period: str) -> float | None:
    t1 = add_months(period, -1)
    lv = idx.level(ALL_ITEMS_ID, period, input_for_forecast=False, allow_actual_month=True)
    l1 = idx.level(ALL_ITEMS_ID, t1)
    if lv is None or l1 is None or l1 == 0:
        return None
    obs = idx.get_obs(ALL_ITEMS_ID, period)
    if obs is None:
        return None
    return 100.0 * (lv / l1 - 1.0)


def _gas_shock(idx: ObsIndex, period: str) -> bool:
    t1 = add_months(period, -1)
    g0 = idx.level(GASOLINE_ID, period, input_for_forecast=False, allow_actual_month=True)
    g1 = idx.level(GASOLINE_ID, t1)
    if g0 is None or g1 is None or g1 == 0:
        return False
    mom = abs(100.0 * (g0 / g1 - 1.0))
    return mom >= 5.0


def _b2_backtest_errors(snapshot: Snapshot, as_of: str, before: str) -> list[float]:
    errors: list[float] = []
    start = "2019-01"
    period = start
    while period < before:
        idx = ObsIndex.build(snapshot, as_of, period)
        fc, skip = _month_forecast(snapshot, period, as_of, for_backtest=True)
        if skip or fc is None or fc.headline_nsa_mom is None:
            period = add_months(period, 1)
            continue
        if period < "2019-01":
            period = add_months(period, 1)
            continue
        actual = _actual_headline_mom(idx, period)
        if actual is None:
            period = add_months(period, 1)
            continue
        errors.append(actual - fc.headline_nsa_mom)
        period = add_months(period, 1)
    return errors


def _sign_match(forecast: float, actual: float) -> bool:
    def sgn(x: float) -> float:
        if x > 0:
            return 1.0
        if x < 0:
            return -1.0
        return 0.0

    return sgn(forecast) == sgn(actual)


def _metrics_row(model: str, regime: str, forecasts: list[float], actuals: list[float]) -> dict[str, Any]:
    n = len(forecasts)
    if n == 0:
        return {"model": model, "regime": regime, "n": 0}
    err = np.array(forecasts) - np.array(actuals)
    return {
        "model": model,
        "regime": regime,
        "n": n,
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "bias": float(np.mean(err)),
        "direction": float(np.mean([_sign_match(f, a) for f, a in zip(forecasts, actuals)])),
    }


def backtest_headline(
    snapshot: Snapshot,
    as_of: str,
    start: str = "2017-01",
    end: str = "2026-08",
) -> dict:
    """Pseudo-OOS latest-vintage headline backtest."""
    rows: list[dict[str, Any]] = []
    period = start
    while period <= end:
        idx = ObsIndex.build(snapshot, as_of, period)
        fc, skip = _month_forecast(snapshot, period, as_of, for_backtest=True)
        actual = _actual_headline_mom(idx, period)
        gas_flag = _gas_shock(idx, period)

        if fc is not None and fc.baselines:
            for model in ("A", "B2", "season5", "carry", "mean3"):
                forecast_val = fc.baselines.get(model)
                if forecast_val is None and model in ("A", "B2"):
                    forecast_val = fc.headline_nsa_mom if model == "B2" else None
                rows.append(
                    {
                        "period": period,
                        "model": model,
                        "forecast": forecast_val,
                        "actual": actual,
                        "gas_shock": gas_flag,
                    }
                )
        period = add_months(period, 1)

    metrics: list[dict[str, Any]] = []
    models = ("A", "B2", "season5", "carry", "mean3")
    for model in models:
        sub = [r for r in rows if r["model"] == model and r["actual"] is not None]
        if not sub:
            continue
        all_f = [r["forecast"] for r in sub if r["forecast"] is not None]
        all_a = [r["actual"] for r in sub if r["forecast"] is not None]
        if all_f:
            metrics.append(_metrics_row(model, "all", all_f, all_a))
        from19 = [
            r
            for r in sub
            if r["period"] >= "2019-01" and r["forecast"] is not None
        ]
        if from19:
            metrics.append(
                _metrics_row(
                    model,
                    "from_2019",
                    [r["forecast"] for r in from19],
                    [r["actual"] for r in from19],
                )
            )
        gas = [
            r
            for r in sub
            if r.get("gas_shock") and r["period"] >= "2025-01" and r["forecast"] is not None
        ]
        if gas:
            metrics.append(
                _metrics_row(
                    model,
                    "gas_shocks_2025_26",
                    [r["forecast"] for r in gas],
                    [r["actual"] for r in gas],
                )
            )

    return {
        "rows": rows,
        "metrics": metrics,
        "limitations": list(BACKTEST_LIMITATIONS),
    }


def _ridge_seasonal_penalty_smoke() -> None:
    """Confirm ridge runs and seasonal block is lightly penalized only."""
    from scripts.canadian_cpi_release.model import ridge_mom_forecast

    moms = {f"2020-{m:02d}": 0.1 * m for m in range(1, 13)}
    moms.update({f"2021-{m:02d}": 0.15 * m for m in range(1, 13)})
    moms.update({f"2022-{m:02d}": 0.12 * m for m in range(1, 13)})
    moms.update({f"2023-{m:02d}": 0.11 * m for m in range(1, 13)})
    moms.update({f"2024-{m:02d}": 0.13 * m for m in range(1, 13)})
    moms.update({f"2025-{m:02d}": 0.14 * m for m in range(1, 13)})
    target = "2025-07"
    val = ridge_mom_forecast(moms, target, min_obs=24)
    assert val is not None


if __name__ == "__main__":
    _ridge_seasonal_penalty_smoke()
