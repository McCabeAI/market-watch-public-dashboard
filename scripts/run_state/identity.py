"""Concept, source, and score identity projections for SeriesDefinition.

The hashed SeriesDefinition document stays the acquisition contract
(concept id, source series id, units, transform). Score identity is an
explicit projection of that definition, not a second registry and not an
extra hashed field. ``definition_id`` values therefore stay stable.

Concept id is the catalog id already stored on SeriesDefinition (for example
``CA.Labor.unemployment``). A source id maps to a score id only when this
module lists that pair exactly. Similar labels are not treated as equivalent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from scripts.macro_freshness import values_close
from scripts.temperature_level import parse_period, period_sort_key

REASON_UNKNOWN_SERIES = "unknown_series"
REASON_TRANSFORM_MISMATCH = "transform_mismatch"
REASON_FREQUENCY_MISMATCH = "frequency_mismatch"
REASON_UNITS_MISMATCH = "units_mismatch"
REASON_SEASONAL_ADJUSTMENT_MISMATCH = "seasonal_adjustment_mismatch"
REASON_FUTURE_RELEASE = "future_release"
REASON_SCORE_SERIES_MISMATCH = "score_series_mismatch"
REASON_SOURCE_SERIES_MISMATCH = "source_series_mismatch"
REASON_DEFINITION_MISMATCH = "definition_mismatch"
REASON_HISTORY_MISMATCH = "history_mismatch"
REASON_MISSING_CALIBRATION = "missing_calibration"

MERGE_PARTIAL_TRANSFORM = "partial_transform_mismatch"
MERGE_FUTURE = "future_release"
MERGE_FREQUENCY = "frequency_mismatch"

_CHECKED_AT_YM_RE = re.compile(r"^(\d{4})-(\d{2})")


@dataclass(frozen=True)
class SourceProjection:
    """One approved source-to-score projection.

    ``rewrite`` is false when the pair is an existing validated contract that
    must be recognized by preflight but must not rewrite observations.
    """

    concept_id: str
    source_series_id: str | None
    source_transformation: str
    score_series_id: str | None
    score_transformation: str
    frequency: str
    units: str
    seasonal_adjustment: bool
    kind: str
    context_series_ids: tuple[str, ...] = ()
    component_series_ids: tuple[str, ...] = ()
    rewrite: bool = True
    rewrite_forward_only: bool = False


# Exact allowlist. Same-transform rows are publisher-id versus calibrated-id
# labels for one series. The GDP row is a frequency split: monthly industry
# GDP stays context and only a quarterly q/q SA print may score.
APPROVED_PROJECTIONS: dict[str, SourceProjection] = {
    "CA.Labor.unemployment": SourceProjection(
        concept_id="CA.Labor.unemployment",
        source_series_id="v2062815",
        source_transformation="percent",
        score_series_id="LFS_unemployment_rate_v2062815",
        score_transformation="percent",
        frequency="monthly",
        units="percent",
        seasonal_adjustment=True,
        kind="label",
    ),
    "CA.Labor.employment": SourceProjection(
        concept_id="CA.Labor.employment",
        source_series_id="v2062811_derived_mom_change",
        source_transformation="mom_sa_change_thousands",
        score_series_id="LFS_employment_level_v2062811",
        score_transformation="mom_sa_change_thousands",
        frequency="monthly",
        units="thousands of persons",
        seasonal_adjustment=True,
        kind="label",
    ),
    "CA.Labor.wages": SourceProjection(
        concept_id="CA.Labor.wages",
        source_series_id="v105812645_derived_yoy",
        source_transformation="yoy_pct",
        score_series_id="LFS_avg_hourly_wage_v105812645",
        score_transformation="yoy_pct",
        frequency="monthly",
        units="percent",
        seasonal_adjustment=False,
        kind="label",
    ),
    # Recognized source/score labels. rewrite stays false: history already
    # stores the score id, and a blanket alias would revise August 2026
    # (history 3.03 vs index ratio 3.033980582524265). Forward-only rewrite
    # with a scored gate appends 2026-09 without touching accepted prints.
    "CA.Inflation.headline": SourceProjection(
        concept_id="CA.Inflation.headline",
        source_series_id="v41690973_derived_yoy",
        source_transformation="yoy_pct",
        score_series_id="CPI_all_items_index_v41690973",
        score_transformation="yoy_pct",
        frequency="monthly",
        units="percent",
        seasonal_adjustment=False,
        kind="label",
        rewrite=False,
        rewrite_forward_only=True,
    ),
    "CA.Inflation.underlying": SourceProjection(
        concept_id="CA.Inflation.underlying",
        source_series_id="CPI_trim_and_median_yoy",
        source_transformation="yoy_pct",
        score_series_id=None,
        score_transformation="yoy_pct",
        frequency="monthly",
        units="percent",
        seasonal_adjustment=False,
        kind="equal_mean_components",
        component_series_ids=(
            "CPI_trim_yoy_v108785715",
            "CPI_median_yoy_v108785714",
        ),
        rewrite=False,
        rewrite_forward_only=False,
    ),
    "CA.Consumer.retail": SourceProjection(
        concept_id="CA.Consumer.retail",
        source_series_id="v1446859483",
        source_transformation="mom_sa_pct",
        score_series_id="retail_total_sa_v1446859483",
        score_transformation="mom_sa_pct",
        frequency="monthly",
        units="percent",
        seasonal_adjustment=True,
        kind="label",
        rewrite=False,
    ),
    "CA.Consumer.income": SourceProjection(
        concept_id="CA.Consumer.income",
        source_series_id="v62305981_derived_qq",
        source_transformation="qoq_sa_pct",
        score_series_id="household_disposable_income_v62305981",
        score_transformation="qoq_sa_pct",
        frequency="quarterly",
        units="percent",
        seasonal_adjustment=True,
        kind="label",
        rewrite=False,
    ),
    "CA.Consumer.spending": SourceProjection(
        concept_id="CA.Consumer.spending",
        source_series_id="v1594571755",
        source_transformation="qoq_sa_pct",
        score_series_id="household_final_consumption_qq_v1594571755",
        score_transformation="qoq_sa_pct",
        frequency="quarterly",
        units="percent",
        seasonal_adjustment=True,
        kind="label",
        rewrite=False,
    ),
    "CA.Activity.gdp_domestic_demand": SourceProjection(
        concept_id="CA.Activity.gdp_domestic_demand",
        source_series_id="monthly_v65201210;quarterly_v1594571783",
        source_transformation="mom_sa_pct_and_qoq_sa_pct",
        score_series_id="GDP_real_market_prices_qq_v1594571783",
        score_transformation="qoq_sa_pct",
        frequency="monthly-and-quarterly",
        units="percent",
        seasonal_adjustment=True,
        kind="frequency_split",
    ),
    "AU.Activity.gdp_domestic_demand": SourceProjection(
        concept_id="AU.Activity.gdp_domestic_demand",
        source_series_id="A2304370T;A2304183K",
        source_transformation="qoq_pct",
        score_series_id="A2304370T",
        score_transformation="qoq_pct",
        frequency="quarterly",
        units="percent",
        seasonal_adjustment=True,
        kind="combined_feed",
        context_series_ids=("A2304183K",),
        rewrite=False,
    ),
    "AU.Consumer.confidence": SourceProjection(
        concept_id="AU.Consumer.confidence",
        source_series_id=None,
        source_transformation="index_level_or_mom_pct",
        score_series_id=None,
        score_transformation="index_level",
        frequency="monthly",
        units="index",
        seasonal_adjustment=False,
        kind="compound_token",
        rewrite=False,
    ),
}


def projection_for(concept_id: str) -> SourceProjection | None:
    return APPROVED_PROJECTIONS.get(concept_id)


def classify_point_transform(
    candidate: Any,
    configured: str,
    allowed: frozenset[str],
) -> str:
    """Classify an adapter transform against the catalog contract.

    ``absent`` keeps the configured transform. ``accepted`` uses the adapter
    value. ``mismatch`` must not be rewritten onto the configured transform.
    """

    if candidate is None:
        return "absent"
    if str(candidate) in allowed:
        return "accepted"
    return "mismatch"


def _blank_series_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        return None
    return value


def _checked_at_year_month(checked_at: str) -> tuple[int, int]:
    match = _CHECKED_AT_YM_RE.match(str(checked_at))
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _period_kind(period: str) -> str | None:
    try:
        kind, _, _ = parse_period(period)
    except ValueError:
        return None
    return kind


def _period_is_future(period: str, checked_at: str) -> bool:
    try:
        key = period_sort_key(period)
    except ValueError:
        return False
    return key > _checked_at_year_month(checked_at)


def _preserve_source_fields(
    point: dict[str, Any],
    *,
    source_series_id: str,
    source_transformation: str | None = None,
) -> None:
    if not point.get("source_series_id"):
        point["source_series_id"] = source_series_id
    if source_transformation is not None and not point.get("source_transformation"):
        point["source_transformation"] = source_transformation


def _frequency_matches(projection: SourceProjection, period: str) -> bool:
    kind = _period_kind(period)
    if projection.frequency == "monthly":
        return kind == "M"
    if projection.frequency == "quarterly":
        return kind == "Q"
    return False


def _forward_only_rewrite_allowed(
    period: str,
    point_value: Any,
    scored_gate: tuple[str | None, float | None] | None,
) -> bool:
    if scored_gate is None:
        return False
    latest_period, latest_value = scored_gate
    if latest_period is None:
        return True
    try:
        period_key = period_sort_key(period)
        latest_key = period_sort_key(latest_period)
    except ValueError:
        return False
    if period_key > latest_key:
        return True
    if period_key < latest_key:
        return False
    if latest_value is None:
        return False
    try:
        value = float(point_value)
    except (TypeError, ValueError):
        return False
    return values_close(latest_value, value)


def _normalize_label(
    point: dict[str, Any],
    projection: SourceProjection,
    period: str,
    checked_at: str,
    *,
    scored_gate: tuple[str | None, float | None] | None = None,
) -> str | None:
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    source_id = projection.source_series_id or ""
    score_id = projection.score_series_id or ""
    transform = projection.source_transformation
    if transformation != transform or series_id not in {source_id, score_id}:
        return None
    if not _frequency_matches(projection, period):
        return MERGE_FREQUENCY
    if _period_is_future(period, checked_at):
        return MERGE_FUTURE
    if series_id == source_id and source_id != score_id:
        if projection.rewrite_forward_only and not projection.rewrite:
            if not _forward_only_rewrite_allowed(period, point.get("value"), scored_gate):
                return None
        _preserve_source_fields(point, source_series_id=source_id)
        point["series_id"] = score_id
    return None


def _normalize_equal_mean_components(
    point: dict[str, Any],
    projection: SourceProjection,
    period: str,
    checked_at: str,
) -> str | None:
    """Reject a future or off-frequency aggregate or component print.

    The aggregate id is not rewritten onto either component. A component id
    with the approved transform passes through for the history merge.
    """

    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    source_id = projection.source_series_id or ""
    if transformation != projection.source_transformation:
        return None
    if series_id != source_id and series_id not in projection.component_series_ids:
        return None
    if _period_is_future(period, checked_at):
        return MERGE_FUTURE
    if not _frequency_matches(projection, period):
        return MERGE_FREQUENCY
    return None


def _normalize_frequency_split(
    point: dict[str, Any],
    projection: SourceProjection,
    period: str,
    checked_at: str,
) -> str | None:
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    source_id = projection.source_series_id or ""
    source_tf = projection.source_transformation
    score_id = projection.score_series_id or ""
    score_tf = projection.score_transformation
    monthly = _period_kind(period) == "M"
    quarterly = _period_kind(period) == "Q"

    if series_id == score_id and transformation == score_tf and quarterly:
        return None

    if monthly and (series_id == score_id or transformation == score_tf):
        return MERGE_PARTIAL_TRANSFORM

    if monthly and series_id == source_id and transformation == source_tf:
        _preserve_source_fields(
            point,
            source_series_id=source_id,
            source_transformation=source_tf,
        )
        point["role"] = "context"
        return None

    if quarterly and series_id == source_id and transformation == source_tf:
        if _period_is_future(period, checked_at):
            return MERGE_FUTURE
        _preserve_source_fields(
            point,
            source_series_id=source_id,
            source_transformation=source_tf,
        )
        point["series_id"] = score_id
        point["transformation"] = score_tf
        return None

    return None


def normalize_score_point(
    point: dict[str, Any],
    *,
    checked_at: str,
    scored_gate: tuple[str | None, float | None] | None = None,
) -> str | None:
    """Project an approved source id onto its score id, in place.

    Returns a merge skip reason, or None when the point may continue. Unknown
    ids and transforms are left unchanged so the history merge still records
    ``partial_series_mismatch`` or ``partial_transform_mismatch``.
    """

    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    projection = projection_for(catalog_id)
    if projection is None:
        return None
    if not projection.rewrite:
        if not projection.rewrite_forward_only and projection.kind != "equal_mean_components":
            return None
    country = point.get("country")
    concept_country = projection.concept_id.split(".", 1)[0]
    if country is not None and str(country) != concept_country:
        return None
    period = point.get("period")
    if not isinstance(period, str):
        return None
    if projection.kind == "frequency_split":
        if not projection.rewrite:
            return None
        return _normalize_frequency_split(point, projection, period, checked_at)
    if projection.kind == "label":
        if not projection.rewrite and not projection.rewrite_forward_only:
            return None
        return _normalize_label(
            point, projection, period, checked_at, scored_gate=scored_gate
        )
    if projection.kind == "equal_mean_components":
        return _normalize_equal_mean_components(point, projection, period, checked_at)
    return None


def classify_source_point(point: Mapping[str, Any], *, checked_at: str) -> dict[str, Any]:
    """Non-mutating identity classification with a machine-actionable reason."""

    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    projection = projection_for(catalog_id)
    series_id = _blank_series_id(point.get("series_id"))
    transformation = str(point.get("transformation") or "")
    period = point.get("period")
    base = {
        "concept_id": catalog_id,
        "source_series_id": series_id,
        "source_transformation": transformation or None,
        "action": "passthrough",
        "reason": None,
        "score_series_id": None,
        "score_transformation": None,
    }
    if projection is None:
        if series_id is None:
            base["reason"] = REASON_UNKNOWN_SERIES
            base["action"] = "reject"
        return base
    base["score_series_id"] = projection.score_series_id
    base["score_transformation"] = projection.score_transformation
    if not isinstance(period, str):
        return base
    if projection.kind == "label":
        known = {projection.source_series_id, projection.score_series_id}
        if series_id not in known or transformation != projection.source_transformation:
            base["action"] = "reject"
            base["reason"] = (
                REASON_TRANSFORM_MISMATCH
                if series_id in known
                else REASON_UNKNOWN_SERIES
            )
            return base
        if not _frequency_matches(projection, period):
            base["action"] = "reject"
            base["reason"] = REASON_FREQUENCY_MISMATCH
            return base
        if _period_is_future(period, checked_at):
            base["action"] = "reject"
            base["reason"] = REASON_FUTURE_RELEASE
            return base
        base["action"] = "accept"
        return base
    if projection.kind == "equal_mean_components":
        components = set(projection.component_series_ids)
        source_id = projection.source_series_id
        transform = projection.source_transformation
        if series_id == source_id and transformation == transform:
            if _period_is_future(period, checked_at):
                base["action"] = "reject"
                base["reason"] = REASON_FUTURE_RELEASE
                return base
            if not _frequency_matches(projection, period):
                base["action"] = "reject"
                base["reason"] = REASON_FREQUENCY_MISMATCH
                return base
            base["action"] = "requires_components"
            return base
        if series_id in components and transformation == transform:
            if not _frequency_matches(projection, period):
                base["action"] = "reject"
                base["reason"] = REASON_FREQUENCY_MISMATCH
                return base
            if _period_is_future(period, checked_at):
                base["action"] = "reject"
                base["reason"] = REASON_FUTURE_RELEASE
                return base
            base["action"] = "accept"
            return base
        if series_id in components or series_id == source_id:
            base["action"] = "reject"
            base["reason"] = REASON_TRANSFORM_MISMATCH
            return base
        base["action"] = "reject"
        base["reason"] = REASON_UNKNOWN_SERIES
        return base
    if projection.kind == "frequency_split":
        monthly = _period_kind(period) == "M"
        quarterly = _period_kind(period) == "Q"
        if monthly and (
            series_id == projection.score_series_id
            or transformation == projection.score_transformation
        ):
            base["action"] = "reject"
            base["reason"] = REASON_FREQUENCY_MISMATCH
            return base
        if (
            monthly
            and series_id == projection.source_series_id
            and transformation == projection.source_transformation
        ):
            base["action"] = "context"
            return base
        if (
            quarterly
            and series_id == projection.source_series_id
            and transformation == projection.source_transformation
        ):
            if _period_is_future(period, checked_at):
                base["action"] = "reject"
                base["reason"] = REASON_FUTURE_RELEASE
                return base
            base["action"] = "accept"
            return base
        if (
            quarterly
            and series_id == projection.score_series_id
            and transformation == projection.score_transformation
        ):
            base["action"] = "accept"
            return base
        base["action"] = "reject"
        base["reason"] = (
            REASON_TRANSFORM_MISMATCH
            if series_id in {projection.source_series_id, projection.score_series_id}
            else REASON_UNKNOWN_SERIES
        )
        return base
    return base


def _mismatch(
    *,
    concept_id: str,
    country: str,
    component: str,
    source: str,
    field: str,
    expected: Any,
    actual: Any,
    reason: str,
) -> dict[str, Any]:
    return {
        "concept_id": concept_id,
        "country": country,
        "component": component,
        "source": source,
        "field": field,
        "expected": expected,
        "actual": actual,
        "reason": reason,
    }


def _history_component(
    histories: Mapping[str, Any] | None,
    country: str,
    history_key: Any,
) -> Mapping[str, Any] | None:
    if not isinstance(histories, Mapping) or not isinstance(history_key, str):
        return None
    country_doc = histories.get(country)
    if not isinstance(country_doc, dict):
        return None
    component = (country_doc.get("components") or {}).get(history_key)
    if not isinstance(component, dict):
        return None
    return component


def _check_projection_row(
    row: Mapping[str, Any],
    component: Mapping[str, Any],
    projection: SourceProjection,
    history: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    concept_id = str(row.get("id") or "")
    country = str(row.get("country") or "")
    name = str(row.get("component") or "")
    found: list[dict[str, Any]] = []

    def add(source: str, field: str, expected: Any, actual: Any, reason: str) -> None:
        if expected != actual:
            found.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=name,
                    source=source,
                    field=field,
                    expected=expected,
                    actual=actual,
                    reason=reason,
                )
            )

    add(
        str(row.get("series_id") or ""),
        "series_id",
        projection.source_series_id,
        _blank_series_id(row.get("series_id")),
        REASON_SOURCE_SERIES_MISMATCH,
    )
    add(
        str(row.get("series_id") or ""),
        "transform",
        projection.source_transformation,
        row.get("transform"),
        REASON_TRANSFORM_MISMATCH,
    )
    add(
        str(row.get("series_id") or ""),
        "units",
        projection.units,
        row.get("units"),
        REASON_UNITS_MISMATCH,
    )
    add(
        str(row.get("series_id") or ""),
        "cadence",
        projection.frequency,
        row.get("cadence"),
        REASON_FREQUENCY_MISMATCH,
    )
    add(
        str(row.get("series_id") or ""),
        "seasonal_adjustment",
        projection.seasonal_adjustment,
        row.get("seasonal_adjustment"),
        REASON_SEASONAL_ADJUSTMENT_MISMATCH,
    )
    add(
        "calibration",
        "series_id",
        projection.score_series_id,
        _blank_series_id(component.get("series_id")),
        REASON_SCORE_SERIES_MISMATCH,
    )
    add(
        "calibration",
        "source_transformation",
        projection.score_transformation,
        component.get("source_transformation"),
        REASON_TRANSFORM_MISMATCH,
    )
    if projection.component_series_ids:
        add(
            "calibration",
            "series_ids",
            list(projection.component_series_ids),
            list(component.get("series_ids") or []),
            REASON_SCORE_SERIES_MISMATCH,
        )
    if history is not None:
        header_series = _blank_series_id(history.get("series_id"))
        allowed_series = {
            projection.source_series_id,
            projection.score_series_id,
            *projection.context_series_ids,
            *projection.component_series_ids,
        }
        if header_series not in allowed_series:
            found.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=name,
                    source="history",
                    field="series_id",
                    expected=sorted(item for item in allowed_series if item is not None) or [None],
                    actual=header_series,
                    reason=REASON_HISTORY_MISMATCH,
                )
            )
        preferred = history.get("preferred_scoring_transformation")
        allowed_tf = {projection.source_transformation, projection.score_transformation}
        if preferred not in allowed_tf:
            found.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=name,
                    source="history",
                    field="preferred_scoring_transformation",
                    expected=sorted(allowed_tf),
                    actual=preferred,
                    reason=REASON_HISTORY_MISMATCH,
                )
            )
        _check_history_semantics(found, row, history, concept_id, country, name)
    return found


def _check_history_semantics(
    found: list[dict[str, Any]],
    row: Mapping[str, Any],
    history: Mapping[str, Any],
    concept_id: str,
    country: str,
    name: str,
) -> None:
    if history.get("units") not in (None, row.get("units")):
        found.append(
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source="history",
                field="units",
                expected=row.get("units"),
                actual=history.get("units"),
                reason=REASON_UNITS_MISMATCH,
            )
        )
    if history.get("cadence") not in (None, row.get("cadence")):
        found.append(
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source="history",
                field="cadence",
                expected=row.get("cadence"),
                actual=history.get("cadence"),
                reason=REASON_FREQUENCY_MISMATCH,
            )
        )
    if "sa" in history and history.get("sa") != row.get("seasonal_adjustment"):
        found.append(
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source="history",
                field="seasonal_adjustment",
                expected=row.get("seasonal_adjustment"),
                actual=history.get("sa"),
                reason=REASON_SEASONAL_ADJUSTMENT_MISMATCH,
            )
        )


def _check_unprojected_row(
    row: Mapping[str, Any],
    component: Mapping[str, Any],
    history: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    concept_id = str(row.get("id") or "")
    country = str(row.get("country") or "")
    name = str(row.get("component") or "")
    found: list[dict[str, Any]] = []
    catalog_series = _blank_series_id(row.get("series_id"))
    catalog_tf = row.get("transform")
    score_tf = component.get("source_transformation")
    if catalog_tf != score_tf:
        found.append(
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source=str(catalog_series or ""),
                field="transform",
                expected=score_tf,
                actual=catalog_tf,
                reason=REASON_TRANSFORM_MISMATCH,
            )
        )
    series_ids = component.get("series_ids")
    score_series = _blank_series_id(component.get("series_id"))
    if isinstance(series_ids, list) and series_ids:
        pass
    elif score_series is None:
        if history is not None:
            header = _blank_series_id(history.get("series_id"))
            if header is not None and catalog_series is not None and header != catalog_series:
                found.append(
                    _mismatch(
                        concept_id=concept_id,
                        country=country,
                        component=name,
                        source="history",
                        field="series_id",
                        expected=catalog_series,
                        actual=header,
                        reason=REASON_HISTORY_MISMATCH,
                    )
                )
    elif catalog_series != score_series:
        found.append(
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source="calibration",
                field="series_id",
                expected=score_series,
                actual=catalog_series,
                reason=REASON_SCORE_SERIES_MISMATCH,
            )
        )
    if history is not None:
        # Header preferred_scoring_transformation may name an auxiliary print
        # (US wages stores mom alongside the y/y score). Identity is the series
        # id plus the catalog/calibration transform pair, not that header.
        if score_series is not None:
            header = _blank_series_id(history.get("series_id"))
            if header not in {catalog_series, score_series}:
                found.append(
                    _mismatch(
                        concept_id=concept_id,
                        country=country,
                        component=name,
                        source="history",
                        field="series_id",
                        expected=[catalog_series, score_series],
                        actual=header,
                        reason=REASON_HISTORY_MISMATCH,
                    )
                )
        _check_history_semantics(found, row, history, concept_id, country, name)
    return found


def _check_definition(
    row: Mapping[str, Any],
    definitions_by_id: Mapping[str, Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if definitions_by_id is None:
        return []
    concept_id = str(row.get("id") or "")
    country = str(row.get("country") or "")
    name = str(row.get("component") or "")
    if _blank_series_id(row.get("series_id")) is None:
        return []
    definition = definitions_by_id.get(concept_id)
    if definition is None:
        return [
            _mismatch(
                concept_id=concept_id,
                country=country,
                component=name,
                source="definition",
                field="concept_id",
                expected=concept_id,
                actual=None,
                reason=REASON_DEFINITION_MISMATCH,
            )
        ]
    found: list[dict[str, Any]] = []
    for field, catalog_key in (
        ("series_id", "series_id"),
        ("transform", "transform"),
        ("units", "units"),
        ("country", "country"),
    ):
        if definition.get(field) != row.get(catalog_key):
            found.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=name,
                    source="definition",
                    field=field,
                    expected=row.get(catalog_key),
                    actual=definition.get(field),
                    reason=REASON_DEFINITION_MISMATCH,
                )
            )
    return found


def preflight_weighted_series(
    catalog: Mapping[str, Any],
    calibration: Mapping[str, Any],
    histories: Mapping[str, Any] | None = None,
    definitions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Network-free contract check for weighted scored series.

    Compares catalog source identity, compiled SeriesDefinition fields,
    calibration score identity, and the history component header. It does not
    scan observation rows and does not invent calendar dates.
    """

    definitions_by_id: dict[str, Mapping[str, Any]] | None
    if definitions is None:
        definitions_by_id = None
    else:
        definitions_by_id = {
            str(item.get("id")): item
            for item in definitions
            if isinstance(item, Mapping) and item.get("id")
        }
    components = calibration.get("components") if isinstance(calibration, Mapping) else None
    if not isinstance(components, Mapping):
        components = {}
    mismatches: list[dict[str, Any]] = []
    checked = 0
    series = catalog.get("series") if isinstance(catalog, Mapping) else None
    if not isinstance(series, list):
        series = []
    for row in series:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("role") or "") != "scored":
            continue
        try:
            weight = float(row.get("weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0.0:
            continue
        concept_id = str(row.get("id") or "")
        component = components.get(concept_id)
        country = str(row.get("country") or "")
        if not isinstance(component, Mapping):
            mismatches.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=str(row.get("component") or ""),
                    source="calibration",
                    field="component",
                    expected=concept_id,
                    actual=None if component is None else type(component).__name__,
                    reason=REASON_MISSING_CALIBRATION,
                )
            )
            checked += 1
            continue
        if component.get("observed") is False:
            continue
        checked += 1
        history = _history_component(histories, country, component.get("history_key"))
        if histories is not None and history is None:
            mismatches.append(
                _mismatch(
                    concept_id=concept_id,
                    country=country,
                    component=str(row.get("component") or ""),
                    source="history",
                    field="history_key",
                    expected=component.get("history_key"),
                    actual=None,
                    reason=REASON_HISTORY_MISMATCH,
                )
            )
        projection = projection_for(concept_id)
        if projection is None:
            mismatches.extend(_check_unprojected_row(row, component, history))
        else:
            mismatches.extend(_check_projection_row(row, component, projection, history))
        mismatches.extend(_check_definition(row, definitions_by_id))

    blocked = sorted({row["country"] for row in mismatches if row.get("country")})
    return {
        "ok": not mismatches,
        "checked": checked,
        "mismatches": mismatches,
        "blocked_countries": blocked,
    }


def view_for_definition(
    definition: Mapping[str, Any],
    catalog_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Identity view beside a SeriesDefinition. Does not mutate the definition."""

    concept_id = str(definition.get("id") or "")
    projection = projection_for(concept_id)
    source_series = definition.get("series_id")
    source_tf = definition.get("transform")
    if projection is None:
        score_series = source_series
        score_tf = source_tf
        kind = "identity"
        rewrite = False
    else:
        score_series = projection.score_series_id
        score_tf = projection.score_transformation
        kind = projection.kind
        rewrite = projection.rewrite
    identity = {
        "concept_id": concept_id,
        "source_series_id": source_series,
        "source_transformation": source_tf,
        "score_series_id": score_series,
        "score_transformation": score_tf,
        "units": definition.get("units"),
        "projection": kind,
        "rewrite": rewrite,
    }
    if catalog_row is not None:
        identity["cadence"] = catalog_row.get("cadence")
        identity["seasonal_adjustment"] = catalog_row.get("seasonal_adjustment")
    return {
        "concept_id": concept_id,
        "definition_id": definition.get("definition_id"),
        "identity": identity,
    }
