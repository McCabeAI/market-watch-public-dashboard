#!/usr/bin/env python3
"""Validate and apply a Git-native ChatGPT PM decision.

The model may not author P&L, NAV, canonical marks, or book state. Trusted code
hydrates packet mids, enforces cap/curve-lock/freshness, and mutates only the
ChatGPT book.
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.store import sha256_json
from scripts.pm.books import empty_books, validate_books
from scripts.trading.apply import apply_pm_decision_with_memory
from scripts.trading.store import TradingStore
from scripts.pm.constants import (
    CHATGPT_PM_ID,
    FORBIDDEN_MODEL_STATE_KEYS,
    SCHEMA_VERSION,
)
from scripts.pm.data_requests import apply_requests, empty_registry
from scripts.pm.errors import FreshnessError, SchemaError
from scripts.pm.review_packets import (
    build_all_packets,
    packet_id,
    market_state_from_source,
    select_daily_pm_source,
)
from scripts.pm.store import PMStore

DECISION_TYPE = "PM_DECISION"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_DIRNAME = "chatgpt"
BOOK_SHA_FILENAME = "book_sha256.txt"


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


def decision_fingerprint(payload: dict[str, Any]) -> str:
    cleaned = {k: v for k, v in payload.items() if k not in FORBIDDEN_MODEL_STATE_KEYS}
    return sha256_json(cleaned)


def receipt_path(store: PMStore, review_packet_id: str) -> Path:
    return store.decisions_dir() / f"{review_packet_id}.json"


def load_receipt(store: PMStore, review_packet_id: str) -> dict[str, Any] | None:
    path = receipt_path(store, review_packet_id)
    if not path.is_file():
        return None
    return store.read_json(path)


def chatgpt_book_sha256(books: dict[str, Any]) -> str:
    """Canonical version of the ChatGPT book.

    This is the SHA-256 of the pretty JSON encoding used by the store
    (sorted keys, indent 2, trailing newline). Tickets copy it; they do not
    invent it.
    """
    book = (books.get("pms") or {}).get(CHATGPT_PM_ID)
    if not isinstance(book, dict):
        raise SchemaError("ChatGPT book is missing")
    return sha256_json(book)


def write_chatgpt_book_pointer(store: PMStore, books: dict[str, Any]) -> str:
    digest = chatgpt_book_sha256(books)
    path = store.packet_path(CHATGPT_PM_ID, BOOK_SHA_FILENAME)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n", encoding="utf-8")
    return digest


def fingerprint_receipt_path(store: PMStore, fingerprint: str) -> Path:
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise SchemaError("decision fingerprint is not a sha256")
    return store.decisions_dir() / _RECEIPT_DIRNAME / f"{fingerprint}.json"


def _read_receipt_record(store: PMStore, path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = store.read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("receipt"), dict):
        return None
    return payload


def stored_chatgpt_book_sha256(store: PMStore) -> str:
    """Hash the ChatGPT book as persisted, before mark refresh mutates a copy."""
    if not store.books_path().is_file():
        raise SchemaError("ChatGPT books are not persisted")
    return chatgpt_book_sha256(store.read_books())


def _assert_book_binding(
    payload: dict[str, Any],
    *,
    actual: str,
    required: bool,
) -> str | None:
    expected = payload.get("expected_book_sha256")
    if expected is None:
        if required:
            raise SchemaError("expected_book_sha256 is required")
        return None
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        raise SchemaError("expected_book_sha256 must be a sha256 hex digest")
    if not isinstance(actual, str) or not _SHA256_RE.fullmatch(actual) or expected != actual:
        raise FreshnessError(
            "expected_book_sha256 does not match the current ChatGPT book; "
            "re-base this ticket on the current book"
        )
    return actual


def _reject_same_freeze(store: PMStore, payload: dict[str, Any], fingerprint: str) -> None:
    """Refuse a second distinct decision bound to a freeze that already has one."""
    packet_sha = payload.get("review_packet_sha256")
    pre_book = payload.get("expected_book_sha256")
    directory = store.decisions_dir() / _RECEIPT_DIRNAME
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        stored = _read_receipt_record(store, path)
        if stored is None:
            continue
        receipt = stored["receipt"]
        if receipt.get("decision_fingerprint") == fingerprint:
            continue
        if receipt.get("review_packet_sha256") != packet_sha:
            continue
        recorded_book = receipt.get("pre_book_sha256")
        if pre_book is None or recorded_book in (None, pre_book):
            raise SchemaError(
                "a different ChatGPT decision was already applied for this review packet state; "
                "refusing to mutate again"
            )


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
    from scripts.trading.harvest import assert_expansion_lifecycle

    for row in payload["actions"]:
        if isinstance(row, dict):
            assert_expansion_lifecycle(row, owner_id=CHATGPT_PM_ID)
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


def frozen_chatgpt_packet(store: PMStore, source: Any) -> dict[str, Any]:
    """Read the frozen accepted review, not a fresh time-dependent memory rebuild.

    Rebuilding the packet during ingestion changes holding_seconds and therefore
    its SHA even though no new market evidence arrived. The saved packet is the
    immutable decision contract; source identity and its own hash are rechecked.
    """
    path = store.packet_path(CHATGPT_PM_ID)
    if not path.is_file():
        raise FreshnessError("current ChatGPT review packet is not published; refresh PM packets")
    packet = store.read_json(path)
    if not isinstance(packet, dict):
        raise FreshnessError("stored ChatGPT review packet is invalid")
    expected_id = packet_id(
        CHATGPT_PM_ID,
        str(source.overnight_run_id or source.run_id),
        review_id=source.review_id if source.is_overnight else None,
    )
    expected_fields = {
        "review_packet_id": expected_id,
        "pm_id": CHATGPT_PM_ID,
        "source": source.kind,
        "review_id": source.review_id if source.is_overnight else None,
        "evidence_cutoff": source.evidence.get("as_of"),
        "evidence_packet_sha256": source.evidence.get("packet_sha256"),
    }
    for field, expected_value in expected_fields.items():
        if packet.get(field) != expected_value:
            raise FreshnessError(
                f"stored ChatGPT review packet {field} does not match current accepted review"
            )
    expected_hash = sha256_json({k: v for k, v in packet.items() if k != "review_packet_sha256"})
    if packet.get("review_packet_sha256") != expected_hash:
        raise FreshnessError("stored ChatGPT review packet hash integrity failed")
    return packet


def load_or_empty_books(
    store: PMStore,
    *,
    trader_room_run_id: str | None,
    overnight_run_id: str | None = None,
) -> dict[str, Any]:
    if store.books_path().is_file():
        return validate_books(store.read_books())
    return empty_books(trader_room_run_id=trader_room_run_id, overnight_run_id=overnight_run_id)


def load_or_empty_registry(store: PMStore) -> dict[str, Any]:
    if store.requests_path().is_file():
        return store.read_requests()
    return empty_registry()


def _matching_receipt(store: PMStore, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return an existing receipt for this exact decision.

    A different decision for the same packet id is allowed only after trusted
    code has refreshed the packet hash. The original receipt file is never
    replaced. A different decision for the same packet hash still fails closed.
    """
    if not isinstance(payload, dict):
        return None
    packet_id = payload.get("review_packet_id")
    if not isinstance(packet_id, str) or not packet_id:
        return None
    fingerprint = decision_fingerprint(payload)
    stored = _read_receipt_record(store, fingerprint_receipt_path(store, fingerprint))
    if stored is not None:
        receipt = stored["receipt"]
        if receipt.get("decision_fingerprint") != fingerprint:
            raise SchemaError("stored ChatGPT receipt fingerprint does not match its path")
        if receipt.get("review_packet_sha256") != payload.get("review_packet_sha256"):
            raise FreshnessError("replay review_packet_sha256 does not match the stored receipt")
        return stored
    legacy = load_receipt(store, packet_id)
    if isinstance(legacy, dict) and isinstance(legacy.get("receipt"), dict):
        receipt = legacy["receipt"]
        same_freeze = receipt.get("review_packet_sha256") == payload.get("review_packet_sha256")
        if same_freeze and receipt.get("decision_fingerprint") == fingerprint:
            return legacy
        if same_freeze and receipt.get("decision_fingerprint") != fingerprint:
            raise SchemaError(
                "a different ChatGPT decision was already applied for this review packet; "
                "refusing to mutate again"
            )
    _reject_same_freeze(store, payload, fingerprint)
    return None


