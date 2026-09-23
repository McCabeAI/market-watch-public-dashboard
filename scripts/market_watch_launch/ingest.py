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
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.macro_ingestion.vintage import latest_period_in_store, load_store
from scripts.market_watch_launch.contract import COUNTRIES, stage_receipt
from scripts.temperature_level import HISTORY_DIR, load_history

_STAGE = "01_ingest"
_LAUNCH_COUNTRIES = tuple(COUNTRIES)


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


def _score_bridge_payload(result: Any) -> dict[str, Any]:
    merge = result.merge or {}
    appended = merge.get("appended") or []
    summary = f"appended={len(appended)}"
    payload: dict[str, Any] = {"ok": bool(result.ok), "summary": summary}
    if result.state is not None:
        payload["state_sha256"] = _sha256_json(result.state)
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


def _fixture_ingestion(
    *,
    root: Path,
    launch_dir: Path,
    when: datetime,
    checked_at: str,
) -> tuple[dict[str, Any], str, str | None]:
    catalog = load_catalog()
    history_dir = root / "data" / "temperature_history"
    if not history_dir.is_dir():
        history_dir = HISTORY_DIR
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

    bridge = recompute_scores_after_observation(
        persist_scores=False,
        persist_history=False,
        points=replay_points,
        checked_at=checked_at,
        histories=histories,
    )
    score_bridge = _score_bridge_payload(bridge)

    missing_countries = [c for c in _LAUNCH_COUNTRIES if c not in countries_with_scored]
    if missing_countries:
        status = "failed"
        reason = "missing_country_history"
    elif not bridge.ok:
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
    )
    if not result.get("rows"):
        raise RuntimeError("ingestion returned no rows")

    catalog = load_catalog()
    by_id = index_series_rows(catalog["series"])
    rows = [
        _enrich_row(raw, by_id[str(raw["series_id"])], when=when, observations_dir=observations_dir)
        for raw in result["rows"]
        if str(raw.get("series_id")) in by_id
    ]

    bridge = recompute_scores_after_observation(
        persist_scores=False,
        persist_history=False,
        observations_dir=observations_dir,
        checked_at=str(result.get("checked_at") or _utc_iso(when)),
    )
    details = {
        "mode": "live",
        "countries": list(_LAUNCH_COUNTRIES),
        "rows": rows,
        "gaps": _gap_entries(rows),
        "score_bridge": _score_bridge_payload(bridge),
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
