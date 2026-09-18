"""01:50 ET freeze of the common evidence snapshot.

The 02:05 trader review must consume this exact packet and must not fetch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.books import empty_books, validate_books
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import FORBIDDEN_ACQUISITION, SCHEMA_VERSION
from scripts.overnight.errors import EvidenceBoundaryError, SchemaError
from scripts.overnight.store import OvernightStore, sha256_json
from scripts.trader_room.evidence import load_research_method


def freeze_snapshot(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    collect = store.read_artifact(run_id, "collect.json")
    delta = None
    if store.has_artifact(run_id, "pre_trader_delta.json"):
        delta = store.read_artifact(run_id, "pre_trader_delta.json")
    families = (delta or collect)["families"]
    if store.books_path().is_file():
        prior_books = validate_books(store.read_books())
    else:
        prior_books = empty_books(overnight_run_id=run_id, when=when)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_EVIDENCE_SNAPSHOT",
        "overnight_run_id": run_id,
        "as_of": isoformat(now_ny(when)),
        "families": families,
        "collect_as_of": collect.get("as_of"),
        "pre_trader_delta": None if delta is None else {"as_of": delta.get("as_of"), "changes": delta.get("changes")},
        "temperature_scores": collect.get("temperature_scores"),
        "research_method": load_research_method(store.root),
        "prior_books": prior_books,
        "known_gaps": [
            note
            for family in families.values()
            for note in (family.get("notes") or [])
        ],
        "acquisition_allowed": False,
    }
    digest = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
    packet["packet_sha256"] = digest
    store.write_artifact(run_id, "evidence_snapshot.json", packet)
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


def require_snapshot(store: OvernightStore, run_id: str) -> dict[str, Any]:
    if not store.has_artifact(run_id, "evidence_snapshot.json"):
        raise SchemaError(f"frozen evidence snapshot missing for {run_id}")
    packet = store.read_artifact(run_id, "evidence_snapshot.json")
    if packet.get("type") != "OVERNIGHT_EVIDENCE_SNAPSHOT":
        raise SchemaError("evidence snapshot type mismatch")
    if packet.get("overnight_run_id") != run_id:
        raise SchemaError("evidence snapshot run_id mismatch")
    expected = sha256_json({k: v for k, v in packet.items() if k != "packet_sha256"})
    if packet.get("packet_sha256") != expected:
        raise EvidenceBoundaryError("frozen evidence snapshot has been mutated")
    return packet
