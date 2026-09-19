#!/usr/bin/env python3
"""Live official-source smoke test for the market-state generator.

Requires US Treasury, BoC, RBA and ECB SDMX. RBNZ is attempted and reported,
but a Cloudflare 403 is not treated as a parser/calculation failure: the official
workbook is unreachable from some hosted runners and must not be replaced.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from scripts.market_state import (
    MarketStateError,
    fetch_au_rates,
    fetch_ca_rates,
    fetch_fx,
    fetch_nz_rates,
    fetch_us_rates,
    fetch_bytes,
    validate_snapshot,
)
from scripts.positioning_data import build_positioning, validate_positioning
from scripts.policy_path_data import (
    build_tradable_rate_curves,
    collect_policy_paths,
    validate_policy_paths,
    validate_tradable_rate_curves,
)


def _latest(series: dict[date, float]) -> tuple[date, float]:
    latest = max(series)
    return latest, series[latest]


def main() -> int:
    today = date.today()
    start = today - timedelta(days=400)
    report: dict[str, object] = {"today": today.isoformat()}

    us = fetch_us_rates(start, today)
    if any(not us.get(t) for t in ("2Y", "5Y", "10Y", "30Y")):
        raise MarketStateError("live US Treasury missing required tenors")
    report["US"] = {t: [_latest(us[t])[0].isoformat(), _latest(us[t])[1]] for t in ("2Y", "5Y", "10Y", "30Y")}

    ca = fetch_ca_rates(start, today)
    if any(not ca.get(t) for t in ("2Y", "5Y", "10Y", "LONG")):
        raise MarketStateError("live BoC missing required tenors")
    report["CA"] = {t: [_latest(ca[t])[0].isoformat(), _latest(ca[t])[1]] for t in ("2Y", "5Y", "10Y", "LONG")}

    au = fetch_au_rates(start, today)
    if any(not au.get(t) for t in ("2Y", "5Y", "10Y")):
        raise MarketStateError("live RBA missing required tenors")
    report["AU"] = {t: [_latest(au[t])[0].isoformat(), _latest(au[t])[1]] for t in ("2Y", "5Y", "10Y")}

    fx = fetch_fx(start)
    if len(fx) != 45 or any(not series for series in fx.values()):
        raise MarketStateError("live ECB FX did not produce 45 populated G10 crosses")
    eurusd_date, eurusd = _latest(fx["EURUSD"])
    audnzd_date, audnzd = _latest(fx["AUDNZD"])
    report["FX"] = {
        "pairs": 45,
        "EURUSD": [eurusd_date.isoformat(), eurusd],
        "AUDNZD": [audnzd_date.isoformat(), audnzd],
    }

    policy_paths = collect_policy_paths(today=today, fetch_bytes=fetch_bytes)
    validate_policy_paths(policy_paths)
    missing_policy = [
        country for country in ("US", "CA", "AU")
        if (policy_paths.get("countries", {}).get(country) or {}).get("status") != "ok"
    ]
    if missing_policy:
        raise MarketStateError(f"live policy paths unavailable for {missing_policy}: {policy_paths}")
    report["policy_paths"] = {
        country: {
            "benchmark": policy_paths["countries"][country].get("benchmark"),
            "terminal": policy_paths["countries"][country].get("terminal"),
        }
        for country in ("US", "CA", "AU")
    }

    tradable = build_tradable_rate_curves(policy_paths)
    validate_tradable_rate_curves(tradable)
    if tradable.get("status") != "ok":
        raise MarketStateError(f"live tradable rate curves unavailable: {tradable}")
    report["tradable_rate_curves"] = {
        curve_id: {
            "product_code": tradable["curves"][curve_id].get("product_code"),
            "contracts": len(tradable["curves"][curve_id].get("contracts") or []),
            "first": (tradable["curves"][curve_id].get("contracts") or [None])[0],
            "last": (tradable["curves"][curve_id].get("contracts") or [None])[-1],
        }
        for curve_id in ("SOFR", "CORRA", "AONIA")
    }

    positioning = build_positioning(
        today=today,
        start=today - timedelta(days=366 * 3 + 30),
        fetch_bytes=fetch_bytes,
    )
    validate_positioning(positioning)
    report["positioning"] = {
        "status": positioning["status"],
        "cftc": positioning["cftc_tff"].get("status"),
        "cftc_as_of": positioning["cftc_tff"].get("report_date"),
        "cme": positioning["cme"].get("status"),
        "cme_as_of": positioning["cme"].get("trade_date"),
        "mapped_cftc_instruments": sorted((positioning["cftc_tff"].get("instruments") or {}).keys()),
        "mapped_cme_instruments": sorted((positioning["cme"].get("instruments") or {}).keys()),
    }

    cftc_keys = set((positioning["cftc_tff"].get("instruments") or {}).keys())
    required_cftc = {"EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "US2Y", "US5Y", "US10Y", "US30Y"}
    if not required_cftc.issubset(cftc_keys):
        raise MarketStateError(f"live CFTC positioning missing {sorted(required_cftc - cftc_keys)}")
    cme_keys = set((positioning["cme"].get("instruments") or {}).keys())
    required_cme = {"EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "NOK", "SEK"}
    if not required_cme.issubset(cme_keys):
        report["CME_status"] = "supplemental_unavailable"
        report["CME_missing"] = sorted(required_cme - cme_keys)
        report["CME_error"] = positioning["cme"].get("errors") or positioning["cme"].get("error")
        print(
            "CME supplemental OI unavailable: "
            f"{report['CME_missing']} {report['CME_error']}",
            file=sys.stderr,
        )

    try:
        nz = fetch_nz_rates(start, today)
        report["NZ"] = {t: [_latest(nz[t])[0].isoformat(), _latest(nz[t])[1]] for t in ("2Y", "5Y", "10Y")}
        report["NZ_status"] = "ok"
    except MarketStateError as exc:
        report["NZ_status"] = "official_source_blocked"
        report["NZ_error"] = str(exc)
        print(f"RBNZ official source blocked: {exc}", file=sys.stderr)

    print(json.dumps(report, indent=2, default=str))
    if "EURUSD" not in fx or not (0.5 < eurusd < 2.5):
        raise MarketStateError("live ECB EURUSD failed sanity")
    # Keep validate_snapshot imported so CI proves the contract module still loads.
    assert callable(validate_snapshot)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MarketStateError as exc:
        print(f"MARKET STATE SMOKE ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
