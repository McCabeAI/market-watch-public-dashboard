import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl

from scripts.australia_housing_data import (
    D1,
    parse_abs_approvals,
    parse_abs_lending,
    parse_abs_prices,
    parse_abs_transfers,
    parse_rba,
    validate_australia_housing,
)
from scripts.trader_room.evidence import load_market_state


class AustraliaHousingTests(unittest.TestCase):
    def test_abs_headline_parsers(self):
        prices = parse_abs_prices("""
            Reference period June Quarter 2026 Released 8/09/2026
            The total value of residential dwellings in Australia fell by $34.1 billion to $12,688.9 billion this quarter.
            The number of residential dwellings rose by 54,400 to 11,531,100 this quarter.
            The mean price of residential dwellings fell by $8,200 to $1,100,400 this quarter.
            <a href="/statistics/economy/jun-quarter-2026/643202.xlsx">Download xlsx</a>
        """)
        self.assertEqual(prices["as_of"], "2026-06-30")
        self.assertEqual(prices["metrics"]["mean_dwelling_price_aud"]["value"], 1100400.0)
        self.assertEqual(prices["metrics"]["mean_dwelling_price_aud"]["change_amount"], -8200.0)
        self.assertTrue(prices["transfer_workbook_url"].endswith("643202.xlsx"))

        approvals = parse_abs_approvals("""
            Reference period July 2026 Released 1/09/2026
            Total dwelling units approved 17,687 -3.6 9.0
            Private sector houses 10,199 -4.2 6.0
            Private sector dwellings excluding houses 7,119 -0.4 19.9
            The value of total residential building fell 4.9% to $11.26b.
        """)
        self.assertEqual(approvals["metrics"]["total_dwellings_approved"]["value"], 17687.0)
        self.assertEqual(approvals["metrics"]["residential_building_value_billion_aud"]["change_mom_pct"], -4.9)

        lending = parse_abs_lending("""
            Reference period June Quarter 2026 Released 14/08/2026
            Number of new loan commitments for dwellings
            Total loan commitments 134,225 -5.4 0.1 Owner occupier 81,626 -3.3 -1.6
            First home buyers 29,319 -2.9 0.0 Investor 52,599 -8.6 2.8
            Value of new loan commitments for dwellings
            Total loan commitments 97.6 -5.2 6.8 Owner occupier 60.5 -1.9 6.0
            First home buyers 18.4 0.2 10.0 Investor 37.1 -10.2 8.1
        """)
        self.assertEqual(lending["metrics"]["investor_count"]["change_qoq_pct"], -8.6)
        self.assertEqual(lending["metrics"]["new_commitments_value_billion_aud"]["value"], 97.6)

    def test_rba_series_id_parser(self):
        text = "\n".join([
            "Title,Credit Housing Monthly,Credit Housing 12m,Owner Monthly,Owner 12m,Investor Monthly,Investor 12m",
            "Frequency,Monthly,Monthly,Monthly,Monthly,Monthly,Monthly",
            "Units,Per cent,Per cent,Per cent,Per cent,Per cent,Per cent",
            "Publication date,31-Aug-2026,31-Aug-2026,31-Aug-2026,31-Aug-2026,31-Aug-2026,31-Aug-2026",
            "Series ID,DGFACHM,DGFACH12,DGFACOHM,DGFACOH12,DGFACIHM,DGFACIH12",
            "31/07/2026,0.5,4.9,0.5,5.4,0.5,4.0",
        ])
        parsed = parse_rba(text, D1)
        self.assertEqual(parsed["as_of"], "2026-07-31")
        self.assertEqual(parsed["metrics"]["housing_yoy_pct"], 4.9)
        self.assertEqual(parsed["metrics"]["investor_yoy_pct"], 4.0)

    def test_abs_transfer_workbook_sums_geographies(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Table 2"])
        ws.append([])
        ws.append([])
        ws.append([
            "Date",
            "Number of Established House Transfers ; Sydney ;",
            "Number of Established House Transfers ; Rest of NSW ;",
            "Number of Attached Dwelling Transfers ; Sydney ;",
            "Number of Attached Dwelling Transfers ; Rest of NSW ;",
        ])
        ws.append(["Mar-26", 10, 20, 30, 40])
        ws.append(["Jun-26", 11, 21, 31, 41])
        buf = io.BytesIO()
        wb.save(buf)
        parsed = parse_abs_transfers(buf.getvalue())
        self.assertEqual(parsed["as_of"], "2026-06-30")
        self.assertEqual(parsed["metrics"]["established_house_transfers"]["value"], 32)
        self.assertEqual(parsed["metrics"]["attached_dwelling_transfers"]["value"], 72)
        self.assertEqual(parsed["metrics"]["residential_transfers_derived"]["value"], 104)

    def test_trader_packet_load_preserves_housing_block(self):
        housing = {
            "country": "AU",
            "status": "ok",
            "feeds": {
                name: {"status": "ok", "url": "https://example.test", "as_of": "2026-07-31"}
                for name in (
                    "prices_and_turnover", "building_approvals", "housing_lending",
                    "housing_credit", "mortgage_rates", "mortgage_cash_flow",
                )
            },
        }
        validate_australia_housing(housing)
        payload = {"status": "ok", "australia_housing": housing}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "market-state.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_market_state(path)
        self.assertEqual(loaded["australia_housing"], housing)


if __name__ == "__main__":
    unittest.main()
