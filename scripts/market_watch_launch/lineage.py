"""Stage verified macro observations into launch-local lineage (history + scores)."""

from __future__ import annotations

import copy
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
from scripts.macro_ingestion.semantic_guards import implausible_nz_employment_qoq_values
from scripts.macro_ingestion.ca_score_identity import expand_equal_mean_points
from scripts.macro_ingestion.canonical_bridge import _skip_id
from scripts.macro_ingestion.score_bridge import (
    points_from_observation_stores,
    recompute_scores_after_observation,
)
from scripts.temperature_level import period_sort_key
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

_BLOCKING_SKIP_REASONS = frozenset({"partial_transform_mismatch", "partial_series_mismatch"})
_NON_BLOCKING_SKIP_REASONS = frozenset(
    {
        "duplicate_value",
        "context_not_scored",
        "not_a_forward_observation",
        "methodology_break_guard",
        "final_not_superseded_by_flash",
        "retired_unobserved",
    }
)


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


def _latest_history_period(
    histories: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    catalog_id: str,
) -> str | None:
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
    series_id = str(spec.get("series_id") or "")
    periods: list[str] = []
    for obs in comp.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        if str(obs.get("transformation") or "") != src_tf:
            continue
        if series_id and obs.get("series_id") and str(obs.get("series_id")) != series_id:
            continue
        period = obs.get("reference_period") or obs.get("period")
        if isinstance(period, str):
            periods.append(period)
    if not periods:
        return None
    return max(periods, key=period_sort_key)


def _point_merge_outcome(
    point: dict[str, Any],
    *,
    appended: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    append_index: int,
    skip_index: int,
) -> tuple[str | None, dict[str, Any] | None, int, int]:
    """Return (skip_reason, append_entry, next_append_index, next_skip_index)."""
    catalog_id = str(point.get("catalog_id") or point.get("id") or "")
    period = str(point.get("period") or "")
    series_id = str(point.get("series_id") or "")
    transformation = str(point.get("transformation") or "")

    if append_index < len(appended):
        entry = appended[append_index]
        if (
            str(entry.get("id") or "") == catalog_id
            and str(entry.get("reference_period") or "") == period
            and str(entry.get("series_id") or "") == series_id
            and str(entry.get("transformation") or "") == transformation
        ):
            return None, entry, append_index + 1, skip_index

    if skip_index < len(skipped) and str(skipped[skip_index].get("id") or "") == _skip_id(point):
        reason = str(skipped[skip_index].get("reason") or "")
        return reason, None, append_index, skip_index + 1

    return "unknown", None, append_index, skip_index


def _scored_lineage_rejections(
    *,
    points: list[dict[str, Any]],
    merge: dict[str, Any],
    histories_before_merge: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
) -> list[dict[str, Any]]:
    appended = list(merge.get("appended") or [])
    skipped = list(merge.get("skipped") or [])
    rejections: list[dict[str, Any]] = []
    ai = 0
    si = 0

    for point in points:
        role = str(point.get("role") or "")
        catalog_id = str(point.get("catalog_id") or point.get("id") or "")
        reason, entry, ai, si = _point_merge_outcome(
            point, appended=appended, skipped=skipped, append_index=ai, skip_index=si
        )
        if role != "scored":
            continue
        period = str(point.get("period") or "")
        series_id = str(point.get("series_id") or "")
        transformation = str(point.get("transformation") or "")

        if entry is not None:
            continue

        skip_reason = reason or "unknown"
        if skip_reason in _NON_BLOCKING_SKIP_REASONS:
            continue

        # Block only a new release. A historical replay whose catalog transform
        # already differs from calibration (for example AU.Consumer.confidence)
        # must not fail an otherwise valid launch.
        latest = _latest_history_period(histories_before_merge, calibration, catalog_id)
        newer = bool(
            latest is not None and period and period_sort_key(period) > period_sort_key(latest)
        )
        blocking = newer and (
            skip_reason in _BLOCKING_SKIP_REASONS or skip_reason != "duplicate_value"
        )
        if not blocking:
            continue

        rejections.append(
            {
                "id": catalog_id,
                "reason": skip_reason,
                "series_id": series_id,
                "transformation": transformation,
                "period": period,
            }
        )

    return rejections


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
    record: dict[str, Any] = {
        "country": str(point.get("country") or ""),
        "catalog_id": str(point.get("catalog_id") or point.get("id") or ""),
        "period": str(point.get("period")),
        "value": value,
        "transformation": str(point.get("transformation") or ""),
        "release_date": point.get("release_date"),
        "vintage": point.get("vintage"),
        "raw_sha256": point.get("raw_sha256"),
    }
    src_series = point.get("source_series_id")
    if isinstance(src_series, str) and src_series:
        record["source_series_id"] = src_series
    src_tf = point.get("source_transformation")
    if isinstance(src_tf, str) and src_tf:
        record["source_transformation"] = src_tf
    return record


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
    _write_bytes_atomic(path, text.encode("utf-8"))


def _destination_snapshot(path: Path) -> bytes | None:
    if path.is_file():
        return path.read_bytes()
    return None


