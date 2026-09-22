"""Immutable review identity beneath a daily overnight session.

``overnight_run_id`` stays the session key used by deterministic scheduling.
``review_id`` is a separate immutable identity for one Trader Room / automated
PM decision cycle. Review artifacts live under:

    data/overnight/runs/<overnight_run_id>/reviews/<review_id>/

Trusted code allocates review IDs. A retry of an open review reuses that ID.
A later cycle in the same session gets the next ID. Acceptance is fail-closed
when the canonical trader or PM books no longer match the hashes captured at
freeze.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.overnight.clock import isoformat, now_ny, parse_iso
from scripts.overnight.errors import EvidenceBoundaryError, SchemaError
from scripts.overnight.store import REVIEW_ID_RE, OvernightStore, sha256_file, sha256_json

OPEN_STATUSES = {"allocating", "freezing", "frozen", "accepting"}
CANONICAL_FILE_BINDING = "canonical_file"


def review_sort_key(review_id: str) -> int:
    if not REVIEW_ID_RE.match(review_id):
        raise SchemaError(f"malformed review_id {review_id!r}")
    return int(review_id.split("-", 1)[1])


def format_review_id(sequence: int) -> str:
    if sequence < 1:
        raise SchemaError("review sequence must be positive")
    return f"review-{sequence:03d}"


def project_review(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": meta["review_id"],
        "status": meta["status"],
        "packet_sha256": meta.get("packet_sha256"),
        "agent_packet_sha256": meta.get("agent_packet_sha256"),
        "starting_trader_books_sha256": meta.get("starting_trader_books_sha256"),
        "starting_pm_books_sha256": meta.get("starting_pm_books_sha256"),
        "starting_state_binding": meta.get("starting_state_binding"),
        "created_at": meta.get("created_at"),
        "frozen_at": meta.get("frozen_at"),
        "accepted_at": meta.get("accepted_at"),
    }


def empty_index(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "OVERNIGHT_REVIEW_INDEX",
        "overnight_run_id": run_id,
        "reviews": [],
    }


def load_index(store: OvernightStore, run_id: str) -> dict[str, Any]:
    payload = store.read_review_index(run_id)
    if payload is None:
        return empty_index(run_id)
    if payload.get("type") != "OVERNIGHT_REVIEW_INDEX":
        raise SchemaError(f"review index type mismatch for {run_id}")
    if payload.get("overnight_run_id") != run_id:
        raise SchemaError("review index overnight_run_id mismatch")
    if not isinstance(payload.get("reviews"), list):
        raise SchemaError("review index reviews must be a list")
    return payload


def save_index(store: OvernightStore, run_id: str, index: dict[str, Any]) -> None:
    index["reviews"] = sorted(index.get("reviews") or [], key=lambda row: review_sort_key(row["review_id"]))
    from scripts.overnight.store import write_json

    write_json(store.reviews_index_path(run_id), index)


def load_review(store: OvernightStore, run_id: str, review_id: str) -> dict[str, Any]:
    path = store.review_dir(run_id, review_id) / "review.json"
    if not path.is_file():
        raise SchemaError(f"missing review metadata for {run_id}/{review_id}")
    from scripts.overnight.store import read_json

    meta = read_json(path)
    if meta.get("type") != "OVERNIGHT_REVIEW":
        raise SchemaError(f"{review_id} metadata type mismatch")
    if meta.get("overnight_run_id") != run_id or meta.get("review_id") != review_id:
        raise SchemaError(f"{review_id} metadata identity mismatch")
    return meta


def persist_review(store: OvernightStore, meta: dict[str, Any]) -> dict[str, Any]:
    if meta.get("status") == "accepted":
        meta["immutable"] = True
    from scripts.overnight.store import write_json

    write_json(store.review_dir(meta["overnight_run_id"], meta["review_id"]) / "review.json", meta)
    index = load_index(store, meta["overnight_run_id"])
    projected = project_review(meta)
    replaced = False
    for row in index["reviews"]:
        if row.get("review_id") == meta["review_id"]:
            row.clear()
            row.update(projected)
            replaced = True
            break
    if not replaced:
        index["reviews"].append(projected)
    save_index(store, meta["overnight_run_id"], index)
    return meta


def _new_meta(run_id: str, review_id: str, when: datetime | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": "OVERNIGHT_REVIEW",
        "overnight_run_id": run_id,
        "review_id": review_id,
        "status": "allocating",
        "created_at": isoformat(now_ny(when)),
        "frozen_at": None,
        "accepted_at": None,
        "packet_sha256": None,
        "agent_packet_sha256": None,
        "starting_trader_books_sha256": None,
        "starting_pm_books_sha256": None,
        "starting_trader_books_present": None,
        "starting_pm_books_present": None,
        "starting_books_as_of": None,
        "starting_state_binding": None,
        "immutable": False,
        "gaps": [],
    }


def allocate_review(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
    reuse_open: bool = True,
) -> dict[str, Any]:
    """Return the open review, or allocate the next immutable review_id.

    Retries of an unaccepted review reuse that review. ``reuse_open=False``
    always allocates a new id so a fresh cycle cannot clobber an earlier
    unaccepted freeze.
    """
    index = load_index(store, run_id)
    if reuse_open:
        for row in reversed(index["reviews"]):
            if row.get("status") in OPEN_STATUSES:
                try:
                    return load_review(store, run_id, row["review_id"])
                except SchemaError:
                    meta = _new_meta(run_id, row["review_id"], when)
                    meta["status"] = row.get("status") or "allocating"
                    return persist_review(store, meta)
    sequence = 1
    for row in index["reviews"]:
        sequence = max(sequence, review_sort_key(row["review_id"]) + 1)
    review_id = format_review_id(sequence)
    meta = _new_meta(run_id, review_id, when)
    return persist_review(store, meta)


def _empty_trader_hash(store: OvernightStore, meta: dict[str, Any]) -> str:
    from scripts.overnight.books import empty_books

    stamp = meta.get("starting_books_as_of")
    when = parse_iso(stamp) if stamp else None
    return sha256_json(empty_books(overnight_run_id=meta["overnight_run_id"], when=when))


def _empty_pm_hash(meta: dict[str, Any]) -> str:
    from scripts.pm.books import empty_books as empty_pm_books

    stamp = meta.get("starting_books_as_of")
    when = parse_iso(stamp) if stamp else None
    return sha256_json(empty_pm_books(overnight_run_id=meta["overnight_run_id"], when=when))


def capture_starting_book_hashes(
    store: OvernightStore,
    *,
    run_id: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Hash canonical book files before a review freeze mutates anything."""
    from scripts.pm.store import PMStore

    stamp = isoformat(now_ny(when))
    meta = {
        "overnight_run_id": run_id,
        "starting_books_as_of": stamp,
        "starting_trader_books_present": store.books_path().is_file(),
        "starting_pm_books_present": PMStore(root=store.root, state_root=store.state_root).books_path().is_file(),
    }
    if meta["starting_trader_books_present"]:
        meta["starting_trader_books_sha256"] = sha256_file(store.books_path())
    else:
        meta["starting_trader_books_sha256"] = _empty_trader_hash(store, meta)
    pm_path = PMStore(root=store.root, state_root=store.state_root).books_path()
    if meta["starting_pm_books_present"]:
        meta["starting_pm_books_sha256"] = sha256_file(pm_path)
    else:
        meta["starting_pm_books_sha256"] = _empty_pm_hash(meta)
    meta["starting_state_binding"] = CANONICAL_FILE_BINDING
    return meta


