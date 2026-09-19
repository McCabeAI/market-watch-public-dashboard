"""Validate and apply ACP-scheduled Market Watch model output.

Provider output is untrusted evidence + structured decisions only. It may never
supply canonical books, NAV, realized P&L, or unrealized P&L. Those are derived
here from trusted repository code after the scheduled-output PR is accepted.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.overnight.books import apply_review, validate_books
from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.overnight.constants import SCHEMA_VERSION, STANDING_SEATS
from scripts.overnight.errors import EvidenceBoundaryError, SchemaError
from scripts.overnight.evidence import require_snapshot
from scripts.overnight.ledger import load_or_create, mark_finished, mark_running, persist_run
from scripts.overnight.store import OvernightStore, sha256_json, write_json
from scripts.pm_layer import (
    MODEL_PM_IDS,
    PM_BOOKS_RELPATH,
    apply_pm_decisions,
    empty_pm_books,
    validate_pm_books,
)

SCHEDULE_ID = "market-watch-weekday-0205"
OUTPUT_TYPE = "OVERNIGHT_SCHEDULED_OUTPUT"
AGENT_PACKET_TYPE = "OVERNIGHT_AGENT_EVIDENCE_PACKET"
ALLOWED_MODELS = {"grok-4.6", "composer-2.5"}
TOTAL_MODEL_CAP = 18
GROK_CAP = 16
COMPOSER_CAP = 2
PM_TOTAL_MODEL_CAP = 21
PM_GROK_CAP = 19
PM_COMPOSER_CAP = 2

FORBIDDEN_MODEL_STATE_KEYS = {
    "books",
    "nav_usd",
    "cash_usd",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "starting_nav_usd",
    "gross_pnl_usd",
    "funding_cost_usd",
    "cash_yield_usd",
    "funding_last_accrual_at",
    "net_pnl_usd",
    "competition_rank",
    "gross_notional_usd",
    "total_pnl_usd",
    "entry_price",
    "mark_price",
    "entry_price_source",
    "mark_price_source",
}


def _walk_forbidden(value: Any, *, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in FORBIDDEN_MODEL_STATE_KEYS:
                found.append(child)
            found.extend(_walk_forbidden(item, path=child))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_walk_forbidden(item, path=f"{path}[{idx}]"))
    return found


def _packet_hash(packet: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})


def validate_execution(execution: dict[str, Any], *, pm_enabled: bool = False) -> dict[str, Any]:
    if not isinstance(execution, dict):
        raise SchemaError("scheduled output missing execution object")
    if execution.get("parent_model") != "grok-4.6":
        raise SchemaError("scheduled parent must be grok-4.6")
    allowed = set(execution.get("allowed_subagent_models") or [])
    if allowed != ALLOWED_MODELS:
        raise SchemaError(f"allowed_subagent_models must be exactly {sorted(ALLOWED_MODELS)}")
    if execution.get("auto_used") is not False:
        raise SchemaError("Cursor Auto is prohibited for the overnight run")
    if int(execution.get("other_models_calls", -1)) != 0:
        raise SchemaError("Other Models usage must be zero")
    total_cap = int(execution.get("total_model_cap", -1))
    grok_cap = int(execution.get("grok_cap", -1))
    composer_cap = int(execution.get("composer_cap", -1))
    expected = (
        (PM_TOTAL_MODEL_CAP, PM_GROK_CAP, PM_COMPOSER_CAP)
        if pm_enabled
        else (TOTAL_MODEL_CAP, GROK_CAP, COMPOSER_CAP)
    )
    if (total_cap, grok_cap, composer_cap) != expected:
        raise SchemaError("scheduled output model caps do not match the selected Market Watch contract")
    total = int(execution.get("declared_total_model_calls", -1))
    grok = int(execution.get("declared_grok_calls", -1))
    composer = int(execution.get("declared_composer_calls", -1))
    if min(total, grok, composer) < 0 or total != grok + composer:
        raise SchemaError("declared model-call counts are inconsistent")
    if total > total_cap or grok > grok_cap or composer > composer_cap:
        raise SchemaError("declared model-call counts exceed the run budget")
    return execution


def validate_output(store: OvernightStore, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("scheduled output schema_version mismatch")
    if payload.get("type") != OUTPUT_TYPE:
        raise SchemaError("scheduled output type mismatch")
    if payload.get("schedule_id") != SCHEDULE_ID:
        raise SchemaError(f"scheduled output schedule_id must be {SCHEDULE_ID}")
    run_id = payload.get("overnight_run_id")
    if not isinstance(run_id, str) or not run_id.startswith("overnight-"):
        raise SchemaError("scheduled output overnight_run_id is missing or malformed")

    forbidden = _walk_forbidden(payload)
    if forbidden:
        raise SchemaError(
            "model output may not provide canonical book/P&L state: " + ", ".join(forbidden[:8])
        )

    base = require_snapshot(store, run_id)
    if payload.get("base_packet_sha256") != base.get("packet_sha256"):
        raise EvidenceBoundaryError("scheduled output does not derive from the trusted 01:50 base packet")

    agent_packet = payload.get("agent_packet")
    if not isinstance(agent_packet, dict):
        raise SchemaError("scheduled output missing agent_packet")
    if agent_packet.get("type") != AGENT_PACKET_TYPE:
        raise SchemaError("agent_packet type mismatch")
    if agent_packet.get("overnight_run_id") != run_id:
        raise SchemaError("agent_packet overnight_run_id mismatch")
    if agent_packet.get("base_packet_sha256") != base.get("packet_sha256"):
        raise EvidenceBoundaryError("agent_packet base hash mismatch")
    if agent_packet.get("base_evidence_cutoff") != base.get("as_of"):
        raise EvidenceBoundaryError("agent_packet base_evidence_cutoff must equal the trusted base cutoff")
    if agent_packet.get("competition") != base.get("competition"):
        raise EvidenceBoundaryError("agent_packet must preserve the frozen competition/funding contract")
    final_cutoff = agent_packet.get("evidence_cutoff")
    if not isinstance(final_cutoff, str):
        raise SchemaError("agent_packet evidence_cutoff is required")
    try:
        base_cutoff = parse_iso(base["as_of"])
        frozen_cutoff = parse_iso(final_cutoff)
    except (TypeError, ValueError) as exc:
        raise SchemaError("agent_packet evidence_cutoff must be an ISO timestamp") from exc
    if frozen_cutoff < base_cutoff:
        raise EvidenceBoundaryError("final agent packet cannot predate the trusted base packet")
    if frozen_cutoff.date() != base_cutoff.date():
        raise EvidenceBoundaryError("final agent packet must remain in the same overnight session date")
    supplement = agent_packet.get("research_supplement")
    if not isinstance(supplement, dict):
        raise SchemaError("agent_packet missing research_supplement")
    for key in ("news", "central_bank_research", "sources"):
        if not isinstance(supplement.get(key), list):
            raise SchemaError(f"research_supplement.{key} must be a list")
    if supplement.get("summary") is not None and not isinstance(supplement.get("summary"), str):
        raise SchemaError("research_supplement.summary must be a string or null")
    expected_packet_hash = _packet_hash(agent_packet)
    if agent_packet.get("packet_sha256") != expected_packet_hash:
        raise EvidenceBoundaryError("agent_packet packet_sha256 mismatch")

    decisions = payload.get("decisions")
    if not isinstance(decisions, dict) or set(decisions) != set(STANDING_SEATS):
        raise SchemaError("scheduled output must contain exactly the locked 14 trader seats")
    for seat, decision in decisions.items():
        if not isinstance(decision, dict):
            raise SchemaError(f"{seat} decision must be an object")
        if decision.get("seat") != seat:
            raise SchemaError(f"{seat} decision seat mismatch")
        if decision.get("overnight_run_id") != run_id:
            raise EvidenceBoundaryError(f"{seat} run_id mismatch")
        if decision.get("packet_sha256") != agent_packet["packet_sha256"]:
            raise EvidenceBoundaryError(f"{seat} did not use the final frozen agent packet")
        if decision.get("evidence_cutoff") != agent_packet["evidence_cutoff"]:
            raise EvidenceBoundaryError(f"{seat} evidence cutoff mismatch")
        if not isinstance(decision.get("actions"), list) or not decision["actions"]:
            raise SchemaError(f"{seat} must return at least one structured action")
        for forbidden_key in ("tools_used", "web_search", "web_fetch", "fetched_new_evidence"):
            if decision.get(forbidden_key):
                raise EvidenceBoundaryError(f"{seat} recorded forbidden post-freeze acquisition: {forbidden_key}")

    pm_decisions = payload.get("pm_decisions")
    if pm_decisions is not None:
        if not isinstance(pm_decisions, dict) or set(pm_decisions) != set(MODEL_PM_IDS):
            raise SchemaError(
                "scheduled pm_decisions must contain exactly swinger-pm, pragmatist-pm and grinder-pm"
            )
        for pm_id, decision in pm_decisions.items():
            if not isinstance(decision, dict):
                raise SchemaError(f"{pm_id} PM decision must be an object")
            if decision.get("pm_id") not in (None, pm_id):
                raise SchemaError(f"{pm_id} PM decision id mismatch")
            if not isinstance(decision.get("actions"), list) or not decision["actions"]:
                raise SchemaError(f"{pm_id} PM decision must contain at least one action")
            if decision.get("packet_sha256") not in (None, agent_packet["packet_sha256"]):
                raise EvidenceBoundaryError(f"{pm_id} PM decision packet hash mismatch")
            if decision.get("evidence_cutoff") not in (None, agent_packet["evidence_cutoff"]):
                raise EvidenceBoundaryError(f"{pm_id} PM decision evidence cutoff mismatch")

    validate_execution(
        payload.get("execution") or {},
        pm_enabled=payload.get("pm_decisions") is not None,
    )
    return payload


def _apply_validated(
    store: OvernightStore,
    payload: dict[str, Any],
    *,
    write: bool,
) -> dict[str, Any]:
    payload = validate_output(store, payload)
    run_id = payload["overnight_run_id"]
    base = require_snapshot(store, run_id)
    prior_books = validate_books(deepcopy(base["prior_books"]))
    decisions = deepcopy(payload["decisions"])

    updated = apply_review(
        prior_books,
        decisions,
        families=base["families"],
        run_id=run_id,
        evidence_cutoff=payload["agent_packet"]["evidence_cutoff"],
        when=parse_iso(payload["agent_packet"]["evidence_cutoff"]),
        market_state=(base.get("families", {}).get("market_state", {}) or {}).get("data"),
    )
    updated["review_status"] = "fresh"
    updated["last_successful_review_run_id"] = run_id

    pm_books = None
    if payload.get("pm_decisions") is not None:
        pm_path = store.state_root / PM_BOOKS_RELPATH
        if pm_path.is_file():
            pm_books = validate_pm_books(json.loads(pm_path.read_text(encoding="utf-8")))
        else:
            pm_books = empty_pm_books()
        market_state = ((base.get("families") or {}).get("market_state") or {}).get("data") or {}
        pm_books = apply_pm_decisions(
            pm_books,
            decisions=payload["pm_decisions"],
            market_state=market_state,
            review_id=f"{run_id}-pm",
            evidence_cutoff=payload["agent_packet"]["evidence_cutoff"],
            when=parse_iso(payload["agent_packet"]["evidence_cutoff"]),
            require_all=False,
        )

    review = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_TRADER_REVIEW",
        "overnight_run_id": run_id,
        "as_of": isoformat(now_ny()),
        "evidence_cutoff": payload["agent_packet"]["evidence_cutoff"],
        "packet_sha256": payload["agent_packet"]["packet_sha256"],
        "base_packet_sha256": payload["base_packet_sha256"],
        "source": "acp-scheduled-output",
        "schedule_id": payload["schedule_id"],
        "model_calls": payload["execution"]["declared_total_model_calls"],
        "full_trader_room": False,
        "status": "succeeded",
        "errors": [],
        "reviews": decisions,
        "books": updated,
        "pm_review_status": "fresh" if pm_books is not None else "not_supplied",
        "pm_ids": sorted(payload.get("pm_decisions") or {}),
    }

    if write:
        store.write_artifact(run_id, "agent_evidence_packet.json", payload["agent_packet"])
        store.write_artifact(run_id, "scheduled_output.json", payload)
        store.write_artifact(run_id, "trader_review.json", review)
        store.write_books(updated)
        if pm_books is not None:
            write_json(store.state_root / PM_BOOKS_RELPATH, pm_books)
            store.write_artifact(
                run_id,
                "pm_review.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "type": "OVERNIGHT_PM_REVIEW",
                    "overnight_run_id": run_id,
                    "review_id": f"{run_id}-pm",
                    "evidence_cutoff": payload["agent_packet"]["evidence_cutoff"],
                    "packet_sha256": payload["agent_packet"]["packet_sha256"],
                    "pm_ids": sorted(payload["pm_decisions"]),
                    "status": "succeeded",
                },
            )
        run = load_or_create(store, run_id=run_id)
        mark_running(
            run,
            "trader_review",
            inputs={
                "source": "acp-scheduled-output",
                "schedule_id": payload["schedule_id"],
                "base_packet_sha256": payload["base_packet_sha256"],
            },
        )
        mark_finished(
            run,
            "trader_review",
            status="succeeded",
            outputs={
                "source": "acp-scheduled-output",
                "packet_sha256": payload["agent_packet"]["packet_sha256"],
                "model_calls": payload["execution"]["declared_total_model_calls"],
            },
        )
        persist_run(store, run)
    return review


def simulate_output(store: OvernightStore, payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mw-scheduled-output-") as tmp:
        tmp_root = Path(tmp)
        source_state = store.state_dir()
        if source_state.is_dir():
            shutil.copytree(source_state, tmp_root / "data" / "overnight", dirs_exist_ok=True)
        source_pm = store.state_root / "data" / "pm" / "books"
        if source_pm.is_dir():
            shutil.copytree(source_pm, tmp_root / "data" / "pm" / "books", dirs_exist_ok=True)
        temp_store = OvernightStore(root=store.root, state_root=tmp_root)
        return _apply_validated(temp_store, payload, write=True)


def apply_output(store: OvernightStore, payload: dict[str, Any]) -> dict[str, Any]:
    return _apply_validated(store, payload, write=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("validate", "apply"))
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--state-root", type=Path, default=None)
    args = ap.parse_args(argv)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    store = OvernightStore(root=args.root, state_root=args.state_root)
    if args.command == "validate":
        review = simulate_output(store, payload)
    else:
        review = apply_output(store, payload)
    print(
        json.dumps(
            {
                "overnight_run_id": review["overnight_run_id"],
                "status": review["status"],
                "model_calls": review["model_calls"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
