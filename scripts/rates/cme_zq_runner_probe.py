#!/usr/bin/env python3
"""Diagnostic CME ZQ settlement probe. Not a required CI gate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_state import fetch_bytes
from scripts.rates.cme_zq import CME_ZQ_PAGE, parse_cme_zq_settlements_json, probe_cme_zq
from scripts.rates.euribor_futures import qualify_euribor_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe CME ZQ and EURIBOR source access")
    parser.add_argument("--session", default="2026-11-06")
    args = parser.parse_args()
    session = date.fromisoformat(args.session)
    probe = probe_cme_zq(fetch_bytes, session_date=session)
    summary = {
        "zq": {
            "url": probe.get("url"),
            "http_status": probe.get("http_status"),
            "via": probe.get("via"),
            "ok": probe.get("ok"),
            "report_type": probe.get("report_type"),
            "trade_date": probe.get("trade_date"),
            "ds_header": probe.get("ds_header"),
            "settlement_count": probe.get("settlement_count"),
            "error": probe.get("error"),
        },
        "euribor": None,
    }
    if probe.get("ok") and probe.get("url"):
        from scripts.rates.cme_zq import _fetch_bytes

        raw, _attempt = _fetch_bytes(fetch_bytes, str(probe["url"]), referer=CME_ZQ_PAGE)
        rows, rejected = parse_cme_zq_settlements_json(
            raw.decode("utf-8", errors="replace"),
            session_date=session,
            source_url=str(probe["url"]),
        )
        summary["zq"]["eligible_count"] = len(rows)
        summary["zq"]["sample_codes"] = [row["code"] for row in rows[:4]]
        summary["zq"]["last_code"] = rows[-1]["code"] if rows else None
        summary["zq"]["rejected_count"] = len(rejected)
        summary["zq"]["observation_date"] = rows[0]["observation_date"] if rows else None
    summary["euribor"] = qualify_euribor_sources(fetch_bytes, today=session)
    summary["euribor"].pop("_body", None)
    json.dump(summary, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
