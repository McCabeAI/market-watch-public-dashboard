"""Stage verified macro observations into launch-local lineage (history + scores)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from scripts.country_registry import history_files
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.score_bridge import (
    points_from_observation_stores,
    recompute_scores_after_observation,
)
from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
)

LINEAGE_SUBDIR = "lineage"
HISTORY_SUBDIR = "history"
STAGED_SCORES_NAME = "temperature_scores.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(blob.encode("utf-8"))


def _finite_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _lineage_dir(launch_dir: Path) -> Path:
    return launch_dir / LINEAGE_SUBDIR


def staged_scores_path(launch_dir: Path) -> Path:
    return _lineage_dir(launch_dir) / STAGED_SCORES_NAME


def staged_history_dir(launch_dir: Path) -> Path:
    return _lineage_dir(launch_dir) / HISTORY_SUBDIR


def _copy_canonical_histories(canonical_history_dir: Path, staging_history_dir: Path) -> None:
    staging_history_dir.mkdir(parents=True, exist_ok=True)
    for _country, filename in history_files().items():
        src = canonical_history_dir / filename
        if src.is_file():
            shutil.copy2(src, staging_history_dir / filename)


def _filter_finite_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    for point in points:
        period = point.get("period")
        if period is None:
            continue
        if _finite_value(point.get("value")) is None:
            continue
        verified.append(point)
    return verified


def _provenance_record(point: dict[str, Any]) -> dict[str, Any]:
    value = _finite_value(point.get("value"))
    assert value is not None
    return {
        "country": str(point.get("country") or ""),
        "catalog_id": str(point.get("catalog_id") or point.get("id") or ""),
        "period": str(point.get("period")),
        "value": value,
        "transformation": str(point.get("transformation") or ""),
        "release_date": point.get("release_date"),
        "vintage": point.get("vintage"),
        "raw_sha256": point.get("raw_sha256"),
    }


def _provenance_sha256(records: list[dict[str, Any]]) -> str:
    return _sha256_json(records)


def _component_metric(state: dict[str, Any], catalog_id: str) -> dict[str, Any] | None:
    parts = catalog_id.split(".")
    if len(parts) != 3:
        return None
    country, dimension, component = parts
    try:
        block = state["countries"][country][dimension]["component_state"][component]
    except (KeyError, TypeError):
        return None
    if not isinstance(block, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("level", "impulse", "transform_value", "as_of"):
        if key in block and isinstance(block[key], (int, float, str)):
            out[key] = block[key]
    return out or None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _is_protected_destination(path: Path) -> bool:
    resolved = path.resolve()
    parts = resolved.parts
    if "evidence_snapshot" in parts:
        return True
    try:
        idx = parts.index("overnight")
        if idx + 1 < len(parts) and parts[idx + 1] == "runs":
            return True
    except ValueError:
        pass
    return False


def stage_verified_lineage(
    *,
    launch_dir: Path,
    checked_at: str,
    canonical_history_dir: Path,
    calibration_path: Path = CALIBRATION_PATH,
    points: list[dict[str, Any]] | None = None,
    observations_dir: Path | None = None,
    mode: str = "live",
) -> dict[str, Any]:
    """
    Copy canonical temperature histories into launch_dir/lineage/history, merge finite
    verified observation points, and persist recomputed scores under launch_dir/lineage/.
    """
    lineage_root = _lineage_dir(launch_dir)
    staging_history = staged_history_dir(launch_dir)
    scores_path = staged_scores_path(launch_dir)

    _copy_canonical_histories(canonical_history_dir, staging_history)
    working_histories = load_history(staging_history)
    calibration = load_calibration(calibration_path)

    baseline_state = build_score_state(calibration, compute_state(calibration, working_histories))

    if points is None:
        if observations_dir is None:
            raise ValueError("points or observations_dir required")
        catalog = load_catalog()
        raw_points = points_from_observation_stores(
            observations_dir=observations_dir,
            catalog=catalog,
            checked_at=checked_at,
        )
    else:
        raw_points = list(points)

    verified_points = _filter_finite_points(raw_points)

    before_metrics: dict[str, dict[str, Any] | None] = {}
    for point in verified_points:
        catalog_id = str(point.get("catalog_id") or point.get("id") or "")
        if catalog_id and catalog_id not in before_metrics:
            before_metrics[catalog_id] = _component_metric(baseline_state, catalog_id)

    bridge = recompute_scores_after_observation(
        persist_history=True,
        persist_scores=True,
        calibration_path=calibration_path,
        history_dir=staging_history,
        scores_path=scores_path,
        points=verified_points,
        checked_at=checked_at,
        histories=working_histories,
        paths_path=None,
    )

    if not bridge.ok or bridge.state is None:
        return {
            "ok": False,
            "checked_at": checked_at,
            "score_state_sha256": None,
            "provenance_sha256": _provenance_sha256([]),
            "appended_points": [],
            "component_deltas": [],
            "lineage_dir": str(lineage_root),
            "mode": mode,
            "error": bridge.score_recompute,
        }

    merge = bridge.merge or {}
    merge_appended = list(merge.get("appended") or [])

    if not scores_path.is_file():
        _write_json_atomic(scores_path, bridge.state)

    score_state_sha256 = _sha256_bytes(scores_path.read_bytes())

    appended_keys = {
        (
            str(item.get("id") or ""),
            str(item.get("reference_period") or ""),
            str(item.get("series_id") or ""),
            str(item.get("transformation") or ""),
        )
        for item in merge_appended
    }

    provenance_records: list[dict[str, Any]] = []
    appended_points: list[dict[str, Any]] = []
    for point in verified_points:
        catalog_id = str(point.get("catalog_id") or point.get("id") or "")
        key = (
            catalog_id,
            str(point.get("period") or ""),
            str(point.get("series_id") or ""),
            str(point.get("transformation") or ""),
        )
        if key not in appended_keys:
            continue
        record = _provenance_record(point)
        provenance_records.append(record)
        appended_points.append(
            {
                **record,
                "release_date": record.get("release_date"),
                "vintage": record.get("vintage"),
                "checked_at": checked_at,
            }
        )

    provenance_records.sort(
        key=lambda row: (
            row.get("country") or "",
            row.get("catalog_id") or "",
            row.get("period") or "",
            row.get("transformation") or "",
        )
    )
    provenance_sha256 = _provenance_sha256(provenance_records)

    component_deltas: list[dict[str, Any]] = []
    for item in merge_appended:
        catalog_id = str(item.get("id") or "")
        before = before_metrics.get(catalog_id)
        after = _component_metric(bridge.state, catalog_id)
        if before == after:
            continue
        component_deltas.append(
            {
                "catalog_id": catalog_id,
                "reference_period": item.get("reference_period"),
                "before": before,
                "after": after,
            }
        )

    return {
        "ok": True,
        "checked_at": checked_at,
        "score_state_sha256": score_state_sha256,
        "provenance_sha256": provenance_sha256,
        "appended_points": appended_points,
        "appended_count": len(appended_points),
        "component_deltas": component_deltas,
        "lineage_dir": str(lineage_root),
        "mode": mode,
    }


def apply_lineage_to_macro_hard(
    families: dict[str, Any],
    launch_dir: Path,
    lineage_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    scores_path = staged_scores_path(launch_dir)
    if not scores_path.is_file():
        return families
    scores = json.loads(scores_path.read_text(encoding="utf-8"))
    summary = lineage_summary or {}
    out = dict(families)
    macro = dict(out.get("macro_hard") or {})
    extra = dict(macro.get("extra") or {})
    extra["temperature_scores"] = scores
    extra["score_lineage"] = {
        "provenance_sha256": summary.get("provenance_sha256"),
        "checked_at": summary.get("checked_at"),
        "appended": summary.get("appended_points") or [],
    }
    macro["extra"] = extra
    digest = summary.get("score_state_sha256")
    if isinstance(digest, str) and digest:
        macro["digest"] = digest
    out["macro_hard"] = macro
    return out


def promote_staged_lineage(
    staging_dir: Path,
    canonical_history_dir: Path,
    canonical_scores_path: Path,
    *,
    promote: bool = False,
    mode: str = "live",
) -> dict[str, Any]:
    if not promote:
        return {"promoted": False, "reason": "promote_not_requested"}
    if mode == "fixture":
        raise ValueError("fixture lineage cannot be promoted to canonical data")
    if _is_protected_destination(canonical_history_dir) or _is_protected_destination(canonical_scores_path):
        raise ValueError("refuse promotion into protected overnight or evidence paths")

    history_src = staging_dir / HISTORY_SUBDIR
    scores_src = staging_dir / STAGED_SCORES_NAME
    if not history_src.is_dir() or not scores_src.is_file():
        raise ValueError("staged lineage incomplete")

    for _country, filename in history_files().items():
        src = history_src / filename
        if not src.is_file():
            continue
        dest = canonical_history_dir / filename
        if _is_protected_destination(dest):
            raise ValueError("refuse promotion into protected overnight or evidence paths")
        shutil.copy2(src, dest)

    if _is_protected_destination(canonical_scores_path):
        raise ValueError("refuse promotion into protected overnight or evidence paths")
    _write_json_atomic(canonical_scores_path, json.loads(scores_src.read_text(encoding="utf-8")))

    return {"promoted": True, "scores_path": str(canonical_scores_path)}
