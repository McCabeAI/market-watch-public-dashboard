#!/usr/bin/env python3
"""GitHub Actions runner probe for CME ESR settlements (no secrets)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

from scripts.rates.cme_esr import (
    CME_ESR_PAGE,
    parse_cme_esr_settlements_json,
    probe_cme_esr,
)

FetchBytes = Callable[..., bytes]


def _runner_claim(
    *,
    ok: bool,
    report_type: str | None,
    trade_date: str | None,
    usable_quarterly_count: int | None,
) -> str:
    if (
        ok
        and report_type == "Final"
        and trade_date == "11/06/2026"
        and usable_quarterly_count is not None
        and usable_quarterly_count >= 4
    ):
        return "verified"
    return "blocked_or_unconfirmed"


def build_probe(fetch_bytes: FetchBytes, session: date) -> dict[str, Any]:
    probe = probe_cme_esr(fetch_bytes, session_date=session)
    out: dict[str, Any] = {
        "url": probe.get("url"),
        "http_status": probe.get("http_status"),
        "via": probe.get("via"),
        "ok": bool(probe.get("ok")),
        "report_type": probe.get("report_type"),
        "trade_date": probe.get("trade_date"),
        "ds_header": probe.get("ds_header"),
        "settlement_count": probe.get("settlement_count"),
        "usable_quarterly_count": None,
        "quarterly_codes": None,
        "error": probe.get("error"),
        "runner_claim": "blocked_or_unconfirmed",
    }
    url = probe.get("url")
    if probe.get("ok") and url:
        try:
            raw = fetch_bytes(url, referer=CME_ESR_PAGE)
            body = raw.decode("utf-8", errors="replace")
            rows = parse_cme_esr_settlements_json(
                body,
                benchmark=2.0,
                session_date=session,
                source_url=str(url),
            )
            quarterly = [r for r in rows if r.get("listing") == "quarterly"]
            out["usable_quarterly_count"] = len(quarterly)
            out["quarterly_codes"] = [r.get("code") for r in quarterly if r.get("code")]
        except Exception as exc:
            out["error"] = str(exc)
            out["ok"] = False
    out["runner_claim"] = _runner_claim(
        ok=out["ok"],
        report_type=out.get("report_type"),
        trade_date=out.get("trade_date"),
        usable_quarterly_count=out.get("usable_quarterly_count"),
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Probe CME ESR settlements from a GitHub Actions runner")
    ap.add_argument("--session", required=True, help="session date YYYY-MM-DD")
    ap.add_argument("--output", help="optional JSON output path")
    args = ap.parse_args(argv)
    session = date.fromisoformat(args.session)

    from scripts.market_state import fetch_bytes

    report = build_probe(fetch_bytes, session)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
