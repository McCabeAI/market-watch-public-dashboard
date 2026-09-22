"""Idempotent Sep 22 session/review split.

Rebuilds review-001 from the accepted morning Git artifacts and review-002 from
the later unaccepted 11:28 ET evidence freeze. It does not apply decisions and
does not rewrite canonical trader books, PM books, or journal economic fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.overnight.constants import ROOT
from scripts.overnight.reviews import persist_review
from scripts.overnight.store import OvernightStore, read_json, sha256_json, write_json

SESSION_ID = "overnight-20260922"
MORNING_COMMIT = "c89f1f4"
MORNING_PACKET = "e0ad7dbc8b2990648797b41ff138ce05456c4f1340ef08baea106e0782197a41"
REFRESH_PACKET = "5c69096c72b8567b8dfde193168b7ff0185332ca2f10fca42b77e5d4508b2619"
MORNING_REVIEW = "review-001"
REFRESH_REVIEW = "review-002"
SESSION_REVIEW_FILES = (
    "evidence_snapshot.json",
    "agent_evidence_packet.json",
    "scheduled_output.json",
    "trader_review.json",
)
MORNING_FILES = SESSION_REVIEW_FILES
REFRESH_DIRS = ("memory", "pm_memory")


def _git_bytes(commit: str, relpath: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{relpath}"], stderr=subprocess.DEVNULL)


def _git_paths(commit: str, prefix: str) -> list[str]:
    raw = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit, prefix], text=True)
    return [line for line in raw.splitlines() if line]


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _packet_digest(payload: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in payload.items() if k != "packet_sha256"})


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _economic_journal(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "event_id": event.get("event_id"),
                "kind": event.get("kind"),
                "actions": event.get("actions"),
                "linked_trade_ids": event.get("linked_trade_ids"),
                "linked_position_ids": event.get("linked_position_ids"),
                "decision_fingerprint": event.get("decision_fingerprint"),
                "thesis": event.get("thesis"),
                "rationale": event.get("rationale"),
            }
        )
    return rows


def _economic_trade(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": payload.get("trade_id"),
        "status": payload.get("status"),
        "current_notional_usd": payload.get("current_notional_usd"),
        "realized_pnl_usd": payload.get("realized_pnl_usd"),
        "events": [
            {
                "kind": event.get("kind"),
                "notional_change_usd": event.get("notional_change_usd"),
                "realized_pnl_increment_usd": event.get("realized_pnl_increment_usd"),
                "mark": event.get("mark"),
            }
            for event in payload.get("events") or []
            if isinstance(event, dict)
        ],
    }


def _snapshot_economics(root: Path) -> dict[str, Any]:
    books = root / "data" / "overnight" / "books" / "latest.json"
    pm = root / "data" / "pm" / "books" / "latest.json"
    journals = {}
    trading = root / "data" / "trading"
    for path in sorted(trading.glob("*/*/journal.json")):
        journals[str(path.relative_to(root))] = _economic_journal(_load(path))
    trades = {}
    for path in sorted((trading / "trades").glob("*.json")):
        trades[path.name] = _economic_trade(_load(path))
    return {
        "books": _sha256(books.read_bytes()) if books.is_file() else None,
        "pm_books": _sha256(pm.read_bytes()) if pm.is_file() else None,
        "journals": journals,
        "trades": trades,
    }


def _copy_git_tree(commit: str, prefix: str, dest_root: Path) -> None:
    for relpath in _git_paths(commit, prefix):
        suffix = relpath.split(prefix, 1)[1].lstrip("/")
        _atomic_bytes(dest_root / suffix, _git_bytes(commit, relpath))


def _require_packet(path: Path, expected: str) -> dict[str, Any]:
    payload = _load(path)
    if payload.get("packet_sha256") != expected:
        raise SystemExit(f"{path} packet_sha256 {payload.get('packet_sha256')} != {expected}")
    if _packet_digest(payload) != expected:
        raise SystemExit(f"{path} failed packet hash verification")
    return payload


def _historical_binding(packet: dict[str, Any]) -> dict[str, Any]:
    gaps: list[str] = []
    trader = packet.get("prior_books")
    pm = packet.get("prior_pm_books")
    trader_hash = sha256_json(trader) if isinstance(trader, dict) else None
    pm_hash = sha256_json(pm) if isinstance(pm, dict) else None
    if trader_hash is None:
        gaps.append("evidence snapshot has no prior_books; starting trader-book hash was not reconstructed")
    if pm_hash is None:
        gaps.append(
            "evidence snapshot has no prior_pm_books; starting PM-book hash was not stored at freeze and was not reconstructed"
        )
    return {
        "starting_trader_books_sha256": trader_hash,
        "starting_pm_books_sha256": pm_hash,
        "starting_state_binding": "historical_embedded",
        "gaps": gaps,
    }


def _write_historical_review(
    store: OvernightStore,
    *,
    review_id: str,
    status: str,
    packet: dict[str, Any],
    agent_packet_sha256: str | None,
    created_at: str | None,
    frozen_at: str | None,
    accepted_at: str | None,
    note: str,
) -> None:
    binding = _historical_binding(packet)
    meta = {
        "schema_version": 1,
        "type": "OVERNIGHT_REVIEW",
        "overnight_run_id": SESSION_ID,
        "review_id": review_id,
        "status": status,
        "created_at": created_at or frozen_at,
        "frozen_at": frozen_at or packet.get("as_of"),
        "accepted_at": accepted_at,
        "packet_sha256": packet.get("packet_sha256"),
        "agent_packet_sha256": agent_packet_sha256,
        "starting_trader_books_present": binding["starting_trader_books_sha256"] is not None,
        "starting_pm_books_present": binding["starting_pm_books_sha256"] is not None,
        "starting_books_as_of": packet.get("as_of"),
        "immutable": True,
        "migration": {
            "session_id": SESSION_ID,
            "source": note,
            "decisions_applied": False,
        },
        **binding,
    }
    existing = store.review_dir(SESSION_ID, review_id) / "review.json"
    if existing.is_file():
        current = read_json(existing)
        if (
            current.get("status") == status
            and current.get("packet_sha256") == meta["packet_sha256"]
            and current.get("review_id") == review_id
        ):
            return
    persist_review(store, meta)


def _stamp_provenance(root: Path) -> int:
    stamped = 0
    trading = root / "data" / "trading"
    for path in trading.glob("*/*/journal.json"):
        payload = _load(path)
        changed = False
        for event in payload.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("kind") not in {"OVERNIGHT_DECISION", "PM_DECISION"}:
                continue
            provenance = event.setdefault("provenance", {})
            run_id = event.get("run_id") or provenance.get("overnight_run_id")
            if run_id != SESSION_ID:
                continue
            if provenance.get("review_id"):
                continue
            provenance["review_id"] = MORNING_REVIEW
            if not provenance.get("overnight_run_id"):
                provenance["overnight_run_id"] = SESSION_ID
            changed = True
            stamped += 1
        if changed:
            write_json(path, payload)
    trades = trading / "trades"
    if trades.is_dir():
        for path in trades.glob("*.json"):
            payload = _load(path)
            provenance = payload.get("provenance")
            if not isinstance(provenance, dict):
                continue
            if provenance.get("overnight_run_id") != SESSION_ID or provenance.get("review_id"):
                continue
            provenance["review_id"] = MORNING_REVIEW
            write_json(path, payload)
            stamped += 1
    return stamped


def _annotate_run(store: OvernightStore) -> None:
    run = store.read_artifact(SESSION_ID, "run.json")
    run["accepted_review_id"] = MORNING_REVIEW
    run["latest_review_id"] = REFRESH_REVIEW
    freeze = run["stages"]["freeze_evidence"]["outputs"]
    freeze.setdefault("accepted_review_id", MORNING_REVIEW)
    freeze.setdefault("accepted_packet_sha256", MORNING_PACKET)
    freeze["review_id"] = REFRESH_REVIEW
    review = run["stages"]["trader_review"]["outputs"]
    review["review_id"] = MORNING_REVIEW
    store.write_artifact(SESSION_ID, "run.json", run)


def _remove_session_copies(session: Path) -> None:
    for name in SESSION_REVIEW_FILES:
        path = session / name
        if path.is_file():
            path.unlink()
    for name in REFRESH_DIRS:
        path = session / name
        if path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()


def migrate_sep22(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or ROOT)
    store = OvernightStore(root=root, state_root=root)
    before = _snapshot_economics(root)
    session = store.run_dir(SESSION_ID)
    morning_dest = store.review_dir(SESSION_ID, MORNING_REVIEW)
    refresh_dest = store.review_dir(SESSION_ID, REFRESH_REVIEW)
    prefix = f"data/overnight/runs/{SESSION_ID}"

    morning_snapshot = morning_dest / "evidence_snapshot.json"
    if not morning_snapshot.is_file() or _load(morning_snapshot).get("packet_sha256") != MORNING_PACKET:
        _copy_git_tree(MORNING_COMMIT, prefix, morning_dest)
        # The morning tree also contains session files (collect, run, deltas). Drop those
        # copies so the review directory holds only review-scoped artifacts.
        for stray in (
            "collect.json",
            "run.json",
            "pre_trader_delta.json",
            "final_delta.json",
            "assembled_dataset.json",
        ):
            stray_path = morning_dest / stray
            if stray_path.is_file():
                stray_path.unlink()
    morning_packet = _require_packet(morning_dest / "evidence_snapshot.json", MORNING_PACKET)
    agent_path = morning_dest / "agent_evidence_packet.json"
    if not agent_path.is_file():
        raise SystemExit("morning agent_evidence_packet.json was not recoverable from git")
    agent_packet = _load(agent_path)

    refresh_snapshot = refresh_dest / "evidence_snapshot.json"
    if not refresh_snapshot.is_file() or _load(refresh_snapshot).get("packet_sha256") != REFRESH_PACKET:
        source_snapshot = session / "evidence_snapshot.json"
        if source_snapshot.is_file() and _load(source_snapshot).get("packet_sha256") == REFRESH_PACKET:
            _atomic_bytes(refresh_snapshot, source_snapshot.read_bytes())
        else:
            _atomic_bytes(refresh_snapshot, _git_bytes("HEAD", f"{prefix}/evidence_snapshot.json"))
        for name in REFRESH_DIRS:
            source = session / name
            if source.is_dir():
                for path in source.rglob("*.json"):
                    rel = path.relative_to(source)
                    _atomic_bytes(refresh_dest / name / rel, path.read_bytes())
            else:
                for relpath in _git_paths("HEAD", f"{prefix}/{name}"):
                    suffix = relpath.split(f"{prefix}/", 1)[1]
                    _atomic_bytes(refresh_dest / suffix, _git_bytes("HEAD", relpath))
    refresh_packet = _require_packet(refresh_dest / "evidence_snapshot.json", REFRESH_PACKET)

    _write_historical_review(
        store,
        review_id=MORNING_REVIEW,
        status="accepted",
        packet=morning_packet,
        agent_packet_sha256=agent_packet.get("packet_sha256"),
        created_at=morning_packet.get("as_of"),
        frozen_at=morning_packet.get("as_of"),
        accepted_at="2026-09-22T07:03:58.914674-04:00",
        note=f"git {MORNING_COMMIT} accepted morning review; decisions were not reapplied",
    )
    _write_historical_review(
        store,
        review_id=REFRESH_REVIEW,
        status="frozen",
        packet=refresh_packet,
        agent_packet_sha256=None,
        created_at=refresh_packet.get("as_of"),
        frozen_at=refresh_packet.get("as_of"),
        accepted_at=None,
        note="unaccepted 11:28 ET evidence refresh preserved from the session freeze; no decisions applied",
    )
    _remove_session_copies(session)
    _stamp_provenance(root)
    _annotate_run(store)
    after = _snapshot_economics(root)
    if before["books"] != after["books"] or before["pm_books"] != after["pm_books"]:
        raise SystemExit("migration changed canonical trader or PM book bytes")
    if before["journals"] != after["journals"] or before["trades"] != after["trades"]:
        raise SystemExit("migration changed journal or trade economic outcomes")
    return {
        "overnight_run_id": SESSION_ID,
        "reviews": {
            MORNING_REVIEW: {
                "status": "accepted",
                "packet_sha256": MORNING_PACKET,
                "agent_packet_sha256": agent_packet.get("packet_sha256"),
            },
            REFRESH_REVIEW: {
                "status": "frozen",
                "packet_sha256": REFRESH_PACKET,
            },
        },
        "books_sha256": after["books"],
        "pm_books_sha256": after["pm_books"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Sep 22 overnight reviews")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(migrate_sep22(args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
