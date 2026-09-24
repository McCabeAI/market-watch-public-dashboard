"""01:50 ET freeze of the common evidence snapshot.

The 02:05 trader review must consume this exact packet and must not fetch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.funding.context import build_funding_context, competition_contract
from scripts.overnight.books import empty_books, validate_books
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import (
    FORBIDDEN_ACQUISITION,
    SCHEMA_VERSION,
)
from scripts.overnight.errors import EvidenceBoundaryError, SchemaError
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.trader_room.evidence import load_research_method


def _snapshot_is_valid(packet: dict[str, Any], run_id: str, review_id: str) -> bool:
    if packet.get("type") != "OVERNIGHT_EVIDENCE_SNAPSHOT":
        return False
    if packet.get("overnight_run_id") != run_id:
        return False
    if packet.get("review_id") not in (None, review_id):
        return False
    expected = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
    return packet.get("packet_sha256") == expected


def freeze_snapshot(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
    reuse_open: bool = True,
) -> dict[str, Any]:
    """Freeze one immutable review under the daily session.

    The scheduled morning path reuses an unaccepted review so retries keep the
    same review_id. A fresh intraday cycle passes ``reuse_open=False``.
    """
    from scripts.overnight.reviews import allocate_review, capture_starting_book_hashes, persist_review

    meta = allocate_review(store, run_id=run_id, when=when, reuse_open=reuse_open)
    review_id = meta["review_id"]
    snapshot_path = store.review_dir(run_id, review_id) / "evidence_snapshot.json"
    if snapshot_path.is_file():
        existing = store.read_artifact(run_id, "evidence_snapshot.json", review_id=review_id)
        if _snapshot_is_valid(existing, run_id, review_id) and meta.get("status") in {
            "allocating",
            "freezing",
            "frozen",
            "accepting",
            "accepted",
        }:
            if meta.get("status") in {"allocating", "freezing"}:
                meta["status"] = "frozen"
                meta["immutable"] = True
                meta["packet_sha256"] = existing.get("packet_sha256")
                meta["frozen_at"] = existing.get("as_of")
                meta["review_id"] = review_id
                persist_review(store, meta)
            return existing
        if meta.get("status") in {"frozen", "accepting", "accepted"}:
            raise EvidenceBoundaryError(
                f"review {review_id} evidence snapshot is immutable but failed validation"
            )

    meta["status"] = "freezing"
    meta["immutable"] = False
    persist_review(store, meta)
    binding = capture_starting_book_hashes(store, run_id=run_id, when=when)

    collect = store.read_artifact(run_id, "collect.json")
    delta = None
    if store.has_artifact(run_id, "pre_trader_delta.json"):
        delta = store.read_artifact(run_id, "pre_trader_delta.json")
    families = (delta or collect)["families"]
    if store.books_path().is_file():
        prior_books = validate_books(store.read_books())
    else:
        prior_books = empty_books(overnight_run_id=run_id, when=when)
    market_state = ((families.get("market_state") or {}).get("data") if isinstance(families.get("market_state"), dict) else None)
    funding_context = build_funding_context(market_state or {}, as_of=isoformat(now_ny(when)))
    packet = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
        "overnight_run_id": run_id,
        "review_id": review_id,
        "as_of": isoformat(now_ny(when)),
        "families": families,
        "collect_as_of": collect.get("as_of"),
        "pre_trader_delta": None if delta is None else {"as_of": delta.get("as_of"), "changes": delta.get("changes")},
        "temperature_scores": collect.get("temperature_scores"),
        "trade_permissions": collect.get("trade_permissions"),
        "research_method": load_research_method(store.root),
        "funding_context": funding_context,
        "competition": competition_contract(funding_context),
        "prior_books": prior_books,
        "starting_trader_books_sha256": binding["starting_trader_books_sha256"],
        "starting_pm_books_sha256": binding["starting_pm_books_sha256"],
        "starting_state_binding": binding["starting_state_binding"],
        "known_gaps": [
            note
            for family in families.values()
            for note in (family.get("notes") or [])
        ],
        "acquisition_allowed": False,
    }
    from scripts.trading.snapshot import snapshot_overnight_traders
    from scripts.trading.store import TradingStore

    trading = TradingStore(root=store.root, state_root=store.state_root)
    review_dir = store.review_dir(run_id, review_id)
    memory_index = snapshot_overnight_traders(
        trading,
        run_dir=review_dir,
        run_id=run_id,
        trader_books=prior_books,
        when=when,
    )
    packet["seat_memory"] = {
        "isolation": "per_seat_sidecar",
        "index": "memory/index.json",
        "hashes": memory_index.get("hashes") or {},
    }
    from scripts.trading.snapshot import snapshot_overnight_pms

    pm_index = snapshot_overnight_pms(
        trading,
        run_dir=review_dir,
        run_id=run_id,
        when=when,
        market_state=market_state if isinstance(market_state, dict) else None,
    )
    packet["pm_memory"] = {
        "isolation": "per_pm_sidecar",
        "index": "pm_memory/index.json",
        "hashes": pm_index.get("hashes") or {},
    }
    from scripts.pm.store import PMStore

    pm_store = PMStore(root=store.root, state_root=store.state_root)
    if pm_store.books_path().is_file():
        from scripts.pm.books import validate_books as validate_pm_books

        packet["prior_pm_books"] = validate_pm_books(pm_store.read_books())
    digest = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
    packet["packet_sha256"] = digest
    if snapshot_path.is_file():
        raise EvidenceBoundaryError(f"refusing to overwrite frozen evidence for {review_id}")
    store.write_artifact(run_id, "evidence_snapshot.json", packet, review_id=review_id)
    meta["status"] = "frozen"
    meta["immutable"] = True
    meta["packet_sha256"] = digest
    meta["frozen_at"] = packet["as_of"]
    meta.update(
        {
            "starting_trader_books_sha256": binding["starting_trader_books_sha256"],
            "starting_pm_books_sha256": binding["starting_pm_books_sha256"],
            "starting_trader_books_present": binding["starting_trader_books_present"],
            "starting_pm_books_present": binding["starting_pm_books_present"],
            "starting_books_as_of": binding["starting_books_as_of"],
            "starting_state_binding": binding["starting_state_binding"],
        }
    )
    persist_review(store, meta)
    return packet


def assert_frozen_only(payload: dict[str, Any], packet: dict[str, Any], label: str) -> None:
    if payload.get("overnight_run_id") != packet.get("overnight_run_id"):
        raise EvidenceBoundaryError(f"{label} overnight_run_id does not match frozen snapshot")
    supplied_hash = payload.get("packet_sha256")
    if supplied_hash and supplied_hash != packet.get("packet_sha256"):
        raise EvidenceBoundaryError(f"{label} packet_sha256 mismatch")
    if payload.get("evidence_cutoff") and payload["evidence_cutoff"] != packet.get("as_of"):
        raise EvidenceBoundaryError(f"{label} evidence_cutoff must equal frozen snapshot as_of")
    blob_keys = set(payload)
    for key in FORBIDDEN_ACQUISITION:
        if key in blob_keys:
            raise EvidenceBoundaryError(f"{label} used forbidden acquisition field {key}")
        tools = payload.get("tools_used") or []
        if key in tools:
            raise EvidenceBoundaryError(f"{label} recorded forbidden tool {key}")
    if payload.get("fetched_new_evidence"):
        raise EvidenceBoundaryError(f"{label} fetched new evidence after freeze")


def require_snapshot(store: OvernightStore, run_id: str, review_id: str | None = None) -> dict[str, Any]:
    if review_id is None:
        review_id = store.latest_review_id(run_id)
    if review_id:
        if not store.has_artifact(run_id, "evidence_snapshot.json", review_id=review_id):
            raise SchemaError(f"frozen evidence snapshot missing for {run_id}/{review_id}")
        packet = store.read_artifact(run_id, "evidence_snapshot.json", review_id=review_id)
    else:
        if not store.has_artifact(run_id, "evidence_snapshot.json"):
            raise SchemaError(f"frozen evidence snapshot missing for {run_id}")
        packet = store.read_artifact(run_id, "evidence_snapshot.json")
    if packet.get("type") != "OVERNIGHT_EVIDENCE_SNAPSHOT":
        raise SchemaError("evidence snapshot type mismatch")
    if packet.get("overnight_run_id") != run_id:
        raise SchemaError("evidence snapshot run_id mismatch")
    if review_id and packet.get("review_id") not in (None, review_id):
        raise SchemaError("evidence snapshot review_id mismatch")
    expected = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
    if packet.get("packet_sha256") != expected:
        raise EvidenceBoundaryError("frozen evidence snapshot has been mutated")
    return packet
