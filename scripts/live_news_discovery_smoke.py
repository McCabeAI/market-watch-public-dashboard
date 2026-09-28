"""Smoke check for live Bloomberg/Reuters discovery surfaces (stdout JSON only)."""

from __future__ import annotations

import json
import sys

from scripts.overnight.clock import now_ny
from scripts.overnight.live_news import acquire_current_news


def main() -> int:
    try:
        result = acquire_current_news(when=now_ny(), offline=False, fetcher=None)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
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