def current_book_hashes(store: OvernightStore, meta: dict[str, Any]) -> tuple[str, str]:
    from scripts.pm.store import PMStore

    if store.books_path().is_file():
        trader_hash = sha256_file(store.books_path())
    elif meta.get("starting_trader_books_present"):
        trader_hash = "missing-trader-books"
    else:
        trader_hash = _empty_trader_hash(store, meta)
    pm_path = PMStore(root=store.root, state_root=store.state_root).books_path()
    if pm_path.is_file():
        pm_hash = sha256_file(pm_path)
    elif meta.get("starting_pm_books_present"):
        pm_hash = "missing-pm-books"
    else:
        pm_hash = _empty_pm_hash(meta)
    return trader_hash, pm_hash


def starting_books_match(store: OvernightStore, meta: dict[str, Any]) -> bool:
    if meta.get("starting_state_binding") != CANONICAL_FILE_BINDING:
        return False
    trader_hash, pm_hash = current_book_hashes(store, meta)
    return (
        trader_hash == meta.get("starting_trader_books_sha256")
        and pm_hash == meta.get("starting_pm_books_sha256")
    )


def later_review_accepted(store: OvernightStore, run_id: str, review_id: str) -> bool:
    seen = False
    for row in load_index(store, run_id)["reviews"]:
        if row.get("review_id") == review_id:
            seen = True
            continue
        if seen and row.get("status") == "accepted":
            return True
    return False


