"""Stage 02: refresh market-state, news, and macro evidence families."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import stage_receipt
from scripts.market_watch_launch.lineage import apply_lineage_to_macro_hard
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import EVIDENCE_FAMILIES
from scripts.overnight.freshness import required_preflight_block
from scripts.overnight.store import OvernightStore, read_json

_STAGE = "02_acquire"
_DEFAULT_FIXTURE = Path("data/overnight/fixtures/market_state.json")


def _overnight_run_id(launch: dict) -> str:
    run_id = launch.get("overnight_run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    session_date = str(launch.get("session_date") or (launch.get("request") or {}).get("session_date") or "")
    if session_date:
        return f"overnight-{session_date.replace('-', '')}"
    return "overnight-unknown"


def read_collect_families(ctx: dict, launch: dict) -> dict[str, Any]:
    store = OvernightStore(root=Path(ctx["root"]), state_root=Path(ctx["overnight_store_root"]))
    run_id = _overnight_run_id(launch)
    path = store.artifact_path(run_id, "collect.json")
    if not path.is_file():
        return {}
    snapshot = read_json(path)
    families = snapshot.get("families")
    return families if isinstance(families, dict) else {}


def _market_leg_matrix(market_payload: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(market_payload, dict):
        return {"US": "missing", "CA": "missing", "AU": "missing", "FX": "missing"}
    rates = market_payload.get("rates") if isinstance(market_payload.get("rates"), dict) else {}
    fx = market_payload.get("fx") if isinstance(market_payload.get("fx"), dict) else {}
    return {
        "US": str((rates.get("US") or {}).get("status") or "missing"),
        "CA": str((rates.get("CA") or {}).get("status") or "missing"),
        "AU": str((rates.get("AU") or {}).get("status") or "missing"),
        "FX": str(fx.get("status") or "missing"),
    }


def _family_digest_block(families: dict[str, Any], name: str) -> dict[str, Any]:
    block = families.get(name) or {}
    return {
        "status": block.get("status"),
        "digest": block.get("digest"),
        "as_of": block.get("as_of"),
    }


def run(launch: dict, ctx: dict) -> dict:
    request = launch.get("request") or {}
    mode = str(request.get("mode") or "fixture")
    root = Path(ctx["root"])
    when: datetime = ctx["when"]
    run_id = _overnight_run_id(launch)

    store = OvernightStore(root=root, state_root=Path(ctx["overnight_store_root"]))
    offline = mode != "live"
    market_state_path: Path | None = None
    if request.get("market_state_path"):
        market_state_path = Path(str(request["market_state_path"]))
        if not market_state_path.is_absolute():
            market_state_path = root / market_state_path
    elif offline:
        candidate = root / _DEFAULT_FIXTURE
        if candidate.is_file():
            market_state_path = candidate

    try:
        snapshot = collect_inputs(
            store,
            when=when,
            run_id=run_id,
            offline=offline,
            market_state_path=market_state_path,
        )
    except Exception as exc:  # noqa: BLE001
        return stage_receipt(
            _STAGE,
            status="failed",
            input_sha256=None,
            reason=str(exc),
            details={"overnight_run_id": run_id, "error": str(exc)},
        )

    families = snapshot.get("families") or {}
    ingest_stage = (launch.get("stages") or {}).get("01_ingest") or {}
    ingest_details = ingest_stage.get("details") or {}
    lineage_summary = ingest_details.get("lineage")
    launch_dir = Path(ctx["launch_dir"])
    families = apply_lineage_to_macro_hard(families, launch_dir, lineage_summary)
    if lineage_summary and (launch_dir / "lineage" / "temperature_scores.json").is_file():
        collect = {**snapshot, "families": families}
        store.write_artifact(run_id, "collect.json", collect)

    market_block = families.get("market_state") or {}
    market_payload = market_block.get("data") if isinstance(market_block, dict) else None
    preflight_error = required_preflight_block(families) if families else "missing families"
    required_mark_ok = preflight_error is None

    details: dict[str, Any] = {
        "overnight_run_id": run_id,
        "mode": mode,
        "offline": offline,
        "families": {name: _family_digest_block(families, name) for name in EVIDENCE_FAMILIES},
        "market_state_generated_at": (market_payload or {}).get("generated_at") if isinstance(market_payload, dict) else None,
        "required_preflight_ok": required_mark_ok,
        "required_preflight_block": preflight_error,
        "market_legs": _market_leg_matrix(market_payload if isinstance(market_payload, dict) else None),
    }

    return stage_receipt(
        _STAGE,
        status="succeeded",
        input_sha256=None,
        details=details,
    )
