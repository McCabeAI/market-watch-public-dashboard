#!/usr/bin/env python3
"""Non-gating GitHub-runner probe for ICE I, ER3, the ICE spread, and CME EUS.

Writes a JSON report and exits 0 even when a source is blocked. A blocked
fetch is recorded as unavailable. It is not treated as a successful strip.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_state import fetch_bytes
from scripts.rates.cme_eus import acquire_eus_contracts
from scripts.rates.ice_euribor import (
    ICE_CONTRACT_DATA_URL,
    ICE_EXPIRY_CSV_URL,
    ICE_SPREAD_CONTRACT_DATA_URL,
    acquire_ice_euribor_contracts,
)


def _sample(rows: list[dict], code: str) -> dict | None:
    for row in rows:
        if row.get("code") == code or row.get("market_strip") == code:
            return {
                "code": row.get("code"),
                "market_strip": row.get("market_strip"),
                "price": row.get("price"),
                "basis_bp": row.get("basis_bp"),
                "observation_date": row.get("observation_date"),
                "quote_time": row.get("quote_time"),
                "ltd": row.get("ltd"),
                "mark_kind": row.get("mark_kind"),
                "volume": row.get("volume"),
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args()
    today = date.fromisoformat(args.today)
    report: dict = {
        "runner": "github_actions_or_local",
        "probed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "today": today.isoformat(),
        "ice_contract_data_url": ICE_CONTRACT_DATA_URL,
        "ice_expiry_csv_url": ICE_EXPIRY_CSV_URL,
        "ice_spread_url": ICE_SPREAD_CONTRACT_DATA_URL,
        "ice": {"ok": False},
        "eus": {"ok": False},
    }
    try:
        rows, url, method, prov = acquire_ice_euribor_contracts(
            fetch_bytes,
            today=today,
            retrieved_at=report["probed_at"],
        )
        cross = prov.get("ice_er3_cross_check") or {}
        dec = next((row for row in rows if row.get("market_strip") == "Dec26"), None)
        dec_cross = next((row for row in cross.get("points") or [] if row.get("market_strip") == "Dec26"), None)
        report["ice"] = {
            "ok": True,
            "method": method,
            "url": url,
            "count": len(rows),
            "quote_date": prov.get("trade_date"),
            "quote_time": prov.get("quote_time"),
            "retrieved_at": prov.get("retrieved_at"),
            "mark_kind": prov.get("mark_kind"),
            "official_settlement": False,
            "dec26": None if dec is None else _sample([dec], "IZ26"),
            "cross_status": cross.get("status"),
            "dec26_cross": dec_cross,
            "direct_spread_error": cross.get("direct_spread_error"),
        }
    except Exception as exc:
        report["ice"] = {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-500:]}
    try:
        rows, url, method, prov = acquire_eus_contracts(fetch_bytes, today=today)
        dec = next((row for row in rows if row.get("code") == "EUSZ26"), None)
        report["eus"] = {
            "ok": True,
            "method": method,
            "url": url,
            "count": len(rows),
            "trade_date": prov.get("trade_date"),
            "freshness": prov.get("freshness_hint"),
            "via": prov.get("via"),
            "ds_header": prov.get("ds_header"),
            "execution_eligible": False,
            "economics": prov.get("economics"),
            "dec26": None
            if dec is None
            else {
                "code": dec.get("code"),
                "settlement": dec.get("settlement"),
                "basis_bp": dec.get("basis_bp"),
                "observation_date": dec.get("observation_date"),
            },
        }
    except Exception as exc:
        report["eus"] = {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-500:]}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    json.dump({"ice_ok": report["ice"].get("ok"), "eus_ok": report["eus"].get("ok")}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
