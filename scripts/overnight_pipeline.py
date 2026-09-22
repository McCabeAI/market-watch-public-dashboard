#!/usr/bin/env python3
"""CLI for the unattended Market Watch overnight pipeline.

GitHub Actions is the scheduler. This entrypoint never spends live trader
models unless OVERNIGHT_TRADER_REVIEW_LIVE=1 and a review payload is supplied.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts.overnight.books import empty_books
from scripts.overnight.clock import overnight_run_id, schedule_catalog, stage_for_time
from scripts.overnight.constants import ROOT, STAGES
from scripts.overnight.pipeline import dry_run, reconcile_due_stages, run_stage
from scripts.overnight.store import OvernightStore


def _parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market Watch overnight production pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    dry = sub.add_parser("dry-run", help="Exercise every stage without live trader model calls")
    dry.add_argument("--root", type=Path, default=ROOT)
    dry.add_argument("--state-root", type=Path, default=None)
    dry.add_argument("--as-of", dest="as_of")
    dry.add_argument("--suffix", default="ci")
    dry.add_argument("--market-state", type=Path, default=None)
    dry.add_argument("--site-dir", type=Path, default=None)
    dry.add_argument("--scenario", default="default")

    stage = sub.add_parser("stage", help="Run one named stage")
    stage.add_argument("name", choices=STAGES)
    stage.add_argument("--root", type=Path, default=ROOT)
    stage.add_argument("--state-root", type=Path, default=None)
    stage.add_argument("--run-id")
    stage.add_argument("--as-of", dest="as_of")
    stage.add_argument("--dry-run", action="store_true")
    stage.add_argument("--live-market-state", action="store_true")
    stage.add_argument("--market-state", type=Path, default=None)
    stage.add_argument("--site-dir", type=Path, default=None)
    stage.add_argument("--reviews", type=Path, default=None)
    stage.add_argument("--require-dataset", action="store_true")

    reconcile = sub.add_parser("reconcile", help="Catch up all due deterministic stages for the current NY session")
    reconcile.add_argument("--root", type=Path, default=ROOT)
    reconcile.add_argument("--state-root", type=Path, default=None)
    reconcile.add_argument("--as-of", dest="as_of")
    reconcile.add_argument("--live-market-state", action="store_true")
    reconcile.add_argument("--site-dir", type=Path, default=None)

    which = sub.add_parser("which-stage", help="Print the ET stage window for now (or --as-of)")
    which.add_argument("--as-of", dest="as_of")

    sched = sub.add_parser("schedule", help="Print the America/New_York stage catalog")

    rid = sub.add_parser("run-id", help="Print the canonical overnight run id")
    rid.add_argument("--as-of", dest="as_of")

    fresh = sub.add_parser(
        "open-review",
        help="Freeze a new immutable review_id under an existing session without applying decisions",
    )
    fresh.add_argument("--run-id", required=True)
    fresh.add_argument("--root", type=Path, default=ROOT)
    fresh.add_argument("--state-root", type=Path, default=None)
    fresh.add_argument("--as-of", dest="as_of")

    seed = sub.add_parser("init-books", help="Write empty $100m books if missing")
    seed.add_argument("--root", type=Path, default=ROOT)
    seed.add_argument("--state-root", type=Path, default=None)

    pub = sub.add_parser("publish-check", help="Validate the canonical dataset for Pages")
    pub.add_argument("--root", type=Path, default=ROOT)
    pub.add_argument("--state-root", type=Path, default=None)
    pub.add_argument("--run-id")
    pub.add_argument("--site-dir", type=Path, default=None)
    pub.add_argument("--require-dataset", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "schedule":
        print(json.dumps(schedule_catalog(), indent=2))
        return 0
    if args.cmd == "run-id":
        print(overnight_run_id(_parse_when(args.as_of)))
        return 0
    if args.cmd == "open-review":
        from scripts.overnight.evidence import freeze_snapshot

        store = OvernightStore(root=args.root, state_root=args.state_root)
        packet = freeze_snapshot(
            store,
            run_id=args.run_id,
            when=_parse_when(args.as_of),
            reuse_open=False,
        )
        print(
            json.dumps(
                {
                    "overnight_run_id": packet["overnight_run_id"],
                    "review_id": packet["review_id"],
                    "packet_sha256": packet["packet_sha256"],
                    "starting_trader_books_sha256": packet.get("starting_trader_books_sha256"),
                    "starting_pm_books_sha256": packet.get("starting_pm_books_sha256"),
                    "status": "frozen",
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "reconcile":
        result = reconcile_due_stages(
            root=args.root,
            state_root=args.state_root,
            when=_parse_when(args.as_of),
            live_market_state=args.live_market_state,
            site_dir=args.site_dir,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.cmd == "which-stage":
        when = _parse_when(args.as_of)
        print(stage_for_time(when) or "idle")
        return 0
    if args.cmd == "init-books":
        store = OvernightStore(root=args.root, state_root=args.state_root)
        if not store.books_path().is_file():
            store.write_books(empty_books())
            print(f"seeded {store.books_path()}")
        else:
            print(f"books already present: {store.books_path()}")
        return 0
    if args.cmd == "dry-run":
        result = dry_run(
            root=args.root,
            state_root=args.state_root or args.root,
            when=_parse_when(args.as_of),
            suffix=args.suffix,
            market_state_path=args.market_state,
            site_dir=args.site_dir,
            review_scenario=args.scenario,
        )
        print(json.dumps({k: result[k] for k in ("overnight_run_id", "as_of", "dry_run", "model_calls", "stages", "publication")}, indent=2))
        return 0
    if args.cmd == "publish-check":
        from scripts.overnight.publish import emit_trader_books_json, publication_gate

        store = OvernightStore(root=args.root, state_root=args.state_root)
        site_dir = args.site_dir
        if site_dir:
            emit_trader_books_json(store, site_dir, run_id=args.run_id)
        gate = publication_gate(
            store,
            run_id=args.run_id,
            require_dataset=args.require_dataset,
            site_dir=site_dir,
        )
        if site_dir:
            from scripts.overnight.publish import emit_pm_books_json

            emit_pm_books_json(args.site_dir, root=args.root)
        print(json.dumps({k: gate[k] for k in gate if k != "dataset"}, indent=2))
        return 0
    if args.cmd == "stage":
        reviews = None
        if args.reviews:
            reviews = json.loads(Path(args.reviews).read_text(encoding="utf-8"))
        result = run_stage(
            args.name,
            root=args.root,
            state_root=args.state_root,
            run_id=args.run_id,
            when=_parse_when(args.as_of),
            dry_run=args.dry_run,
            offline=not args.live_market_state,
            market_state_path=args.market_state,
            live_reviews=reviews,
            site_dir=args.site_dir,
            require_dataset=args.require_dataset,
        )
        print(json.dumps({"overnight_run_id": result["overnight_run_id"], "stage": result["stage"], "status": result["status"]}, indent=2))
        return 0
    raise SystemExit(f"unhandled command {args.cmd}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
