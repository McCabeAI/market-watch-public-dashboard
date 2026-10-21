"""Walk-forward scores for the Australian CPI nowcast.

Pseudo-OOS uses the latest vintage and periods strictly before the target.
That lets later seasonal-factor revisions into the history, so every metric
is labeled ``pseudo_oos_latest_vintage``. The true-vintage section is separate
and is not a skill estimate. The two are never averaged together.
"""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from statistics import fmean
from typing import Any

from scripts.au_cpi_release import BACKTEST_SCHEMA
from scripts.au_cpi_release.contract import Snapshot, previous_month, previous_quarter
from scripts.au_cpi_release.models import (
    CANDIDATE_MODELS,
    INDEX_OF,
    PROXY_BRIDGE_MODEL,
    REGIME_OF,
    VINTAGE_API,
    VINTAGE_AUGUST_RELEASE,
    VINTAGE_JULY,
    YOY_OF,
    ModelContext,
    actual_change,
    add_months,
    add_quarters,
    build_frame,
    chronologically_on_or_after,
    forecast_change_models,
    mean_last,
    percent_change,
    proxy_bridge,
    quarterly_bridge_gap,
    round_1dp,
    yoy_from_change,
)
from scripts.au_cpi_release.uncertainty import PSEUDO_OOS_LABEL

TRUE_VINTAGE_LABEL = "true_vintage"
QUARTERLY_TARGET = "trimmed_mean_quarterly_legacy_qoq"


def quarter_subperiod(period: str) -> str:
    year = int(period[:4])
    if year < 2020:
        return "pre_2020"
    if year <= 2021:
        return "2020_2021"
    if year <= 2023:
        return "2022_2023"
    return "2024_plus"


def _metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mae": None,
            "bias": None,
            "rmse": None,
            "n_1dp": 0,
            "mae_1dp": None,
            "bias_1dp": None,
            "rmse_1dp": None,
        }
    errors = [float(row["error"]) for row in rows]
    block = {
        "n": len(errors),
        "mae": fmean(abs(error) for error in errors),
        "bias": fmean(errors),
        "rmse": sqrt(fmean(error * error for error in errors)),
    }
    rounded = [row for row in rows if row.get("error_1dp") is not None]
    if not rounded:
        block.update({"n_1dp": 0, "mae_1dp": None, "bias_1dp": None, "rmse_1dp": None})
        return block
    errors_1dp = [float(row["error_1dp"]) for row in rounded]
    block.update(
        {
            "n_1dp": len(errors_1dp),
            "mae_1dp": fmean(abs(error) for error in errors_1dp),
            "bias_1dp": fmean(errors_1dp),
            "rmse_1dp": sqrt(fmean(error * error for error in errors_1dp)),
        }
    )
    return block


def _score_change(
    *,
    target: str,
    model: str,
    period: str,
    forecast: float,
    actual_unrounded: float,
    actual_1dp: float | None,
    eligible: bool,
) -> dict[str, Any]:
    forecast_1dp = round_1dp(forecast)
    published_1dp = actual_1dp if actual_1dp is not None else round_1dp(actual_unrounded)
    return {
        "label": PSEUDO_OOS_LABEL,
        "target": target,
        "model": model,
        "period": period,
        "regime": REGIME_OF[target],
        "eligible": eligible,
        "forecast": forecast,
        "actual": actual_unrounded,
        "error": forecast - actual_unrounded,
        "forecast_1dp": forecast_1dp,
        "actual_1dp": published_1dp,
        "error_1dp": forecast_1dp - published_1dp,
    }


def _score_yoy(
    frame: Any,
    *,
    change_target: str,
    model: str,
    period: str,
    forecast_change: float,
    eligible: bool,
) -> dict[str, Any] | None:
    index_id = INDEX_OF[change_target]
    if "-Q" in period:
        previous = previous_quarter(period)
        lag = add_quarters(period, -4)
    else:
        previous = previous_month(period)
        lag = add_months(period, -12)
    index_prev = frame.get(index_id, previous)
    index_lag = frame.get(index_id, lag)
    index_now = frame.get(index_id, period)
    if index_prev is None or index_lag is None or index_now is None:
        return None
    forecast = yoy_from_change(index_prev, index_lag, forecast_change)
    actual = percent_change(index_now, index_lag)
    if actual is None:
        return None
    yoy_target = YOY_OF[change_target]
    published = frame.get(yoy_target, period)
    return _score_change(
        target=yoy_target,
        model=model,
        period=period,
        forecast=forecast,
        actual_unrounded=actual,
        actual_1dp=None if published is None else round_1dp(published),
        eligible=eligible,
    )


