"""03:50 ET assemble + validate the canonical morning dashboard dataset."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from scripts.overnight.books import empty_books, public_books_view, validate_books
from scripts.overnight.clock import isoformat, now_ny
from scripts.overnight.constants import SCHEMA_VERSION
from scripts.overnight.errors import SchemaError
from scripts.overnight.accepted_news import (
    overlay_accepted_research,
    persist_accepted_public_news_from_assembly,
)
from scripts.overnight.freshness import publication_decision
from scripts.overnight.ledger import artifact_index
from scripts.overnight.store import OvernightStore


def _load_books(store: OvernightStore, run: dict[str, Any]) -> dict[str, Any]:
    if store.books_path().is_file():
        return validate_books(store.read_books())
    return empty_books(overnight_run_id=run["overnight_run_id"])


def _families_for_publication(store: OvernightStore, run_id: str) -> dict[str, Any]:
    if store.has_artifact(run_id, "final_delta.json"):
        return store.read_artifact(run_id, "final_delta.json")["families"]
    if store.has_artifact(run_id, "evidence_snapshot.json"):
        return store.read_artifact(run_id, "evidence_snapshot.json")["families"]
    if store.has_artifact(run_id, "collect.json"):
        return store.read_artifact(run_id, "collect.json")["families"]
    raise SchemaError("cannot assemble: no collected families")


def _load_agent_packet(store: OvernightStore, run_id: str) -> dict[str, Any] | None:
    if not store.has_artifact(run_id, "agent_evidence_packet.json"):
        return None
    return store.read_artifact(run_id, "agent_evidence_packet.json")


def assemble_dataset(
    store: OvernightStore,
    run: dict[str, Any],
    *,
    when: datetime | None = None,
) -> dict[str, Any]:
    run_id = run["overnight_run_id"]
    agent_packet = _load_agent_packet(store, run_id)
    families = overlay_accepted_research(
        _families_for_publication(store, run_id),
        agent_packet,
        when=when,
    )
    review_status = "missing"
    last_success = None
    review: dict[str, Any] = {}
    books = _load_books(store, run)
    accepted_review_id = store.latest_review_id(run_id, statuses={"accepted"})
    if accepted_review_id and store.has_artifact(run_id, "evidence_snapshot.json", review_id=accepted_review_id):
        snapshot = store.read_artifact(run_id, "evidence_snapshot.json", review_id=accepted_review_id)
    elif store.has_artifact(run_id, "evidence_snapshot.json"):
        snapshot = store.read_artifact(run_id, "evidence_snapshot.json")
    else:
        snapshot = {}
    evidence_cutoff = snapshot.get("as_of")
    if store.has_artifact(run_id, "trader_review.json"):
        review = store.read_artifact(run_id, "trader_review.json")
        if review.get("status") == "succeeded":
            review_status = "fresh"
            last_success = run_id
        else:
            review_status = "failed"
            last_success = books.get("last_successful_review_run_id")
    elif books.get("last_successful_review_run_id"):
        review_status = "stale"
        last_success = books["last_successful_review_run_id"]
    books["review_status"] = review_status
    if last_success:
        books["last_successful_review_run_id"] = last_success
    store.write_books(books)

    pm_books_status: str | None = None
    last_successful_pm_run_id: str | None = None
    try:
        from scripts.pm.books import (
            automated_pm_publication_status,
            empty_books as empty_pm_books,
            overlay_automated_pm_stale_for_cycle,
            validate_books as validate_pm_books,
        )
        from scripts.pm.cli import refresh_packets
        from scripts.pm.store import PMStore

        pm_store = PMStore(root=store.root, state_root=store.state_root)
        if review_status == "fresh":
            if pm_store.books_path().is_file():
                pm_books = validate_pm_books(pm_store.read_books())
            else:
                pm_books = empty_pm_books(overnight_run_id=run_id)
            if not review.get("pm_books"):
                try:
                    refresh_packets(
                        pm_store,
                        allow_trader_room_fallback=False,
                        overnight_run_id=run_id,
                    )
                    pm_books = validate_pm_books(pm_store.read_books())
                except Exception:
                    pass
            pm_books_status, last_successful_pm_run_id = automated_pm_publication_status(
                pm_books,
                trader_review_status=review_status,
                run_id=run_id,
                evidence_cutoff=evidence_cutoff,
            )
        else:
            if pm_store.books_path().is_file():
                pm_books = overlay_automated_pm_stale_for_cycle(validate_pm_books(pm_store.read_books()))
                pm_store.write_books(pm_books)
            else:
                pm_books = overlay_automated_pm_stale_for_cycle(empty_pm_books(overnight_run_id=run_id))
            pm_books_status, last_successful_pm_run_id = automated_pm_publication_status(
                pm_books,
                trader_review_status=review_status,
                run_id=run_id,
                evidence_cutoff=evidence_cutoff,
            )
    except Exception:
        pm_books_status = review_status if review_status in {"failed", "missing"} else "stale"

    decision = publication_decision(
        families=families,
        trader_review_status=review_status,
        last_successful_review_run_id=last_success,
        pm_books_status=pm_books_status,
        last_successful_pm_run_id=last_successful_pm_run_id,
    )
    collect = store.read_artifact(run_id, "collect.json") if store.has_artifact(run_id, "collect.json") else {}
    dataset = {
        "schema_version": SCHEMA_VERSION,
        "type": "OVERNIGHT_MORNING_DATASET",
        "overnight_run_id": run_id,
        "as_of": isoformat(now_ny(when)),
        "timezone": "America/New_York",
        "dry_run": bool(run.get("dry_run")),
        "core": {
            "macro_hard": families.get("macro_hard"),
            "news": families.get("news"),
            "central_bank_research": families.get("central_bank_research"),
            "market_state": families.get("market_state"),
            "temperature_scores": collect.get("temperature_scores"),
        },
        "evidence_cutoff": snapshot.get("as_of"),
        "packet_sha256": snapshot.get("packet_sha256"),
        "agent_research": (agent_packet or {}).get("research_supplement"),
        "agent_research_cutoff": (agent_packet or {}).get("evidence_cutoff"),
        "trader_books": public_books_view(books),
        "publication": decision,
        "stage_ledger": {name: run["stages"][name]["status"] for name in run["stages"]},
        "artifacts": artifact_index(run),
        "preservation": collect.get("preservation")
        or {
            "dashboard_patches_rewritten": False,
            "sep18_news_fixes": True,
            "front_page_format": "preserved",
        },
    }
    validate_dataset(dataset)
    store.write_artifact(run_id, "assembled_dataset.json", dataset)
    if not run.get("dry_run"):
        persist_accepted_public_news_from_assembly(
            store,
            run_id=run_id,
            families=families,
            agent_packet=agent_packet,
            agent_research=dataset.get("agent_research"),
        )
    if review_status == "fresh" and last_success == run_id:
        try:
            from scripts.pm.cli import refresh_packets
            from scripts.pm.store import PMStore

            refresh_packets(
                PMStore(root=store.root, state_root=store.state_root),
                allow_trader_room_fallback=False,
                overnight_run_id=run_id,
            )
        except Exception:
            # Morning assembly still publishes trader books if PM refresh cannot run.
            pass
    store.write_latest(
        {
            "overnight_run_id": run_id,
            "as_of": dataset["as_of"],
            "assembled_dataset": f"data/overnight/runs/{run_id}/assembled_dataset.json",
            "books_path": "data/overnight/books/latest.json",
            "publication": decision,
            "dry_run": bool(run.get("dry_run")),
        }
    )
    return dataset


def validate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    if dataset.get("type") != "OVERNIGHT_MORNING_DATASET":
        raise SchemaError("assembled dataset type mismatch")
    if not dataset.get("overnight_run_id"):
        raise SchemaError("assembled dataset missing overnight_run_id")
    core = dataset.get("core") or {}
    for key in ("macro_hard", "news", "central_bank_research", "market_state"):
        if key not in core:
            raise SchemaError(f"assembled dataset missing core.{key}")
    pub = dataset.get("publication") or {}
    if "may_publish" not in pub or "core_status" not in pub:
        raise SchemaError("assembled dataset missing publication decision")
    books = dataset.get("trader_books") or {}
    if books.get("seat_count") != 14:
        raise SchemaError("assembled dataset must surface all 14 seats")
    return dataset
