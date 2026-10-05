"""Offline replay helpers for architecture repair milestones."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping

from scripts.market_watch_launch.contract import COUNTRIES
from scripts.market_watch_launch.ingest import _merge_ingestion_rows
from scripts.market_watch_launch.quality_gate import evaluate_gate
from scripts.overnight.public_prose import room_data_caveat
from scripts.run_state.expectations import build_expectation
from scripts.run_state.schema import (
    SCHEMA_ACQUISITION_ATTEMPT,
    SCHEMA_QUALITY_POLICY,
    SCHEMA_SCHEDULER_EVENT,
    ContractError,
    sha256_json,
    validate_acquisition_attempt,
    validate_scheduler_event,
)

LABOR_SERIES = (
    "US.Labor.payrolls",
    "US.Labor.unemployment",
    "US.Labor.wages",
)

OTHER_COUNTRY_ROWS: tuple[tuple[str, str], ...] = (
    ("CA", "CA.Inflation.cpi"),
    ("AU", "AU.Labor.unemployment"),
    ("NZ", "NZ.Inflation.cpi"),
    ("EA", "EA.Inflation.hicp"),
    ("JP", "JP.Labor.unemployment"),
)


class ScoreConflict(ValueError):
    """Two temperature_scores documents disagree."""


def reject_unequal_score_copies(payload: Mapping[str, Any]) -> None:
    """Raise ScoreConflict when nested temperature_scores dicts hash differently."""

    hashes: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "temperature_scores" and isinstance(value, dict):
                    hashes.append(sha256_json(value))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    unique = set(hashes)
    if len(unique) > 1:
        raise ScoreConflict("ScoreConflict: unequal temperature_scores copies in payload")


def _attempt_id(series_id: str) -> str:
    return "aa_" + series_id.rsplit(".", 1)[-1]


def _families() -> dict[str, Any]:
    return {
        "macro_hard": {"status": "fresh", "notes": []},
        "market_state": {
            "status": "fresh",
            "data": {
                "rates": {code: {"status": "ok"} for code in COUNTRIES},
                "fx": {"status": "ok"},
            },
        },
    }


def _build_acquisition_attempt(
    *,
    run_id: str,
    fixture_attempt: Mapping[str, Any],
) -> Dict[str, Any]:
    series_id = str(fixture_attempt["series_id"])
    doc: Dict[str, Any] = {
        "schema_version": SCHEMA_ACQUISITION_ATTEMPT,
        "attempt_id": _attempt_id(series_id),
        "run_id": run_id,
        "series_id": series_id,
        "kind": fixture_attempt.get("kind", "primary"),
        "ordinal": int(fixture_attempt.get("ordinal", 1)),
        "result": "timeout",
        "queued_at": fixture_attempt["queued_at"],
        "started_at": fixture_attempt["started_at"],
        "ended_at": fixture_attempt["ended_at"],
        "elapsed_ms": int(fixture_attempt["elapsed_ms"]),
        "deadline_at": fixture_attempt["deadline_at"],
    }
    return validate_acquisition_attempt(doc)


def _build_scheduler_event(
    *,
    run_id: str,
    series_id: str,
    related_attempt_id: str,
    reason: str,
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema_version": SCHEMA_SCHEDULER_EVENT,
        "run_id": run_id,
        "series_id": series_id,
        "kind": "skipped_retry",
        "reason": reason,
        "related_attempt_id": related_attempt_id,
    }
    return validate_scheduler_event(doc)


def _assert_not_acquisition_attempt(doc: Mapping[str, Any]) -> None:
    try:
        validate_acquisition_attempt(doc)
    except ContractError:
        return
    raise ValueError("scheduler event must not validate as AcquisitionAttempt")


def replay_october5(fixture: dict) -> dict:
    run_id = str(fixture["run_id"])
    cutoff_at = str(fixture["cutoff_at"])
    freeze_cutoff = str(fixture["freeze_cutoff"])
    employment = fixture["employment_situation"]
    release_at = str(employment["release_at"])
    period = str(employment["period"])

    expectations: List[Dict[str, Any]] = []
    for sid in LABOR_SERIES:
        definition = {"series_id": sid, "calendar_status": "unknown"}
        overlay = {"calendar_status": "known", "release_at": release_at, "period": period}
        expectations.append(
            build_expectation(
                definition,
                run_id=run_id,
                cutoff_at=cutoff_at,
                overlay=overlay,
            )
        )

    attempts: List[Dict[str, Any]] = []
    attempt_by_series: Dict[str, Dict[str, Any]] = {}
    for raw in fixture["reconstructed_primary_attempts"]:
        doc = _build_acquisition_attempt(run_id=run_id, fixture_attempt=raw)
        attempts.append(doc)
        attempt_by_series[str(raw["series_id"])] = doc

    scheduler_events: List[Dict[str, Any]] = []
    for skip in fixture["labor_skipped_retries"]:
        sid = str(skip["series_id"])
        primary = attempt_by_series[sid]
        event = _build_scheduler_event(
            run_id=run_id,
            series_id=sid,
            related_attempt_id=str(primary["attempt_id"]),
            reason="budget_deferred",
        )
        _assert_not_acquisition_attempt(event)
        scheduler_events.append(event)

    primary_rows: List[Dict[str, Any]] = []
    for raw in fixture["reconstructed_primary_attempts"]:
        sid = str(raw["series_id"])
        defect = next(row for row in fixture["defect_rows"] if row["series_id"] == sid)
        primary_rows.append(
            {
                "series_id": sid,
                "country": "US",
                "role": "scored",
                "weight": defect["weight"],
                "status": "source_failed",
                "error": raw["error"],
                "release_due": True,
                "due_period": period,
                "attempt_history": [dict(raw)],
            }
        )

    secondary = [dict(row) for row in fixture["defect_rows"]]
    attempt_counters = {str(row["series_id"]): int(row["attempts"]) for row in secondary}
    merged_rows = _merge_ingestion_rows(primary_rows, secondary, attempts=attempt_counters)

    gate_rows: List[Dict[str, Any]] = list(merged_rows)
    for country, series_id in OTHER_COUNTRY_ROWS:
        gate_rows.append(
            {
                "series_id": series_id,
                "country": country,
                "role": "scored",
                "weight": 1.0,
                "status": "checked_unchanged",
                "release_due": False,
                "observation_period": "2026-08",
            }
        )

    gate = evaluate_gate(rows=gate_rows, families=_families())
    gate["cutoff_at"] = cutoff_at
    gate["freeze_cutoff"] = freeze_cutoff

    score_copy_a = dict(fixture["score_copies"]["score_copy_a"])
    score_state_sha256 = sha256_json(score_copy_a)

    permissions: MutableMapping[str, Any] = {
        "countries": {
            code: {"eligible": bool((gate.get("countries") or {}).get(code, {}).get("eligible"))}
            for code in COUNTRIES
        },
        "source_health": [
            {
                "country": "US",
                "series_id": "US.Inflation.core_pce",
                "carried_forward": True,
                "blocks_new_risk": False,
            }
        ],
    }
    public_caveat = room_data_caveat(dict(permissions))

    return {
        "run_id": run_id,
        "cutoff_at": cutoff_at,
        "freeze_cutoff": freeze_cutoff,
        "expectations": expectations,
        "attempts": attempts,
        "scheduler_events": scheduler_events,
        "merged_rows": merged_rows,
        "gate": gate,
        "score_state_sha256": score_state_sha256,
        "temperature_scores": score_copy_a,
        "public_caveat": public_caveat,
        "policy_version": SCHEMA_QUALITY_POLICY,
    }
