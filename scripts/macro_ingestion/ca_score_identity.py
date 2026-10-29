"""Statistics Canada source-to-score identity normalization for lineage merge.

The approved source-to-score allowlist and rewrite rules live in
``scripts.run_state.identity`` (``normalize_score_point``). This module is the
CA ingestion entry point for acquisition and lineage merge; behavior for
existing CA labor and GDP merge skip reasons is unchanged.

Wrong country, series, transform, or malformed points are left untouched so
existing merge paths still emit ``partial_*`` skip reasons.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from scripts.macro_source_refresh import parse_statcan_vector_payload
from scripts.run_state.identity import _period_is_future, normalize_score_point, projection_for
from scripts.temperature_level import parse_period, period_sort_key

_TRIM_MEDIAN_VECTOR_TO_COMPONENT: dict[int, str] = {
    108785715: "CPI_trim_yoy_v108785715",
    108785714: "CPI_median_yoy_v108785714",
}


def _latest_scored_gate(
    histories: Mapping[str, Any] | None,
    calibration: Mapping[str, Any] | None,
    catalog_id: str,
) -> tuple[str | None, float | None] | None:
    if histories is None or calibration is None:
        return None
    spec = calibration.get("components", {}).get(catalog_id)
    if not isinstance(spec, dict):
        return None
    country = catalog_id.split(".", 1)[0]
    history = histories.get(country)
    if not isinstance(history, dict):
        return None
    history_key = spec.get("history_key")
    comp = (history.get("components") or {}).get(history_key)
    if not isinstance(comp, dict):
        return None
    src_tf = str(spec.get("source_transformation") or "")
    series_id = spec.get("series_id")
    series_filter = str(series_id) if series_id else None
    latest_period: str | None = None
    latest_value: float | None = None
    for obs in comp.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        if str(obs.get("transformation") or "") != src_tf:
            continue
        obs_series = obs.get("series_id")
        if series_filter and obs_series and str(obs_series) != series_filter:
            continue
        period = obs.get("reference_period") or obs.get("period")
        if not isinstance(period, str):
            continue
        if latest_period is None or period_sort_key(period) > period_sort_key(latest_period):
            latest_period = period
            try:
                latest_value = float(obs.get("value"))
            except (TypeError, ValueError):
                latest_value = None
    return (latest_period, latest_value)


def prepare_ca_score_point(
    point: dict[str, Any],
    *,
    checked_at: str,
    histories: Mapping[str, Any] | None = None,
    calibration: Mapping[str, Any] | None = None,
    scored_gate: tuple[str | None, float | None] | None = None,
    use_supplied_gate: bool = False,
) -> str | None:
    """Normalize CA ingestion identities in place; return a merge skip reason or None.

    Which concepts actually rewrite is the ``rewrite`` flag on the shared
    projection. Other CA rows pass through unchanged.

    ``use_supplied_gate`` keeps the forward-only comparison on the history as
    the merge started. A later month appended earlier in the same pass must
    not turn the previous new month into a revision of an already-scored print.
    """
    country = point.get("country")
    if country is not None and str(country) != "CA":
        return None

    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    if not catalog_id.startswith("CA."):
        return None

    if not use_supplied_gate:
        scored_gate = _latest_scored_gate(histories, calibration, catalog_id)
    return normalize_score_point(point, checked_at=checked_at, scored_gate=scored_gate)


def _raw_file_for_sha256(raw_dir: Path, raw_sha256: str) -> Path | None:
    if not raw_dir.is_dir():
        return None
    for path in raw_dir.iterdir():
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == raw_sha256:
            return path
    return None


def _vector_values_for_period(payload: Any, period: str) -> dict[int, float]:
    blocks = payload if isinstance(payload, list) else [payload]
    out: dict[int, float] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        obj = block.get("object") if isinstance(block.get("object"), dict) else block
        vector_id = obj.get("vectorId")
        if vector_id is None:
            continue
        try:
            vid = int(vector_id)
        except (TypeError, ValueError):
            continue
        points = obj.get("vectorDataPoint") or obj.get("vectorDataPoints") or []
        parsed = dict(parse_statcan_vector_payload([{"object": {"vectorDataPoint": points}}]))
        if period in parsed:
            out[vid] = parsed[period]
    return out


def _expand_underlying_point(
    point: dict[str, Any],
    *,
    observations_dir: Path,
    checked_at: str,
) -> list[dict[str, Any]]:
    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    projection = projection_for(catalog_id)
    if projection is None or projection.kind != "equal_mean_components":
        return [point]

    period = point.get("period")
    if not isinstance(period, str):
        return [point]
    try:
        kind, _, _ = parse_period(period)
    except ValueError:
        return [point]
    if kind != "M":
        return [point]

    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")
    if series_id != projection.source_series_id or transformation != projection.source_transformation:
        return [point]

    if _period_is_future(period, checked_at):
        return [point]

    raw_sha = point.get("raw_sha256")
    if not isinstance(raw_sha, str) or not raw_sha:
        return [point]

    country = str(point.get("country") or "CA").lower()
    raw_dir = observations_dir.parent / "raw" / country / series_id
    raw_path = _raw_file_for_sha256(raw_dir, raw_sha)
    if raw_path is None:
        return [point]

    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [point]

    by_vector = _vector_values_for_period(payload, period)
    trim_vid, med_vid = 108785715, 108785714
    if trim_vid not in by_vector or med_vid not in by_vector:
        return [point]

    trim_val = by_vector[trim_vid]
    med_val = by_vector[med_vid]
    try:
        obs_val = float(point.get("value"))
    except (TypeError, ValueError):
        return [point]
    mean = (trim_val + med_val) / 2.0
    if not (math.isclose(mean, obs_val) or mean == obs_val):
        return [point]

    source_series_id = projection.source_series_id or ""
    source_tf = projection.source_transformation
    expanded: list[dict[str, Any]] = []
    for vid, value in ((trim_vid, trim_val), (med_vid, med_val)):
        component_id = _TRIM_MEDIAN_VECTOR_TO_COMPONENT[vid]
        row = dict(point)
        row["series_id"] = component_id
        row["value"] = value
        row["source_series_id"] = source_series_id
        row["source_transformation"] = source_tf
        expanded.append(row)
    return expanded


def expand_equal_mean_points(
    points: list[dict[str, Any]],
    *,
    observations_dir: Path,
    checked_at: str,
) -> list[dict[str, Any]]:
    """Split CPI trim/median aggregate observations into component score rows."""
    out: list[dict[str, Any]] = []
    for point in points:
        catalog_id = str(point.get("catalog_id") or point.get("id") or "")
        if catalog_id != "CA.Inflation.underlying":
            out.append(point)
            continue
        out.extend(
            _expand_underlying_point(point, observations_dir=observations_dir, checked_at=checked_at)
        )
    return out
