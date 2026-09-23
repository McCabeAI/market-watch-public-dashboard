"""Stage 08 — explicit Pages deploy plan (no silent production publish)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from scripts.market_watch_launch import contract

STAGE = "08_pages"
PRIOR_STAGE = "07_finalize"
LAUNCH_STATE_DIR = "market_watch_launch"


def launch_record_candidates(state_root: Path | str, launch_id: str) -> tuple[Path, Path]:
    root = Path(state_root)
    legacy = root / LAUNCH_STATE_DIR / launch_id / "launch.json"
    canonical = root / "data" / "market_watch_launches" / launch_id / "launch.json"
    return legacy, canonical


def launch_record_path(state_root: Path | str, launch_id: str) -> Path:
    legacy, canonical = launch_record_candidates(state_root, launch_id)
    if legacy.is_file():
        return legacy
    if canonical.is_file():
        return canonical
    return legacy


def load_launch_record(*, launch_id: str, state_root: Path | str) -> dict[str, Any] | None:
    path = launch_record_path(state_root, launch_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def authorize_pages_dispatch(
    *,
    launch_id: str,
    review_id: str,
    state_root: Path | str,
    root: Path | str,
) -> bool:
    _ = root
    record = load_launch_record(launch_id=launch_id, state_root=state_root)
    if record is None:
        return False
    if record.get("launch_id") != launch_id:
        return False
    finalize = (record.get("stages") or {}).get("07_finalize") or {}
    if finalize.get("status") != "succeeded":
        return False
    freeze = (record.get("stages") or {}).get("04_freeze") or {}
    freeze_review = ((freeze.get("details") or {}).get("review_id")) or record.get("review_id")
    if freeze_review != review_id:
        return False
    provider = (record.get("request") or {}).get("provider")
    if provider != "acp":
        return False
    if not (record.get("request") or {}).get("publish_production"):
        return False
    return True


def _provider(launch: dict[str, Any]) -> str:
    return (launch.get("request") or {}).get("provider", "stub")


def _build_plan(launch: dict[str, Any]) -> dict[str, Any]:
    freeze = ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}
    return {
        "workflow": "deploy-pages.yml",
        "event": "workflow_dispatch",
        "ref": "main",
        "launch_id": launch["launch_id"],
        "review_id": freeze.get("review_id") or launch.get("review_id"),
    }


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    finalize = (launch.get("stages") or {}).get(PRIOR_STAGE) or {}
    if finalize.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_require_finalized",
        )

    plan = _build_plan(launch)
    provider = _provider(launch)
    publish_production = bool(ctx.get("publish_production") or (launch.get("request") or {}).get("publish_production"))

    if provider == "stub" or not publish_production:
        return contract.stage_receipt(
            STAGE,
            status="succeeded",
            input_sha256=input_sha,
            reason="stub_pages_dry_run",
            details={
                "plan": plan,
                "executed": False,
                "dry_run": True,
                "production_published": False,
            },
        )

    dispatch: Callable[..., dict[str, Any]] | None = ctx.get("pages_dispatch")
    if dispatch is None:
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_dispatch_not_confirmed",
            details={"plan": plan, "executed": False, "production_published": False},
        )

    result = dispatch(plan=plan, launch=launch, ctx=ctx)
    if not (isinstance(result, dict) and result.get("dispatched")):
        return contract.stage_receipt(
            STAGE,
            status="blocked",
            input_sha256=input_sha,
            reason="pages_dispatch_not_confirmed",
            details={"plan": plan, "executed": False, "production_published": False},
        )

    return contract.stage_receipt(
        STAGE,
        status="succeeded",
        input_sha256=input_sha,
        details={
            "plan": plan,
            "executed": True,
            "dry_run": False,
            "production_published": True,
        },
    )
