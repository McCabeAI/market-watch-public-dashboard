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
from scripts.pm.review_packets import build_all_packets
from scripts.pm.store import PMStore
from scripts.trader_room_public import build_public_packet, select_newest_complete_run


def init_layer(store: PMStore, *, write_trader_pointer: bool = False) -> dict[str, object]:
    run_dir = select_newest_complete_run(store.root)
    run_id = run_dir.name if run_dir else None
    if store.books_path().is_file():
        books = validate_books(store.read_books())
    else:
        books = empty_books(trader_room_run_id=run_id)
        store.write_books(books)
    if store.requests_path().is_file():
        registry = store.read_requests()
    else:
        registry = empty_registry()
        store.write_requests(registry)
    packets = {}
    if run_dir is not None:
        packets = build_all_packets(root=store.root, books=books, registry=registry, run_dir=run_dir)
        books = mark_stale_if_packet_changed(books, packets)
        store.write_books(books)
        for pm_id, packet in packets.items():
            store.write_packet(pm_id, packet)
    public = write_public_state(store, books, registry)
    if write_trader_pointer:
        tr_packet = build_public_packet(store.root)
        pointer = store.root / "data" / "trader-room" / "public" / "latest.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps(tr_packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "trader_room_run_id": run_id,
        "pm_count": 4,
        "packet_count": len(packets),
        "public_pm_count": public.get("pm_count"),
    }


def refresh_packets(store: PMStore) -> dict[str, object]:
    run_dir = select_newest_complete_run(store.root)
    if run_dir is None:
        raise SystemExit("no complete valid Trader Room run")
    books = load_or_empty_books(store, trader_room_run_id=run_dir.name)
    registry = load_or_empty_registry(store)
    packets = build_all_packets(root=store.root, books=books, registry=registry, run_dir=run_dir)
    books = mark_stale_if_packet_changed(books, packets)
    store.write_books(books)
    for pm_id, packet in packets.items():
        store.write_packet(pm_id, packet)
    write_public_state(store, books, registry)
    return {"trader_room_run_id": run_dir.name, "packet_count": len(packets)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "refresh-packets", "publish"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, default=None)
        item.add_argument("--state-root", type=Path, default=None)
        if name == "publish":
            item.add_argument("--site-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    store = PMStore(root=args.root, state_root=args.state_root)
    if args.cmd == "init":
        print(json.dumps(init_layer(store, write_trader_pointer=True), sort_keys=True))
        return 0
    if args.cmd == "refresh-packets":
        print(json.dumps(refresh_packets(store), sort_keys=True))
        return 0
    emit_pm_json(store, args.site_dir)
    print(json.dumps({"wrote": str(Path(args.site_dir) / "pm-books.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
