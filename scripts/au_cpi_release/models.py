"""Transparent CPI nowcast models. Pure functions of an information set.

Change values are percent, the ABS convention (0.4 means 0.4 percent).
Models read published index levels and use the unrounded percent change
implied by those levels. PLAN.md section 5 is the model list. The
pre-registered selection rule is applied in ``uncertainty.py``, not here.

No wall-clock and no network. ``generated_at`` is not an input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Iterable

from scripts.au_cpi_release.contract import (
    previous_month,
    previous_quarter,
    guard_series_use,
)
from scripts.au_cpi_release.trim import trimmed_weighted_mean

ELECTRICITY_CLASS = "40055"
TRAVEL_DOMESTIC_CLASS = "40101"
TRAVEL_INTERNATIONAL_CLASS = "40102"

# Reviewer amendment A1 (2026-10-21), before the September 2026 outcome.
# MAE is compared on the intersection of periods where every eligible model
# and the baseline both have an error. The earlier unequal-sample wording is
# kept so that result can still be reported.
LEGACY_SELECTION_RULE = (
    "Per target, pick the model with the lowest pseudo-OOS MAE in the target "
    "regime among models with n >= 12. If that set is empty, or the lowest-MAE "
    "model does not beat the simplest baseline by at least 0.02 percentage points "
    "of MAE (the baseline must itself have n >= 12 to be beaten), use the simplest "
    "baseline. The simplest baseline is seasonal_naive for headline_nsa_mom and "
    "persistence for every other change target. Year-ended rates are not selected "
    "separately: they inherit the selected change model and are obtained by index "
    "arithmetic. proxy_bridge_non_equivalent is a different statistic (a "
    "quarter-average of the monthly trimmed mean) and is excluded from the "
    "candidate set; it is reported only as a labeled proxy."
)
SELECTION_RULE = (
    "Per target, eligible candidates are models with pseudo-OOS n >= 12 in the "
    "target regime. MAE for those candidates and the simplest baseline is computed "
    "on the intersection of their target periods. If that common sample has n < 12, "
    "use the baseline (common_sample_below_12). Otherwise pick the lowest common-sample "
    "MAE only when it beats the baseline's common-sample MAE by at least 0.02 "
    "percentage points; otherwise use the baseline. The simplest baseline is "
    "seasonal_naive for headline_nsa_mom and persistence for every other change "
    "target. Year-ended rates inherit the selected change model via index arithmetic. "
    "Bands use the selected model's full walk-forward errors, not the common sample. "
    "proxy_bridge_non_equivalent is excluded from the candidate set. The earlier "
    "unequal-sample rule is still computed and reported as selection_unequal_sample_legacy."
)
MIN_SELECTION_N = 12
MIN_IMPROVEMENT_PP = 0.02
LOW_SAMPLE_N = 20
ROUNDING_HALF_WIDTH_PP = 0.05

CHANGE_TARGETS: tuple[str, ...] = (
    "headline_nsa_mom",
    "headline_sa_mom",
    "trimmed_mean_monthly_sa_mom",
    "trimmed_mean_quarterly_legacy_qoq",
    "weighted_median_monthly_sa_mom",
)

YOY_OF: dict[str, str] = {
    "headline_nsa_mom": "headline_nsa_yoy",
    "headline_sa_mom": "headline_sa_yoy",
    "trimmed_mean_monthly_sa_mom": "trimmed_mean_monthly_sa_yoy",
    "trimmed_mean_quarterly_legacy_qoq": "trimmed_mean_quarterly_legacy_yoy",
    "weighted_median_monthly_sa_mom": "weighted_median_monthly_sa_yoy",
}

INDEX_OF: dict[str, str] = {
    "headline_nsa_mom": "headline_nsa_index",
    "headline_sa_mom": "headline_sa_index",
    "trimmed_mean_monthly_sa_mom": "trimmed_mean_monthly_sa_index",
    "trimmed_mean_quarterly_legacy_qoq": "trimmed_mean_quarterly_legacy_index",
    "weighted_median_monthly_sa_mom": "weighted_median_monthly_sa_index",
}

PUBLISHED_CHANGE_OF: dict[str, str] = {
    "headline_nsa_mom": "headline_nsa_mom",
    "headline_sa_mom": "headline_sa_mom",
    "trimmed_mean_monthly_sa_mom": "trimmed_mean_monthly_sa_mom",
    "trimmed_mean_quarterly_legacy_qoq": "trimmed_mean_quarterly_legacy_qoq",
    "weighted_median_monthly_sa_mom": "weighted_median_monthly_sa_mom",
}

REGIME_OF: dict[str, str] = {
    "headline_nsa_mom": "complete_monthly_cpi",
    "headline_nsa_yoy": "complete_monthly_cpi",
    "headline_sa_mom": "complete_monthly_cpi",
    "headline_sa_yoy": "complete_monthly_cpi",
    "trimmed_mean_monthly_sa_mom": "complete_monthly_cpi",
    "trimmed_mean_monthly_sa_yoy": "complete_monthly_cpi",
    "trimmed_mean_quarterly_legacy_qoq": "quarterly_legacy_tm",
    "trimmed_mean_quarterly_legacy_yoy": "quarterly_legacy_tm",
    "weighted_median_monthly_sa_mom": "complete_monthly_cpi",
    "weighted_median_monthly_sa_yoy": "complete_monthly_cpi",
}

BASELINE_MODEL: dict[str, str] = {
    "headline_nsa_mom": "seasonal_naive",
    "headline_sa_mom": "persistence",
    "trimmed_mean_monthly_sa_mom": "persistence",
    "trimmed_mean_quarterly_legacy_qoq": "persistence",
    "weighted_median_monthly_sa_mom": "persistence",
}

CANDIDATE_MODELS: dict[str, tuple[str, ...]] = {
    "headline_nsa_mom": (
        "seasonal_naive",
        "sa_persistence_x_seasonal_3",
        "sa_persistence_x_seasonal_6",
        "sa_persistence_x_seasonal_12",
        "component_bottom_up_3",
        "component_bottom_up_6",
    ),
    "headline_sa_mom": (
        "persistence",
        "mean_3",
        "mean_6",
        "mean_12",
        "component_sa_3",
        "component_sa_6",
    ),
    "trimmed_mean_monthly_sa_mom": (
        "persistence",
        "mean_3",
        "mean_6",
        "mean_12",
        "component_trim_3",
        "component_trim_6",
    ),
    "trimmed_mean_quarterly_legacy_qoq": (
        "persistence",
        "mean_4",
    ),
    "weighted_median_monthly_sa_mom": (
        "persistence",
        "mean_3",
        "mean_6",
        "mean_12",
    ),
}

PROXY_BRIDGE_MODEL = "proxy_bridge_non_equivalent"
QUARTERLY_SERIES_USED: tuple[str, ...] = (
    "trimmed_mean_quarterly_legacy_index",
    "trimmed_mean_quarterly_legacy_qoq",
)
# Touched so a direct call fails if a later edit feeds the quarterly target
# with the monthly trimmed mean. The proxy bridge reads the monthly index on
# purpose and is not a candidate for this target.
_QUARTERLY_GUARD_OK = tuple(
    guard_series_use(series_id, target_id="trimmed_mean_quarterly_legacy_qoq")
    for series_id in QUARTERLY_SERIES_USED
)

ELECTRICITY_TREATMENT = (
    "Electricity (class 40055) does not use a September seasonal factor. "
    "The class forecast is the mean of its last 3 or 6 seasonally adjusted "
    "month-to-month changes (original changes if no SA index is available). "
    "A seasonal-naive or implied-seasonal path would import the 2025 rebate-timing "
    "pattern. No month is dropped as rebate-affected: the snapshot has official "
    "index levels and contribution levels, not an official rebate flag or a rebate "
    "amount. Sensitivity rows recompute the class and its all-groups contribution "
    "under the seasonal alternatives."
)

TRIM_POINT_FORECAST_CAVEAT = (
    "component_trim passes class point forecasts through the rank-and-trim. "
    "The trimmed mean of point forecasts is not the expectation of the trimmed "
    "mean, because the cross-section of point forecasts understates dispersion. "
    "The model is scored on pseudo-OOS errors and is not assumed to be better."
)

VINTAGE_API = "abs_api"
VINTAGE_JULY = "abs_release_2026-07"
VINTAGE_AUGUST_RELEASE = "abs_release_2026-08"


def round_1dp(value: float) -> float:
    """Half-up to one decimal, matching published ABS percent changes.

    The formatting step matches scripts.au_cpi_release.trim._round_1dp, which
    reproduces MEASURE 2 and MEASURE 3 on this fixture.
    """
    rounded = float(Decimal(f"{value:.10f}").quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if rounded == 0:
        return 0.0
    return rounded


def add_months(period: str, delta: int) -> str:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def add_quarters(period: str, delta: int) -> str:
    year_text, quarter_text = period.split("-Q")
    index = int(year_text) * 4 + (int(quarter_text) - 1) + delta
    return f"{index // 4:04d}-Q{index % 4 + 1}"


def quarter_end_month(period: str) -> str:
    year_text, quarter_text = period.split("-Q")
    return f"{int(year_text):04d}-{int(quarter_text) * 3:02d}"


def quarter_months(period: str) -> tuple[str, str, str]:
    end = quarter_end_month(period)
    return (add_months(end, -2), add_months(end, -1), end)


def month_quarter(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    return f"{year:04d}-Q{(month - 1) // 3 + 1}"


def is_quarter_end_month(period: str) -> bool:
    return period[5:7] in {"03", "06", "09", "12"}


def period_key(period: str) -> tuple[int, int, int]:
    """Chronological key. A quarter sorts at its end month, after that month."""
    if "-Q" in period:
        year_text, quarter_text = period.split("-Q")
        return (int(year_text), int(quarter_text) * 3, 1)
    return (int(period[:4]), int(period[5:7]), 0)


def chronologically_on_or_after(period: str, cutoff: str) -> bool:
    return period_key(period) >= period_key(cutoff)


def percent_change(level: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (level / previous - 1.0) * 100.0


def yoy_from_change(index_previous: float, index_lag: float, change_percent: float) -> float:
    """Year-ended percent rate from a forecast change and official index levels.

    index_t = index_previous * (1 + change_percent/100)
    yoy = index_t / index_lag - 1, in percent.
    Quarterly callers pass the t-4 index as ``index_lag``.
    """
    if index_lag == 0:
        raise ValueError("index_lag is zero")
    index_t = index_previous * (1.0 + change_percent / 100.0)
    return (index_t / index_lag - 1.0) * 100.0


def combine_sa_and_seasonal(sa_change_percent: float, seasonal_movement: float) -> float:
    """NSA percent change. ``seasonal_movement`` is S_t / S_{t-1}."""
    return ((1.0 + sa_change_percent / 100.0) * seasonal_movement - 1.0) * 100.0


@dataclass
class Frame:
    """Latest-vintage levels visible to a model. Keys are (canonical_id, period)."""

    values: dict[tuple[str, str], float]
    vintage_policy: str

    def get(self, canonical_id: str, period: str) -> float | None:
        return self.values.get((canonical_id, period))

    def periods(self, canonical_id: str) -> list[str]:
        found = [period for (cid, period) in self.values if cid == canonical_id]
        return sorted(found, key=period_key)


def _vintage_rank(vintage: str) -> tuple[int, str]:
    if vintage == VINTAGE_API:
        return (2, vintage)
    return (1, vintage)


def build_frame(
    observations: Iterable[Any],
    *,
    as_of: str | None = None,
    vintage: str | None = None,
    drop_on_or_after: str | None = None,
) -> Frame:
    """Collapse observations to one value per series and period.

    ``vintage=None`` keeps the ABS API row when one exists and otherwise the
    lexicographically latest vintage label. ``as_of`` drops rows whose
    ``published_at`` is after the cutoff. ``drop_on_or_after`` drops periods
    chronologically on or after a target (the leakage cut).
    """
    from scripts.au_cpi_release.calendar import published_on_or_before

    grouped: dict[tuple[str, str], list[Any]] = {}
    for obs in observations:
        if as_of is not None and not published_on_or_before(obs.published_at, as_of):
            continue
        if vintage is not None and obs.vintage != vintage:
            continue
        if drop_on_or_after is not None and chronologically_on_or_after(obs.period, drop_on_or_after):
            continue
        grouped.setdefault((obs.canonical_id, obs.period), []).append(obs)
    values: dict[tuple[str, str], float] = {}
    for key, rows in grouped.items():
        if vintage is not None:
            chosen = rows[0]
        else:
            chosen = max(rows, key=lambda row: _vintage_rank(row.vintage))
        values[key] = float(chosen.value)
    policy = vintage or "latest_abs_api_else_latest_release_label"
    return Frame(values=values, vintage_policy=policy)


def change_at(frame: Frame, index_id: str, period: str, step: Callable[[str], str]) -> float | None:
    previous = step(period)
    current = frame.get(index_id, period)
    prior = frame.get(index_id, previous)
    if current is None or prior is None:
        return None
    return percent_change(current, prior)


def trailing_changes(
    frame: Frame,
    index_id: str,
    target: str,
    count: int,
    step: Callable[[str], str],
) -> list[float] | None:
    """The ``count`` realized changes ending at target-1, oldest first."""
    period = step(target)
    found: list[float] = []
    for _ in range(count):
        value = change_at(frame, index_id, period, step)
        if value is None:
            return None
        found.append(value)
        period = step(period)
    found.reverse()
    return found


def mean_last(
    frame: Frame,
    index_id: str,
    target: str,
    count: int,
    step: Callable[[str], str],
) -> float | None:
    values = trailing_changes(frame, index_id, target, count, step)
    if values is None:
        return None
    return fmean(values)


def _class_index(class_id: str, tsest: str) -> str:
    return f"cpi.m.1.{class_id}.{tsest}.50"


def _class_contribution(class_id: str) -> str:
    return f"cpi.m.4.{class_id}.10.50"


def class_weight(frame: Frame, class_id: str, weight_period: str) -> float | None:
    """Price-updated weight contribution(t) / all-groups index(t). Not renormalised."""
    contribution = frame.get(_class_contribution(class_id), weight_period)
    all_groups = frame.get("headline_nsa_index", weight_period)
    if contribution is None or all_groups is None or all_groups == 0 or contribution <= 0:
        return None
    return contribution / all_groups


@dataclass
class SeasonalFactors:
    by_class: dict[str, dict[str, float]]
    max_period: str | None
    matched_class_count: int
    unmatched_titles: tuple[str, ...]
    provenance: dict[str, Any] = field(default_factory=dict)

    def has_period(self, class_id: str, period: str) -> bool:
        return period in self.by_class.get(class_id, {})


def _norm_name(value: str) -> str:
    return " ".join(value.casefold().replace(",", " ").split())


def load_table8_factors(path: Path, names: dict[str, str]) -> SeasonalFactors:
    """Read combined seasonal factors from an ABS Table 8 workbook.

    Columns are matched to expenditure-class ids by the class name in the
    series title. Periods are taken from the date column. Nothing is interpolated.
    """
    import openpyxl

    by_name = {_norm_name(name): class_id for class_id, name in names.items()}
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["Data1"]
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if len(rows) < 12:
        raise ValueError(f"table 8 {path} has no data rows")
    titles = rows[0]
    header_index = next(
        (index for index, row in enumerate(rows[:15]) if row and row[0] == "Series ID"),
        None,
    )
    if header_index is None:
        raise ValueError(f"table 8 {path} has no Series ID row")
    by_class: dict[str, dict[str, float]] = {}
    unmatched: list[str] = []
    column_class: dict[int, str] = {}
    for col, title in enumerate(titles):
        if col == 0 or not title:
            continue
        parts = [part.strip() for part in str(title).split(";") if part.strip()]
        label = parts[-1] if parts else str(title)
        class_id = by_name.get(_norm_name(label))
        if class_id is None:
            unmatched.append(label)
            continue
        column_class[col] = class_id
        by_class[class_id] = {}
    max_period: str | None = None
    for row in rows[header_index + 1 :]:
        stamp = row[0]
        if stamp is None:
            continue
        if isinstance(stamp, datetime):
            period = f"{stamp.year:04d}-{stamp.month:02d}"
        else:
            text = str(stamp)[:7]
            if len(text) != 7 or text[4] != "-":
                continue
            period = text
        if max_period is None or period > max_period:
            max_period = period
        for col, class_id in column_class.items():
            raw = row[col] if col < len(row) else None
            if raw is None or raw == "":
                continue
            by_class[class_id][period] = float(raw)
    return SeasonalFactors(
        by_class=by_class,
        max_period=max_period,
        matched_class_count=len(column_class),
        unmatched_titles=tuple(unmatched),
    )


def seasonal_factor_report(
    factors: SeasonalFactors | None,
    classes: Iterable[str],
    target_period: str,
) -> dict[str, Any]:
    """Say whether Table 8 contains a factor for the target month."""
    class_list = list(classes)
    if factors is None:
        return {
            "table8_file_read": False,
            "forward_factors_for_target": False,
            "classes_with_target_factor": 0,
            "class_count": len(class_list),
            "source_used_for_classes": "implied_nsa_over_sa_same_month_last_year",
            "reason": "no Table 8 workbook was attached to this information set",
        }
    have = sum(1 for class_id in class_list if factors.has_period(class_id, target_period))
    previous = previous_month(target_period)
    have_pair = sum(
        1
        for class_id in class_list
        if factors.has_period(class_id, target_period) and factors.has_period(class_id, previous)
    )
    forward = have_pair == len(class_list) and len(class_list) > 0
    return {
        "table8_file_read": True,
        "table8_max_period": factors.max_period,
        "matched_class_count": factors.matched_class_count,
        "unmatched_titles": list(factors.unmatched_titles),
        "target_period": target_period,
        "classes_with_target_factor": have,
        "classes_with_target_and_previous_factor": have_pair,
        "class_count": len(class_list),
        "forward_factors_for_target": forward,
        "source_used_for_classes": (
            "table8_combined_seasonal_factor" if forward else "implied_nsa_over_sa_same_month_last_year"
        ),
        "provenance": factors.provenance,
        "reason": (
            "Table 8 contains a combined seasonal factor for the target month and the previous month "
            "on every expenditure class, so those forward factors are the seasonal movement."
            if forward
            else (
                f"Table 8 factors end at {factors.max_period}. "
                f"{have} of {len(class_list)} classes have a factor in {target_period}, "
                "so the target month is not a forward-factor month. Class seasonal movements "
                "are the implied NSA/SA index ratio versus the same month a year earlier."
            )
        ),
    }


@dataclass
class ModelContext:
    classes: tuple[str, ...]
    names: dict[str, str]
    seasonal: SeasonalFactors | None = None


def _seasonal_movement_table8(
    factors: SeasonalFactors | None,
    class_id: str,
    target: str,
) -> float | None:
    if factors is None:
        return None
    previous = previous_month(target)
    current = factors.by_class.get(class_id, {}).get(target)
    prior = factors.by_class.get(class_id, {}).get(previous)
    if current is None or prior is None or prior == 0:
        return None
    return current / prior


def _implied_seasonal_movement(
    frame: Frame,
    nsa_id: str,
    sa_id: str,
    target: str,
    step: Callable[[str], str],
    lag: int,
) -> float | None:
    """S_{t-lag} / S_{t-lag-1} with S = NSA index / SA index."""
    current_period = target
    for _ in range(lag):
        current_period = step(current_period)
    previous_period = step(current_period)
    nsa_now = frame.get(nsa_id, current_period)
    sa_now = frame.get(sa_id, current_period)
    nsa_prev = frame.get(nsa_id, previous_period)
    sa_prev = frame.get(sa_id, previous_period)
    if None in (nsa_now, sa_now, nsa_prev, sa_prev):
        return None
    if sa_now == 0 or sa_prev == 0 or nsa_prev == 0:
        return None
    seasonal_now = nsa_now / sa_now
    seasonal_prev = nsa_prev / sa_prev
    if seasonal_prev == 0:
        return None
    return seasonal_now / seasonal_prev


def class_seasonal_movement(
    frame: Frame,
    class_id: str,
    target: str,
    factors: SeasonalFactors | None,
    *,
    use_forward_factors: bool,
) -> tuple[float | None, str]:
    if use_forward_factors:
        movement = _seasonal_movement_table8(factors, class_id, target)
        if movement is not None:
            return movement, "table8_combined_seasonal_factor"
    movement = _implied_seasonal_movement(
        frame,
        _class_index(class_id, "10"),
        _class_index(class_id, "20"),
        target,
        previous_month,
        12,
    )
    if movement is None:
        return None, "unavailable"
    return movement, "implied_nsa_over_sa_same_month_last_year"


def _identity_month(
    frame: Frame,
    classes: tuple[str, ...],
    month: str,
    *,
    sa: bool,
) -> dict[str, Any] | None:
    """Weighted sum of realized class changes against the published aggregate."""
    weight_period = previous_month(month)
    aggregate_id = "headline_sa_index" if sa else "headline_nsa_index"
    aggregate = change_at(frame, aggregate_id, month, previous_month)
    if aggregate is None:
        return None
    weighted = 0.0
    weight_sum = 0.0
    used = 0
    missing = 0
    for class_id in classes:
        weight = class_weight(frame, class_id, weight_period)
        if sa:
            change = change_at(frame, _class_index(class_id, "20"), month, previous_month)
            if change is None:
                change = change_at(frame, _class_index(class_id, "10"), month, previous_month)
        else:
            change = change_at(frame, _class_index(class_id, "10"), month, previous_month)
        if weight is None or change is None:
            missing += 1
            continue
        weighted += weight * change
        weight_sum += weight
        used += 1
    if used == 0:
        return {
            "period": month,
            "class_count": 0,
            "missing_class_count": missing,
            "weight_sum": 0.0,
            "weighted_sum": None,
            "aggregate_unrounded": aggregate,
            "residual": None,
            "coverage": "no_contribution_weights",
        }
    residual = aggregate - weighted
    return {
        "period": month,
        "class_count": used,
        "missing_class_count": missing,
        "weight_sum": weight_sum,
        "weighted_sum": weighted,
        "aggregate_unrounded": aggregate,
        "residual": residual,
        "coverage": "full" if missing == 0 else "partial",
    }


def aggregation_identity(
    frame: Frame,
    classes: tuple[str, ...],
    *,
    before: str | None = None,
) -> dict[str, Any]:
    """sum_i w_i * class NSA change versus the all-groups NSA change.

    w_i = contribution_i(t-1) / all-groups index(t-1), not renormalised.
    The residual is published-index change minus that weighted sum.
    """
    months = [
        period
        for period in frame.periods("headline_nsa_index")
        if before is None or period_key(period) < period_key(before)
    ]
    rows = []
    for month in months:
        row = _identity_month(frame, classes, month, sa=False)
        if row is not None:
            rows.append(row)
    full = [row for row in rows if row["coverage"] == "full" and row["residual"] is not None]
    residuals = [float(row["residual"]) for row in full]
    link_months = [row["period"] for row in full if abs(float(row["residual"])) > 0.02]
    no_weight = [row["period"] for row in rows if row["coverage"] == "no_contribution_weights"]
    return {
        "definition": (
            "residual = unrounded all-groups NSA percent change minus "
            "sum over expenditure classes of (contribution(t-1)/all-groups index(t-1)) "
            "* class NSA percent change. Weights are not renormalised."
        ),
        "n_months_attempted": len(rows),
        "n_full_coverage": len(full),
        "mean_residual_pp": fmean(residuals) if residuals else None,
        "mean_abs_residual_pp": fmean(abs(value) for value in residuals) if residuals else None,
        "max_abs_residual_pp": max(abs(value) for value in residuals) if residuals else None,
        "min_residual_pp": min(residuals) if residuals else None,
        "max_residual_pp": max(residuals) if residuals else None,
        "link_or_reweight_months_abs_residual_gt_0.02pp": link_months,
        "months_without_contribution_weights": no_weight,
        "weight_note": (
            "CPI_WEIGHTS observation dates in this project are annual basket updates "
            "(through 2024-Q4). Price-updated MEASURE 4 contributions already apply the "
            "basket in force. A month is listed as a link/reweight candidate only when the "
            "full-coverage absolute residual exceeds 0.02 percentage points. The September 2025 "
            "index reference (all-groups original = 100) is a level rebase; the month-to-month "
            "identity is still the check used here."
        ),
        "rows": rows,
    }


def sa_aggregate_gap(
    frame: Frame,
    classes: tuple[str, ...],
    *,
    before: str | None = None,
) -> dict[str, Any]:
    """Bottom-up SA class changes versus INDEX 999901.

    ABS seasonally adjusts the all-groups index indirectly, so a weighted sum of
    class SA changes need not equal 999901. The gap is reported and, in the
    component SA forecast, added as an explicit mean residual.
    """
    months = [
        period
        for period in frame.periods("headline_sa_index")
        if before is None or period_key(period) < period_key(before)
    ]
    rows = []
    for month in months:
        row = _identity_month(frame, classes, month, sa=True)
        if row is not None:
            rows.append(row)
    full = [row for row in rows if row["coverage"] == "full" and row["residual"] is not None]
    residuals = [float(row["residual"]) for row in full]
    return {
        "definition": (
            "gap = unrounded INDEX 999901 percent change minus the contribution-weighted "
            "sum of class SA percent changes (original change if the class has no SA index). "
            "This gap is the indirect-adjustment residual, carried explicitly in component_sa forecasts."
        ),
        "n_full_coverage": len(full),
        "mean_gap_pp": fmean(residuals) if residuals else None,
        "mean_abs_gap_pp": fmean(abs(value) for value in residuals) if residuals else None,
        "max_abs_gap_pp": max(abs(value) for value in residuals) if residuals else None,
        "rows": [
            {
                "period": row["period"],
                "class_count": row["class_count"],
                "weight_sum": row["weight_sum"],
                "weighted_sum": row["weighted_sum"],
                "index_999901_unrounded": row["aggregate_unrounded"],
                "gap": row["residual"],
                "coverage": row["coverage"],
            }
            for row in rows
        ],
    }


def _mean_full_residual(rows: list[dict[str, Any]]) -> tuple[float, int]:
    full = [float(row["residual"]) for row in rows if row.get("coverage") == "full" and row.get("residual") is not None]
    if not full:
        return 0.0, 0
    return fmean(full), len(full)


def _class_change_forecast(
    frame: Frame,
    class_id: str,
    target: str,
    window: int,
    factors: SeasonalFactors | None,
    *,
    use_forward_factors: bool,
    sa_only: bool,
) -> dict[str, Any] | None:
    sa_mean = mean_last(frame, _class_index(class_id, "20"), target, window, previous_month)
    if sa_only:
        if sa_mean is None:
            sa_mean = mean_last(frame, _class_index(class_id, "10"), target, window, previous_month)
            source = "original_mean_no_sa"
        else:
            source = "sa_mean"
        if sa_mean is None:
            return None
        return {"mom": sa_mean, "sa_mom": sa_mean, "seasonal_movement": None, "seasonal_source": source}
    if class_id == ELECTRICITY_CLASS:
        value = sa_mean
        source = f"electricity_non_seasonal_mean_sa_{window}"
        if value is None:
            value = mean_last(frame, _class_index(class_id, "10"), target, window, previous_month)
            source = f"electricity_non_seasonal_mean_original_{window}"
        if value is None:
            return None
        return {"mom": value, "sa_mom": sa_mean, "seasonal_movement": None, "seasonal_source": source}
    movement, movement_source = class_seasonal_movement(
        frame, class_id, target, factors, use_forward_factors=use_forward_factors
    )
    if sa_mean is not None and movement is not None:
        return {
            "mom": combine_sa_and_seasonal(sa_mean, movement),
            "sa_mom": sa_mean,
            "seasonal_movement": movement,
            "seasonal_source": movement_source,
        }
    naive = change_at(frame, _class_index(class_id, "10"), add_months(target, -12), previous_month)
    if naive is None:
        return None
    return {
        "mom": naive,
        "sa_mom": sa_mean,
        "seasonal_movement": None,
        "seasonal_source": "seasonal_naive_fallback",
    }


def _bottom_up(
    frame: Frame,
    target: str,
    ctx: ModelContext,
    window: int,
    *,
    sa_only: bool,
    with_rows: bool,
) -> tuple[float | None, dict[str, Any]]:
    report = seasonal_factor_report(ctx.seasonal, ctx.classes, target)
    use_forward = bool(report["forward_factors_for_target"])
    identity = sa_aggregate_gap if sa_only else aggregation_identity
    history = identity(frame, ctx.classes, before=target)
    residual_mean, residual_n = _mean_full_residual(history["rows"])
    weight_period = previous_month(target)
    rows: list[dict[str, Any]] = []
    weighted = 0.0
    weight_sum = 0.0
    missing: list[str] = []
    for class_id in ctx.classes:
        weight = class_weight(frame, class_id, weight_period)
        forecast = _class_change_forecast(
            frame,
            class_id,
            target,
            window,
            ctx.seasonal,
            use_forward_factors=use_forward,
            sa_only=sa_only,
        )
        if weight is None or forecast is None:
            missing.append(class_id)
            continue
        contribution = weight * float(forecast["mom"])
        weighted += contribution
        weight_sum += weight
        if with_rows:
            rows.append(
                {
                    "class_id": class_id,
                    "name": ctx.names.get(class_id, class_id),
                    "weight": weight,
                    "forecast_mom": forecast["mom"],
                    "contribution_pp": contribution,
                    "sa_mom_forecast": forecast["sa_mom"],
                    "seasonal_movement": forecast["seasonal_movement"],
                    "seasonal_source": forecast["seasonal_source"],
                }
            )
    meta: dict[str, Any] = {
        "window": window,
        "weight_period": weight_period,
        "weight_sum": weight_sum,
        "weighted_sum_before_residual": weighted,
        "residual_mean_pp": residual_mean,
        "residual_n": residual_n,
        "missing_forecast_classes": missing,
        "seasonal": report,
        "class_rows": rows,
    }
    # Every expenditure class has to carry a positive t-1 weight and a forecast.
    # Dropping a class would hide a hole in the basket inside the residual.
    if missing or weight_sum == 0:
        return None, meta
    value = weighted + residual_mean
    meta["value"] = value
    return value, meta


def embedded_headline_sa_mom(frame: Frame, target: str, method: str | None) -> float | None:
    """SA MoM path inside an NSA model of the form sa_persistence_x_seasonal_k.

    Other NSA models do not embed a single all-groups SA forecast.
    """
    prefix = "sa_persistence_x_seasonal_"
    if not method or not str(method).startswith(prefix):
        return None
    window = int(str(method)[len(prefix) :])
    return mean_last(frame, "headline_sa_index", target, window, previous_month)


def headline_coherence(
    *,
    nsa_method: str | None,
    nsa_mom: float | None,
    sa_method: str | None,
    sa_mom: float | None,
    embedded_sa_mom: float | None,
    seasonal_movement: float | None,
    index_previous: float | None,
    index_lag: float | None,
) -> dict[str, Any]:
    """Compare the SA path inside the NSA forecast with the selected SA forecast.

    Does not change either selected value. ``mom_gap_pp`` is selected NSA MoM
    minus the NSA MoM implied by the selected SA forecast and the all-groups
    seasonal movement. The YoY gap uses the same two MoMs and the official indexes.
    """
    nsa_from_sa = None
    if sa_mom is not None and seasonal_movement is not None:
        nsa_from_sa = combine_sa_and_seasonal(sa_mom, seasonal_movement)
    mom_gap = None if nsa_mom is None or nsa_from_sa is None else nsa_mom - nsa_from_sa
    sa_gap = None if embedded_sa_mom is None or sa_mom is None else embedded_sa_mom - sa_mom
    yoy_selected = None
    yoy_from_sa = None
    yoy_gap = None
    if None not in (index_previous, index_lag, nsa_mom):
        yoy_selected = yoy_from_change(index_previous, index_lag, nsa_mom)  # type: ignore[arg-type]
    if None not in (index_previous, index_lag, nsa_from_sa):
        yoy_from_sa = yoy_from_change(index_previous, index_lag, nsa_from_sa)  # type: ignore[arg-type]
    if yoy_selected is not None and yoy_from_sa is not None:
        yoy_gap = yoy_selected - yoy_from_sa
    flagged = (mom_gap is not None and abs(mom_gap) >= 0.05) or (yoy_gap is not None and abs(yoy_gap) >= 0.05)
    return {
        "nsa_method": nsa_method,
        "sa_method": sa_method,
        "selected_nsa_mom": nsa_mom,
        "selected_sa_mom": sa_mom,
        "implied_sa_mom_inside_selected_nsa_model": embedded_sa_mom,
        "all_groups_seasonal_movement": seasonal_movement,
        "nsa_mom_implied_by_selected_sa_forecast": nsa_from_sa,
        "mom_gap_pp": mom_gap,
        "sa_path_gap_pp": sa_gap,
        "yoy_from_selected_nsa": yoy_selected,
        "yoy_from_sa_implied_nsa": yoy_from_sa,
        "yoy_gap_pp": yoy_gap,
        "flag_abs_gap_at_least_0_05pp": flagged,
        "values_not_overridden": True,
        "note": (
            "The selected NSA model and the selected SA model can embed different SA paths. "
            "mom_gap_pp is the selected NSA MoM minus the NSA MoM obtained by applying the "
            "all-groups seasonal movement to the selected SA forecast. Neither selected value is replaced."
        ),
    }


def _sa_seasonal_headline(frame: Frame, target: str, window: int) -> float | None:
    sa_mean = mean_last(frame, "headline_sa_index", target, window, previous_month)
    movement = _implied_seasonal_movement(
        frame,
        "headline_nsa_index",
        "headline_sa_index",
        target,
        previous_month,
        12,
    )
    if sa_mean is None or movement is None:
        return None
    return combine_sa_and_seasonal(sa_mean, movement)


def forecast_headline_nsa(frame: Frame, target: str, ctx: ModelContext, *, detail: bool = False) -> dict[str, Any]:
    seasonal = change_at(frame, "headline_nsa_index", add_months(target, -12), previous_month)
    values: dict[str, float | None] = {
        "seasonal_naive": seasonal,
        "sa_persistence_x_seasonal_3": _sa_seasonal_headline(frame, target, 3),
        "sa_persistence_x_seasonal_6": _sa_seasonal_headline(frame, target, 6),
        "sa_persistence_x_seasonal_12": _sa_seasonal_headline(frame, target, 12),
    }
    details: dict[str, Any] = {}
    for window in (3, 6):
        value, meta = _bottom_up(frame, target, ctx, window, sa_only=False, with_rows=detail)
        values[f"component_bottom_up_{window}"] = value
        if detail:
            details[f"component_bottom_up_{window}"] = meta
    return {"values": values, "details": details}


def forecast_headline_sa(frame: Frame, target: str, ctx: ModelContext, *, detail: bool = False) -> dict[str, Any]:
    values = {
        "persistence": mean_last(frame, "headline_sa_index", target, 1, previous_month),
        "mean_3": mean_last(frame, "headline_sa_index", target, 3, previous_month),
        "mean_6": mean_last(frame, "headline_sa_index", target, 6, previous_month),
        "mean_12": mean_last(frame, "headline_sa_index", target, 12, previous_month),
    }
    details: dict[str, Any] = {}
    for window, model_id in ((3, "component_sa_3"), (6, "component_sa_6")):
        value, meta = _bottom_up(frame, target, ctx, window, sa_only=True, with_rows=detail)
        values[model_id] = value
        if detail:
            details[model_id] = meta
    return {"values": values, "details": details}


def _trim_forecast(frame: Frame, target: str, ctx: ModelContext, window: int) -> float | None:
    weight_period = previous_month(target)
    changes: list[float] = []
    weights: list[float] = []
    for class_id in ctx.classes:
        weight = class_weight(frame, class_id, weight_period)
        forecast = _class_change_forecast(
            frame,
            class_id,
            target,
            window,
            ctx.seasonal,
            use_forward_factors=False,
            sa_only=True,
        )
        if weight is None or forecast is None:
            return None
        changes.append(float(forecast["mom"]))
        weights.append(weight)
    if len(changes) != len(ctx.classes):
        return None
    return trimmed_weighted_mean(changes, weights)


def forecast_trimmed_mean(frame: Frame, target: str, ctx: ModelContext) -> dict[str, float | None]:
    return {
        "persistence": mean_last(frame, "trimmed_mean_monthly_sa_index", target, 1, previous_month),
        "mean_3": mean_last(frame, "trimmed_mean_monthly_sa_index", target, 3, previous_month),
        "mean_6": mean_last(frame, "trimmed_mean_monthly_sa_index", target, 6, previous_month),
        "mean_12": mean_last(frame, "trimmed_mean_monthly_sa_index", target, 12, previous_month),
        "component_trim_3": _trim_forecast(frame, target, ctx, 3),
        "component_trim_6": _trim_forecast(frame, target, ctx, 6),
    }


def forecast_weighted_median(frame: Frame, target: str) -> dict[str, float | None]:
    return {
        "persistence": mean_last(frame, "weighted_median_monthly_sa_index", target, 1, previous_month),
        "mean_3": mean_last(frame, "weighted_median_monthly_sa_index", target, 3, previous_month),
        "mean_6": mean_last(frame, "weighted_median_monthly_sa_index", target, 6, previous_month),
        "mean_12": mean_last(frame, "weighted_median_monthly_sa_index", target, 12, previous_month),
    }


def forecast_quarterly(frame: Frame, target: str) -> dict[str, float | None]:
    """Legacy quarterly trimmed mean. Does not read the monthly trimmed mean.

    ``proxy_bridge_non_equivalent`` is computed by ``proxy_bridge`` and is not
    returned here, so it cannot be selected as this target.
    """
    for series_id in QUARTERLY_SERIES_USED:
        guard_series_use(series_id, target_id="trimmed_mean_quarterly_legacy_qoq")
    return {
        "persistence": mean_last(frame, "trimmed_mean_quarterly_legacy_index", target, 1, previous_quarter),
        "mean_4": mean_last(frame, "trimmed_mean_quarterly_legacy_index", target, 4, previous_quarter),
    }


def proxy_bridge(frame: Frame, target: str, monthly_tm_forecast: float | None) -> float | None:
    """Quarter-average of the monthly trimmed-mean index versus the previous quarter.

    The last month of ``target`` uses ``monthly_tm_forecast`` (percent). Earlier
    months in the quarter use published monthly index levels. This is not the
    legacy quarterly trimmed mean.
    """
    months = quarter_months(target)
    levels: list[float] = []
    for index, month in enumerate(months):
        if index < 2:
            level = frame.get("trimmed_mean_monthly_sa_index", month)
            if level is None:
                return None
            levels.append(level)
        else:
            if monthly_tm_forecast is None:
                return None
            previous = frame.get("trimmed_mean_monthly_sa_index", months[1])
            if previous is None:
                return None
            levels.append(previous * (1.0 + monthly_tm_forecast / 100.0))
    previous_quarter_period = previous_quarter(target)
    previous_levels = []
    for month in quarter_months(previous_quarter_period):
        level = frame.get("trimmed_mean_monthly_sa_index", month)
        if level is None:
            return None
        previous_levels.append(level)
    current_avg = fmean(levels)
    previous_avg = fmean(previous_levels)
    value = percent_change(current_avg, previous_avg)
    return value


def quarterly_bridge_gap(frame: Frame) -> dict[str, Any]:
    """QoQ of quarter-average monthly TM indexes minus the legacy quarterly TM.

    Uses actual monthly indexes for every month (no forecast). This is the
    measured gap between the two statistics on overlap quarters.
    """
    quarters = frame.periods("trimmed_mean_quarterly_legacy_index")
    rows = []
    for quarter in quarters:
        months = quarter_months(quarter)
        previous = previous_quarter(quarter)
        current_levels = [frame.get("trimmed_mean_monthly_sa_index", month) for month in months]
        previous_levels = [frame.get("trimmed_mean_monthly_sa_index", month) for month in quarter_months(previous)]
        if any(level is None for level in current_levels + previous_levels):
            continue
        bridge = percent_change(fmean(current_levels), fmean(previous_levels))  # type: ignore[arg-type]
        actual = change_at(frame, "trimmed_mean_quarterly_legacy_index", quarter, previous_quarter)
        if bridge is None or actual is None:
            continue
        rows.append(
            {
                "period": quarter,
                "bridge_qoq": bridge,
                "legacy_qoq_unrounded": actual,
                "gap_pp": bridge - actual,
            }
        )
    gaps = [float(row["gap_pp"]) for row in rows]
    return {
        "label": PROXY_BRIDGE_MODEL,
        "note": (
            "The bridge is the percent change in the average of the three monthly trimmed-mean "
            "index levels. The legacy quarterly trimmed mean is a different statistic. "
            "The bridge is not a candidate under the pre-registered selection rule."
        ),
        "n_overlap": len(rows),
        "mean_gap_pp": fmean(gaps) if gaps else None,
        "mean_abs_gap_pp": fmean(abs(value) for value in gaps) if gaps else None,
        "max_abs_gap_pp": max((abs(value) for value in gaps), default=None),
        "rows": rows,
    }


def forecast_change_models(frame: Frame, target: str, ctx: ModelContext) -> dict[str, dict[str, float | None]]:
    """Every selectable change model for one monthly or quarterly target period."""
    if "-Q" in target:
        quarterly = forecast_quarterly(frame, target)
        return {"trimmed_mean_quarterly_legacy_qoq": quarterly}
    return {
        "headline_nsa_mom": forecast_headline_nsa(frame, target, ctx)["values"],
        "headline_sa_mom": forecast_headline_sa(frame, target, ctx)["values"],
        "trimmed_mean_monthly_sa_mom": forecast_trimmed_mean(frame, target, ctx),
        "weighted_median_monthly_sa_mom": forecast_weighted_median(frame, target),
    }


def actual_change(frame: Frame, target_id: str, period: str) -> dict[str, float | None]:
    """Unrounded index change and the published 1-decimal change, if present."""
    index_id = INDEX_OF[target_id]
    step = previous_quarter if "-Q" in period else previous_month
    unrounded = change_at(frame, index_id, period, step)
    published = frame.get(PUBLISHED_CHANGE_OF[target_id], period)
    published_1dp = None if published is None else round_1dp(published)
    return {"unrounded": unrounded, "published_1dp": published_1dp}


def index_publication_convention(frame: Frame) -> dict[str, Any]:
    """Whether published MoM/YoY equal 1-decimal changes of published indexes."""
    checks = []
    specs = [
        ("headline_nsa_mom", "headline_nsa_index", "headline_nsa_mom", previous_month),
        ("headline_sa_mom", "headline_sa_index", "headline_sa_mom", previous_month),
        ("trimmed_mean_monthly_sa_mom", "trimmed_mean_monthly_sa_index", "trimmed_mean_monthly_sa_mom", previous_month),
        ("weighted_median_monthly_sa_mom", "weighted_median_monthly_sa_index", "weighted_median_monthly_sa_mom", previous_month),
        ("trimmed_mean_quarterly_legacy_qoq", "trimmed_mean_quarterly_legacy_index", "trimmed_mean_quarterly_legacy_qoq", previous_quarter),
        ("headline_nsa_yoy", "headline_nsa_index", "headline_nsa_yoy", lambda period: add_months(period, -12)),
        ("headline_sa_yoy", "headline_sa_index", "headline_sa_yoy", lambda period: add_months(period, -12)),
        (
            "trimmed_mean_monthly_sa_yoy",
            "trimmed_mean_monthly_sa_index",
            "trimmed_mean_monthly_sa_yoy",
            lambda period: add_months(period, -12),
        ),
        (
            "trimmed_mean_quarterly_legacy_yoy",
            "trimmed_mean_quarterly_legacy_index",
            "trimmed_mean_quarterly_legacy_yoy",
            lambda period: add_quarters(period, -4),
        ),
        (
            "weighted_median_monthly_sa_yoy",
            "weighted_median_monthly_sa_index",
            "weighted_median_monthly_sa_yoy",
            lambda period: add_months(period, -12),
        ),
    ]
    for name, index_id, published_id, step in specs:
        compared = 0
        matched = 0
        max_abs = 0.0
        for period in frame.periods(published_id):
            unrounded = change_at(frame, index_id, period, step)
            published = frame.get(published_id, period)
            if unrounded is None or published is None:
                continue
            compared += 1
            max_abs = max(max_abs, abs(unrounded - published))
            if round_1dp(unrounded) == round_1dp(published):
                matched += 1
        checks.append(
            {
                "series": name,
                "n": compared,
                "n_1dp_match": matched,
                "max_abs_unrounded_minus_published_pp": None if compared == 0 else max_abs,
            }
        )
    return {
        "convention": (
            "Models and unrounded outputs use the percent change implied by published index levels. "
            "value_1dp is that unrounded percent rounded half-up to one decimal, which is the ABS "
            "display precision. On each series below, the published percent change equals that "
            "one-decimal rounding wherever both the index change and the published change exist."
        ),
        "rounding": "ROUND_HALF_UP to 1 decimal via decimal.Decimal, not Python bankers' round",
        "series": checks,
    }


def _top_contributions(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: abs(float(row["contribution_pp"])), reverse=True)
    return ordered[:limit]


def electricity_history(frame: Frame) -> dict[str, Any]:
    """Official electricity NSA changes and contribution levels. No invented rebates."""
    rows = []
    for period in ("2024-09", "2025-09"):
        change = change_at(frame, _class_index(ELECTRICITY_CLASS, "10"), period, previous_month)
        sa_change = change_at(frame, _class_index(ELECTRICITY_CLASS, "20"), period, previous_month)
        contribution = frame.get(_class_contribution(ELECTRICITY_CLASS), period)
        previous_contribution = frame.get(_class_contribution(ELECTRICITY_CLASS), previous_month(period))
        all_groups = frame.get("headline_nsa_index", previous_month(period))
        derived_pp = None
        if contribution is not None and previous_contribution is not None and all_groups not in (None, 0):
            derived_pp = (contribution - previous_contribution) / all_groups * 100.0
        rows.append(
            {
                "period": period,
                "nsa_mom_from_official_index": change,
                "sa_mom_from_official_index": sa_change,
                "nsa_index": frame.get(_class_index(ELECTRICITY_CLASS, "10"), period),
                "previous_nsa_index": frame.get(_class_index(ELECTRICITY_CLASS, "10"), previous_month(period)),
                "contribution_to_index_measure_4": contribution,
                "derived_contribution_to_mom_pp": derived_pp,
                "contribution_note": (
                    "MEASURE 4 is the contribution to the CPI index number, which is present from 2024-12. "
                    "MEASURE 6 (contribution to the percentage-point change) was not in the snapshot. "
                    "derived_contribution_to_mom_pp = (contribution_t - contribution_t-1) / all-groups index_t-1 * 100 "
                    "and is labeled derived."
                    if contribution is None
                    else "MEASURE 4 contribution to the CPI index number at this period."
                ),
            }
        )
    return {"class_id": ELECTRICITY_CLASS, "name": "Electricity", "periods": rows}


def base_effect_contributions(frame: Frame, ctx: ModelContext, month: str = "2025-09") -> dict[str, Any]:
    """Class contributions to the all-groups NSA change in ``month``.

    These are the percentage-point moves that drop out of the year-ended rate
    twelve months later. Weights are contribution shares at month-1.
    """
    weight_period = previous_month(month)
    rows = []
    for class_id in ctx.classes:
        weight = class_weight(frame, class_id, weight_period)
        change = change_at(frame, _class_index(class_id, "10"), month, previous_month)
        if weight is None or change is None:
            continue
        rows.append(
            {
                "class_id": class_id,
                "name": ctx.names.get(class_id, class_id),
                "weight": weight,
                "nsa_mom": change,
                "contribution_pp": weight * change,
            }
        )
    return {
        "month": month,
        "meaning": (
            f"Each contribution is the class share of the {month} all-groups NSA percent change. "
            "That month drops out of the year-ended rate when the same month of the following year is published."
        ),
        "top_10_by_absolute_contribution": _top_contributions(rows),
        "n_classes": len(rows),
    }


def electricity_sensitivity(frame: Frame, target: str, ctx: ModelContext, primary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Alternative electricity treatments and the all-groups contribution of each."""
    weight = class_weight(frame, ELECTRICITY_CLASS, previous_month(target))
    primary = next((row for row in primary_rows if row["class_id"] == ELECTRICITY_CLASS), None)
    primary_mom = None if primary is None else float(primary["forecast_mom"])

    def contribution(mom: float | None) -> float | None:
        if mom is None or weight is None:
            return None
        return weight * mom

    alternatives: list[tuple[str, float | None]] = [
        ("primary_non_seasonal_mean_sa_3", primary_mom),
        (
            "seasonal_naive_same_month_last_year",
            change_at(frame, _class_index(ELECTRICITY_CLASS, "10"), add_months(target, -12), previous_month),
        ),
    ]
    sa_mean = mean_last(frame, _class_index(ELECTRICITY_CLASS, "20"), target, 3, previous_month)
    movement, movement_source = class_seasonal_movement(
        frame, ELECTRICITY_CLASS, target, ctx.seasonal, use_forward_factors=False
    )
    implied = None if sa_mean is None or movement is None else combine_sa_and_seasonal(sa_mean, movement)
    alternatives.append((f"implied_seasonal_{movement_source}", implied))
    alternatives.append(
        (
            "non_seasonal_mean_sa_6",
            mean_last(frame, _class_index(ELECTRICITY_CLASS, "20"), target, 6, previous_month),
        )
    )
    alternatives.append(
        (
            "non_seasonal_last_sa_mom",
            mean_last(frame, _class_index(ELECTRICITY_CLASS, "20"), target, 1, previous_month),
        )
    )
    rows = []
    for name, mom in alternatives:
        rows.append(
            {
                "treatment": name,
                "class_mom": mom,
                "weight": weight,
                "contribution_pp": contribution(mom),
                "contribution_minus_primary_pp": (
                    None
                    if contribution(mom) is None or contribution(primary_mom) is None
                    else contribution(mom) - contribution(primary_mom)
                ),
            }
        )
    return {
        "class_id": ELECTRICITY_CLASS,
        "treatment_note": ELECTRICITY_TREATMENT,
        "rows": rows,
    }