def _write_decision_receipt(
    store: PMStore,
    *,
    packet_id: str,
    fingerprint: str,
    record: dict[str, Any],
) -> str:
    """Persist an immutable receipt. Never replace an earlier decision."""
    path = fingerprint_receipt_path(store, fingerprint)
    if path.is_file():
        raise SchemaError("refusing to overwrite an existing ChatGPT decision receipt")
    store.write_json(path, record)
    legacy = receipt_path(store, packet_id)
    if not legacy.is_file():
        store.write_json(legacy, record)
    relative = path.relative_to(store.state_root).as_posix()
    return relative


def apply_chatgpt_decision(
    store: PMStore,
    payload: dict[str, Any],
    *,
    write: bool = True,
    require_book_binding: bool = False,
    issue_number: int | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaError("ChatGPT decision must be a JSON object")
    if issue_number is not None and (isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0):
        raise SchemaError("issue_number must be a positive integer")
    existing = _matching_receipt(store, payload)
    if existing is not None:
        books = store.read_books() if store.books_path().is_file() else existing.get("books")
        registry = store.read_requests() if store.requests_path().is_file() else existing.get("registry")
        receipt = dict(existing["receipt"])
        receipt["already_applied"] = True
        return {
            "books": books,
            "registry": registry,
            "packets": {},
            "receipt": receipt,
            "already_applied": True,
        }

    source = select_daily_pm_source(store.root, store.state_root, allow_trader_room_fallback=True)
    books = load_or_empty_books(
        store,
        trader_room_run_id=source.trader_room_run_id,
        overnight_run_id=source.overnight_run_id,
    )
    registry = load_or_empty_registry(store)
    packet = frozen_chatgpt_packet(store, source)
    pre_book_sha256 = stored_chatgpt_book_sha256(store)
    _assert_book_binding(payload, actual=pre_book_sha256, required=require_book_binding)
    payload = validate_chatgpt_decision(payload, packet=packet)
    market_state = market_state_from_source(source)
    run_id = source.overnight_run_id or source.trader_room_run_id
    updated = apply_pm_decision_with_memory(
        books,
        payload,
        pm_id=CHATGPT_PM_ID,
        store=TradingStore(root=store.root, state_root=store.state_root),
        market_state=market_state,
        run_id=run_id,
        evidence_cutoff=packet.get("evidence_cutoff"),
        review_packet_id=packet.get("review_packet_id"),
        review_packet_sha256=packet.get("review_packet_sha256"),
        expected_memory_sha256=packet.get("memory_context_sha256"),
        evidence_hash=packet.get("review_packet_sha256"),
        review_packet=packet,
    )
    registry = apply_requests(
        registry,
        payload.get("future_data_requests") or [],
        pm_id=CHATGPT_PM_ID,
    )
    packets = build_all_packets(
        root=store.root,
        state_root=store.state_root,
        books=updated,
        registry=registry,
        source=source,
    )
    updated = _attach_packet_pointers(updated, packets)
    if source.overnight_run_id:
        updated["overnight_run_id"] = source.overnight_run_id
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "type": "PM_CHATGPT_APPLY_RECEIPT",
        "pm_id": CHATGPT_PM_ID,
        "as_of": isoformat(now_ny()),
        "source": source.kind,
        "overnight_run_id": source.overnight_run_id,
        "trader_room_run_id": source.trader_room_run_id,
        "review_packet_id": packet["review_packet_id"],
        "review_packet_sha256": packet["review_packet_sha256"],
        "evidence_cutoff": packet.get("evidence_cutoff"),
        "decision_fingerprint": decision_fingerprint(payload),
        "decision_status": updated["pms"][CHATGPT_PM_ID]["decision_status"],
        "gross_utilization_usd": updated["pms"][CHATGPT_PM_ID]["gross_utilization_usd"],
        "pre_book_sha256": pre_book_sha256,
        "post_book_sha256": chatgpt_book_sha256(updated),
        "already_applied": False,
    }
    if issue_number is not None:
        receipt["submission"] = {"channel": "github_issue", "issue_number": issue_number}
    receipt["receipt_path"] = fingerprint_receipt_path(
        store, receipt["decision_fingerprint"]
    ).relative_to(store.state_root).as_posix()
    record = {
        "decision": {k: v for k, v in payload.items() if k not in FORBIDDEN_MODEL_STATE_KEYS},
        "receipt": receipt,
    }
    if write:
        store.write_books(updated)
        store.write_requests(registry)
        for pm_id, item in packets.items():
            store.write_packet(pm_id, item)
        from scripts.pm.public import write_public_state

        write_public_state(store, updated, registry)
        _write_decision_receipt(
            store,
            packet_id=packet["review_packet_id"],
            fingerprint=receipt["decision_fingerprint"],
            record=record,
        )
        write_chatgpt_book_pointer(store, updated)
    return {
        "books": updated,
        "registry": registry,
        "packets": packets,
        "receipt": receipt,
        "already_applied": False,
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
    ap.add_argument(
        "--require-book-binding",
        action="store_true",
        help="Require expected_book_sha256 to match the current ChatGPT book",
    )
    args = ap.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SchemaError("ChatGPT decision must be a JSON object")
    store = PMStore(root=args.root, state_root=args.state_root)
    if args.command == "validate":
        existing = _matching_receipt(store, payload) if isinstance(payload, dict) else None
        if existing is not None:
            print(
                json.dumps(
                    {
                        "status": "already_applied",
                        "pm_id": CHATGPT_PM_ID,
                        "review_packet_id": payload.get("review_packet_id"),
                        "already_applied": True,
                    }
                )
            )
            return 0
        source = select_daily_pm_source(store.root, store.state_root, allow_trader_room_fallback=True)
        packet = frozen_chatgpt_packet(store, source)
        _assert_book_binding(
            payload,
            actual=stored_chatgpt_book_sha256(store),
            required=args.require_book_binding,
        )
        validate_chatgpt_decision(payload, packet=packet)
        print(
            json.dumps(
                {
                    "status": "valid",
                    "pm_id": CHATGPT_PM_ID,
                    "review_packet_id": packet["review_packet_id"],
                    "source": source.kind,
                    "overnight_run_id": source.overnight_run_id,
                }
            )
        )
        return 0
    result = apply_chatgpt_decision(store, payload, write=True)
    print(json.dumps(result["receipt"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
