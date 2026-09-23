"""Stage 04 — trusted review freeze at the manual launch timestamp."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.market_watch_launch import contract
from scripts.market_watch_launch.contract import LAUNCHER_ID, LEGACY_SCHEDULE_ID
from scripts.overnight.constants import FIXTURE_MARKET_STATE
from scripts.overnight.delta import compute_delta
from scripts.overnight.errors import EvidenceBoundaryError, OvernightError, SchemaError
from scripts.overnight.evidence import freeze_snapshot, require_snapshot
from scripts.overnight.ledger import load_or_create
from scripts.overnight.store import OvernightStore

STAGE = "04_freeze"
PRIOR_STAGE = "03_quality_gate"


def _overnight_run_id(launch: dict[str, Any]) -> str:
    ident = launch.get("overnight_run_id")
    if ident:
        return ident
    session = launch["session_date"].replace("-", "")
    return f"overnight-{session}"


def _prior_failed(launch: dict[str, Any], *, input_sha256: str | None) -> dict[str, Any] | None:
    prior = (launch.get("stages") or {}).get(PRIOR_STAGE) or {}
    if prior.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha256,
            reason="prior_stage_not_verified",
        )
    return None


def _offline_and_market_state(launch: dict[str, Any], ctx: dict[str, Any]) -> tuple[bool, Path | None]:
    mode = (launch.get("request") or {}).get("mode", "fixture")
    offline = mode != "live"
    req_path = (launch.get("request") or {}).get("market_state_path")
    if req_path:
        return offline, Path(req_path)
    if offline:
        return True, Path(ctx["root"]) / FIXTURE_MARKET_STATE
    return False, None


def apply_macro_overlay(families: dict[str, Any], launch: dict[str, Any]) -> dict[str, Any]:
    ingest = ((launch.get("stages") or {}).get("01_ingest") or {}).get("details") or {}
    rows = ingest.get("rows")
    if not rows:
        return families
    try:
        from scripts.market_watch_launch import quality_gate as qg

        if hasattr(qg, "apply_macro_overlay") and isinstance(rows, list):
            return qg.apply_macro_overlay(families, rows)
    except Exception:
        pass
    out = deepcopy(families)
    macro = dict(out.get("macro_hard") or {})
    extra = dict(macro.get("extra") or {})
    extra["ingested"] = rows
    notes = list(macro.get("notes") or [])
    notes.append(f"manual launch ingest overlay: {len(rows)} row(s)")
    macro["extra"] = extra
    macro["notes"] = notes
    out["macro_hard"] = macro
    return out


def _write_collect_with_overlay(store: OvernightStore, run_id: str, launch: dict[str, Any]) -> None:
    collect = store.read_artifact(run_id, "collect.json")
    families = apply_macro_overlay(collect.get("families") or {}, launch)
    collect = {**collect, "families": families}
    store.write_artifact(run_id, "collect.json", collect)


def _overlay_delta_artifact(store: OvernightStore, run_id: str, filename: str, launch: dict[str, Any]) -> None:
    if not store.has_artifact(run_id, filename):
        return
    delta = store.read_artifact(run_id, filename)
    families = apply_macro_overlay(delta.get("families") or {}, launch)
    store.write_artifact(run_id, filename, {**delta, "families": families})


def run(launch: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    input_sha = launch.get("base_packet_sha256")
    blocked = _prior_failed(launch, input_sha256=input_sha)
    if blocked:
        return blocked
    q = (launch.get("stages") or {}).get(PRIOR_STAGE) or {}
    if q.get("status") != "succeeded":
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="prior_stage_not_verified",
        )

    launch_dir = Path(ctx["launch_dir"])
    launch_dir.mkdir(parents=True, exist_ok=True)
    binding_path = launch_dir / "freeze_binding.json"

    store = OvernightStore(root=ctx["root"], state_root=ctx["overnight_store_root"])
    run_id = _overnight_run_id(launch)
    when: datetime | None = ctx.get("when")
    load_or_create(store, run_id=run_id, when=when, dry_run=(launch.get("request") or {}).get("mode") == "fixture")

    if not store.has_artifact(run_id, "collect.json"):
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason="missing_collect",
        )

    offline, market_state_path = _offline_and_market_state(launch, ctx)
    try:
        _write_collect_with_overlay(store, run_id, launch)
        compute_delta(
            store,
            run_id=run_id,
            stage="pre_trader_delta",
            when=when,
            offline=offline,
            market_state_path=market_state_path,
        )
        _overlay_delta_artifact(store, run_id, "pre_trader_delta.json", launch)

        reuse_open = not (launch.get("rerun") or (launch.get("request") or {}).get("rerun"))
        packet = freeze_snapshot(store, run_id=run_id, when=when, reuse_open=reuse_open)
        review_id = packet["review_id"]
        packet_sha256 = packet["packet_sha256"]

        if binding_path.is_file():
            existing_binding = json.loads(binding_path.read_text(encoding="utf-8"))
            if existing_binding.get("launch_id") == launch.get("launch_id"):
                if existing_binding.get("packet_sha256") == packet_sha256:
                    verified = require_snapshot(store, run_id, review_id)
                    if verified.get("packet_sha256") != packet_sha256:
                        return contract.stage_receipt(
                            STAGE,
                            status="failed",
                            input_sha256=input_sha,
                            reason="freeze_verification_failed",
                        )
                    launch["overnight_run_id"] = run_id
                    launch["review_id"] = review_id
                    launch["base_packet_sha256"] = packet_sha256
                    launch["starting_trader_books_sha256"] = verified.get("starting_trader_books_sha256")
                    launch["starting_pm_books_sha256"] = verified.get("starting_pm_books_sha256")
                    return contract.stage_receipt(
                        STAGE,
                        status="succeeded",
                        input_sha256=input_sha,
                        output_sha256=packet_sha256,
                        artifact=str(binding_path),
                        details={
                            "overnight_run_id": run_id,
                            "review_id": review_id,
                            "packet_sha256": packet_sha256,
                            "as_of": verified.get("as_of"),
                            "starting_trader_books_sha256": verified.get("starting_trader_books_sha256"),
                            "starting_pm_books_sha256": verified.get("starting_pm_books_sha256"),
                            "evidence_boundary": "actual_freeze_timestamp",
                            "legacy_0150_used": False,
                            "idempotent": True,
                        },
                    )
                return contract.stage_receipt(
                    STAGE,
                    status="failed",
                    input_sha256=input_sha,
                    reason="freeze_hash_conflict",
                )

        verified = require_snapshot(store, run_id, review_id)
        if verified.get("packet_sha256") != packet_sha256:
            return contract.stage_receipt(
                STAGE,
                status="failed",
                input_sha256=input_sha,
                reason="freeze_verification_failed",
            )

        binding = {
            "launch_id": launch["launch_id"],
            "overnight_run_id": run_id,
            "review_id": review_id,
            "packet_sha256": packet_sha256,
            "as_of": verified.get("as_of"),
            "starting_trader_books_sha256": verified.get("starting_trader_books_sha256"),
            "starting_pm_books_sha256": verified.get("starting_pm_books_sha256"),
            "launcher_id": LAUNCHER_ID,
            "legacy_schedule_id": LEGACY_SCHEDULE_ID,
            "legacy_schedule_id_active": False,
        }
        binding_path.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        launch["overnight_run_id"] = run_id
        launch["review_id"] = review_id
        launch["base_packet_sha256"] = packet_sha256
        launch["starting_trader_books_sha256"] = verified.get("starting_trader_books_sha256")
        launch["starting_pm_books_sha256"] = verified.get("starting_pm_books_sha256")

        return contract.stage_receipt(
            STAGE,
            status="succeeded",
            input_sha256=input_sha,
            output_sha256=packet_sha256,
            artifact=str(binding_path),
            details={
                "overnight_run_id": run_id,
                "review_id": review_id,
                "packet_sha256": packet_sha256,
                "as_of": verified.get("as_of"),
                "starting_trader_books_sha256": verified.get("starting_trader_books_sha256"),
                "starting_pm_books_sha256": verified.get("starting_pm_books_sha256"),
                "evidence_boundary": "actual_freeze_timestamp",
                "legacy_0150_used": False,
            },
        )
    except (EvidenceBoundaryError, SchemaError, OvernightError) as exc:
        return contract.stage_receipt(
            STAGE,
            status="failed",
            input_sha256=input_sha,
            reason=str(exc),
        )
