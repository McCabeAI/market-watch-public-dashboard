#!/usr/bin/env python3
"""GitHub Actions runner probe for ASX cash-rate EOD (no secrets, diagnostic only)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

from scripts.asx_eod import ASX_EOD_TEMPLATE, parse_asx_eod_products

ASX_PROBE_URL = ASX_EOD_TEMPLATE.format(yymmdd="261106")
ASX_REFERER = "https://www.asx.com.au/"
HTTP_TIMEOUT_SECONDS = 20

FetchBytes = Callable[..., bytes]


def evaluate_probe_payload(
    *,
    url: str,
    http_status: int | None,
    body: str | None,
    error: str | None,
    expected_session: date,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "url": url,
        "http_status": http_status,
        "session_date": None,
        "publication_time": None,
        "ib_row_count": 0,
        "ir_row_count": 0,
        "ir_quarterly_tradable_count": 0,
        "dec_2026_settlement": None,
        "mar_2027_settlement": None,
        "runner_claim": "blocked_or_unconfirmed",
        "error": error,
    }
    if http_status != 200 or body is None:
        return out

    parsed = parse_asx_eod_products(body, source_url=url)
    out["session_date"] = parsed.get("session_date")
    out["publication_time"] = parsed.get("publication_time")
    if parsed.get("document_error"):
        out["error"] = parsed["document_error"]
        return out

    ib = parsed["products"].get("IB") or {}
    ir = parsed["products"].get("IR") or {}
    ib_rows = ib.get("raw_contracts") or []
    ir_rows = ir.get("raw_contracts") or []
    out["ib_row_count"] = len(ib_rows)
    out["ir_row_count"] = len(ir_rows)

    ir_tradable = ir.get("contracts") or []
    quarterly_tradable = [
        r for r in ir_tradable if r.get("listing_role") == "quarterly" and r.get("tradable")
    ]
    out["ir_quarterly_tradable_count"] = len(quarterly_tradable)

    by_expiry = {str(r.get("expiry")): r for r in ir_rows if r.get("expiry")}
    dec = by_expiry.get("2026-12")
    mar = by_expiry.get("2027-03")
    if dec is not None and dec.get("price") is not None:
        out["dec_2026_settlement"] = float(dec["price"])
    if mar is not None and mar.get("price") is not None:
        out["mar_2027_settlement"] = float(mar["price"])

    expected_iso = expected_session.isoformat()
    verified = (
        http_status == 200
        and out["session_date"] == expected_iso
        and out["ib_row_count"] >= 1
        and out["ir_row_count"] >= 1
        and out["ir_quarterly_tradable_count"] >= 5
        and out["dec_2026_settlement"] == 95.05
        and out["mar_2027_settlement"] == 95.04
    )
    out["runner_claim"] = "verified" if verified else "blocked_or_unconfirmed"
    return out


def fetch_probe_body(fetch_bytes: FetchBytes, url: str) -> tuple[int | None, str | None, str | None]:
    try:
        raw = fetch_bytes(
            url,
            referer=ASX_REFERER,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            timeout=HTTP_TIMEOUT_SECONDS,
            retries=1,
        )
        body = raw.decode("utf-8", errors="replace")
        return 200, body, None
    except Exception as exc:
        status: int | None = None
        if hasattr(exc, "code") and isinstance(getattr(exc, "code"), int):
            status = int(exc.code)
        return status, None, str(exc)


def build_probe(fetch_bytes: FetchBytes, session: date) -> dict[str, Any]:
    url = ASX_PROBE_URL
    http_status, body, error = fetch_probe_body(fetch_bytes, url)
    return evaluate_probe_payload(
        url=url,
        http_status=http_status,
        body=body,
        error=error,
        expected_session=session,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Probe ASX EOD settlements from a GitHub Actions runner")
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
