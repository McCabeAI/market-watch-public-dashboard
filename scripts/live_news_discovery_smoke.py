"""Smoke check for live Bloomberg/Reuters discovery surfaces (stdout JSON only)."""

from __future__ import annotations

import argparse
import json
import sys

from scripts.overnight.clock import now_ny
from scripts.overnight.live_news import acquire_current_news


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live news discovery smoke check.")
    parser.add_argument(
        "--report",
        dest="report_path",
        metavar="PATH",
        help="Also write a shadow diagnostics JSON report to PATH.",
    )
    args = parser.parse_args(argv)

    when = now_ny()
    try:
        result = acquire_current_news(when=when, offline=False, fetcher=None)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1

    if args.report_path:
        from scripts.overnight.live_news import merge_live_news
        from scripts.overnight.news_diagnostics import build_report, write_report

        candidates = result.get("candidates") or []
        merge = merge_live_news(baseline=[], live_candidates=candidates, when=when)
        # build_report publication_rows describe the research pool, not webpage 6/3/12 slots.
        report = build_report(result, merge, when=when)
        write_report(args.report_path, report)

    preview = [
        {
            "headline": c.get("headline"),
            "url": c.get("url"),
            "source_name": c.get("source_name"),
            "published_at": c.get("published_at"),
            "verification_status": c.get("verification_status"),
        }
        for c in (result.get("candidates") or [])[:5]
    ]
    out = {
        "mode": result.get("mode"),
        "partial": result.get("partial"),
        "cutoff": result.get("cutoff"),
        "receipts": result.get("receipts"),
        "candidate_preview": preview,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