def _restore_destination(path: Path, prior: bytes | None) -> None:
    if prior is None:
        if path.is_file():
            path.unlink()
        return
    _write_bytes_atomic(path, prior)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _rollback_promotion(snapshots: list[tuple[Path, bytes | None]]) -> None:
    first_error: BaseException | None = None
    for path, prior in reversed(snapshots):
        try:
            _restore_destination(path, prior)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


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
    histories_before_merge = copy.deepcopy(working_histories)
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
    if observations_dir is not None:
        verified_points = expand_equal_mean_points(
            verified_points,
            observations_dir=observations_dir,
            checked_at=checked_at,
        )

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
            "appended_count": 0,
            "rejections": [],
            "component_deltas": [],
            "lineage_dir": str(lineage_root),
            "mode": mode,
            "error": bridge.score_recompute,
        }

    merge = bridge.merge or {}
    merge_appended = list(merge.get("appended") or [])
    rejections = _scored_lineage_rejections(
        points=verified_points,
        merge=merge,
        histories_before_merge=histories_before_merge,
        calibration=calibration,
    )
    if rejections:
        _copy_canonical_histories(canonical_history_dir, staging_history)
        if scores_path.is_file():
            scores_path.unlink()
        return {
            "ok": False,
            "checked_at": checked_at,
            "score_state_sha256": None,
            "provenance_sha256": _provenance_sha256([]),
            "appended_points": [],
            "appended_count": 0,
            "rejections": rejections,
            "component_deltas": [],
            "lineage_dir": str(lineage_root),
            "mode": mode,
            "error": "score_lineage_rejected",
        }

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
        "rejections": [],
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


class CanonicalScorePromotionError(ValueError):
    """Accepted lineage could not be written to canonical score state."""


def promote_accepted_launch_lineage(
    *,
    launch_dir: Path,
    canonical_history_dir: Path,
    canonical_scores_path: Path,
    mode: str,
    accepted: bool,
    recorded_score_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy staged history and scores into canonical state after acceptance.

    Fixture mode and any launch that is not accepted return without writing.
    A live accepted launch with missing or mismatched lineage fails loudly
    instead of leaving the previous canonical scores in place.
    """
    if not accepted:
        return {"promoted": False, "ok": True, "reason": "launch_not_accepted"}
    if mode != "live":
        return {"promoted": False, "ok": True, "reason": "non_live_mode"}

    staging = launch_dir / LINEAGE_SUBDIR
    scores_src = staging / STAGED_SCORES_NAME
    history_src = staging / HISTORY_SUBDIR
    if not history_src.is_dir() or not scores_src.is_file():
        raise CanonicalScorePromotionError("accepted launch is missing staged score lineage")

    digest = _sha256_bytes(scores_src.read_bytes())
    if recorded_score_sha256 and digest != recorded_score_sha256:
        raise CanonicalScorePromotionError(
            "staged score state does not match the accepted lineage digest"
        )
    staged_doc = json.loads(scores_src.read_text(encoding="utf-8"))
    result = promote_staged_lineage(
        staging,
        canonical_history_dir,
        canonical_scores_path,
        promote=True,
        mode="live",
        verify_scores_document=staged_doc,
    )
    result["ok"] = True
    result["score_state_sha256"] = digest
    return result


def promote_staged_lineage(
    staging_dir: Path,
    canonical_history_dir: Path,
    canonical_scores_path: Path,
    *,
    promote: bool = False,
    mode: str = "live",
    verify_scores_document: dict[str, Any] | None = None,
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

    filenames = list(history_files().values())
    staged_histories: list[tuple[str, bytes]] = []
    for filename in filenames:
        src = history_src / filename
        if not src.is_file():
            raise ValueError(f"staged history file missing: {filename}")
        dest = canonical_history_dir / filename
        if _is_protected_destination(dest):
            raise ValueError("refuse promotion into protected overnight or evidence paths")
        staged_histories.append((filename, src.read_bytes()))

    for filename, data in staged_histories:
        if filename != "nz.json":
            continue
        try:
            nz_doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanonicalScorePromotionError("staged NZ history is not valid JSON") from exc
        if not isinstance(nz_doc, dict):
            raise CanonicalScorePromotionError("staged NZ history is not valid JSON")
        bad_values = implausible_nz_employment_qoq_values(nz_doc)
        if bad_values:
            raise CanonicalScorePromotionError(
                "staged NZ employment change is an employment level, not a quarterly change"
            )

    if _is_protected_destination(canonical_scores_path):
        raise ValueError("refuse promotion into protected overnight or evidence paths")

    scores_payload = json.loads(scores_src.read_text(encoding="utf-8"))
    snapshots: list[tuple[Path, bytes | None]] = []
    for filename, _data in staged_histories:
        snapshots.append((canonical_history_dir / filename, _destination_snapshot(canonical_history_dir / filename)))
    snapshots.append((canonical_scores_path, _destination_snapshot(canonical_scores_path)))

    try:
        for filename, data in staged_histories:
            _write_bytes_atomic(canonical_history_dir / filename, data)
        _write_json_atomic(canonical_scores_path, scores_payload)
        if verify_scores_document is not None:
            written = json.loads(canonical_scores_path.read_text(encoding="utf-8"))
            if written != verify_scores_document:
                _rollback_promotion(snapshots)
                raise CanonicalScorePromotionError(
                    "canonical score state does not match staged lineage after promotion"
                )
    except CanonicalScorePromotionError:
        raise
    except Exception:
        _rollback_promotion(snapshots)
        raise

    return {"promoted": True, "scores_path": str(canonical_scores_path)}
