#!/usr/bin/env python3
"""Apply the public dashboard repair to a built Pages HTML file."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.dashboard_repair.apply import apply_dashboard_repair, load_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair the built Market Watch dashboard HTML")
    parser.add_argument("html", help="Path to _site/index.html")
    parser.add_argument("--market-state", default="", help="Dated market-state JSON. Omit only when the packet was not published.")
    parser.add_argument("--scores", default="", help="Temperature score state JSON")
    parser.add_argument("--now", default="", help="ISO timestamp used as the release-calendar clock")
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
    updated = apply_dashboard_repair(path.read_text(encoding="utf-8"), market_state=packet, scores=scores, now=now)
    path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
