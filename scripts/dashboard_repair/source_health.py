"""Public source-health snapshot from the newest Stage 01 ingest ledger.

Last successful check, ledger retrieval, and observation period stay separate.
A series absent from the ledger is not checked. Failed and blocked rows are
not described as healthy, and no check time is invented for them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LAUNCHES = ROOT / "data" / "market_watch_launches"

_SUCCESS = {"new_observation", "checked_unchanged", "revision_applied"}
_FAILURE = {"source_failed"}
_BLOCKED = {"license_gap", "due_missing"}
_NOT_CHECKED = {"calendar_unparsed"}


def load_latest_ingest(root: Path | None = None) -> dict[str, Any] | None:
    """Newest succeeded Stage 01 artifact that actually recorded rows."""
    base = (root or ROOT) / "data" / "market_watch_launches"
    if not base.is_dir():
        return None
    candidates = sorted(path for path in base.iterdir() if path.is_dir() and path.name.startswith("mwl-"))
    for launch in reversed(candidates):
        path = launch / "artifacts" / "01_ingest.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows = payload.get("rows")
        if payload.get("status") != "succeeded" or not isinstance(rows, list) or not rows:
            continue
        quality_path = launch / "artifacts" / "03_quality_gate.json"
        quality = None
        if quality_path.is_file():
            try:
                parsed = json.loads(quality_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                quality = parsed
        return {
            "launch_id": launch.name,
            "checked_at": str(payload.get("checked_at") or ""),
            "stage_status": str(payload.get("status") or ""),
            "rows": rows,
            "quality": quality,
            "source": str(path.relative_to(root or ROOT)),
        }
    return None


def _bucket(status: str) -> str:
    if status in _SUCCESS:
        return "checked"
    if status in _FAILURE:
        return "failure"
    if status in _BLOCKED:
        return "blocked"
    if status in _NOT_CHECKED or status == "":
        return "not_checked"
    if status == "not_applicable":
        return "not_applicable"
    return "partial"


def _next_release(series_id: str, model: dict[str, Any] | None) -> str:
    if not model:
        return "date unavailable"
    for bucket in ("upcoming", "later"):
        for item in model.get(bucket) or []:
            if series_id in (item.get("series_ids") or []):
                when = item.get("et_display") or item.get("local_display") or "date pinned"
                clock = item.get("clock") or ""
                return f"{when} ({clock})" if clock else str(when)
    return "date unavailable"


def build_source_health_snapshot(
    series: list[dict[str, Any]],
    ingest: dict[str, Any] | None,
    release_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    if ingest:
        for row in ingest.get("rows") or []:
            if isinstance(row, dict) and row.get("series_id"):
                by_id[str(row["series_id"])] = row
    partial = set()
    blocked = set()
    quality = (ingest or {}).get("quality") if isinstance((ingest or {}).get("quality"), dict) else None
    if isinstance(quality, dict):
        partial = {str(item) for item in quality.get("partial_series") or []}
        blocked = {str(item) for item in quality.get("blocked_sources") or []}
    stage_checked_at = str((ingest or {}).get("checked_at") or "")
    rows_out: list[dict[str, str]] = []
    counts = {
        "checked": 0,
        "failure": 0,
        "blocked": 0,
        "partial": 0,
        "not_checked": 0,
        "not_applicable": 0,
        "carried_forward": 0,
    }
    for spec in series:
        series_id = str(spec.get("id") or "")
        ledger = by_id.get(series_id)
        health = (ledger or {}).get("source_health") if isinstance((ledger or {}).get("source_health"), dict) else {}
        if ledger is None:
            bucket = "not_checked"
            status = "not_checked"
            error = ""
            observation = str(spec.get("latest_period") or "")
            successful = ""
            attempt = ""
        else:
            status = str(ledger.get("status") or "")
            bucket = _bucket(status)
            if series_id in blocked and bucket not in {"failure", "checked"}:
                bucket = "blocked"
            elif series_id in partial and bucket == "checked":
                bucket = "partial"
            error = str(ledger.get("error") or health.get("fetch_error") or "")
            observation = str(ledger.get("observation_period") or spec.get("latest_period") or "")
            successful = stage_checked_at if bucket == "checked" else ""
            attempt = stage_checked_at
        retrieval = str(health.get("retrieved_at") or spec.get("latest_retrieved_at") or "")
        carried = bool(health.get("carried_forward"))
        if carried:
            counts["carried_forward"] += 1
        counts[bucket] = counts.get(bucket, 0) + 1
        urls = [str(url) for url in (spec.get("registry_urls") or []) if str(url).startswith("https://")]
        rows_out.append(
            {
                "series_id": series_id,
                "country": str(spec.get("country") or (ledger or {}).get("country") or ""),
                "dimension": str(spec.get("dimension") or ""),
                "component": str(spec.get("component") or ""),
                "publisher": str(spec.get("publisher") or ""),
                "publisher_series": str(spec.get("series_id") or ""),
                "url": urls[0] if urls else "",
                "weight": "" if spec.get("weight") is None else str(spec.get("weight")),
                "role": str(spec.get("role") or (ledger or {}).get("role") or ""),
                "cadence": str(spec.get("cadence") or ""),
                "status": status if ledger is not None else "not_checked",
                "bucket": bucket,
                "error": error,
                "observation_period": observation,
                "ledger_retrieval": retrieval,
                "stage_attempt": attempt,
                "last_successful_check": successful,
                "carried_forward": "yes" if carried else "no",
                "expected_next": _next_release(series_id, release_model),
            }
        )
    return {
        "launch_id": str((ingest or {}).get("launch_id") or ""),
        "stage_checked_at": stage_checked_at if ingest else "",
        "stage_status": str((ingest or {}).get("stage_status") or ("missing" if ingest is None else "")),
        "source": str((ingest or {}).get("source") or ""),
        "audit_ledger": "data/temperature_history/macro_source_audit.json is not published; this snapshot is the Stage 01 ingest ledger.",
        "counts": counts,
        "rows": rows_out,
    }
