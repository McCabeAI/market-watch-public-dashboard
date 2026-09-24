"""Stage 01: six-country macro ingestion (live or canonical-history fixture replay)."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.macro_ingestion.calendar import latest_due_release, release_due as calendar_release_due
from scripts.macro_ingestion.contract import index_series_rows, load_catalog
from scripts.macro_ingestion.retries import DEFAULT_ATTEMPTS
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.vintage import latest_period_in_store, load_store
from scripts.market_watch_launch.contract import COUNTRIES, stage_receipt
from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.temperature_level import HISTORY_DIR, load_history

_STAGE = "01_ingest"
_LAUNCH_COUNTRIES = tuple(COUNTRIES)

_NON_RETRY_ERRORS = frozenset({"license_gap", "mapped_bridge_transform_not_wired"})


def load_ingestion_rows(details: dict[str, Any]) -> list[dict[str, Any]]:
    rows = details.get("rows")
    return list(rows) if isinstance(rows, list) else []


def _utc_iso(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_json(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _history_component(history: dict[str, Any], catalog_row: dict[str, Any]) -> dict[str, Any]:
    parts = str(catalog_row["id"]).split(".", 1)
    if len(parts) != 2:
        return {}
    key = parts[1]
    return (history.get("components") or {}).get(key) or {}


def _finite_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _latest_finite_observation(
    comp: dict[str, Any], *, transformation: str, series_id: str | None
) -> tuple[str, float] | None:
    preferred = transformation or str(comp.get("preferred_scoring_transformation") or "")
    candidates: list[tuple[str, float]] = []
    for obs in comp.get("observations") or []:
        if series_id and obs.get("series_id") and str(obs.get("series_id")) != series_id:
            continue
        period = obs.get("reference_period") or obs.get("period")
        value = _finite_value(obs.get("value"))
        if period is None or value is None:
            continue
        obs_transform = str(obs.get("transformation") or "")
        if preferred and obs_transform != preferred:
            continue
        candidates.append((str(period), value))
    if not candidates and preferred:
        for obs in comp.get("observations") or []:
            if series_id and obs.get("series_id") and str(obs.get("series_id")) != series_id:
                continue
            period = obs.get("reference_period") or obs.get("period")
            value = _finite_value(obs.get("value"))
            if period is None or value is None:
                continue
            candidates.append((str(period), value))
    if not candidates:
        return None
    period, value = max(candidates, key=lambda item: item[0])
    return period, value


def _enrich_row(
    raw: dict[str, Any],
    spec: dict[str, Any],
    *,
    when: datetime,
    observations_dir: Path | None,
    observation_period: str | None = None,
    provenance: str | None = None,
) -> dict[str, Any]:
    series_id = str(raw.get("series_id") or spec["id"])
    transform = str(spec.get("transform") or "")
    obs_series = str(spec.get("series_id") or series_id)
    country = str(spec.get("country") or "")

    due_info = latest_due_release(spec, when)
    due_period = str(due_info["period"]) if due_info and due_info.get("period") else None
    is_due = calendar_release_due(spec, when)

    if observation_period is None and observations_dir is not None:
        store = load_store(country, observations_dir)
        observation_period = latest_period_in_store(store, obs_series, transform)

    row = {
        "series_id": series_id,
        "country": country,
        "role": spec.get("role"),
        "status": raw.get("status"),
        "release_due": bool(is_due),
        "observation_period": observation_period,
        "due_period": due_period,
        "weight": spec.get("weight"),
        "provenance": provenance or raw.get("provenance"),
        "error": raw.get("error"),
    }
    if provenance == "canonical_history_fixture":
        row["release_due"] = False
        if observation_period and not row["due_period"]:
            row["due_period"] = observation_period
    return row


def _score_bridge_payload(lineage: dict[str, Any]) -> dict[str, Any]:
    appended = lineage.get("appended_points") or []
    summary = f"appended={len(appended)}"
    payload: dict[str, Any] = {"ok": bool(lineage.get("ok")), "summary": summary}
    if lineage.get("score_state_sha256"):
        payload["state_sha256"] = lineage["score_state_sha256"]
    return payload


def _gap_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status in {"due_missing", "source_failed", "incomplete_country", "license_gap", "calendar_unparsed"}:
            gaps.append(
                {
                    "series_id": row.get("series_id"),
                    "country": row.get("country"),
                    "status": status,
                    "error": row.get("error"),
                }
            )
    return gaps


def _lineage_details(lineage: dict[str, Any]) -> dict[str, Any]:
    return {
        "score_state_sha256": lineage.get("score_state_sha256"),
        "provenance_sha256": lineage.get("provenance_sha256"),
        "appended_count": lineage.get("appended_count", 0),
        "checked_at": lineage.get("checked_at"),
        "appended_points": lineage.get("appended_points") or [],
        "lineage_dir": lineage.get("lineage_dir"),
    }


def _canonical_history_dir(root: Path) -> Path:
    history_dir = root / "data" / "temperature_history"
    if history_dir.is_dir():
        return history_dir
    return HISTORY_DIR


def _row_fetch_attempts(row: dict[str, Any], *, configured_attempts: int = DEFAULT_ATTEMPTS) -> int:
    error = str(row.get("error") or "")
    status = str(row.get("status") or "")
    if error == "budget_deferred":
        return 0
    if status in {"incomplete_country", "calendar_unparsed"} and not error:
        return 0
    return configured_attempts


def _should_retry_live_row(row: dict[str, Any]) -> bool:
    error = str(row.get("error") or "")
    if error in _NON_RETRY_ERRORS:
        return False
    if "HTTP 404" in error:
        return False
    if error == "budget_deferred":
        return True
    if "timed out" in error.lower():
        return True
    return False


def _merge_ingestion_rows(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    attempts: dict[str, int],
) -> list[dict[str, Any]]:
    by_id = {str(row["series_id"]): dict(row) for row in primary}
    for row in secondary:
        sid = str(row["series_id"])
        merged = dict(row)
        merged["attempts"] = attempts.get(sid, _row_fetch_attempts(row))
        by_id[sid] = merged
    for sid, row in by_id.items():
        row.setdefault("attempts", attempts.get(sid, _row_fetch_attempts(row)))
    return list(by_id.values())


def _build_source_matrix(
    rows: list[dict[str, Any]],
    catalog_series: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    by_id = index_series_rows(catalog_series)
    matrix: list[dict[str, Any]] = []
    for row in rows:
        spec = by_id.get(str(row.get("series_id")))
        error = row.get("error")
        error_text = str(error) if error is not None else ""
        matrix.append(
            {
                "series_id": row.get("series_id"),
                "country": row.get("country"),
                "status": row.get("status"),
                "error": error,
                "attempts": row.get("attempts", _row_fetch_attempts(row)),
                "endpoint": spec.get("endpoint") if spec else None,
                "http_403": "HTTP 403" in error_text,
            }
        )
    matrix.sort(key=lambda item: (str(item.get("country") or ""), str(item.get("series_id") or "")))
    return matrix, _sha256_json(matrix)


def _fixture_ingestion(
    *,
    root: Path,
    launch_dir: Path,
    when: datetime,
    checked_at: str,
) -> tuple[dict[str, Any], str, str | None]:
    catalog = load_catalog()
    history_dir = _canonical_history_dir(root)
    histories = load_history(history_dir)

    observations_dir = launch_dir / "ingestion" / "observations"
    observations_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    replay_points: list[dict[str, Any]] = []
    countries_with_scored: set[str] = set()

    for spec in catalog["series"]:
        country = str(spec.get("country") or "")
        if country not in _LAUNCH_COUNTRIES:
            continue
        catalog_id = str(spec["id"])
        transform = str(spec.get("transform") or "")
        comp = _history_component(histories.get(country) or {}, spec)
        latest = _latest_finite_observation(comp, transformation=transform, series_id=spec.get("series_id"))

        if latest is not None:
            period, value = latest
            raw = {
                "series_id": catalog_id,
                "status": "checked_unchanged",
                "error": None,
            }
            row = _enrich_row(
                raw,
                spec,
                when=when,
                observations_dir=None,
                observation_period=period,
                provenance="canonical_history_fixture",
            )
            if str(spec.get("role") or "") == "scored":
                countries_with_scored.add(country)
                replay_points.append(
                    {
                        "country": country,
                        "catalog_id": catalog_id,
                        "role": spec.get("role"),
                        "series_id": str(spec.get("series_id") or catalog_id),
                        "period": period,
                        "value": value,
                        "transformation": transform,
                    }
                )
        else:
            status = "license_gap" if str(spec.get("role") or "") != "scored" else "due_missing"
            raw = {"series_id": catalog_id, "status": status, "error": "no_canonical_history_point"}
            row = _enrich_row(raw, spec, when=when, observations_dir=None, provenance="canonical_history_fixture")

        rows.append(row)

    lineage = stage_verified_lineage(
        launch_dir=launch_dir,
        checked_at=checked_at,
        canonical_history_dir=history_dir,
        points=replay_points,
        mode="fixture",
    )
    score_bridge = _score_bridge_payload(lineage)

    missing_countries = [c for c in _LAUNCH_COUNTRIES if c not in countries_with_scored]
    if missing_countries:
        status = "failed"
        reason = "missing_country_history"
    elif not lineage.get("ok"):
        status = "failed"
        reason = "score_bridge_failed"
    else:
        status = "succeeded"
        reason = None

    details = {
        "mode": "fixture",
        "countries": list(_LAUNCH_COUNTRIES),
        "rows": rows,
        "gaps": _gap_entries(rows),
        "score_bridge": score_bridge,
        "lineage": _lineage_details(lineage),
        "live_fetch": False,
        "invented_values": False,
        "checked_at": checked_at,
        "cutoff_class": None,
    }
    if missing_countries:
        details["missing_countries"] = missing_countries
    return details, status, reason


def _live_ingestion(
    *,
    launch_dir: Path,
    when: datetime,
    launch_id: str | None,
    root: Path,
) -> tuple[dict[str, Any], str]:
    base = launch_dir / "ingestion"
    observations_dir = base / "observations"
    health_dir = base / "health"
    raw_dir = base / "raw"
    for path in (observations_dir, health_dir, raw_dir):
        path.mkdir(parents=True, exist_ok=True)

    result = run_ingestion(
        mode="live",
        countries=list(_LAUNCH_COUNTRIES),
        now=when,
        run_id=launch_id,
        persist_canonical=False,
        observations_dir=observations_dir,
        health_dir=health_dir,
        raw_dir=raw_dir,
        # Breadth first: try every scored series once before spending the
        # remaining budget retrying flaky sources.
        timeout_seconds=10,
        country_budget_seconds=180,
        run_budget_seconds=15 * 60,
        attempts=1,
    )
    if not result.get("rows"):
        raise RuntimeError("ingestion returned no rows")

    attempts: dict[str, int] = {}
    for row in result["rows"]:
        sid = str(row["series_id"])
        attempts[sid] = _row_fetch_attempts(row, configured_attempts=1)

    retry_ids = {
        str(row["series_id"])
        for row in result["rows"]
        if _should_retry_live_row(row)
    }
    if retry_ids:
        retry_result = run_ingestion(
            mode="live",
            countries=list(_LAUNCH_COUNTRIES),
            now=when,
            run_id=launch_id,
            persist_canonical=False,
            observations_dir=observations_dir,
            health_dir=health_dir,
            raw_dir=raw_dir,
            timeout_seconds=20,
            country_budget_seconds=120,
            run_budget_seconds=8 * 60,
            only_series_ids=retry_ids,
            attempts=2,
        )
        for row in retry_result.get("rows") or []:
            sid = str(row["series_id"])
            attempts[sid] = attempts.get(sid, 0) + _row_fetch_attempts(row, configured_attempts=2)
        merged_raw = _merge_ingestion_rows(result["rows"], retry_result["rows"], attempts=attempts)
    else:
        merged_raw = _merge_ingestion_rows(result["rows"], [], attempts=attempts)

    catalog = load_catalog()
    by_id = index_series_rows(catalog["series"])
    rows = [
        _enrich_row(raw, by_id[str(raw["series_id"])], when=when, observations_dir=observations_dir)
        for raw in merged_raw
        if str(raw.get("series_id")) in by_id
    ]
    for row in rows:
        row["attempts"] = attempts.get(str(row["series_id"]), _row_fetch_attempts(row))

    checked_at = str(result.get("checked_at") or _utc_iso(when))
    history_dir = _canonical_history_dir(root)
    lineage = stage_verified_lineage(
        launch_dir=launch_dir,
        checked_at=checked_at,
        canonical_history_dir=history_dir,
        observations_dir=observations_dir,
        mode="live",
    )

    source_matrix, source_matrix_sha256 = _build_source_matrix(rows, catalog["series"])
    matrix_path = launch_dir / "source_matrix.json"
    matrix_path.write_text(json.dumps(source_matrix, indent=2) + "\n", encoding="utf-8")

    details = {
        "mode": "live",
        "countries": list(_LAUNCH_COUNTRIES),
        "rows": rows,
        "gaps": _gap_entries(rows),
        "score_bridge": _score_bridge_payload(lineage),
        "lineage": _lineage_details(lineage),
        "source_matrix_sha256": source_matrix_sha256,
        "live_fetch": True,
        "invented_values": False,
        "checked_at": result.get("checked_at"),
        "cutoff_class": result.get("cutoff_class"),
    }
    return details, "succeeded"


def run(launch: dict, ctx: dict) -> dict:
    request = launch.get("request") or {}
    mode = str(request.get("mode") or "fixture")
    when: datetime = ctx["when"]
    launch_dir: Path = ctx["launch_dir"]
    launch_dir.mkdir(parents=True, exist_ok=True)

    session_date = str(launch.get("session_date") or request.get("session_date") or "")
    overnight_run_id = launch.get("overnight_run_id")
    if not overnight_run_id and session_date:
        overnight_run_id = f"overnight-{session_date.replace('-', '')}"

    try:
        if mode == "fixture":
            checked_at = _utc_iso(when)
            details, status, reason = _fixture_ingestion(
                root=Path(ctx["root"]),
                launch_dir=launch_dir,
                when=when,
                checked_at=checked_at,
            )
        elif mode == "live":
            details, status = _live_ingestion(
                launch_dir=launch_dir,
                when=when,
                launch_id=launch.get("launch_id"),
                root=Path(ctx["root"]),
            )
            reason = None
        else:
            return stage_receipt(
                _STAGE,
                status="failed",
                input_sha256=None,
                reason=f"unsupported_mode:{mode}",
                details={"mode": mode, "invented_values": False},
            )
    except Exception as exc:  # noqa: BLE001
        return stage_receipt(
            _STAGE,
            status="failed",
            input_sha256=None,
            reason=str(exc),
            details={"mode": mode, "invented_values": False, "error": str(exc)},
        )

    if overnight_run_id:
        details["overnight_run_id"] = overnight_run_id

    return stage_receipt(
        _STAGE,
        status=status,
        input_sha256=None,
        reason=reason,
        details=details,
    )
