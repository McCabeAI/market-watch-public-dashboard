#!/usr/bin/env python3
from __future__ import annotations

import argparse
import unittest
from datetime import date
from pathlib import Path

from scripts.japan_rates_data import (
    JGB_TENORS,
    JPX_TONA_EXPECTED_CONTRACTS,
    JapanRatesError,
    build_jp_rates_bundle,
    collect_jp_official_curve,
    collect_jp_policy_path,
    fetch_jp_jgb_rates,
    fetch_tona_history,
    parse_boj_tona_api_csv,
    parse_jpx_ose_tona_settlement_csv,
    parse_jpx_settlement_page_html,
    parse_mof_jgb,
    validate_jp_rates_bundle,
)
from scripts.market_state import BROWSER_USER_AGENT, fetch_bytes

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jp_rates"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


class JapanRatesParserTests(unittest.TestCase):
    def test_parse_mof_jgb_current_fixture(self):
        parsed = parse_mof_jgb(_read("mof_jgbcme_current.csv"))
        self.assertEqual(set(parsed), set(JGB_TENORS))
        latest = max(parsed["10Y"])
        self.assertGreater(parsed["10Y"][latest], 0.5)
        self.assertIn(latest.year, (2026,))

    def test_parse_boj_tona_api_fixture(self):
        hist = parse_boj_tona_api_csv(_read("boj_strdclucon_202609.csv"))
        self.assertGreaterEqual(len(hist), 10)
        d = date(2026, 9, 10)
        self.assertAlmostEqual(hist[d], 0.977, places=3)

    def test_parse_jpx_tona_settlement_fixture(self):
        rows = parse_jpx_ose_tona_settlement_csv(
            _read("jpx_rb_e_tona_subset.csv"),
            benchmark=0.477,
        )
        self.assertEqual(len(rows), JPX_TONA_EXPECTED_CONTRACTS)
        self.assertEqual(rows[0]["expiry"], "2026-09")
        self.assertEqual(rows[0]["code"], "261215")
        self.assertAlmostEqual(rows[0]["implied_rate"], 100.0 - 98.775, places=3)
        self.assertEqual(rows[0]["source"], "JPX_OSE_TOA3M_SETTLEMENT")

    def test_parse_jpx_settlement_page_link(self):
        html = (
            '<a href="/english/markets/derivatives/settlement-price/'
            'tvdivq00000014l6-att/rb_e20260918.csv" rel="external">csv</a>'
        )
        url = parse_jpx_settlement_page_html(html)
        self.assertIn("rb_e20260918.csv", url or "")

    def test_validate_jp_rates_bundle_synthetic(self):
        payload = {
            "country": "JP",
            "rates": {t: {"2026-09-01": 1.0} for t in JGB_TENORS},
            "freshness": {"status": "ok", "as_of": "2026-09-18", "age_days": 0},
            "policy": {
                "status": "ok",
                "benchmark": {"rate": 0.477, "as_of": "2026-09-18", "name": "TONA"},
                "contracts_3m": [
                    {
                        "expiry": "2026-12",
                        "implied_rate": 1.475,
                        "price": 98.525,
                        "change_from_overnight_bps": 99.8,
                    }
                ],
                "tradable_curve": {
                    "curve_id": "TONA",
                    "status": "ok",
                    "contracts": [{"expiry": f"2027-{m:02d}", "implied_rate": 1.0} for m in (3, 6, 9, 12)],
                },
            },
            "official_curve": {
                "status": "ok",
                "par_yields": {
                    t: {"value": 1.5, "as_of": "2026-09-18"} for t in JGB_TENORS
                },
            },
        }
        validate_jp_rates_bundle(payload)

    def test_reject_bad_tona_underlying(self):
        bad = _read("jpx_rb_e_tona_subset.csv").replace("3-Month TONA", "Wrong")
        with self.assertRaises(JapanRatesError):
            parse_jpx_ose_tona_settlement_csv(bad, benchmark=0.48)


@unittest.skipUnless(__name__ == "__main__", "live smoke runs via python3 -m tests.test_japan_rates_data --live")
class JapanRatesLiveSmoke(unittest.TestCase):
    def test_live_collectors(self):
        today = date.today()
        start = today.replace(year=today.year - 1)

        def _fetch(url: str, **kwargs):
            return fetch_bytes(url, timeout=45, retries=2, user_agent=BROWSER_USER_AGENT, **kwargs)

        rates = fetch_jp_jgb_rates(start, today, fetch_bytes=_fetch)
        for tenor in JGB_TENORS:
            self.assertGreater(len(rates[tenor]), 100)

        tona = fetch_tona_history(start, today, fetch_bytes=_fetch)
        self.assertGreater(len(tona), 100)

        policy = collect_jp_policy_path(today, _fetch)
        self.assertEqual(policy.get("status"), "ok")
        contracts = policy.get("contracts_3m") or []
        self.assertEqual(len(contracts), JPX_TONA_EXPECTED_CONTRACTS)
        tradable = policy.get("tradable_curve") or {}
        self.assertEqual(tradable.get("status"), "ok")
        self.assertEqual(tradable.get("curve_id"), "TONA")

        official = collect_jp_official_curve(today, _fetch)
        self.assertEqual(official.get("status"), "ok")
        self.assertEqual(official.get("kind"), "benchmark_par_yields_only")

        bundle = build_jp_rates_bundle(today=today, fetch_bytes=_fetch)
        self.assertEqual(bundle["country"], "JP")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Run network smoke tests")
    args, remaining = parser.parse_known_args()
    suite = unittest.TestSuite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(JapanRatesParserTests))
    if args.live:
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(JapanRatesLiveSmoke))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    _main()
else:
    # `python3 -m unittest tests.test_japan_rates_data` runs parser tests only.
    pass
