"""Deterministic overnight stage orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.overnight.assemble import assemble_dataset
from scripts.overnight.books import empty_books
from scripts.overnight.clock import isoformat, now_ny, overnight_run_id, schedule_catalog, stage_for_time
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import FIXTURE_MARKET_STATE, STAGES
from scripts.overnight.delta import compute_delta
from scripts.overnight.errors import OvernightError, PublicationError, StageError
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.freshness import assert_may_publish
from scripts.overnight.ledger import load_or_create, mark_finished, mark_running, persist_run
from scripts.overnight.publish import emit_pm_books_json, emit_trader_books_json, publication_gate
from scripts.overnight.review import record_missing_live_review, run_trader_review
from scripts.overnight.store import OvernightStore


def ensure_seed_books(store: OvernightStore, run_id: str, when: datetime | None = None) -> None:
    if not store.books_path().is_file():
        store.write_books(empty_books(overnight_run_id=run_id, when=when))


def run_stage(
    stage: str,
    *,
    root: Path | None = None,
    state_root: Path | None = None,
    run_id: str | None = None,
    when: datetime | None = None,
    dry_run: bool = False,
    offline: bool = True,
    market_state_path: Path | None = None,
    review_scenario: str = "default",
    live_reviews: dict[str, Any] | None = None,
    site_dir: Path | None = None,
    require_dataset: bool = False,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise StageError(f"unknown stage {stage}")
    store = OvernightStore(root=root, state_root=state_root)
    run = load_or_create(store, run_id=run_id, when=when, dry_run=dry_run)
    ensure_seed_books(store, run["overnight_run_id"], when=when)
    mark_running(run, stage, when=when, inputs={"dry_run": dry_run, "offline": offline})
    persist_run(store, run)
    try:
        outputs = _dispatch(
            stage,
            store=store,
            run=run,
            when=when,
            dry_run=dry_run,
            offline=offline,
            market_state_path=market_state_path,
            review_scenario=review_scenario,
            live_reviews=live_reviews,
            site_dir=site_dir,
            require_dataset=require_dataset,
        )
        status = "succeeded"
        if stage == "trader_review" and outputs.get("status") == "failed":
            status = "stale"
        errors = list(outputs.get("errors") or [])
        mark_finished(run, stage, status=status, when=when, outputs=_summarize(outputs), errors=errors)
        persist_run(store, run)
        return {"overnight_run_id": run["overnight_run_id"], "stage": stage, "status": status, "run": run, "result": outputs}
    except Exception as exc:
        mark_finished(run, stage, status="failed", when=when, errors=[f"{type(exc).__name__}: {exc}"])
        persist_run(store, run)
        raise


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    keep = ("as_of", "status", "packet_sha256", "source", "model_calls", "unchanged", "core_status", "trader_books_status", "may_publish")
    return {k: payload[k] for k in keep if k in payload}


def _dispatch(
    stage: str,
    *,
    store: OvernightStore,
    run: dict[str, Any],
    when: datetime | None,
    dry_run: bool,
    offline: bool,
    market_state_path: Path | None,
    review_scenario: str,
    live_reviews: dict[str, Any] | None,
    site_dir: Path | None,
    require_dataset: bool,
) -> dict[str, Any]:
    run_id = run["overnight_run_id"]
    if stage == "collect":
        return collect_inputs(store, when=when, run_id=run_id, offline=offline, market_state_path=market_state_path)
    if stage in {"pre_trader_delta", "final_delta"}:
        return compute_delta(
            store,
            run_id=run_id,
            stage=stage,
            when=when,
            offline=offline,
            market_state_path=market_state_path,
        )
    if stage == "freeze_evidence":
        return freeze_snapshot(store, run_id=run_id, when=when)
    if stage == "trader_review":
        if dry_run:
            return run_trader_review(
                store,
                run_id=run_id,
                when=when,
                dry_run=True,
                scenario=review_scenario,
                live_reviews=None,
            )
        if live_reviews is not None:
            return run_trader_review(
                store,
                run_id=run_id,
                when=when,
                dry_run=False,
                live_reviews=live_reviews,
            )
        return record_missing_live_review(store, run_id=run_id, when=when)
    if stage == "assemble":
        return assemble_dataset(store, run, when=when)
    if stage == "publish":
        gate = publication_gate(store, run_id=run_id, require_dataset=require_dataset or dry_run)
        if site_dir is not None:
            site = Path(site_dir)
            emit_trader_books_json(store, site, run_id=run_id)
            emit_pm_books_json(site, root=store.root, state_root=store.state_root)
        return gate
    raise StageError(f"unhandled stage {stage}")


def dry_run(
    *,
    root: Path | None = None,
    state_root: Path | None = None,
    when: datetime | None = None,
    suffix: str = "ci",
    market_state_path: Path | None = None,
    site_dir: Path | None = None,
    review_scenario: str = "default",
) -> dict[str, Any]:
    """Complete orchestration without live trader model spend."""
    store = OvernightStore(root=root, state_root=state_root)
    stamp = now_ny(when)
    run_id = overnight_run_id(stamp, dry_run=True, suffix=suffix)
    fixture = market_state_path or (store.root / FIXTURE_MARKET_STATE)
    if fixture.is_file():
        market_state_path = fixture
    results = []
    for stage in STAGES:
        item = run_stage(
            stage,
            root=store.root,
            state_root=store.state_root,
            run_id=run_id,
            when=stamp,
            dry_run=True,
            offline=True,
            market_state_path=market_state_path,
            review_scenario=review_scenario,
            site_dir=site_dir,
            require_dataset=True,
        )
        results.append({"stage": stage, "status": item["status"]})
    run = store.read_artifact(run_id, "run.json")
    dataset = store.read_artifact(run_id, "assembled_dataset.json")
    assert_may_publish(dataset["publication"])
    if dataset.get("model_calls"):
        raise StageError("dry-run consumed model calls")
    return {
        "overnight_run_id": run_id,
        "as_of": isoformat(stamp),
        "dry_run": True,
        "model_calls": 0,
        "stages": results,
        "publication": dataset["publication"],
        "schedule": schedule_catalog(),
        "run": run,
    }


def selected_stage(when: datetime | None = None) -> str | None:
    return stage_for_time(when)


__all__ = ["dry_run", "run_stage", "selected_stage", "OvernightError", "PublicationError"]
