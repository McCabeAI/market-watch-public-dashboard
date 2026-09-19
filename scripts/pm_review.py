#!/usr/bin/env python3
"""Build PM review packets and deterministically ingest PM decisions."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from scripts.overnight.store import sha256_json, write_json
from scripts.pm_layer import (
    PM_BOOKS_RELPATH,
    PM_IDS,
    PM_SPECS,
    apply_pm_decisions,
    empty_pm_books,
    public_pm_view,
    refresh_pm_marks,
    validate_pm_books,
)
from scripts.trader_room_public import latest_complete_run_dir

ROOT = Path(__file__).resolve().parents[1]
DECISION_TYPE = "PM_DECISIONS"
REVIEW_PACKET_TYPE = "PM_REVIEW_PACKET"
FORBIDDEN_DECISION_KEYS = {
    "books",
    "pms",
    "realized_pnl_usd",
    "unrealized_pnl_usd",
    "total_pnl_usd",
    "gross_notional_usd",
    "entry_price",
    "mark_price",
    "entry_price_source",
    "mark_price_source",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_books(root: Path) -> dict[str, Any]:
    path = root / BOOKS_RELPATH
    if path.is_file():
        return validate_pm_books(_load(path))
    return empty_pm_books()


def _trader_room_source(root: Path, run_id: str | None = None) -> dict[str, Any]:
    if run_id:
        run_dir = root / "trader-room" / "runs" / run_id
    else:
        run_dir = latest_complete_run_dir(root)
    if run_dir is None or not run_dir.is_dir():
        raise ValueError("no complete Trader Room run is available")
    evidence = _load(run_dir / "evidence_packet.json")
    submissions = {
        p.stem: _load(p)
        for p in sorted((run_dir / "submissions").glob("*.json"))
    }
    rebuttals = {
        p.stem: _load(p)
        for p in sorted((run_dir / "rebuttals").glob("*.json"))
    } if (run_dir / "rebuttals").is_dir() else {}
    if len(submissions) != 14:
        raise ValueError("Trader Room PM input requires all 14 submissions")
    return {
        "source_type": "trader_room",
        "source_id": run_dir.name,
        "source_packet_sha256": evidence.get("packet_sha256"),
        "evidence_cutoff": evidence.get("as_of"),
        "market_state": evidence.get("market_state") or {},
        "common_context": {
            "evidence_packet": evidence,
            "submissions": submissions,
            "rebuttals": rebuttals,
            "conflict_map": _load(run_dir / "conflict_map.json"),
            "pm_handoff": _load(run_dir / "pm_handoff.json"),
        },
    }


def _overnight_source(root: Path, run_id: str) -> dict[str, Any]:
    run_dir = root / "data" / "overnight" / "runs" / run_id
    if not run_dir.is_dir():
        raise ValueError(f"overnight run {run_id} is unavailable")
    base = _load(run_dir / "evidence_snapshot.json")
    agent_path = run_dir / "agent_evidence_packet.json"
    agent = _load(agent_path) if agent_path.is_file() else None
    trader_path = run_dir / "trader_review.json"
    trader_review = _load(trader_path) if trader_path.is_file() else None
    packet_hash = (
        agent.get("packet_sha256")
        if isinstance(agent, Mapping)
        else base.get("packet_sha256")
    )
    cutoff = (
        agent.get("evidence_cutoff")
        if isinstance(agent, Mapping)
        else base.get("as_of")
    )
    market_state = (
        ((base.get("families") or {}).get("market_state") or {}).get("data")
        or {}
    )
    return {
        "source_type": "overnight",
        "source_id": run_id,
        "source_packet_sha256": packet_hash,
        "evidence_cutoff": cutoff,
        "market_state": market_state,
        "common_context": {
            "base_evidence_packet": base,
            "agent_evidence_packet": agent,
            "trader_review": trader_review,
        },
    }


def resolve_source(
    root: Path,
    *,
    source_type: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    if source_type == "trader_room":
        return _trader_room_source(root, source_id)
    if source_type == "overnight":
        if not source_id:
            raise ValueError("overnight PM review requires source_id")
        return _overnight_source(root, source_id)
    raise ValueError("source_type must be trader_room or overnight")


def build_review_packet(
    root: Path,
    *,
    pm_id: str,
    source_type: str = "trader_room",
    source_id: str | None = None,
) -> dict[str, Any]:
    if pm_id not in PM_IDS:
        raise ValueError(f"unknown PM {pm_id}")
    source = resolve_source(root, source_type=source_type, source_id=source_id)
    books = _load_books(root)
    market_state = source["market_state"]
    if market_state:
        refresh_pm_marks(books, market_state)
    packet = {
        "schema_version": 1,
        "type": REVIEW_PACKET_TYPE,
        "pm_id": pm_id,
        "pm_spec": deepcopy(PM_SPECS[pm_id]),
        "max_gross_notional_usd": 1_000_000_000,
        "source": {
            "type": source["source_type"],
            "id": source["source_id"],
            "packet_sha256": source["source_packet_sha256"],
            "evidence_cutoff": source["evidence_cutoff"],
        },
        "common_context": source["common_context"],
        "own_book": deepcopy(books["pms"][pm_id]),
        "allowed_actions": ["OPEN", "ADD", "HOLD", "REDUCE", "HEDGE", "CLOSE"],
        "execution_rules": [
            "NO TRADE / HOLD is always valid.",
            "All four PMs receive the same common evidence and trader work.",
            "Do not infer or inspect another PM's current decision before committing.",
            "Canonical entry, exit, mark and P&L arithmetic is deterministic code, not model-authored numbers.",
            "Gross open notional may not exceed $1bn.",
            "A position keeps the instrument/curve family/paper_expression chosen at OPEN until CLOSE.",
            "The Swinger may not use HEDGE; reduce or close instead.",
        ],
    }
    packet["packet_sha256"] = sha256_json(packet)
    return packet


def _walk_forbidden(value: Any, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_DECISION_KEYS:
                hits.append(child_path)
            hits.extend(_walk_forbidden(child, child_path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            hits.extend(_walk_forbidden(child, f"{path}[{i}]"))
    return hits


def validate_decision_payload(root: Path, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if payload.get("schema_version") != 1 or payload.get("type") != DECISION_TYPE:
        raise ValueError("PM decision payload schema/type mismatch")
    review_id = payload.get("review_id")
    if not isinstance(review_id, str) or not review_id.strip():
        raise ValueError("PM decision payload requires review_id")
    source_meta = payload.get("source")
    if not isinstance(source_meta, dict):
        raise ValueError("PM decision payload requires source metadata")
    source = resolve_source(
        root,
        source_type=str(source_meta.get("type") or ""),
        source_id=source_meta.get("id"),
    )
    if source_meta.get("packet_sha256") != source["source_packet_sha256"]:
        raise ValueError("PM decision payload source packet hash mismatch")
    if source_meta.get("evidence_cutoff") != source["evidence_cutoff"]:
        raise ValueError("PM decision payload evidence cutoff mismatch")
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict) or not decisions:
        raise ValueError("PM decision payload must contain at least one PM decision")
    unknown = set(decisions) - set(PM_IDS)
    if unknown:
        raise ValueError(f"unknown PM decisions: {sorted(unknown)}")
    forbidden = _walk_forbidden(decisions)
    if forbidden:
        raise ValueError(
            "PM model/chat output may not author canonical book/P&L state: "
            + ", ".join(forbidden[:8])
        )
    for pm_id, decision in decisions.items():
        if not isinstance(decision, dict):
            raise ValueError(f"{pm_id} decision must be an object")
        if decision.get("pm_id") not in (None, pm_id):
            raise ValueError(f"{pm_id} decision id mismatch")
        actions = decision.get("actions")
        if actions is not None and not isinstance(actions, list):
            raise ValueError(f"{pm_id} actions must be a list")
    return source, decisions


def apply_decision_payload(
    root: Path,
    payload: dict[str, Any],
    *,
    output: Path | None = None,
) -> dict[str, Any]:
    source, decisions = validate_decision_payload(root, payload)
    books = _load_books(root)
    updated = apply_pm_decisions(
        books,
        decisions=decisions,
        market_state=source["market_state"],
        review_id=payload["review_id"],
        evidence_cutoff=source["evidence_cutoff"],
        require_all=False,
    )
    if output is not None:
        write_json(output, updated)
    return updated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare")
    prep.add_argument("--pm-id", required=True, choices=PM_IDS)
    prep.add_argument("--source-type", default="trader_room", choices=("trader_room", "overnight"))
    prep.add_argument("--source-id")
    prep.add_argument("--output", required=True, type=Path)
    prep.add_argument("--root", type=Path, default=ROOT)

    validate = sub.add_parser("validate")
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--root", type=Path, default=ROOT)

    apply = sub.add_parser("apply")
    apply.add_argument("--input", required=True, type=Path)
    apply.add_argument("--output", type=Path)
    apply.add_argument("--root", type=Path, default=ROOT)

    public = sub.add_parser("public")
    public.add_argument("--output", required=True, type=Path)
    public.add_argument("--root", type=Path, default=ROOT)

    args = ap.parse_args(argv)
    root = args.root
    if args.command == "prepare":
        write_json(
            args.output,
            build_review_packet(
                root,
                pm_id=args.pm_id,
                source_type=args.source_type,
                source_id=args.source_id,
            ),
        )
        return 0
    if args.command == "validate":
        payload = _load(args.input)
        apply_decision_payload(root, payload)
        print(json.dumps({"status": "valid", "review_id": payload["review_id"]}, sort_keys=True))
        return 0
    if args.command == "apply":
        payload = _load(args.input)
        output = args.output or (root / BOOKS_RELPATH)
        updated = apply_decision_payload(root, payload, output=output)
        print(json.dumps({"status": "applied", "review_id": payload["review_id"], "pms": sorted(payload["decisions"])}, sort_keys=True))
        return 0
    if args.command == "public":
        books = _load_books(root)
        write_json(args.output, public_pm_view(books))
        return 0
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