def walk_forward(frame: Any, ctx: ModelContext) -> list[dict[str, Any]]:
    """Score every computable model on every period the frame can actualise."""
    rows: list[dict[str, Any]] = []
    for period in frame.periods("headline_nsa_index"):
        if "-Q" in period:
            continue
        forecasts = forecast_change_models(frame, period, ctx)
        for target, values in forecasts.items():
            actual = actual_change(frame, target, period)
            if actual["unrounded"] is None:
                continue
            for model in CANDIDATE_MODELS[target]:
                forecast = values.get(model)
                if forecast is None:
                    continue
                rows.append(
                    _score_change(
                        target=target,
                        model=model,
                        period=period,
                        forecast=forecast,
                        actual_unrounded=float(actual["unrounded"]),
                        actual_1dp=actual["published_1dp"],
                        eligible=True,
                    )
                )
                yoy = _score_yoy(
                    frame,
                    change_target=target,
                    model=model,
                    period=period,
                    forecast_change=forecast,
                    eligible=True,
                )
                if yoy is not None:
                    rows.append(yoy)
    for period in frame.periods("trimmed_mean_quarterly_legacy_index"):
        values = forecast_change_models(frame, period, ctx)[QUARTERLY_TARGET]
        actual = actual_change(frame, QUARTERLY_TARGET, period)
        if actual["unrounded"] is None:
            continue
        for model in CANDIDATE_MODELS[QUARTERLY_TARGET]:
            forecast = values.get(model)
            if forecast is None:
                continue
            rows.append(
                _score_change(
                    target=QUARTERLY_TARGET,
                    model=model,
                    period=period,
                    forecast=forecast,
                    actual_unrounded=float(actual["unrounded"]),
                    actual_1dp=actual["published_1dp"],
                    eligible=True,
                )
            )
            yoy = _score_yoy(
                frame,
                change_target=QUARTERLY_TARGET,
                model=model,
                period=period,
                forecast_change=forecast,
                eligible=True,
            )
            if yoy is not None:
                rows.append(yoy)
        monthly_forecast = mean_last(frame, "trimmed_mean_monthly_sa_index", _quarter_last_month(period), 1, previous_month)
        bridge = proxy_bridge(frame, period, monthly_forecast)
        if bridge is None:
            continue
        rows.append(
            _score_change(
                target=QUARTERLY_TARGET,
                model=PROXY_BRIDGE_MODEL,
                period=period,
                forecast=bridge,
                actual_unrounded=float(actual["unrounded"]),
                actual_1dp=actual["published_1dp"],
                eligible=False,
            )
        )
    return rows


def _quarter_last_month(period: str) -> str:
    year_text, quarter_text = period.split("-Q")
    return f"{int(year_text):04d}-{int(quarter_text) * 3:02d}"


def metrics_from_errors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, bool], list[dict[str, Any]]] = defaultdict(list)
    seeded: set[tuple[str, str, str]] = set()
    for target, models in CANDIDATE_MODELS.items():
        for model in models:
            seeded.add((target, model, REGIME_OF[target]))
            seeded.add((YOY_OF[target], model, REGIME_OF[target]))
    for target, model, regime in seeded:
        groups[(target, model, regime, "full", True)] = []
    for row in rows:
        key = (str(row["target"]), str(row["model"]), str(row["regime"]), "full", bool(row["eligible"]))
        groups[key].append(row)
        if row["regime"] == "quarterly_legacy_tm" and "-Q" in str(row["period"]):
            bucket = quarter_subperiod(str(row["period"]))
            groups[(str(row["target"]), str(row["model"]), str(row["regime"]), bucket, bool(row["eligible"]))].append(row)
    metrics = []
    for (target, model, regime, sub_period, eligible), grouped in sorted(groups.items()):
        block = _metric_block(grouped)
        metrics.append(
            {
                "label": PSEUDO_OOS_LABEL,
                "target": target,
                "model": model,
                "regime": regime,
                "sub_period": sub_period,
                "eligible": eligible,
                **block,
            }
        )
    return metrics


