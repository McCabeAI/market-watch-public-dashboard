"""Recompute temperature LEVEL scores after verified macro observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.macro_ingestion.canonical_bridge import merge_scored_points, persist_if_changed
from scripts.macro_ingestion.contract import COUNTRY_CODES, index_series_rows, load_catalog
from scripts.macro_ingestion.vintage import load_store
from scripts.temperature_level import (
    CALIBRATION_PATH,
    HISTORY_DIR,
    PATHS_PATH,
    STATE_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
)

ROOT = Path(__file__).resolve().parents[2]
OBSERVATIONS_DIR = ROOT / "data/macro_ingestion/observations"


@dataclass
class ScoreRecomputeResult:
    ok: bool
    score_recompute: str | None = None
    state: dict[str, Any] | None = None
    merge: dict[str, Any] | None = None


def _utc_iso(when: datetime | None = None) -> str:
    stamp = when or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _catalog_lookup(catalog: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in catalog.get("series") or []:
        country = str(row.get("country") or "")
        series_id = str(row.get("series_id") or "")
        transform = str(row.get("transform") or "")
        if country and series_id and transform:
            by_key[(country, series_id, transform)] = row
    return by_key


def points_from_observation_stores(
    *,
    observations_dir: Path,
    catalog: dict[str, Any] | None = None,
    checked_at: str,
) -> list[dict[str, Any]]:
    catalog = catalog or load_catalog()
    lookup = _catalog_lookup(catalog)
    by_id = index_series_rows(catalog["series"])
    points: list[dict[str, Any]] = []

    for country in COUNTRY_CODES:
        store = load_store(country, observations_dir)
        for obs in store.get("observations") or []:
            series_id = obs.get("series_id")
            transformation = obs.get("transformation")
            if not isinstance(series_id, str) or not isinstance(transformation, str):
                continue
            row = lookup.get((country, series_id, transformation))
            if row is None:
                continue
            catalog_id = str(row["id"])
            spec_row = by_id.get(catalog_id, row)
            points.append(
                {
                    "country": country,
                    "catalog_id": catalog_id,
                    "role": spec_row.get("role"),
                    "series_id": series_id,
                    "period": obs.get("period"),
                    "value": obs.get("value"),
                    "transformation": transformation,
                    "revision_status": obs.get("revision_status"),
                    "source_url": obs.get("source_url"),
                    "raw_sha256": obs.get("raw_sha256"),
                    "vintage": obs.get("vintage"),
                    "release_date": obs.get("release_date"),
                    "retrieved_at": obs.get("retrieved_at") or checked_at,
                }
            )
    return points


def recompute_scores_after_observation(
    *,
    persist_scores: bool = False,
    persist_history: bool = False,
    calibration_path: Path = CALIBRATION_PATH,
    history_dir: Path = HISTORY_DIR,
    observations_dir: Path | None = None,
    points: list[dict[str, Any]] | None = None,
    checked_at: str | None = None,
    scores_path: Path = STATE_PATH,
    paths_path: Path | None = PATHS_PATH,
    histories: dict[str, dict[str, Any]] | None = None,
) -> ScoreRecomputeResult:
    """
    Merge ingestion observations into in-memory history, then recompute scores.

    Calibration bytes are never modified here. History and score persistence are opt-in.
    """
    stamp = checked_at or _utc_iso()
    cal_before = calibration_path.read_bytes()
    cal = load_calibration(calibration_path)
    working_histories = histories if histories is not None else load_history(history_dir)

    if points is None:
        obs_dir = observations_dir or OBSERVATIONS_DIR
        points = points_from_observation_stores(observations_dir=obs_dir, checked_at=stamp)

    merge_result = merge_scored_points(working_histories, cal, points, checked_at=stamp)

    if merge_result["appended"] and (persist_history or persist_scores):
        try:
            persist_if_changed(
                working_histories,
                appended=merge_result["appended"],
                history_dir=history_dir,
                scores_path=scores_path,
                paths_path=paths_path if persist_scores else None,
                calibration_path=calibration_path,
            )
        except RuntimeError as exc:
            return ScoreRecomputeResult(
                ok=False,
                score_recompute=str(exc),
                merge=merge_result,
            )

    cal_after = calibration_path.read_bytes()
    if cal_after != cal_before:
        return ScoreRecomputeResult(
            ok=False,
            score_recompute="blocked_calibration_lock",
            merge=merge_result,
        )

    computed = compute_state(cal, working_histories)
    state = build_score_state(cal, computed)

    return ScoreRecomputeResult(ok=True, state=state, merge=merge_result)
