#!/usr/bin/env python3
"""Production entrypoint for the minimal no-secret Market Watch state feed.

The original Sal analytics module is kept deterministic. This entrypoint only
corrects Bank of Canada retrieval to the currently working one-series-per-call
Valet route; FX remains the no-key ECB reference-rate implementation.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import date

from scripts import sal_market_data as sal

BOC_SERIES = {"V39051": "2Y", "V39053": "5Y", "V39055": "10Y", "V39056": "LONG"}
BOC_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"


def fetch_ca_rates(start: date, end: date) -> dict[str, dict[date, float]]:
    query = urllib.parse.urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
    out = {tenor: {} for tenor in BOC_SERIES.values()}
    for series_id, tenor in BOC_SERIES.items():
        payload = json.loads(sal.fetch_bytes(f"{BOC_URL.format(series=series_id)}?{query}").decode("utf-8"))
        for obs in payload.get("observations", []):
            d = sal.parse_date(obs.get("d"))
            cell = obs.get(series_id)
            value = cell.get("v") if isinstance(cell, dict) else cell
            number = sal.to_float(value)
            if d and number is not None:
                out[tenor][d] = number
    if any(not out[t] for t in sal.RATE_TENORS):
        raise sal.SalError("Bank of Canada single-series calls missing required tenors")
    return out


sal.fetch_ca_rates = fetch_ca_rates


if __name__ == "__main__":
    try:
        raise SystemExit(sal.main())
    except sal.SalError as exc:
        print(f"MARKET STATE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
