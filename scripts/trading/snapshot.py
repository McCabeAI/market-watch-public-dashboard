"""Per-identity memory snapshots. Common evidence stays identical."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import STANDING_SEATS
from scripts.overnight.store import write_json
from scripts.pm.constants import PM_IDS
from scripts.trading.constants import SCHEMA_VERSION
from scripts.trading.memory import build_memory_context
from scripts.trading.migrate import backfill_from_books
from scripts.trading.store import TradingStore


def snapshot_identities(
    store: TradingStore,
    *,
    owner_type: str,
    owner_ids: tuple[str, ...],
    dest_dir: Path,
    run_id: str,
    common_evidence_sha256: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    store.ensure_initialized()
    dest_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for owner_id in owner_ids:
        context = build_memory_context(store, owner_type, owner_id, when=when)
        filename = f"{owner_id}.json"
        write_json(dest_dir / filename, context)
        hashes[owner_id] = context["memory_context_sha256"]
        paths[owner_id] = str(Path(dest_dir.name) / filename)
    index = {
        "schema_version": SCHEMA_VERSION,
        "type": "IDENTITY_MEMORY_SNAPSHOT_INDEX",
        "run_id": run_id,
        "owner_type": owner_type,
        "as_of": isoformat(now_ny(when)),
        "isolation": "own_sidecar_only",
        "common_evidence_sha256": common_evidence_sha256,
        "hashes": hashes,
        "paths": paths,
    }
    write_json(dest_dir / "index.json", index)
    return index


def snapshot_overnight_traders(
    store: TradingStore,
    *,
    run_dir: Path,
    run_id: str,
    trader_books: dict[str, Any] | None = None,
    common_evidence_sha256: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    backfill_from_books(store, trader_books=trader_books, when=when)
    return snapshot_identities(
        store,
        owner_type="trader",
        owner_ids=STANDING_SEATS,
        dest_dir=run_dir / "memory",
        run_id=run_id,
        common_evidence_sha256=common_evidence_sha256,
        when=when,
    )


def snapshot_trader_room(
    store: TradingStore,
    *,
    run_dir: Path,
    run_id: str,
    common_evidence_sha256: str | None = None,
    when: datetime | None = None,
) -> dict[str, Any]:
    backfill_from_books(store, when=when)
    return snapshot_identities(
        store,
        owner_type="trader",
        owner_ids=STANDING_SEATS,
        dest_dir=run_dir / "memory",
        run_id=run_id,
        common_evidence_sha256=common_evidence_sha256,
        when=when,
    )


def compact_memory_for_packet(store: TradingStore, owner_type: str, owner_id: str) -> dict[str, Any]:
    context = build_memory_context(store, owner_type, owner_id)
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "memory_context_sha256": context["memory_context_sha256"],
        "calibration": context["calibration"],
        "recent_closed_trades": context["recent_closed_trades"],
        "active_lessons": context["active_lessons"],
        "postmortems_due": context["postmortems_due"],
        "open_positions": context["open_positions"],
        "as_of": context["as_of"],
    }


def snapshot_pm_contexts(store: TradingStore, *, when: datetime | None = None) -> dict[str, dict[str, Any]]:
    backfill_from_books(store, when=when)
    return {pm_id: compact_memory_for_packet(store, "pm", pm_id) for pm_id in PM_IDS}
