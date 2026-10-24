#!/usr/bin/env python3
"""Apply the public dashboard repair to a built Pages HTML file."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scripts.dashboard_repair.apply import apply_dashboard_repair, load_scores
from scripts.dashboard_repair.official_schedule import fetch_official_schedules


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _write_sidecars(site: Path) -> None:
    snapshot = getattr(apply_dashboard_repair, "last_snapshot", None)
    calendar = getattr(apply_dashboard_repair, "last_calendar", None)
    if isinstance(snapshot, dict):
        (site / "source-health.json").write_text(json.dumps(_jsonable(snapshot), indent=2) + "\n", encoding="utf-8")
    if isinstance(calendar, dict):
        public = {
            "window_start": calendar.get("window_start"),
            "window_end": calendar.get("window_end"),
            "calibration_anchor": calendar.get("calibration_anchor"),
            "score_inputs_last_ingested": calendar.get("score_inputs_last_ingested"),
            "score_freeze": calendar.get("score_freeze"),
            "schedule_fetch": calendar.get("schedule_fetch"),
            "upcoming": calendar.get("upcoming"),
            "recent": calendar.get("recent"),
            "later": calendar.get("later"),
            "unscheduled_count": len(calendar.get("unscheduled_scored") or []),
        }
        (site / "release-calendar.json").write_text(json.dumps(_jsonable(public), indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair the built Market Watch dashboard HTML")
    parser.add_argument("html", help="Path to _site/index.html")
    parser.add_argument("--market-state", default="", help="Dated market-state JSON. Omit only when the packet was not published.")
    parser.add_argument("--scores", default="", help="Temperature score state JSON")
    parser.add_argument("--now", default="", help="ISO timestamp used as the release-calendar clock")
    parser.add_argument("--fetch-schedules", action="store_true", help="Read bounded official schedule pages")
    parser.add_argument("--schedule-timeout", type=float, default=6.0)
    parser.add_argument("--trader-room", default="", help="Public trader-room.json to render inside Trader Book")
    args = parser.parse_args()

    path = Path(args.html)
    packet = None
    if args.market_state:
        market_path = Path(args.market_state)
        if not market_path.is_file():
            raise SystemExit(f"market-state file missing: {market_path}")
        packet = json.loads(market_path.read_text(encoding="utf-8"))
        if not isinstance(packet, dict):
            raise SystemExit("market-state JSON must be an object")
    scores = load_scores(Path(args.scores) if args.scores else None)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    schedule_fetch = None
    if args.fetch_schedules:
        try:
            schedule_fetch = fetch_official_schedules(now, timeout=args.schedule_timeout)
        except Exception as exc:  # noqa: BLE001 — a schedule outage must not restore stale dates
            schedule_fetch = {
                "attempted": True,
                "retrieved_at": "",
                "pages": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
                "slots": [],
            }
    trader_room = None
    trader_path = Path(args.trader_room) if args.trader_room else path.parent / "trader-room.json"
    if trader_path.is_file():
        loaded = json.loads(trader_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            trader_room = loaded
    from scripts.apply_country_detail import load_country_detail_context

    country_detail = load_country_detail_context()
    updated = apply_dashboard_repair(
        path.read_text(encoding="utf-8"),
        market_state=packet,
        scores=scores,
        now=now,
        trader_room=trader_room,
        schedule_fetch=schedule_fetch,
        country_detail=country_detail,
    )
    path.write_text(updated, encoding="utf-8")
    _write_sidecars(path.parent)


if __name__ == "__main__":
    main()
