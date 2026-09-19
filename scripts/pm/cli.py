#!/usr/bin/env python3
"""Initialize, refresh, and publish the four-PM layer. Never invokes models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pm.books import empty_books, mark_stale_if_packet_changed, validate_books
from scripts.pm.chatgpt_ingest import load_or_empty_books, load_or_empty_registry
from scripts.pm.data_requests import empty_registry
from scripts.pm.public import emit_pm_json, write_public_state
from scripts.pm.review_packets import (
    SOURCE_TRADER_ROOM_FALLBACK,
    build_all_packets,
    select_daily_pm_source,
)
from scripts.pm.store import PMStore
from scripts.trader_room_public import build_public_packet


def _persist_packets(store: PMStore, books: dict, registry: dict, packets: dict) -> dict:
    books = mark_stale_if_packet_changed(books, packets)
    source = next(iter(packets.values()), {})
    books["overnight_run_id"] = source.get("overnight_run_id")
    books["trader_room_run_id"] = source.get("trader_room_run_id")
    if source.get("evidence_cutoff"):
        books["evidence_cutoff"] = source["evidence_cutoff"]
    store.write_books(books)
    for pm_id, packet in packets.items():
        store.write_packet(pm_id, packet)
    write_public_state(store, books, registry)
    return books


def refresh_packets(
    store: PMStore,
    *,
    allow_trader_room_fallback: bool = True,
    overnight_run_id: str | None = None,
    source=None,
) -> dict[str, object]:
    selected = source or select_daily_pm_source(
        store.root,
        store.state_root,
        allow_trader_room_fallback=allow_trader_room_fallback,
        overnight_run_id=overnight_run_id,
    )
    books = load_or_empty_books(
        store,
        trader_room_run_id=selected.trader_room_run_id,
        overnight_run_id=selected.overnight_run_id,
    )
    registry = load_or_empty_registry(store)
    packets = build_all_packets(
        root=store.root,
        state_root=store.state_root,
        books=books,
        registry=registry,
        source=selected,
    )
    books = _persist_packets(store, books, registry, packets)
    return {
        "source": selected.kind,
        "overnight_run_id": selected.overnight_run_id,
        "trader_room_run_id": selected.trader_room_run_id,
        "evidence_cutoff": selected.evidence.get("as_of"),
        "evidence_packet_sha256": selected.evidence.get("packet_sha256"),
        "packet_count": len(packets),
        "fallback": selected.kind == SOURCE_TRADER_ROOM_FALLBACK,
    }


def init_layer(store: PMStore, *, write_trader_pointer: bool = False) -> dict[str, object]:
    """Seed PM books and packets. Overnight is preferred; Trader Room is explicit fallback."""
    try:
        selected = select_daily_pm_source(store.root, store.state_root, allow_trader_room_fallback=True)
    except Exception:
        selected = None
    if store.books_path().is_file():
        books = validate_books(store.read_books())
    else:
        books = empty_books(
            trader_room_run_id=selected.trader_room_run_id if selected else None,
            overnight_run_id=selected.overnight_run_id if selected else None,
        )
        store.write_books(books)
    if store.requests_path().is_file():
        registry = store.read_requests()
    else:
        registry = empty_registry()
        store.write_requests(registry)
    packets = {}
    summary: dict[str, object] = {
        "source": selected.kind if selected else None,
        "overnight_run_id": selected.overnight_run_id if selected else None,
        "trader_room_run_id": selected.trader_room_run_id if selected else None,
        "pm_count": 4,
        "packet_count": 0,
        "fallback": bool(selected and selected.kind == SOURCE_TRADER_ROOM_FALLBACK),
    }
    if selected is not None:
        packets = build_all_packets(
            root=store.root,
            state_root=store.state_root,
            books=books,
            registry=registry,
            source=selected,
        )
        books = _persist_packets(store, books, registry, packets)
        summary["packet_count"] = len(packets)
        summary["evidence_cutoff"] = selected.evidence.get("as_of")
        summary["evidence_packet_sha256"] = selected.evidence.get("packet_sha256")
    else:
        write_public_state(store, books, registry)
    if write_trader_pointer:
        tr_packet = build_public_packet(store.root)
        pointer = store.root / "data" / "trader-room" / "public" / "latest.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps(tr_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    public = store.read_json(store.public_path()) if store.public_path().is_file() else {}
    summary["public_pm_count"] = public.get("pm_count")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "refresh-packets", "publish"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, default=None)
        item.add_argument("--state-root", type=Path, default=None)
        if name == "refresh-packets":
            item.add_argument(
                "--allow-trader-room-fallback",
                action="store_true",
                help="Explicit initialization/manual fallback to on-demand Trader Room. Never labeled as overnight.",
            )
            item.add_argument("--overnight-run-id", default=None)
        if name == "publish":
            item.add_argument("--site-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    store = PMStore(root=args.root, state_root=args.state_root)
    if args.cmd == "init":
        print(json.dumps(init_layer(store, write_trader_pointer=True), sort_keys=True))
        return 0
    if args.cmd == "refresh-packets":
        print(
            json.dumps(
                refresh_packets(
                    store,
                    allow_trader_room_fallback=args.allow_trader_room_fallback,
                    overnight_run_id=args.overnight_run_id,
                ),
                sort_keys=True,
            )
        )
        return 0
    emit_pm_json(store, args.site_dir)
    print(json.dumps({"wrote": str(Path(args.site_dir) / "pm-books.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
