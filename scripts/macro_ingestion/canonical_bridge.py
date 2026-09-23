"""Merge macro-ingestion observations into temperature history for scoring."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from scripts.country_registry import history_files
from scripts.macro_freshness import values_close
from scripts.temperature_level import (
    build_paths,
    build_score_state,
    compute_state,
    load_calibration,
    parse_period,
    period_sort_key,
    validate_state,
)

_FLASH_REVISION = frozenset({"flash", "preliminary", "prelim"})
_ZERO_WEIGHT_ROLES = frozenset({"context", "registry_unweighted", "explanatory_alias"})


def period_after(period: str) -> str:
    kind, year, num = parse_period(period)
    if kind == "Q":
        quarter = num // 3
        if quarter >= 4:
            return f"{year + 1}-Q1"
        return f"{year}-Q{quarter + 1}"
    if num >= 12:
        return f"{year + 1}-01"
    return f"{year}-{num + 1:02d}"


def _finite_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _component_weight(calibration: dict[str, Any], catalog_id: str) -> float:
    parts = catalog_id.split(".")
    if len(parts) != 3:
        return 0.0
    country, dimension, component = parts
    try:
        return float(calibration["weights"][country][dimension][component])
    except (KeyError, TypeError, ValueError):
        return 0.0


def _series_allowed(spec: dict[str, Any], series_id: str | None) -> bool:
    if not series_id:
        return False
    if "series_ids" in spec:
        return series_id in spec["series_ids"]
    expected = spec.get("series_id")
    if expected is None:
        return True
    return series_id == expected


def _matching_rows(
    observations: list[dict[str, Any]], *, transformation: str, series_id: str
) -> list[dict[str, Any]]:
    return [
        obs
        for obs in observations
        if obs.get("transformation") == transformation and obs.get("series_id") == series_id
    ]


def _latest_template(
    observations: list[dict[str, Any]], *, transformation: str, series_id: str
) -> dict[str, Any] | None:
    template: dict[str, Any] | None = None
    for obs in observations:
        if obs.get("transformation") == transformation and obs.get("series_id") == series_id:
            template = obs
    return template


def _latest_period(
    observations: list[dict[str, Any]], *, transformation: str, series_id: str
) -> str | None:
    rows = _matching_rows(observations, transformation=transformation, series_id=series_id)
    if not rows:
        return None
    return max((str(r["reference_period"]) for r in rows), key=period_sort_key)


def _skip_id(point: dict[str, Any]) -> str:
    return str(point.get("catalog_id") or point.get("id") or "unknown")


def merge_scored_points(
    histories: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    points: list[dict[str, Any]],
    *,
    checked_at: str,
) -> dict[str, Any]:
    cal_as_of = str(calibration.get("as_of") or "")
    appended: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    countries_changed: set[str] = set()

    for point in points:
        point_id = _skip_id(point)
        role = str(point.get("role") or "")
        catalog_id = str(point.get("catalog_id") or point_id)
        weight = _component_weight(calibration, catalog_id)
        if role != "scored" or weight == 0.0:
            skipped.append({"id": point_id, "reason": "context_not_scored"})
            continue
        if catalog_id == "US.Inflation.mapped_bridge":
            skipped.append({"id": point_id, "reason": "context_not_scored"})
            continue

        spec = calibration.get("components", {}).get(catalog_id)
        if not isinstance(spec, dict):
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        country = str(point.get("country") or catalog_id.split(".", 1)[0])
        history = histories.get(country)
        if not isinstance(history, dict):
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        history_key = spec.get("history_key")
        comp = (history.get("components") or {}).get(history_key)
        if not isinstance(comp, dict):
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        breaks = comp.get("methodology_breaks")
        if isinstance(breaks, list) and breaks:
            skipped.append({"id": point_id, "reason": "methodology_break_guard"})
            continue

        period = point.get("period")
        if not isinstance(period, str):
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue
        try:
            parse_period(period)
        except ValueError:
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        value = _finite_value(point.get("value"))
        if value is None:
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        series_id = point.get("series_id")
        if not isinstance(series_id, str) or not series_id:
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        src_tf = str(spec.get("source_transformation") or "")
        transformation = str(point.get("transformation") or "")
        if transformation != src_tf:
            skipped.append({"id": point_id, "reason": "partial_transform_mismatch"})
            continue

        if not _series_allowed(spec, series_id):
            skipped.append({"id": point_id, "reason": "partial_series_mismatch"})
            continue

        observations = comp.setdefault("observations", [])
        matching = _matching_rows(observations, transformation=transformation, series_id=series_id)
        same_period = [r for r in matching if r.get("reference_period") == period]

        if same_period:
            for row in same_period:
                existing_value = _finite_value(row.get("value"))
                if existing_value is not None and values_close(existing_value, value):
                    skipped.append({"id": point_id, "reason": "duplicate_value"})
                    break
            else:
                incoming_rev = str(point.get("revision_status") or "")
                if incoming_rev in _FLASH_REVISION and any(
                    str(r.get("revision_status") or "") == "final" for r in same_period
                ):
                    skipped.append({"id": point_id, "reason": "final_not_superseded_by_flash"})
                else:
                    template = _latest_template(
                        observations, transformation=transformation, series_id=series_id
                    )
                    if template is None:
                        skipped.append({"id": point_id, "reason": "partial_malformed"})
                    else:
                        _append_row(
                            observations,
                            template=template,
                            point=point,
                            period=period,
                            value=value,
                            series_id=series_id,
                            transformation=transformation,
                            checked_at=checked_at,
                            cal_as_of=cal_as_of,
                        )
                        entry = {
                            "id": catalog_id,
                            "country": country,
                            "history_key": history_key,
                            "reference_period": period,
                            "series_id": series_id,
                            "transformation": transformation,
                        }
                        appended.append(entry)
                        countries_changed.add(country)
            continue

        latest = _latest_period(
            observations, transformation=transformation, series_id=series_id
        )
        if latest is None:
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue
        if period_sort_key(period) <= period_sort_key(latest):
            skipped.append({"id": point_id, "reason": "not_a_forward_observation"})
            continue

        template = _latest_template(
            observations, transformation=transformation, series_id=series_id
        )
        if template is None:
            skipped.append({"id": point_id, "reason": "partial_malformed"})
            continue

        _append_row(
            observations,
            template=template,
            point=point,
            period=period,
            value=value,
            series_id=series_id,
            transformation=transformation,
            checked_at=checked_at,
            cal_as_of=cal_as_of,
        )
        entry = {
            "id": catalog_id,
            "country": country,
            "history_key": history_key,
            "reference_period": period,
            "series_id": series_id,
            "transformation": transformation,
        }
        appended.append(entry)
        countries_changed.add(country)

    return {
        "appended": appended,
        "skipped": skipped,
        "countries_changed": sorted(countries_changed),
    }


def _append_row(
    observations: list[dict[str, Any]],
    *,
    template: dict[str, Any],
    point: dict[str, Any],
    period: str,
    value: float,
    series_id: str,
    transformation: str,
    checked_at: str,
    cal_as_of: str,
) -> None:
    row = dict(template)
    row.pop("calibration_lookback", None)
    row.pop("notes", None)
    row["reference_period"] = period
    row["value"] = value
    row["series_id"] = series_id
    row["transformation"] = transformation
    row["retrieved_at"] = checked_at
    vintage = point.get("vintage")
    if not isinstance(vintage, str) or not vintage or vintage == cal_as_of:
        vintage = "latest_available"
    row["vintage"] = vintage
    rev = point.get("revision_status")
    if rev is not None:
        row["revision_status"] = rev
    source_url = point.get("source_url")
    if isinstance(source_url, str) and source_url:
        row["source_url"] = source_url
    release_date = point.get("release_date")
    if isinstance(release_date, str) and release_date and release_date != cal_as_of:
        row["release_date"] = release_date
    observations.append(row)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def persist_if_changed(
    histories: dict[str, dict[str, Any]],
    *,
    appended: list[dict[str, Any]],
    history_dir: Path,
    scores_path: Path,
    paths_path: Path | None,
    calibration_path: Path,
) -> dict[str, Any]:
    if not appended:
        return {"persisted": False}

    cal_before = calibration_path.read_bytes()
    names = history_files()
    countries = sorted({str(item["country"]) for item in appended})
    for country in countries:
        filename = names.get(country)
        if not filename:
            continue
        _write_json(history_dir / filename, histories[country])

    cal_mid = calibration_path.read_bytes()
    if cal_mid != cal_before:
        raise RuntimeError("calibration bytes changed after history write")

    cal = load_calibration(calibration_path)
    computed = compute_state(cal, histories)
    state = build_score_state(cal, computed)
    validate_state(state)
    _write_json(scores_path, state)

    if paths_path is not None:
        paths_doc = build_paths(cal, histories)
        _write_json(paths_path, paths_doc)

    cal_after = calibration_path.read_bytes()
    if cal_after != cal_before:
        raise RuntimeError("calibration bytes changed after score persist")

    return {"persisted": True, "countries": countries}
