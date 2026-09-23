"""Stage 05 — ACP one-shot delegation request (fail-closed; no live dispatch)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.contract import AWAITING_ACP, LAUNCHER_ID, LEGACY_SCHEDULE_ID

STAGE = "05_acp_handoff"
PRIOR_STAGE = "04_freeze"
TARGET_REPO = "McCabeAI/market-watch-public-dashboard"
GRANT_TYPE = "MW_ACP_ONE_SHOT_GRANT"
REQUEST_TYPE = "MW_ACP_ONE_SHOT_DELEGATION_REQUEST"


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


def build_delegation_request(launch: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_details(launch)
    origin = dict((launch.get("request") or {}).get("origin") or {})
    return {
        "type": REQUEST_TYPE,
        "version": 1,
        "target_repo": TARGET_REPO,
        "launch_id": launch["launch_id"],
        "session_date": launch["session_date"],
        "review_id": freeze.get("review_id") or launch.get("review_id"),
        "overnight_run_id": freeze.get("overnight_run_id") or launch.get("overnight_run_id"),
        "base_packet_sha256": freeze.get("packet_sha256") or launch.get("base_packet_sha256"),
        "origin": origin,
        "budget": {
            "launcher_id": LAUNCHER_ID,
            "legacy_schedule_id_inactive": LEGACY_SCHEDULE_ID,
            "total_model_cap": 19,
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


def _grant_matches(grant: dict[str, Any], launch: dict[str, Any], request: dict[str, Any]) -> bool:
    if grant.get("type") != GRANT_TYPE:
        return False
    if grant.get("issuer") != "acp":
        return False
    if not grant.get("single_use"):
        return False
    if grant.get("launch_id") != launch["launch_id"]:
        return False
    if grant.get("review_id") != request.get("review_id"):
        return False
    if grant.get("base_packet_sha256") != request.get("base_packet_sha256"):
        return False
    return True


def _dispatch_implemented(ctx: dict[str, Any]) -> bool:
    if ctx.get("acp_dispatch_implemented"):
        return bool(ctx["acp_dispatch_implemented"])
    return os.environ.get("MW_LAUNCH_ACP_DISPATCH_IMPLEMENTED") == "1"


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

    grant = _load_grant(launch_dir)
    grant_ok = grant is not None and _grant_matches(grant, launch, request)
    if not grant_ok:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason=AWAITING_ACP,
            artifact=str(request_path),
            details={
                "delegation_request": request,
                "grant_present": False,
                "grant_verified": False,
                "live_provider_dispatched": False,
                "live_model_calls": 0,
            },
        )

    dispatch_on = _dispatch_implemented(ctx)
    if not dispatch_on:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason=AWAITING_ACP,
            artifact=str(request_path),
            details={
                "delegation_request": request,
                "grant_present": True,
                "grant_verified": True,
                "dispatch_implemented": False,
                "live_provider_dispatched": False,
                "live_model_calls": 0,
            },
        )

    return contract.stage_receipt(
        STAGE,
        status="succeeded",
        input_sha256=input_sha,
        artifact=str(request_path),
        reason="grant_verified_dispatch_not_implemented",
        details={
            "delegation_request": request,
            "grant_present": True,
            "grant_verified": True,
            "dispatch_implemented": True,
            "live_provider_dispatched": False,
            "live_model_calls": 0,
        },
    )
