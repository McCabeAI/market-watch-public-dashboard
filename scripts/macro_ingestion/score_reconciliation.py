"""Reconcile weighted score components with history and observation stores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.macro_ingestion.canonical_bridge import _series_allowed
from scripts.macro_ingestion.contract import (
    COUNTRY_CODES,
    index_series_rows,
    load_catalog,
    lookup_series_by_observation_key,
)
from scripts.macro_ingestion.vintage import load_store
from scripts.temperature_level import (
    MONTH_RE,
    period_sort_key,
    raw_values_by_period,
    scoring_cutoff,
)

ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_DIR = ROOT / "data/macro_ingestion/observations"

CA_GDP_CATALOG_ID = "CA.Activity.gdp_domestic_demand"
CA_GDP_COMPOUND_SERIES = "monthly_v65201210;quarterly_v1594571783"
NZ_CONFIDENCE_CATALOG_ID = "NZ.Consumer.confidence"


def _weighted_catalog_ids(calibration: dict[str, Any]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for country, dims in calibration["weights"].items():
        for dimension, comps in dims.items():
            for component, weight in comps.items():
                w = float(weight)
                if w <= 0:
                    continue
                rows.append((f"{country}.{dimension}.{component}", w))
    rows.sort(key=lambda item: item[0])
    return rows


def _load_observations_by_country(
    observations_by_country: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if observations_by_country is not None:
        return observations_by_country
    return {country: load_store(country, OBSERVATIONS_DIR) for country in COUNTRY_CODES}


def _store_points_by_catalog(
    calibration: dict[str, Any],
    observations_by_country: dict[str, dict[str, Any]] | None,
    *,
    catalog: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    catalog = catalog or load_catalog()
    lookup = lookup_series_by_observation_key(catalog.get("series") or [])
    by_id = index_series_rows(catalog["series"])
    stores = _load_observations_by_country(observations_by_country)
    out: dict[str, list[dict[str, Any]]] = {}
    for country, store in stores.items():
        for obs in store.get("observations") or []:
            series_id = obs.get("series_id")
            transformation = obs.get("transformation")
            if not isinstance(series_id, str) or not isinstance(transformation, str):
                continue
            row = lookup.get((country, series_id, transformation))
            if row is None and series_id in by_id:
                candidate = by_id[series_id]
                catalog_id = str(candidate.get("id") or "")
                if (
                    catalog_id == series_id
                    and str(candidate.get("country") or "") == country
                    and str(candidate.get("transform") or "") == transformation
                ):
                    if catalog_id == NZ_CONFIDENCE_CATALOG_ID:
                        period_binding = str(obs.get("period_binding") or "")
                        endpoint = str(candidate.get("endpoint") or "")
                        if period_binding == "verified":
                            if str(obs.get("source_url") or "") != endpoint:
                                row = None
                            else:
                                row = candidate
                        else:
                            row = candidate
                    else:
                        row = candidate
            if row is None:
                continue
            cid = str(row["id"])
            spec_row = by_id.get(cid, row)
            out.setdefault(cid, []).append(
                {
                    **obs,
                    "country": country,
                    "catalog_id": cid,
                    "role": spec_row.get("role"),
                }
            )
    return out


def _latest_mapped_period(points: list[dict[str, Any]]) -> str | None:
    periods = [str(p["period"]) for p in points if isinstance(p.get("period"), str)]
    if not periods:
        return None
    return max(periods, key=period_sort_key)


def _newer_mapped_points(
    points: list[dict[str, Any]], scored_period: str | None
) -> list[dict[str, Any]]:
    if scored_period is None:
        return list(points)
    scored_key = period_sort_key(scored_period)
    out: list[dict[str, Any]] = []
    for point in points:
        period = point.get("period")
        if not isinstance(period, str):
            continue
        try:
            if period_sort_key(period) > scored_key:
                out.append(point)
        except ValueError:
            continue
    return out


def _is_ca_gdp_monthly_split_point(point: dict[str, Any]) -> bool:
    if str(point.get("series_id") or "") != CA_GDP_COMPOUND_SERIES:
        return False
    period = point.get("period")
    return isinstance(period, str) and bool(MONTH_RE.match(period))


def _point_eligible_for_scoring_merge(
    point: dict[str, Any],
    *,
    catalog_id: str,
    spec: dict[str, Any],
    weight: float,
    scored_period: str | None,
) -> bool:
    if float(weight) <= 0:
        return False
    if str(point.get("role") or "") != "scored":
        return False
    if spec.get("observed") is False:
        return False
    src_tf = str(spec.get("source_transformation") or "")
    if str(point.get("transformation") or "") != src_tf:
        return False
    series_id = point.get("series_id")
    if not isinstance(series_id, str) or not series_id:
        return False
    if not _series_allowed(spec, series_id):
        return False
    if catalog_id == NZ_CONFIDENCE_CATALOG_ID:
        if str(point.get("period_binding") or "") != "verified":
            return False
    if catalog_id == CA_GDP_CATALOG_ID and _is_ca_gdp_monthly_split_point(point):
        return False
    period = point.get("period")
    if not isinstance(period, str) or scored_period is None:
        return False
    try:
        return period_sort_key(period) > period_sort_key(scored_period)
    except ValueError:
        return False


def _nz_has_unverified_newer(newer: list[dict[str, Any]]) -> bool:
    for point in newer:
        if str(point.get("period_binding") or "") != "verified":
            return True
    return False


def _ca_frequency_split_only(newer: list[dict[str, Any]]) -> bool:
    if not newer:
        return False
    return all(_is_ca_gdp_monthly_split_point(point) for point in newer)


def _gap_reason(
    *,
    catalog_id: str,
    spec: dict[str, Any],
    weight: float,
    scored_period: str | None,
    history_period: str | None,
    store_points: list[dict[str, Any]],
) -> str:
    if spec.get("observed") is False:
        return "retired_unobserved"

    newer = _newer_mapped_points(store_points, scored_period)

    if catalog_id == NZ_CONFIDENCE_CATALOG_ID and _nz_has_unverified_newer(newer):
        return "ambiguous_confidence_period"

    eligible = [
        point
        for point in newer
        if _point_eligible_for_scoring_merge(
            point,
            catalog_id=catalog_id,
            spec=spec,
            weight=weight,
            scored_period=scored_period,
        )
    ]
    if eligible:
        return "newer_source_not_scored"

    if catalog_id == CA_GDP_CATALOG_ID and _ca_frequency_split_only(newer):
        return "frequency_split_context"

    if (
        scored_period is not None
        and history_period is not None
        and period_sort_key(scored_period) == period_sort_key(history_period)
    ):
        if not newer:
            return "source_not_in_store"
        return "scored"

    if scored_period is not None and history_period is not None:
        return "scored"
    return "source_not_in_store"


def reconcile_weighted_components(
    calibration: dict[str, Any],
    histories: dict[str, dict[str, Any]],
    score_state: dict[str, Any],
    observations_by_country: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cutoff = scoring_cutoff(calibration, histories)
    by_catalog = _store_points_by_catalog(calibration, observations_by_country)
    rows: list[dict[str, Any]] = []

    for catalog_id, weight in _weighted_catalog_ids(calibration):
        parts = catalog_id.split(".")
        if len(parts) != 3:
            continue
        country, dimension, component = parts
        spec = calibration.get("components", {}).get(catalog_id)
        if not isinstance(spec, dict):
            continue
        history = histories.get(country) or {}
        dim_state = (
            (score_state.get("countries") or {}).get(country) or {}
        ).get(dimension) or {}
        comp_state = (dim_state.get("component_state") or {}).get(component) or {}
        scored_period = comp_state.get("as_of")
        if scored_period is not None:
            scored_period = str(scored_period)

        store_points = by_catalog.get(catalog_id, [])
        source_period = _latest_mapped_period(store_points)

        if spec.get("observed") is False:
            rows.append(
                {
                    "catalog_id": catalog_id,
                    "weight": weight,
                    "scored_period": scored_period,
                    "history_period": None,
                    "source_period": source_period,
                    "gap_reason": "retired_unobserved",
                }
            )
            continue

        values = raw_values_by_period(history, spec, cutoff)
        history_period = (
            max(values.keys(), key=period_sort_key) if values else None
        )

        gap_reason = _gap_reason(
            catalog_id=catalog_id,
            spec=spec,
            weight=weight,
            scored_period=scored_period,
            history_period=history_period,
            store_points=store_points,
        )

        rows.append(
            {
                "catalog_id": catalog_id,
                "weight": weight,
                "scored_period": scored_period,
                "history_period": history_period,
                "source_period": source_period,
                "gap_reason": gap_reason,
            }
        )

    return rows
