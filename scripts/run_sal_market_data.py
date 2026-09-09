#!/usr/bin/env python3
"""Production entrypoint for Sal V1.

Keeps source-specific retrieval corrections isolated from the deterministic
analytics module. No model calls.
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
    """Fetch each BoC benchmark series explicitly.

    The Valet endpoint documents comma-separated series names, but the live
    benchmark-bond route currently returns 404 for the combined V-series URL.
    Four single-series calls are deterministic and use the same official API.
    """
    qs = urllib.parse.urlencode({"start_date": start.isoformat(), "end_date": end.isoformat()})
    out = {tenor: {} for tenor in BOC_SERIES.values()}
    for series_id, tenor in BOC_SERIES.items():
        url = f"{BOC_URL.format(series=series_id)}?{qs}"
        payload = json.loads(sal.fetch_bytes(url).decode("utf-8"))
        for obs in payload.get("observations", []):
            d = sal.parse_date(obs.get("d"))
            if not d:
                continue
            cell = obs.get(series_id)
            value = cell.get("v") if isinstance(cell, dict) else cell
            v = sal.to_float(value)
            if v is not None:
                out[tenor][d] = v
    if any(not out[k] for k in sal.RATE_TENORS):
        raise sal.SalError("BoC single-series calls missing required benchmark tenors")
    return out


sal.fetch_ca_rates = fetch_ca_rates


if __name__ == "__main__":
    try:
        raise SystemExit(sal.main())
    except sal.SalError as exc:
        print(f"SAL ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
