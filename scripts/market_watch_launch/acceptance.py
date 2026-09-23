"""Stage 06 — trusted acceptance of provider scheduled output."""

from __future__ import annotations

from typing import Any

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.contract import AWAITING_ACP
from scripts.market_watch_launch.provider_stub import build_stub_output
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.reviews import load_review, review_effects_recorded
from scripts.overnight.scheduled_output import apply_output, validate_output
from scripts.overnight.store import OvernightStore

STAGE = "06_acceptance"
PRIOR_STAGE = "05_acp_handoff"


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


def assess_provider_payload(
    store: OvernightStore,
    launch: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    freeze = _freeze_details(launch)
    expected_review = freeze.get("review_id") or launch.get("review_id")
    expected_launch = launch.get("launch_id")
    expected_hash = freeze.get("packet_sha256") or launch.get("base_packet_sha256")
    run_id = freeze.get("overnight_run_id") or launch.get("overnight_run_id")

    if expected_launch and payload.get("launch_id") not in (None, expected_launch):
        return {"ok": False, "reason": "launch_mismatch"}

    if expected_review and payload.get("review_id") != expected_review:
        return {"ok": False, "reason": "late_review"}

    if expected_hash and payload.get("base_packet_sha256") != expected_hash:
        return {"ok": False, "reason": "hash_drift"}

    if run_id and payload.get("overnight_run_id") != run_id:
        return {"ok": False, "reason": "review_mismatch"}

    try:
        validate_output(store, payload)
    except Exception:
        return {"ok": False, "reason": "rejected"}

    return {"ok": True, "reason": None}


def _success_details(
    *,
    launch: dict[str, Any],
    review_id: str,
    packet_sha256: str | None,
    already_applied: bool,
) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "packet_sha256": packet_sha256,
        "launch_id": launch["launch_id"],
        "applied": True,
        "already_applied": already_applied,
        "live_model_calls": 0,
        "stub": True,
        "trader_seats": 14,
        "pm_count": 3,
    }


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    blocked = _prior_failed(launch, input_sha256=input_sha)
    if blocked:
        return blocked

    provider = _provider(launch)
    freeze = _freeze_details(launch)
    run_id = freeze.get("overnight_run_id") or launch.get("overnight_run_id")
    review_id = freeze.get("review_id") or launch.get("review_id")
    packet_sha256 = freeze.get("packet_sha256") or launch.get("base_packet_sha256")

    store = OvernightStore(root=ctx["root"], state_root=ctx["overnight_store_root"])

    if provider == "acp":
        handoff = (launch.get("stages") or {}).get("05_acp_handoff") or {}
        if handoff.get("status") != "succeeded":
            return contract.stage_receipt(
                STAGE,
                status="blocked",
                input_sha256=input_sha,
                reason=AWAITING_ACP,
                details={"live_model_calls": 0},
            )
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="awaiting_provider_output",
            details={"live_model_calls": 0},
        )

    if not run_id or not review_id:
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="missing_freeze_identity",
        )

    base = require_snapshot(store, run_id, review_id)
    books_path = store.books_path()
    books_before = books_path.read_bytes() if books_path.is_file() else b""

    meta = load_review(store, run_id, review_id)
    if meta.get("status") == "accepted" or review_effects_recorded(store, run_id, review_id):
        return contract.stage_receipt(
            STAGE,
            status="succeeded",
            input_sha256=input_sha,
            output_sha256=packet_sha256,
            details=_success_details(
                launch=launch,
                review_id=review_id,
                packet_sha256=packet_sha256,
                already_applied=True,
            ),
        )

    payload = build_stub_output(store, launch=launch, base_packet=base)
    assessment = assess_provider_payload(store, launch, payload)
    if not assessment["ok"]:
        if books_path.is_file() and books_before and books_path.read_bytes() != books_before:
            raise AssertionError("books mutated on rejected acceptance")
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason=assessment["reason"] or "rejected",
            details={"live_model_calls": 0, "stub": True},
        )

    apply_output(store, payload)
    return contract.stage_receipt(
        STAGE,
        status="succeeded",
        input_sha256=input_sha,
        output_sha256=packet_sha256,
        details=_success_details(
            launch=launch,
            review_id=review_id,
            packet_sha256=packet_sha256,
            already_applied=False,
        ),
    )
