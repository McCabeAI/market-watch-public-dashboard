"""Immutable overnight_run_id ledger spanning every stage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny, overnight_run_id
from scripts.overnight.constants import SCHEMA_VERSION, STAGE_STATUSES, STAGES
from scripts.overnight.errors import SchemaError, StageError
from scripts.overnight.store import OvernightStore, sha256_json


def empty_stage(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "as_of": None,
        "inputs": {},
        "outputs": {},
        "errors": [],
    }


def new_run(
    *,
    when: datetime | None = None,
    dry_run: bool = False,
    suffix: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    ny = now_ny(when)
    ident = run_id or overnight_run_id(ny, dry_run=dry_run, suffix=suffix)
    return {
        "schema_version": SCHEMA_VERSION,
        "overnight_run_id": ident,
        "timezone": "America/New_York",
        "session_date": ny.date().isoformat(),
        "created_at": isoformat(ny),
        "dry_run": bool(dry_run),
        "model_calls": 0,
        "status": "pending",
        "stages": {name: empty_stage(name) for name in STAGES},
    }


def validate_run(run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise SchemaError("run ledger must be an object")
    if run.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("run ledger schema_version mismatch")
    run_id = run.get("overnight_run_id")
    if not isinstance(run_id, str) or not run_id.startswith("overnight-"):
        raise SchemaError("overnight_run_id is missing or malformed")
    stages = run.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise SchemaError(f"run ledger must record exactly these stages: {STAGES}")
    for name, stage in stages.items():
        if stage.get("name") != name:
            raise SchemaError(f"stage {name} name mismatch")
        if stage.get("status") not in STAGE_STATUSES:
            raise SchemaError(f"stage {name} has invalid status {stage.get('status')}")
    return run


def load_or_create(
    store: OvernightStore,
    *,
    run_id: str | None = None,
    when: datetime | None = None,
    dry_run: bool = False,
    suffix: str = "",
) -> dict[str, Any]:
    if run_id and store.has_artifact(run_id, "run.json"):
        run = validate_run(store.read_artifact(run_id, "run.json"))
        if run["overnight_run_id"] != run_id:
            raise SchemaError("stored overnight_run_id does not match path")
        return run
    latest = store.read_latest()
    if run_id is None and latest and latest.get("overnight_run_id"):
        existing = latest["overnight_run_id"]
        if store.has_artifact(existing, "run.json"):
            found = validate_run(store.read_artifact(existing, "run.json"))
            if found["session_date"] == now_ny(when).date().isoformat() and found.get("dry_run") == dry_run:
                return found
    run = new_run(when=when, dry_run=dry_run, suffix=suffix, run_id=run_id)
    persist_run(store, run)
    return run


def persist_run(store: OvernightStore, run: dict[str, Any]) -> dict[str, Any]:
    validate_run(run)
    store.write_artifact(run["overnight_run_id"], "run.json", run)
    return run


def mark_running(run: dict[str, Any], stage: str, *, when: datetime | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_stage(run, stage)
    stamp = isoformat(now_ny(when))
    item = run["stages"][stage]
    item["status"] = "running"
    item["started_at"] = stamp
    item["as_of"] = stamp
    if inputs:
        item["inputs"] = inputs
    run["status"] = "running"
    return run


def mark_finished(
    run: dict[str, Any],
    stage: str,
    *,
    status: str,
    when: datetime | None = None,
    outputs: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    _require_stage(run, stage)
    if status not in STAGE_STATUSES:
        raise SchemaError(f"invalid stage status {status}")
    item = run["stages"][stage]
    item["status"] = status
    item["finished_at"] = isoformat(now_ny(when))
    item["as_of"] = item["finished_at"]
    if outputs is not None:
        item["outputs"] = outputs
    if errors:
        item["errors"] = list(errors)
    if status == "failed" and stage in {"collect", "assemble", "publish"}:
        run["status"] = "failed"
    elif all(run["stages"][name]["status"] == "succeeded" for name in STAGES):
        run["status"] = "succeeded"
    else:
        run["status"] = "running"
    return run


def assert_same_run_id(run: dict[str, Any], payload: dict[str, Any], label: str) -> None:
    got = payload.get("overnight_run_id")
    if got != run["overnight_run_id"]:
        raise StageError(f"{label} overnight_run_id {got} != {run['overnight_run_id']}")


def artifact_index(run: dict[str, Any]) -> dict[str, str]:
    run_id = run["overnight_run_id"]
    prefix = f"data/overnight/runs/{run_id}"
    freeze_outputs = ((run.get("stages") or {}).get("freeze_evidence") or {}).get("outputs") or {}
    review_outputs = ((run.get("stages") or {}).get("trader_review") or {}).get("outputs") or {}
    review_id = review_outputs.get("review_id") or freeze_outputs.get("review_id")
    review_prefix = f"{prefix}/reviews/{review_id}" if review_id else prefix
    return {
        "run": f"{prefix}/run.json",
        "collect": f"{prefix}/collect.json",
        "pre_trader_delta": f"{prefix}/pre_trader_delta.json",
        "review_index": f"{prefix}/reviews/index.json",
        "evidence_snapshot": f"{review_prefix}/evidence_snapshot.json",
        "trader_review": f"{review_prefix}/trader_review.json",
        "final_delta": f"{prefix}/final_delta.json",
        "assembled_dataset": f"{prefix}/assembled_dataset.json",
        "digest": sha256_json({k: run["stages"][k]["status"] for k in STAGES}),
    }


def _require_stage(run: dict[str, Any], stage: str) -> None:
    validate_run(run)
    if stage not in STAGES:
        raise SchemaError(f"unknown stage {stage}")