def leakage_guard(snapshot: Snapshot, ctx: ModelContext, *, period: str = "2026-08") -> dict[str, Any]:
    """Forecasts at ``period`` must not change when later periods are deleted."""
    full = build_frame(snapshot.observations)
    remaining = [obs for obs in snapshot.observations if not chronologically_on_or_after(obs.period, period)]
    cut = build_frame(remaining)
    left = forecast_change_models(full, period, ctx)
    right = forecast_change_models(cut, period, ctx)
    return {
        "period": period,
        "rule": "delete observations whose period is chronologically on or after the target, then recompute",
        "pass": left == right,
        "n_observations_removed": len(snapshot.observations) - len(remaining),
    }


def _true_vintage_actuals(snapshot: Snapshot) -> dict[str, dict[str, Any]]:
    """August 2026 comparison values. Headline from the 640101 mirror; else latest API."""
    august = build_frame(snapshot.observations, vintage=VINTAGE_AUGUST_RELEASE)
    api = build_frame(snapshot.observations, vintage=VINTAGE_API)
    specs = {
        "headline_nsa_mom": (august, "wayback_aug-2026_640101 mirror of the August 2026 first-release workbook"),
        "headline_sa_mom": (
            api,
            "abs_api latest vintage, not a first-release workbook (August 2026 Table 6 was not in the snapshot). "
            "The percent change uses latest-vintage index levels, so the July base may already be revised.",
        ),
        "trimmed_mean_monthly_sa_mom": (
            api,
            "abs_api latest vintage, not a first-release workbook (August 2026 Table 6 was not in the snapshot). "
            "The percent change uses latest-vintage index levels, so the July base may already be revised.",
        ),
        "weighted_median_monthly_sa_mom": (
            api,
            "abs_api latest vintage, not a first-release workbook (August 2026 Table 6 was not in the snapshot). "
            "The percent change uses latest-vintage index levels, so the July base may already be revised.",
        ),
    }
    out: dict[str, dict[str, Any]] = {}
    for target, (frame, source) in specs.items():
        actual = actual_change(frame, target, "2026-08")
        out[target] = {"frame": frame, "source": source, "actual": actual}
    return out


