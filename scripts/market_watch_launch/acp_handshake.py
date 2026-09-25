"""Stage 05 — ACP one-shot delegation request (fail-closed; no live dispatch)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.contract import AWAITING_ACP, LAUNCHER_ID, LEGACY_SCHEDULE_ID
from scripts.market_watch_launch.durability import remote_freeze_verified

STAGE = "05_acp_handoff"
PRIOR_STAGE = "04_freeze"
TARGET_REPO = "McCabeAI/market-watch-public-dashboard"
PUBLIC_VERIFICATION_REPO = TARGET_REPO
GRANT_TYPE = "MW_ACP_ONE_SHOT_GRANT"
REQUEST_TYPE = "MW_ACP_ONE_SHOT_DELEGATION_REQUEST"
RECEIPT_TYPE = "MW_ACP_ONE_SHOT_DISPATCH_RECEIPT"
AWAITING_REMOTE_FREEZE = "awaiting_remote_freeze"


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


def _request_origin(launch: dict[str, Any]) -> dict[str, Any]:
    request = launch.get("request") or {}
    origin = dict(request.get("origin") or {})
    if origin:
        return origin
    return {
        "source": request.get("source"),
        "issue_number": request.get("issue_number"),
        "issue_url": request.get("issue_url"),
        "actor": request.get("actor"),
        "actor_type": request.get("actor_type"),
    }


def build_delegation_request(launch: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_details(launch)
    launch_id = launch["launch_id"]
    binding_relpath = f"data/market_watch_launches/{launch_id}/freeze_binding.json"
    return {
        "type": REQUEST_TYPE,
        "version": 1,
        "target_repo": TARGET_REPO,
        "launch_id": launch_id,
        "session_date": launch["session_date"],
        "review_id": freeze.get("review_id") or launch.get("review_id"),
        "overnight_run_id": freeze.get("overnight_run_id") or launch.get("overnight_run_id"),
        "base_packet_sha256": freeze.get("packet_sha256") or launch.get("base_packet_sha256"),
        "freeze_commit_sha": launch.get("freeze_commit_sha") or freeze.get("freeze_commit_sha"),
        "score_state_sha256": freeze.get("score_state_sha256") or launch.get("score_state_sha256"),
        "starting_trader_books_sha256": freeze.get("starting_trader_books_sha256")
        or launch.get("starting_trader_books_sha256"),
        "starting_pm_books_sha256": freeze.get("starting_pm_books_sha256")
        or launch.get("starting_pm_books_sha256"),
        "binding_relpath": binding_relpath,
        "public_verification": {
            "repo": PUBLIC_VERIFICATION_REPO,
            "ref": "main",
            "readable_without_secrets": True,
        },
        "origin": _request_origin(launch),
        "budget": {
            "launcher_id": LAUNCHER_ID,
            "legacy_schedule_id_inactive": LEGACY_SCHEDULE_ID,
            "total_model_cap": 20,
            "grok_cap": 18,
            "composer_cap": 2,
            "parent_model": "grok-4.6",
            "frozen_command": ".cursor/commands/overnight-scheduled.md",
        },
        "dispatch_when": "freeze-succeeded",
        "single_use": True,
    }


def _load_grant(launch_dir: Path) -> dict[str, Any] | None:
    path = launch_dir / "acp_one_shot_grant.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_receipt(launch_dir: Path) -> dict[str, Any] | None:
    path = launch_dir / "acp_one_shot_dispatch_receipt.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_matches(
    artifact: dict[str, Any],
    *,
    artifact_type: str,
    launch: dict[str, Any],
    request: dict[str, Any],
) -> bool:
    if artifact.get("type") != artifact_type:
        return False
    if artifact.get("issuer") != "acp":
        return False
    if not artifact.get("single_use"):
        return False
    if artifact.get("launch_id") != launch["launch_id"]:
        return False
    if artifact.get("review_id") != request.get("review_id"):
        return False
    if artifact.get("base_packet_sha256") != request.get("base_packet_sha256"):
        return False
    return True


def _grant_matches(grant: dict[str, Any], launch: dict[str, Any], request: dict[str, Any]) -> bool:
    return _artifact_matches(grant, artifact_type=GRANT_TYPE, launch=launch, request=request)


def _receipt_matches(receipt: dict[str, Any], launch: dict[str, Any], request: dict[str, Any]) -> bool:
    return _artifact_matches(receipt, artifact_type=RECEIPT_TYPE, launch=launch, request=request)


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    blocked = _prior_failed(launch, input_sha256=input_sha)
    if blocked:
        return blocked

    provider = _provider(launch)
    launch_dir = Path(ctx["launch_dir"])
    launch_dir.mkdir(parents=True, exist_ok=True)
    request = build_delegation_request(launch)
    request_path = launch_dir / "acp_one_shot_delegation_request.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if provider == "stub":
        return contract.stage_receipt(
            STAGE,
            status="succeeded",
            input_sha256=input_sha,
            output_sha256=None,
            artifact=str(request_path),
            reason="stub_provider_skips_live_acp",
            details={
                "delegation_request": request,
                "provider": "stub",
                "live_provider_dispatched": False,
                "authority": "stub_not_live",
                "live_model_calls": 0,
            },
        )

    if not remote_freeze_verified(launch_dir):
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason=AWAITING_REMOTE_FREEZE,
            artifact=str(request_path),
            details={
                "delegation_request": request,
                "remote_freeze_verified": False,
                "live_provider_dispatched": False,
                "live_model_calls": 0,
            },
        )

    grant = _load_grant(launch_dir)
    receipt = _load_receipt(launch_dir)
    grant_ok = grant is not None and _grant_matches(grant, launch, request)
    receipt_ok = receipt is not None and _receipt_matches(receipt, launch, request)

    # Verified remote freeze only means the delegation request is ready for ACP.
    # Grants and local receipts are never treated as live provider dispatch.
    _ = ctx.get("acp_dispatch_implemented")
    return contract.stage_receipt(
        STAGE,
        status="blocked",
        input_sha256=input_sha,
        reason=AWAITING_ACP,
        artifact=str(request_path),
        details={
            "delegation_request": request,
            "remote_freeze_verified": True,
            "grant_present": grant is not None,
            "grant_verified": grant_ok,
            "receipt_present": receipt is not None,
            "receipt_matches": receipt_ok,
            "handoff_status": "request_ready",
            "handoff_url": None,
            "dispatch_implemented": False,
            "live_provider_dispatched": False,
            "live_model_calls": 0,
        },
    )