def _journal_has_review(
    store: OvernightStore,
    *,
    owner_type: str,
    owner_id: str,
    kind: str,
    run_id: str,
    review_id: str,
) -> bool:
    from scripts.trading.journal import find_event
    from scripts.trading.store import TradingStore

    trading = TradingStore(root=store.root, state_root=store.state_root)
    if not trading.journal_path(owner_type, owner_id).is_file():
        return False
    return (
        find_event(
            trading,
            owner_type=owner_type,
            owner_id=owner_id,
            kind=kind,
            run_id=run_id,
            review_id=review_id,
        )
        is not None
    )


def review_effects_recorded(store: OvernightStore, run_id: str, review_id: str) -> bool:
    from scripts.overnight.constants import STANDING_SEATS
    from scripts.pm.constants import AUTOMATED_PM_IDS

    for seat in STANDING_SEATS:
        if not _journal_has_review(
            store,
            owner_type="trader",
            owner_id=seat,
            kind="OVERNIGHT_DECISION",
            run_id=run_id,
            review_id=review_id,
        ):
            return False
    for pm_id in AUTOMATED_PM_IDS:
        if not _journal_has_review(
            store,
            owner_type="pm",
            owner_id=pm_id,
            kind="PM_DECISION",
            run_id=run_id,
            review_id=review_id,
        ):
            return False
    return True


def assert_review_acceptable(store: OvernightStore, meta: dict[str, Any]) -> None:
    """Fail closed before canonical writes when a review is stale or unbound."""
    status = meta.get("status")
    review_id = meta.get("review_id")
    run_id = meta.get("overnight_run_id")
    if status == "accepted":
        return
    if later_review_accepted(store, run_id, review_id):
        raise EvidenceBoundaryError(
            f"review {review_id} is older than an accepted review in {run_id}; refusing out-of-order acceptance"
        )
    if meta.get("starting_state_binding") != CANONICAL_FILE_BINDING:
        raise EvidenceBoundaryError(
            f"review {review_id} has no canonical starting-book binding; refusing acceptance"
        )
    if status == "frozen":
        if not starting_books_match(store, meta):
            trader_hash, pm_hash = current_book_hashes(store, meta)
            raise EvidenceBoundaryError(
                f"review {review_id} stale: starting trader/PM book hashes "
                f"{meta.get('starting_trader_books_sha256')}/{meta.get('starting_pm_books_sha256')} "
                f"do not match current {trader_hash}/{pm_hash}"
            )
        return
    if status == "accepting":
        if starting_books_match(store, meta) or review_effects_recorded(store, run_id, review_id):
            return
        raise EvidenceBoundaryError(
            f"review {review_id} was interrupted and its starting books no longer match"
        )
    raise SchemaError(f"review {review_id} cannot be accepted from status {status}")


def mark_accepting(store: OvernightStore, meta: dict[str, Any]) -> dict[str, Any]:
    if meta.get("status") == "accepted":
        return meta
    if meta.get("status") == "accepting":
        return meta
    meta["status"] = "accepting"
    meta["immutable"] = False
    return persist_review(store, meta)


def mark_accepted(
    store: OvernightStore,
    meta: dict[str, Any],
    *,
    when: datetime | None = None,
    agent_packet_sha256: str | None = None,
) -> dict[str, Any]:
    meta["status"] = "accepted"
    meta["immutable"] = True
    meta["accepted_at"] = meta.get("accepted_at") or isoformat(now_ny(when))
    if agent_packet_sha256:
        meta["agent_packet_sha256"] = agent_packet_sha256
    return persist_review(store, meta)


def same_accepted_output(meta: dict[str, Any], payload: dict[str, Any]) -> bool:
    if payload.get("base_packet_sha256") != meta.get("packet_sha256"):
        return False
    agent = payload.get("agent_packet") or {}
    recorded = meta.get("agent_packet_sha256")
    if recorded and agent.get("packet_sha256") != recorded:
        return False
    return True


def raise_if_replay_conflict(meta: dict[str, Any], payload: dict[str, Any]) -> None:
    if meta.get("status") == "accepted" and not same_accepted_output(meta, payload):
        raise EvidenceBoundaryError(
            f"review {meta.get('review_id')} is already accepted with a different packet"
        )