def true_vintage_section(snapshot: Snapshot, ctx: ModelContext) -> dict[str, Any]:
    """Forecast 2026-08 from the in-repo July 2026 workbook vintage. n = 1."""
    july = build_frame(snapshot.observations, vintage=VINTAGE_JULY)
    forecasts = forecast_change_models(july, "2026-08", ctx)
    actuals = _true_vintage_actuals(snapshot)
    rows: list[dict[str, Any]] = []
    for target, values in forecasts.items():
        if target == QUARTERLY_TARGET:
            continue
        actual_info = actuals.get(target)
        if actual_info is None or actual_info["actual"]["unrounded"] is None:
            for model in CANDIDATE_MODELS[target]:
                rows.append(
                    {
                        "label": TRUE_VINTAGE_LABEL,
                        "target": target,
                        "model": model,
                        "period": "2026-08",
                        "status": "blocked",
                        "reason": "august_2026_actual_not_in_snapshot",
                        "n": 0,
                        "not_a_skill_estimate": True,
                    }
                )
            continue
        frame = actual_info["frame"]
        for model in CANDIDATE_MODELS[target]:
            forecast = values.get(model)
            if forecast is None:
                reason = (
                    "july_2026_workbook_observations contain Table 6 analytical series only; "
                    "class indexes and contribution weights were not parsed, so this model cannot run"
                    if model.startswith("component")
                    else "not_computable_from_july_2026_vintage"
                )
                rows.append(
                    {
                        "label": TRUE_VINTAGE_LABEL,
                        "target": target,
                        "model": model,
                        "period": "2026-08",
                        "status": "blocked",
                        "reason": reason,
                        "n": 0,
                        "not_a_skill_estimate": True,
                    }
                )
                continue
            actual = float(actual_info["actual"]["unrounded"])
            forecast_1dp = round_1dp(forecast)
            actual_1dp = actual_info["actual"]["published_1dp"]
            if actual_1dp is None:
                actual_1dp = round_1dp(actual)
            yoy = _score_yoy(
                frame,
                change_target=target,
                model=model,
                period="2026-08",
                forecast_change=forecast,
                eligible=False,
            )
            # The YoY score above used the actuals frame, whose lag indexes are the
            # comparison vintage. Recompute the forecast YoY from July index levels.
            july_prev = july.get(INDEX_OF[target], "2026-07")
            july_lag = july.get(INDEX_OF[target], "2025-08")
            yoy_forecast = None
            if july_prev is not None and july_lag is not None:
                yoy_forecast = yoy_from_change(july_prev, july_lag, forecast)
            rows.append(
                {
                    "label": TRUE_VINTAGE_LABEL,
                    "target": target,
                    "model": model,
                    "period": "2026-08",
                    "status": "ok",
                    "forecast": forecast,
                    "forecast_1dp": forecast_1dp,
                    "actual": actual,
                    "actual_1dp": actual_1dp,
                    "error": forecast - actual,
                    "error_1dp": forecast_1dp - actual_1dp,
                    "actual_source": actual_info["source"],
                    "yoy_forecast_from_july_indexes": yoy_forecast,
                    "yoy_actual_from_comparison_vintage": None if yoy is None else yoy["actual"],
                    "n": 1,
                    "not_a_skill_estimate": True,
                }
            )
    rows.append(
        {
            "label": TRUE_VINTAGE_LABEL,
            "target": QUARTERLY_TARGET,
            "model": None,
            "period": "2026-Q3",
            "status": "blocked",
            "reason": (
                "The true-vintage pair is the July 2026 workbook versus the August 2026 monthly "
                "release. It does not contain a pre-release vintage of the 2026-Q3 legacy quarterly "
                "trimmed mean paired with a first-release quarterly print."
            ),
            "n": 0,
            "not_a_skill_estimate": True,
        }
    )
    return {
        "label": TRUE_VINTAGE_LABEL,
        "note": "n=1 is not a skill estimate. These rows are not included in pseudo-OOS metrics.",
        "information_set": (
            "vintage abs_release_2026-07 (in-repo July 2026 Table 6). Every row in that vintage "
            "carries the July release published_at. Forecast target month is 2026-08."
        ),
        "rows": rows,
    }


def run_backtest(
    snapshot: Snapshot,
    *,
    as_of: str,
    generated_at: str,
    ctx: ModelContext,
    frame: Any | None = None,
) -> dict[str, Any]:
    """Pseudo-OOS metrics, the true-vintage section, and the leakage guard."""
    if frame is None:
        frame = build_frame(snapshot.observations, as_of=as_of)
    errors = walk_forward(frame, ctx)
    return {
        "schema_version": BACKTEST_SCHEMA,
        "label": PSEUDO_OOS_LABEL,
        "generated_at": generated_at,
        "as_of": as_of,
        "snapshot_retrieved_at": snapshot.retrieved_at,
        "vintage_policy": frame.vintage_policy,
        "metrics": metrics_from_errors(errors),
        "errors": errors,
        "true_vintage": true_vintage_section(snapshot, ctx),
        "leakage_guard": {
            "monthly_2026-08": leakage_guard(snapshot, ctx, period="2026-08"),
            "quarterly_2026-Q2": leakage_guard(snapshot, ctx, period="2026-Q2"),
        },
        "quarterly_bridge_gap_actual_months": quarterly_bridge_gap(frame),
        "proxy_bridge_note": (
            "proxy_bridge_non_equivalent scores are in the error list with eligible=false. "
            "The internal monthly forecast is persistence of the monthly trimmed mean. "
            "They are excluded from selection and from pseudo-OOS headline metrics' candidate set."
        ),
    }
