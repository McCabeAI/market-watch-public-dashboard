#!/usr/bin/env python3
"""Validate and apply a Git-native ChatGPT PM decision.

The model may not author P&L, NAV, canonical marks, or book state. Trusted code
hydrates packet mids, enforces cap/curve-lock/freshness, and mutates only the
ChatGPT book.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.pm.books import apply_decision, empty_books, validate_books
from scripts.pm.constants import (
    CHATGPT_PM_ID,
    FORBIDDEN_MODEL_STATE_KEYS,
    SCHEMA_VERSION,
)
from scripts.pm.data_requests import apply_requests, empty_registry
from scripts.pm.errors import FreshnessError, SchemaError
from scripts.pm.review_packets import build_all_packets, market_state_from_run
from scripts.pm.store import PMStore
from scripts.trader_room_public import select_newest_complete_run

DECISION_TYPE = "PM_DECISION"


def _walk_forbidden(value: Any, *, path: str = "$", allow_action_prices: bool = False) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        action = value.get("action")
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in FORBIDDEN_MODEL_STATE_KEYS:
                if allow_action_prices and action and key in {"mark_price", "entry_price"}:
                    continue
                found.append(child)
            found.extend(_walk_forbidden(item, path=child, allow_action_prices=allow_action_prices))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            found.extend(_walk_forbidden(item, path=f"{path}[{idx}]", allow_action_prices=allow_action_prices))
    return found


def validate_chatgpt_decision(
    payload: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaError("ChatGPT decision must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError("ChatGPT decision schema_version mismatch")
    if payload.get("type") != DECISION_TYPE:
        raise SchemaError(f"ChatGPT decision type must be {DECISION_TYPE}")
    if payload.get("pm_id") != CHATGPT_PM_ID:
        raise SchemaError("ChatGPT decision pm_id must be chatgpt")
    forbidden = _walk_forbidden(payload, allow_action_prices=True)
    if forbidden:
        raise SchemaError(
            "model may not author canonical book/P&L/mark state: " + ", ".join(forbidden[:8])
        )
    if payload.get("review_packet_id") != packet.get("review_packet_id"):
        raise FreshnessError("ChatGPT decision review_packet_id does not match the current packet")
    if payload.get("review_packet_sha256") != packet.get("review_packet_sha256"):
        raise FreshnessError("ChatGPT decision review_packet_sha256 is stale or wrong")
    if payload.get("evidence_cutoff") != packet.get("evidence_cutoff"):
        raise FreshnessError("ChatGPT decision evidence_cutoff does not match the current packet")
    if not isinstance(payload.get("actions"), list):
        raise SchemaError("ChatGPT decision actions must be a list")
    if payload.get("conviction") is not None:
        conviction = int(payload["conviction"])
        if not 0 <= conviction <= 100:
            raise SchemaError("conviction must be 0-100")
    for key in ("thesis", "invalidation", "rationale", "synthesis"):
        if payload.get(key) is not None and not isinstance(payload.get(key), str):
            raise SchemaError(f"{key} must be a string or null")
    if payload.get("alerts") is not None and not isinstance(payload.get("alerts"), list):
        raise SchemaError("alerts must be a list")
    if payload.get("future_data_requests") is not None and not isinstance(payload.get("future_data_requests"), list):
        raise SchemaError("future_data_requests must be a list")
    return payload


def load_or_empty_books(store: PMStore, *, trader_room_run_id: str | None) -> dict[str, Any]:
    if store.books_path().is_file():
        return validate_books(store.read_books())
    return empty_books(trader_room_run_id=trader_room_run_id)


def load_or_empty_registry(store: PMStore) -> dict[str, Any]:
    if store.requests_path().is_file():
        return store.read_requests()
    return empty_registry()


def apply_chatgpt_decision(
    store: PMStore,
    payload: dict[str, Any],
    *,
    write: bool = True,
) -> dict[str, Any]:
    run_dir = select_newest_complete_run(store.root)
    if run_dir is None:
        raise SchemaError("no complete valid Trader Room run for ChatGPT ingest")
    books = load_or_empty_books(store, trader_room_run_id=run_dir.name)
    registry = load_or_empty_registry(store)
    packets = build_all_packets(root=store.root, books=books, registry=registry, run_dir=run_dir)
    packet = packets[CHATGPT_PM_ID]
    payload = validate_chatgpt_decision(payload, packet=packet)
    market_state = market_state_from_run(run_dir)
    updated = apply_decision(
        books,
        payload,
        pm_id=CHATGPT_PM_ID,
        market_state=market_state,
        run_id=run_dir.name,
        evidence_cutoff=packet.get("evidence_cutoff"),
        review_packet_id=packet.get("review_packet_id"),
        review_packet_sha256=packet.get("review_packet_sha256"),
    )
    registry = apply_requests(
        registry,
        payload.get("future_data_requests") or [],
        pm_id=CHATGPT_PM_ID,
    )
    packets = build_all_packets(root=store.root, books=updated, registry=registry, run_dir=run_dir)
    updated = _attach_packet_pointers(updated, packets)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_CHATGPT_APPLY_RECEIPT",
        "pm_id": CHATGPT_PM_ID,
        "as_of": isoformat(now_ny()),
        "trader_room_run_id": run_dir.name,
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": packet["review_packet_sha256"],
        "decision_status": updated["pms"][CHATGPT_PM_ID]["decision_status"],
        "gross_utilization_usd": updated["pms"][CHATGPT_PM_ID]["gross_utilization_usd"],
    }
    if write:
        store.write_books(updated)
        store.write_requests(registry)
        for pm_id, item in packets.items():
            store.write_packet(pm_id, item)
        from scripts.pm.public import write_public_state

        write_public_state(store, updated, registry)
        store.write_json(
            store.decisions_dir() / f"{run_dir.name}-chatgpt.json",
            {
                "decision": {k: v for k, v in payload.items() if k not in FORBIDDEN_MODEL_STATE_KEYS},
                "receipt": receipt,
            },
        )
    return {
        "books": updated,
        "registry": registry,
        "packets": packets,
        "receipt": receipt,
    }


def _attach_packet_pointers(books: dict[str, Any], packets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = deepcopy(books)
    for pm_id, packet in packets.items():
        book = out["pms"][pm_id]
        book["review_packet_id"] = packet.get("review_packet_id")
        book["review_packet_sha256"] = packet.get("review_packet_sha256")
        if not book.get("last_decision_at"):
            book["review_status"] = "awaiting"
        elif book.get("evidence_cutoff") == packet.get("evidence_cutoff") and book.get(
            "last_decision_packet_id"
        ):
            book["review_status"] = "fresh"
        else:
            book["review_status"] = "stale"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate or apply a ChatGPT PM decision")
    ap.add_argument("command", choices=("validate", "apply"))
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--state-root", type=Path, default=None)
    args = ap.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    store = PMStore(root=args.root, state_root=args.state_root)
    if args.command == "validate":
        run_dir = select_newest_complete_run(store.root)
        if run_dir is None:
            raise SchemaError("no complete valid Trader Room run")
        books = load_or_empty_books(store, trader_room_run_id=run_dir.name)
        registry = load_or_empty_registry(store)
        packets = build_all_packets(root=store.root, books=books, registry=registry, run_dir=run_dir)
        validate_chatgpt_decision(payload, packet=packets[CHATGPT_PM_ID])
        print(json.dumps({"status": "valid", "pm_id": CHATGPT_PM_ID, "review_packet_id": packets[CHATGPT_PM_ID]["review_packet_id"]}))
        return 0
    result = apply_chatgpt_decision(store, payload, write=True)
    print(json.dumps(result["receipt"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
