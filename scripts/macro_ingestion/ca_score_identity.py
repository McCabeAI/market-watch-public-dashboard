"""Statistics Canada source-to-score identity normalization for lineage merge.

Mixed-frequency GDP (``CA.Activity.gdp_domestic_demand``): only the verified
quarterly StatCan vector v1594571783 published q/q percent is scored as
``GDP_real_market_prices_qq_v1594571783`` with transformation ``qoq_sa_pct``.
Monthly industry GDP m/m from v65201210 arrives on the same catalog row with
compound transform ``mom_sa_pct_and_qoq_sa_pct``; those monthly prints are
marked ``role=context`` (not converted into q/q and never scored). Quarterly
compound observations map to the scoring identity; monthly masquerade as q/q
is rejected fail-closed.

Labor: WDS / adapter-derived series ids are aliased to calibrated scoring ids
(``LFS_*``) with transforms unchanged (mom change in thousands, unemployment
rate percent, wage y/y percent). Bare level series ids are never aliased.

Wrong country, series, transform, or malformed points are left untouched so
existing merge paths still emit ``partial_*`` skip reasons.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.temperature_level import parse_period, period_sort_key

_GDP_CATALOG = "CA.Activity.gdp_domestic_demand"
_GDP_COMBINED_SERIES = "monthly_v65201210;quarterly_v1594571783"
_GDP_COMPOUND_TF = "mom_sa_pct_and_qoq_sa_pct"
_GDP_SCORING_SERIES = "GDP_real_market_prices_qq_v1594571783"
_GDP_SCORING_TF = "qoq_sa_pct"

_LABOR_ALIASES: dict[tuple[str, str, str], tuple[str, str]] = {
    ("CA.Labor.unemployment", "v2062815", "percent"): (
        "LFS_unemployment_rate_v2062815",
        "v2062815",
    ),
    ("CA.Labor.employment", "v2062811_derived_mom_change", "mom_sa_change_thousands"): (
        "LFS_employment_level_v2062811",
        "v2062811_derived_mom_change",
    ),
    ("CA.Labor.wages", "v105812645_derived_yoy", "yoy_pct"): (
        "LFS_avg_hourly_wage_v105812645",
        "v105812645_derived_yoy",
    ),
}

_CHECKED_AT_YM_RE = re.compile(r"^(\d{4})-(\d{2})")


def _checked_at_year_month(checked_at: str) -> tuple[int, int]:
    m = _CHECKED_AT_YM_RE.match(str(checked_at))
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


def _is_monthly_period(period: str) -> bool:
    try:
        kind, _, _ = parse_period(period)
    except ValueError:
        return False
    return kind == "M"


def _is_quarterly_period(period: str) -> bool:
    try:
        kind, _, _ = parse_period(period)
    except ValueError:
        return False
    return kind == "Q"


def _period_is_future(period: str, checked_at: str) -> bool:
    try:
        pkey = period_sort_key(period)
    except ValueError:
        return False
    return pkey > _checked_at_year_month(checked_at)


def _preserve_source_fields(
    point: dict[str, Any], *, source_series_id: str, source_transformation: str | None = None
) -> None:
    if not point.get("source_series_id"):
        point["source_series_id"] = source_series_id
    if source_transformation is not None and not point.get("source_transformation"):
        point["source_transformation"] = source_transformation


def _acceptable_labor_identity(catalog_id: str, series_id: str, transformation: str, period: str) -> bool:
    """True for an exact source alias or an already-calibrated monthly labor identity."""
    if not _is_monthly_period(period):
        return False
    for (cat, src, tf), (scoring_id, _auth) in _LABOR_ALIASES.items():
        if catalog_id == cat and transformation == tf and series_id in (src, scoring_id):
            return True
    return False


def _apply_labor_alias(point: dict[str, Any], catalog_id: str, period: str) -> bool:
    if not _is_monthly_period(period):
        return False
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    key = (catalog_id, series_id, transformation)
    alias = _LABOR_ALIASES.get(key)
    if alias is None:
        return False
    scoring_id, authoritative_source = alias
    _preserve_source_fields(point, source_series_id=authoritative_source)
    point["series_id"] = scoring_id
    return True


def _gdp_monthly_masquerade(point: dict[str, Any], period: str) -> bool:
    if not _is_monthly_period(period):
        return False
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    return series_id == _GDP_SCORING_SERIES or transformation == _GDP_SCORING_TF


def _apply_gdp_rules(point: dict[str, Any], catalog_id: str, period: str, checked_at: str) -> str | None:
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")

    if series_id == _GDP_SCORING_SERIES and transformation == _GDP_SCORING_TF and _is_quarterly_period(
        period
    ):
        return None

    if _gdp_monthly_masquerade(point, period):
        return "partial_transform_mismatch"

    if (
        _is_monthly_period(period)
        and series_id == _GDP_COMBINED_SERIES
        and transformation == _GDP_COMPOUND_TF
    ):
        _preserve_source_fields(
            point,
            source_series_id=_GDP_COMBINED_SERIES,
            source_transformation=_GDP_COMPOUND_TF,
        )
        point["role"] = "context"
        return None

    if (
        _is_quarterly_period(period)
        and series_id == _GDP_COMBINED_SERIES
        and transformation == _GDP_COMPOUND_TF
    ):
        if _period_is_future(period, checked_at):
            return "future_release"
        _preserve_source_fields(
            point,
            source_series_id=_GDP_COMBINED_SERIES,
            source_transformation=_GDP_COMPOUND_TF,
        )
        point["series_id"] = _GDP_SCORING_SERIES
        point["transformation"] = _GDP_SCORING_TF
        return None

    return None


def _would_accept_labor_or_gdp(point: dict[str, Any], catalog_id: str) -> bool:
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    for (cat, src, tf), (scoring_id, _auth) in _LABOR_ALIASES.items():
        if catalog_id == cat and series_id in (src, scoring_id) and transformation == tf:
            return True
    if catalog_id == _GDP_CATALOG:
        return series_id == _GDP_SCORING_SERIES and transformation == _GDP_SCORING_TF
    return False


def prepare_ca_score_point(point: dict[str, Any], *, checked_at: str) -> str | None:
    """Normalize CA ingestion identities in place; return a merge skip reason or None."""
    country = point.get("country")
    if country is not None and str(country) != "CA":
        return None

    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    if not catalog_id.startswith("CA."):
        return None

    period = point.get("period")
    if not isinstance(period, str):
        return None

    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    # Reject a not-yet-arrived period before rewriting the source id, so the
    # skip still names the submitted series.
    if _acceptable_labor_identity(catalog_id, series_id, transformation, period) and _period_is_future(
        period, checked_at
    ):
        return "future_release"

    labor_accepted = False
    if catalog_id in {row[0] for row in _LABOR_ALIASES}:
        labor_accepted = _apply_labor_alias(point, catalog_id, period)

    gdp_block: str | None = None
    if catalog_id == _GDP_CATALOG:
        gdp_block = _apply_gdp_rules(point, catalog_id, period, checked_at)
        if gdp_block is not None:
            return gdp_block

    if str(point.get("role") or "") == "context":
        return None

    if labor_accepted or _would_accept_labor_or_gdp(point, catalog_id):
        if _period_is_future(period, checked_at):
            return "future_release"

    return None
