"""Pre-registered model selection and empirical error bands.

The selection rule is PLAN.md section 5, operationalised in
``scripts.au_cpi_release.models.SELECTION_RULE``. Bands are quantiles of
absolute pseudo-OOS errors. A 0.05 percentage-point floor is the half-width
of one-decimal rounding. ``low_sample`` is n < 20. Year-ended bands are the
month-to-month (or quarter-to-quarter) band pushed through index arithmetic.
"""

from __future__ import annotations

from statistics import fmean
from typing import Any

from scripts.au_cpi_release.models import (
    BASELINE_MODEL,
    LEGACY_SELECTION_RULE,
    MIN_IMPROVEMENT_PP,
    MIN_SELECTION_N,
    ROUNDING_HALF_WIDTH_PP,
    SELECTION_RULE,
    YOY_OF,
    yoy_from_change,
)

PSEUDO_OOS_LABEL = "pseudo_oos_latest_vintage"


def empirical_quantile(samples: list[float], probability: float) -> float:
    """Hyndman-Fan type 7 quantile. Deterministic. ``probability`` is in [0, 1]."""
    if not samples:
        raise ValueError("quantile of an empty sample")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability out of range")
    ordered = sorted(samples)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    position = (count - 1) * probability
    lower = int(position)
    upper = min(lower + 1, count - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def absolute_error_band(errors: list[float], probability: float) -> dict[str, Any]:
    """Symmetric band from the empirical quantile of |error|, with the rounding floor."""
    if not errors:
        return {
            "probability": probability,
            "n": 0,
            "raw_quantile_pp": None,
            "half_width_pp": None,
            "floor_pp": ROUNDING_HALF_WIDTH_PP,
            "floor_applied": False,
            "quantile_method": "hyndman_fan_type7",
        }
    raw = empirical_quantile([abs(error) for error in errors], probability)
    half = raw if raw >= ROUNDING_HALF_WIDTH_PP else ROUNDING_HALF_WIDTH_PP
    return {
        "probability": probability,
        "n": len(errors),
        "raw_quantile_pp": raw,
        "half_width_pp": half,
        "floor_pp": ROUNDING_HALF_WIDTH_PP,
        "floor_applied": raw < ROUNDING_HALF_WIDTH_PP,
        "quantile_method": "hyndman_fan_type7",
    }


def symmetric_interval(center: float, half_width: float) -> dict[str, float]:
    return {
        "lower": center - half_width,
        "upper": center + half_width,
        "half_width_pp": half_width,
    }


def propagate_yoy_band(
    *,
    index_previous: float,
    index_lag: float,
    change_percent: float,
    half_width_pp: float,
) -> dict[str, float]:
    """Push a change-band through index_t = index_previous * (1+m/100)."""
    lower = yoy_from_change(index_previous, index_lag, change_percent - half_width_pp)
    upper = yoy_from_change(index_previous, index_lag, change_percent + half_width_pp)
    return {
        "lower": lower,
        "upper": upper,
        "half_width_pp": (upper - lower) / 2.0,
    }


def select_model(metric_rows: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """Apply the pre-registered rule to one change target.

    ``metric_rows`` are pseudo-OOS metric dicts. Only ``sub_period == "full"``
    rows in the target regime are used. Ineligible models (the quarterly proxy
    bridge) are reported and never selected.
    """
    baseline = BASELINE_MODEL[target]
    pool = [
        row
        for row in metric_rows
        if row.get("target") == target
        and row.get("sub_period") == "full"
        and row.get("label") == PSEUDO_OOS_LABEL
    ]
    eligible = [row for row in pool if row.get("eligible", True)]
    ineligible = [row for row in pool if not row.get("eligible", True)]
    by_model = {str(row["model"]): row for row in eligible}

    def _compact(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": row.get("model"),
            "n": row.get("n"),
            "mae": row.get("mae"),
            "bias": row.get("bias"),
            "rmse": row.get("rmse"),
            "eligible": row.get("eligible", True),
        }

    base = by_model.get(baseline)
    qualified = [
        row
        for row in eligible
        if row.get("mae") is not None and int(row.get("n") or 0) >= MIN_SELECTION_N
    ]
    candidates = [_compact(row) for row in eligible]
    candidates.sort(key=lambda row: (row["mae"] is None, row["mae"] if row["mae"] is not None else 0.0, str(row["model"])))
    result: dict[str, Any] = {
        "target": target,
        "baseline": baseline,
        "rule": LEGACY_SELECTION_RULE,
        "min_n": MIN_SELECTION_N,
        "min_improvement_pp": MIN_IMPROVEMENT_PP,
        "candidates": candidates,
        "ineligible": [_compact(row) for row in ineligible],
        "yoy_target": YOY_OF[target],
        "yoy_inherits_change_model": True,
    }
    if base is None or base.get("mae") is None or int(base.get("n") or 0) == 0:
        result.update({"model": None, "reason": "baseline_unavailable", "n": 0, "mae": None})
        return result
    if not qualified or int(base.get("n") or 0) < MIN_SELECTION_N:
        result.update(
            {
                "model": baseline,
                "reason": "n_below_12",
                "n": base.get("n"),
                "mae": base.get("mae"),
            }
        )
        return result
    best = min(qualified, key=lambda row: (float(row["mae"]), 0 if row["model"] == baseline else 1, str(row["model"])))
    improvement = float(base["mae"]) - float(best["mae"])
    if best["model"] != baseline and improvement >= MIN_IMPROVEMENT_PP:
        result.update(
            {
                "model": best["model"],
                "reason": "lowest_mae_beats_baseline_by_at_least_0.02pp",
                "n": best.get("n"),
                "mae": best.get("mae"),
                "improvement_vs_baseline_pp": improvement,
            }
        )
        return result
    reason = "baseline_has_lowest_mae" if best["model"] == baseline else "no_model_beats_baseline_by_0.02pp"
    result.update(
        {
            "model": baseline,
            "reason": reason,
            "n": base.get("n"),
            "mae": base.get("mae"),
            "best_challenger": None if best["model"] == baseline else best["model"],
            "best_challenger_improvement_pp": None if best["model"] == baseline else improvement,
        }
    )
    return result


def _full_sample_pool(metric_rows: list[dict[str, Any]], target: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pool = [
        row
        for row in metric_rows
        if row.get("target") == target and row.get("sub_period") == "full" and row.get("label") == PSEUDO_OOS_LABEL
    ]
    eligible = [row for row in pool if row.get("eligible", True)]
    ineligible = [row for row in pool if not row.get("eligible", True)]
    return eligible, ineligible


def _compact_metric(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": row.get("model"),
        "n": row.get("n"),
        "mae": row.get("mae"),
        "bias": row.get("bias"),
        "rmse": row.get("rmse"),
        "eligible": row.get("eligible", True),
    }


def select_common_sample(
    error_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    target: str,
) -> dict[str, Any]:
    """Select on the periods shared by every model with n >= 12 and the baseline.

    Full-sample n/MAE/bias/RMSE stay on ``candidates``. The decision uses the
    common-sample MAEs. Bands are not computed here.
    """
    baseline = BASELINE_MODEL[target]
    full_rows, ineligible = _full_sample_pool(metric_rows, target)
    by_metric = {str(row["model"]): row for row in full_rows}
    errors_by_model: dict[str, dict[str, float]] = {}
    for row in error_rows:
        if row.get("target") != target or row.get("label") != PSEUDO_OOS_LABEL:
            continue
        if row.get("eligible") is False:
            continue
        model = str(row["model"])
        errors_by_model.setdefault(model, {})[str(row["period"])] = float(row["error"])

    def _full_mae(model: str) -> float | None:
        metric = by_metric.get(model)
        if metric is None or metric.get("mae") is None:
            return None
        return float(metric["mae"])

    candidates = [_compact_metric(row) for row in full_rows]
    candidates.sort(key=lambda row: (row["mae"] is None, row["mae"] if row["mae"] is not None else 0.0, str(row["model"])))
    result: dict[str, Any] = {
        "target": target,
        "baseline": baseline,
        "rule": SELECTION_RULE,
        "sample": "common",
        "min_n": MIN_SELECTION_N,
        "min_improvement_pp": MIN_IMPROVEMENT_PP,
        "candidates": candidates,
        "candidates_common_sample": [],
        "ineligible": [_compact_metric(row) for row in ineligible],
        "yoy_target": YOY_OF[target],
        "yoy_inherits_change_model": True,
        "band_sample": "full_walk_forward_errors_of_the_selected_model",
    }
    if baseline not in errors_by_model or not errors_by_model[baseline]:
        result.update({"model": None, "reason": "baseline_unavailable", "n": 0, "common_n": 0, "mae": None})
        return result

    eligible_models = [model for model, periods in errors_by_model.items() if len(periods) >= MIN_SELECTION_N]
    intersect_models = list(dict.fromkeys([*sorted(eligible_models), baseline]))
    common_periods = set.intersection(*(set(errors_by_model[model]) for model in intersect_models))
    common_n = len(common_periods)
    common_rows = []
    for model in intersect_models:
        mae = None
        if common_n:
            mae = fmean(abs(errors_by_model[model][period]) for period in common_periods)
        common_rows.append(
            {
                "model": model,
                "n": common_n,
                "mae": mae,
                "full_n": len(errors_by_model[model]),
                "full_mae": _full_mae(model),
            }
        )
    common_rows.sort(key=lambda row: (row["mae"] is None, row["mae"] if row["mae"] is not None else 0.0, str(row["model"])))
    ordered_periods = sorted(common_periods)
    result["candidates_common_sample"] = common_rows
    result["common_n"] = common_n
    result["common_sample_models"] = intersect_models
    result["common_period_first"] = ordered_periods[0] if ordered_periods else None
    result["common_period_last"] = ordered_periods[-1] if ordered_periods else None
    base_common = next(row for row in common_rows if row["model"] == baseline)
    if common_n < MIN_SELECTION_N:
        result.update(
            {
                "model": baseline,
                "reason": "common_sample_below_12",
                "n": common_n,
                "mae": base_common["mae"],
                "full_sample_n": len(errors_by_model[baseline]),
                "full_sample_mae": _full_mae(baseline),
            }
        )
        return result
    best = min(common_rows, key=lambda row: (float(row["mae"]), 0 if row["model"] == baseline else 1, str(row["model"])))
    improvement = float(base_common["mae"]) - float(best["mae"])
    if best["model"] != baseline and improvement >= MIN_IMPROVEMENT_PP:
        chosen = best
        reason = "lowest_common_sample_mae_beats_baseline_by_at_least_0.02pp"
        extra: dict[str, Any] = {"improvement_vs_baseline_pp": improvement}
    elif best["model"] == baseline:
        chosen = best
        reason = "baseline_has_lowest_common_sample_mae"
        extra = {}
    else:
        chosen = base_common
        reason = "no_model_beats_baseline_by_0.02pp_on_common_sample"
        extra = {
            "best_challenger": best["model"],
            "best_challenger_improvement_pp": improvement,
        }
    result.update(
        {
            "model": chosen["model"],
            "reason": reason,
            "n": common_n,
            "mae": chosen["mae"],
            "full_sample_n": len(errors_by_model[str(chosen["model"])]),
            "full_sample_mae": _full_mae(str(chosen["model"])),
            **extra,
        }
    )
    return result
