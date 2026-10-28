"""Publication milestones and trader-acceptance gates (pure, no network)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scripts.market_watch_launch.contract import (
    AWAITING_ACP,
    CONCURRENCY_BLOCK,
    LIVE_LAUNCH_STATUSES,
    PHASE_AWAITING_TRADER,
    PHASE_BLOCKED,
    PHASE_COLLECTING,
    PHASE_FAILED,
    PHASE_FINAL_PUBLISHED,
    PHASE_RESEARCH_PUBLISHING,
    PHASE_RESEARCH_READY,
    PHASE_SUPERSEDED,
    PHASE_TRADER_ACCEPTED,
    SUPERSEDED_BY_NEWER_FREEZE,
    TWO_TRIGGER_CONTRACT,
)
from scripts.market_watch_launch.publication_release import (
    PHASE_RESEARCH,
    RESEARCH_RECEIPT_NAME,
    RESEARCH_RECEIPT_TYPE,
    launch_stamp,
    release_sha256,
)

STORE_RELPATH = Path("data") / "market_watch_launches"


def research_required(launch: dict[str, Any]) -> bool:
    if launch.get("publication_contract") != TWO_TRIGGER_CONTRACT:
        return False
    request = launch.get("request") or {}
    return (
        request.get("provider") == "acp"
        and request.get("mode") == "live"
        and request.get("publish_production") is True
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def research_publication(launch_dir: Path, launch: dict[str, Any]) -> dict[str, Any] | None:
    try:
        path = Path(launch_dir) / RESEARCH_RECEIPT_NAME
        if not path.is_file():
            return None
        raw = path.read_bytes()
        receipt = json.loads(raw.decode("utf-8"))
        if not isinstance(receipt, dict):
            return None
        if receipt.get("type") != RESEARCH_RECEIPT_TYPE:
            return None
        launch_id = launch.get("launch_id")
        if receipt.get("launch_id") != launch_id:
            return None
        freeze = ((launch.get("stages") or {}).get("04_freeze") or {}).get("details") or {}
        packet = freeze.get("packet_sha256")
        review_id = freeze.get("review_id")
        if not packet or not review_id:
            return None
        if receipt.get("packet_sha256") != packet or receipt.get("review_id") != review_id:
            return None
        release = receipt.get("release")
        if not isinstance(release, dict):
            return None
        if release.get("phase") != PHASE_RESEARCH:
            return None
        if (
            release.get("launch_id") != launch_id
            or release.get("packet_sha256") != packet
            or release.get("review_id") != review_id
        ):
            return None
        rel_sha = receipt.get("release_sha256")
        if not rel_sha or release_sha256(release) != rel_sha:
            return None
        matching: list[dict[str, Any]] = []
        for row in receipt.get("deploys") or []:
            if not isinstance(row, dict):
                continue
            if row.get("public_state") != "matched":
                continue
            if row.get("release_sha256") != rel_sha:
                continue
            run_id = row.get("run_id")
            if not isinstance(run_id, (int, float)) and not (
                isinstance(run_id, str) and run_id.isdigit()
            ):
                continue
            matching.append(row)
        if not matching:
            return None
        last = matching[-1]
        run_id = last.get("run_id")
        if isinstance(run_id, str):
            run_id = int(run_id) if run_id.isdigit() else run_id
        return {
            "receipt_path": RESEARCH_RECEIPT_NAME,
            "receipt_sha256": _sha256_bytes(raw),
            "release_sha256": rel_sha,
            "run_id": run_id,
            "run_url": last.get("run_url"),
            "page_url": last.get("page_url"),
            "public_state": last.get("public_state"),
            "recorded_at": last.get("recorded_at"),
        }
    except Exception:  # noqa: BLE001 — invalid receipt is treated as absent
        return None


def launch_phase(launch: dict[str, Any], *, research_verified: bool) -> str:
    stages = launch.get("stages") or {}
    auth = stages.get("00_authenticate") or {}
    if auth.get("status") == "blocked" and auth.get("reason") == CONCURRENCY_BLOCK:
        return PHASE_BLOCKED
    if (stages.get("08_pages") or {}).get("status") == "succeeded":
        return PHASE_FINAL_PUBLISHED
    if (stages.get("06_acceptance") or {}).get("status") == "succeeded":
        return PHASE_TRADER_ACCEPTED
    if (stages.get("07_finalize") or {}).get("status") == "succeeded":
        return PHASE_TRADER_ACCEPTED
    if launch.get("superseded_by"):
        return PHASE_SUPERSEDED
    if launch.get("status") == "failed":
        return PHASE_FAILED
    handoff = stages.get("05_acp_handoff") or {}
    if handoff.get("status") == "blocked":
        if research_verified:
            return PHASE_RESEARCH_READY
        return PHASE_AWAITING_TRADER
    if launch.get("status") == "blocked":
        return PHASE_BLOCKED
    if research_verified:
        return PHASE_RESEARCH_READY
    if (stages.get("04_freeze") or {}).get("status") == "succeeded":
        return PHASE_RESEARCH_PUBLISHING
    return PHASE_COLLECTING


def holds_data_collection_lock(
    launch: dict[str, Any],
    *,
    launch_dir: Path,
    today: str | None,
) -> bool:
    """Whether this launch still excludes a new Trigger A data-collection run.

    The GitHub concurrency group ``market-watch-manual-launch`` serializes launch
    workflow runs; this committed lock only guards against stale state, so a
    launch from an earlier NY session that never reached research-ready (e.g.
    research deploy failed) no longer blocks a new session; trader-phase launches
    never hold it.
    """
    if launch.get("status") not in LIVE_LAUNCH_STATUSES:
        return False
    verified = research_publication(launch_dir, launch) is not None
    phase = launch_phase(launch, research_verified=verified)
    if phase not in (PHASE_COLLECTING, PHASE_RESEARCH_PUBLISHING):
        return False
    session = str(launch.get("session_date") or "")
    if today is not None and session < today:
        return False
    return True


def _is_concurrency_blocked(launch: dict[str, Any]) -> bool:
    auth = ((launch.get("stages") or {}).get("00_authenticate") or {})
    return auth.get("status") == "blocked" and auth.get("reason") == CONCURRENCY_BLOCK


def newer_frozen_launch(store: Any, launch: dict[str, Any]) -> str | None:
    this_stamp = launch_stamp(launch.get("launch_id"))
    if not this_stamp:
        return None
    rows = store.index_rows() if hasattr(store, "index_rows") else (store._read_index().get("launches") or [])
    for row in rows:
        other_id = row.get("launch_id")
        if not other_id or other_id == launch.get("launch_id"):
            continue
        other_stamp = launch_stamp(str(other_id))
        if not other_stamp or other_stamp <= this_stamp:
            continue
        try:
            other = store.load_launch(str(other_id))
        except FileNotFoundError:
            continue
        if _is_concurrency_blocked(other):
            continue
        freeze = (other.get("stages") or {}).get("04_freeze") or {}
        if freeze.get("status") == "succeeded":
            return str(other_id)
    return None


def trader_acceptance_refusal(root: Path, launch: dict[str, Any]) -> str | None:
    if launch.get("superseded_by"):
        return "superseded_by_newer_launch"
    newer = newer_frozen_launch(_store_from_root(root), launch)
    if newer:
        return f"{SUPERSEDED_BY_NEWER_FREEZE}:{newer}"
    if not research_required(launch):
        return None
    launch_id = launch.get("launch_id")
    launch_dir = root / STORE_RELPATH / str(launch_id)
    pub = research_publication(launch_dir, launch)
    if pub is None:
        return "research_publication_not_verified"
    handoff = (launch.get("stages") or {}).get("05_acp_handoff") or {}
    if handoff.get("status") != "blocked" or handoff.get("reason") != AWAITING_ACP:
        return "delegation_request_not_ready"
    rp = (handoff.get("details") or {}).get("research_publication")
    if not isinstance(rp, dict) or rp.get("release_sha256") != pub.get("release_sha256"):
        return "delegation_request_not_ready"
    return None


def _store_from_root(root: Path) -> Any:
    from scripts.market_watch_launch.state import LaunchStateStore

    return LaunchStateStore(root)


def mark_superseded_launches(
    store: Any,
    newer_launch: dict[str, Any],
    *,
    when_iso: str,
) -> list[str]:
    newer_id = newer_launch["launch_id"]
    newer_session = newer_launch.get("session_date")
    marked: list[str] = []
    rows = store.index_rows() if hasattr(store, "index_rows") else (store._read_index().get("launches") or [])
    newer_stamp = launch_stamp(newer_id)
    for row in rows:
        other_id = row.get("launch_id")
        if not other_id or other_id == newer_id:
            continue
        other_stamp = launch_stamp(str(other_id))
        if not other_stamp or not newer_stamp or other_stamp >= newer_stamp:
            continue
        try:
            other = store.load_launch(str(other_id))
        except FileNotFoundError:
            continue
        if other.get("publication_contract") != TWO_TRIGGER_CONTRACT:
            continue
        if other.get("superseded_by"):
            continue
        if other.get("status") == "failed":
            continue
        if _is_concurrency_blocked(other):
            continue
        launch_dir = store.launch_dir(str(other_id))
        verified = research_publication(launch_dir, other) is not None
        phase = launch_phase(other, research_verified=verified)
        if phase not in (PHASE_COLLECTING, PHASE_RESEARCH_PUBLISHING, PHASE_RESEARCH_READY):
            continue
        other["superseded_by"] = {
            "launch_id": newer_id,
            "session_date": newer_session,
            "recorded_at": when_iso,
            "reason": "newer_launch_frozen",
            "phase_at_supersession": phase,
            "trader_output_accepted": False,
            "trader_request_observed": False,
        }
        store.save_launch(other)
        marked.append(str(other_id))
    existing = list(newer_launch.get("supersedes") or [])
    merged = sorted(set(existing) | set(marked))
    if merged != existing:
        newer_launch["supersedes"] = merged
    return marked


def _load_launch_file(root: Path, launch_id: str) -> dict[str, Any]:
    path = root / STORE_RELPATH / launch_id / "launch.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _cli_acceptance_gate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    launch = _load_launch_file(root, args.launch_id)
    reason = trader_acceptance_refusal(root, launch)
    payload = {
        "launch_id": args.launch_id,
        "allowed": reason is None,
        "reason": reason,
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if reason is None else 1


def _cli_phase(args: argparse.Namespace) -> int:
    root = Path(args.root)
    launch = _load_launch_file(root, args.launch_id)
    launch_dir = root / STORE_RELPATH / args.launch_id
    verified = research_publication(launch_dir, launch) is not None
    phase = launch_phase(launch, research_verified=verified)
    print(json.dumps({"launch_id": args.launch_id, "phase": phase}, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch launch milestones")
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("acceptance-gate", help="Trader acceptance gate check")
    gate.add_argument("--launch-id", required=True)
    gate.add_argument("--root", default=".")
    gate.set_defaults(func=_cli_acceptance_gate)
    phase_p = sub.add_parser("phase", help="Launch phase")
    phase_p.add_argument("--launch-id", required=True)
    phase_p.add_argument("--root", default=".")
    phase_p.set_defaults(func=_cli_phase)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
