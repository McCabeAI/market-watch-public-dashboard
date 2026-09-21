#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from scripts.euro_area_rates_data import (
    EuroAreaRatesError,
    compute_fragmentation_spreads,
    fetch_ea_bund_rates,
    parse_bundesbank_csv,
    parse_ecb_estr_csv,
    parse_ecb_yc_spot_csv,
    parse_eurostat_mcby_json,
    parse_fst3_settlement_csv,
    parse_peripheral_yields_csv,
    validate_ea_rates_bundle,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ea_rates"


class EuroAreaRatesParserTests(unittest.TestCase):
    def test_bundesbank_csv(self):
        text = (FIXTURES / "bundesbank_2y_sample.csv").read_text(encoding="utf-8")
        parsed = parse_bundesbank_csv(text)
        self.assertEqual(parsed[date(2024, 1, 2)], 2.45)
        self.assertEqual(parsed[date(2024, 1, 5)], 2.57)
        self.assertNotIn(date(2024, 1, 1), parsed)
        self.assertNotIn(date(2024, 1, 6), parsed)

    def test_bundesbank_csv_english_comma_dialect(self):
        text = (FIXTURES / "bundesbank_2y_en_sample.csv").read_text(encoding="utf-8")
        parsed = parse_bundesbank_csv(text)
        self.assertEqual(parsed[date(2024, 1, 2)], 2.45)
        self.assertEqual(parsed[date(2024, 1, 5)], 2.57)
        self.assertEqual(parsed[date(2024, 1, 10)], 2.60)
        self.assertNotIn(date(2024, 1, 6), parsed)
        self.assertNotIn(date(2026, 9, 21), parsed)

    def test_ecb_estr_csv(self):
        text = (FIXTURES / "ecb_estr_sample.csv").read_text(encoding="utf-8")
        parsed = parse_ecb_estr_csv(text)
        self.assertAlmostEqual(parsed[date(2024, 1, 2)], 3.906)
        self.assertEqual(len(parsed), 7)

    def test_ecb_yc_spot_csv(self):
        text = (FIXTURES / "ecb_yc_sr2y_sample.csv").read_text(encoding="utf-8")
        parsed = parse_ecb_yc_spot_csv(text)
        self.assertIn(date(2024, 9, 2), parsed)
        self.assertGreater(parsed[date(2024, 9, 2)], 2.0)

    def test_fst3_implied_rate_arithmetic(self):
        text = (FIXTURES / "fst3_settlement_sample.csv").read_text(encoding="utf-8")
        rows = parse_fst3_settlement_csv(text, benchmark=3.75)
        self.assertEqual(rows[0]["expiry"], "2024-12")
        self.assertEqual(rows[0]["price"], 96.25)
        self.assertEqual(rows[0]["implied_rate"], 3.75)
        self.assertEqual(rows[0]["change_from_overnight_bps"], 0.0)
        self.assertEqual(rows[1]["implied_rate"], 3.9)

    def test_eurostat_mcby_json(self):
        payload = json.loads((FIXTURES / "eurostat_mcby_sample.json").read_text(encoding="utf-8"))
        parsed = parse_eurostat_mcby_json(payload)
        self.assertEqual(parsed["DE"][date(2024, 1, 31)], 2.5)
        self.assertEqual(parsed["IT"][date(2024, 2, 29)], 4.0)

    def test_fragmentation_exact_common_dates_no_forward_fill(self):
        bund_text = (FIXTURES / "bundesbank_2y_sample.csv").read_text(encoding="utf-8")
        it_text = (FIXTURES / "peripheral_it_2y_sample.csv").read_text(encoding="utf-8")
        bund = {"2Y": parse_bundesbank_csv(bund_text)}
        it = {"2Y": parse_peripheral_yields_csv(it_text, country="IT", tenor="2Y")}
        # Extra IT date must not appear in spreads.
        it["2Y"][date(2024, 1, 6)] = 4.2
        out = compute_fragmentation_spreads(
            bund_yields=bund,
            peripheral_yields={"IT": it},
            tenors=("2Y",),
        )
        spreads = out["spreads"]["IT"]["2Y"]
        self.assertEqual(set(spreads.keys()), {
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        })
        self.assertAlmostEqual(spreads["2024-01-02"], 4.10 - 2.45)
        self.assertNotIn("2024-01-06", spreads)

    def test_validate_ea_rates_bundle_fail_loud(self):
        with self.assertRaises(EuroAreaRatesError):
            validate_ea_rates_bundle({"bund_rates": {}})
        ok = {
            "bund_rates": {
                "2Y": {"2024-01-02": 2.0},
                "5Y": {"2024-01-02": 2.1},
                "10Y": {"2024-01-02": 2.2},
                "30Y": {"2024-01-02": 2.3},
            },
            "policy_path": {
                "status": "partial",
                "benchmark": {"name": "€STR", "rate": 3.5, "as_of": "2024-01-02"},
                "tradable_curve": {"status": "unavailable"},
            },
        }
        validate_ea_rates_bundle(ok)


class EuroAreaRatesLiveSmoke(unittest.TestCase):
    @unittest.skipUnless(
        __import__("os").environ.get("EA_RATES_LIVE") == "1",
        "set EA_RATES_LIVE=1 to run network smoke tests",
    )
    def test_live_bundesbank_2y(self):
        end = date.today()
        start = end - __import__("datetime").timedelta(days=30)
        data = fetch_ea_bund_rates(start, end)
        self.assertTrue(data["2Y"])


if __name__ == "__main__":
    unittest.main()
