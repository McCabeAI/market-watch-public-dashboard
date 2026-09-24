"""Stage 07 — final delta, assemble, publication gate."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.freeze import apply_macro_overlay
from scripts.overnight.assemble import assemble_dataset
from scripts.overnight.constants import FIXTURE_MARKET_STATE
from scripts.overnight.delta import compute_delta
from scripts.overnight.errors import PublicationError
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.ledger import load_or_create, mark_finished, mark_running, persist_run
from scripts.overnight.publish import publication_gate
from scripts.overnight.reviews import load_review
from scripts.overnight.store import OvernightStore

STAGE = "07_finalize"
PRIOR_STAGE = "06_acceptance"


def _provider(launch: dict[str, Any]) -> str:
    return (launch.get("request") or {}).get("provider", "stub")


def _prior_failed(launch: dict[str, Any], *, input_sha256: str | None) -> dict[str, Any] | None:
    prior = (launch.get("stages") or {}).get(PRIOR_STAGE) or {}
    if prior.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha256,
            reason="prior_stage_not_verified",
        )
    q = (launch.get("stages") or {}).get("03_quality_gate") or {}
    if q.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha256,
            reason="prior_stage_not_verified",
        )
    return None


def _freeze_details(launch: dict[str, Any]) -> dict[str, Any]:
    return ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}


def _offline_and_market_state(launch: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, Path | None]:
    mode = (launch.get("request") or {}).get("mode", "fixture")
    offline = mode != "live"
    req_path = (launch.get("request") or {}).get("market_state_path")
    if req_path:
        return offline, Path(req_path)
    if offline:
        return True, Path(ctx["root"]) / FIXTURE_MARKET_STATE
    return False, None


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    blocked = _prior_failed(launch, input_sha256=input_sha)
    if blocked:
        return blocked

    acceptance = (launch.get("stages") or {}).get("06_acceptance") or {}
    if acceptance.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="prior_stage_not_verified",
        )

    provider = _provider(launch)
    if provider not in ("stub", "acp"):
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="unknown_provider",
        )

    freeze = _freeze_details(launch)
    run_id = freeze.get("overnight_run_id") or launch.get("overnight_run_id")
    review_id = freeze.get("review_id") or launch.get("review_id")
    packet_sha256 = freeze.get("packet_sha256") or launch.get("base_packet_sha256")
    when: datetime | None = ctx.get("when")

    store = OvernightStore(root=ctx["root"], state_root=ctx["overnight_store_root"])
    meta = load_review(store, run_id, review_id)
    if meta.get("status") != "accepted" and provider == "stub":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="review_not_accepted",
        )

    if meta.get("review_id") != review_id or meta.get("overnight_run_id") != run_id:
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="review_identity_mismatch",
        )

    require_snapshot(store, run_id, review_id)

    offline, market_state_path = _offline_and_market_state(launch, ctx)
    run = load_or_create(store, run_id=run_id, when=when, dry_run=(launch.get("request") or {}).get("mode") == "fixture")

    compute_delta(
        store,
        run_id=run_id,
        stage="final_delta",
        when=when,
        offline=offline,
        market_state_path=market_state_path,
    )
    if store.has_artifact(run_id, "final_delta.json"):
        delta = store.read_artifact(run_id, "final_delta.json")
        families = apply_macro_overlay(delta.get("families") or {}, launch)
        store.write_artifact(run_id, "final_delta.json", {**delta, "families": families})

    mark_running(run, "final_delta", when=when)
    mark_finished(run, "final_delta", status="succeeded", when=when)
    persist_run(store, run)

    dataset = assemble_dataset(store, run, when=when)
    store.write_artifact(run_id, "assembled_dataset.json", dataset)

    mark_running(run, "assemble", when=when)
    mark_finished(run, "assemble", status="succeeded", when=when)
    persist_run(store, run)

    coverage = ((launch.get("stages") or {}).get("03_quality_gate") or {}).get("details") or {}
    partial = coverage.get("partial") if "partial" in coverage else coverage.get("coverage") == "PARTIAL"

    try:
        gate = publication_gate(store, run_id=run_id, require_dataset=True)
    except PublicationError as exc:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="publication_gate",
            details={
                "launch_id": launch["launch_id"],
                "session_date": launch["session_date"],
                "review_id": review_id,
                "packet_sha256": packet_sha256,
                "publication": {"may_publish": False, "core_status": None, "reason": str(exc)},
                "coverage": coverage.get("coverage"),
                "partial": bool(partial),
            },
        )

    ds = gate.get("dataset") or {}
    if ds.get("overnight_run_id") != run_id:
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="dataset_run_mismatch",
        )

    if not gate.get("may_publish"):
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="publication_gate",
            details={
                "launch_id": launch["launch_id"],
                "session_date": launch["session_date"],
                "review_id": review_id,
                "packet_sha256": packet_sha256,
                "publication": {
                    "may_publish": gate.get("may_publish"),
                    "core_status": gate.get("core_status"),
                    "reason": gate.get("reason"),
                },
                "coverage": coverage.get("coverage"),
                "partial": bool(partial),
            },
        )

    if review_id != (freeze.get("review_id") or launch.get("review_id")):
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="review_mismatch",
        )

    return contract.stage_receipt(
        STAGE,
        status="succeeded",
        input_sha256=input_sha,
        output_sha256=packet_sha256,
        details={
            "launch_id": launch["launch_id"],
            "session_date": launch["session_date"],
            "review_id": review_id,
            "packet_sha256": packet_sha256,
            "publication": {
                "core_status": gate.get("core_status"),
                "may_publish": gate.get("may_publish"),
                "reason": gate.get("reason"),
            },
            "coverage": coverage.get("coverage"),
            "partial": bool(partial),
        },
    )