def travel_assumptions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {TRAVEL_DOMESTIC_CLASS, TRAVEL_INTERNATIONAL_CLASS}
    return [row for row in rows if row["class_id"] in wanted]


def release_model_bundle(frame: Frame, release_month: str, ctx: ModelContext) -> dict[str, Any]:
    """Point forecasts for a monthly release, plus the class diagnostics."""
    nsa = forecast_headline_nsa(frame, release_month, ctx, detail=True)
    sa = forecast_headline_sa(frame, release_month, ctx, detail=True)
    trimmed = forecast_trimmed_mean(frame, release_month, ctx)
    median = forecast_weighted_median(frame, release_month)
    quarter = month_quarter(release_month) if is_quarter_end_month(release_month) else None
    quarterly = forecast_quarterly(frame, quarter) if quarter else None
    bridge = None
    if quarter is not None:
        bridge = proxy_bridge(frame, quarter, trimmed.get("persistence"))
    return {
        "headline_nsa_mom": nsa,
        "headline_sa_mom": sa,
        "trimmed_mean_monthly_sa_mom": {"values": trimmed, "details": {}},
        "weighted_median_monthly_sa_mom": {"values": median, "details": {}},
        "trimmed_mean_quarterly_legacy_qoq": None
        if quarterly is None
        else {"values": quarterly, "details": {"proxy_bridge_value": bridge, "proxy_internal_monthly_model": "persistence"}},
        "quarter": quarter,
    }
