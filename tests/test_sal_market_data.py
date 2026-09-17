import unittest
from datetime import date

from scripts.sal_market_data import (
    build_fx_crosses,
    curve_spread,
    fx_metrics,
    parse_boc_json,
    parse_ecb_fx_csv,
    parse_rba_csv,
    parse_rbnz_xlsx,
    parse_treasury_csv,
    percentile_rank,
    rv_spread,
)


class SalTests(unittest.TestCase):
    def test_treasury_parser(self):
        text = "Date,2 Yr,5 Yr,10 Yr,30 Yr\n09/08/2026,4.39,4.57,4.80,5.25\n"
        p = parse_treasury_csv(text)
        self.assertEqual(p["2Y"][date(2026, 9, 8)], 4.39)
        self.assertEqual(p["30Y"][date(2026, 9, 8)], 5.25)

    def test_boc_parser(self):
        payload = {"observations": [{"d": "2026-09-08", "V39051": {"v": "2.50"}, "V39053": {"v": "2.75"}, "V39055": {"v": "3.00"}, "V39056": {"v": "3.40"}}]}
        p = parse_boc_json(payload)
        self.assertEqual(p["10Y"][date(2026, 9, 8)], 3.0)

    def test_rba_parser(self):
        text = "\n".join([
            "Title,Australian Government 2 year bond,Australian Government 5 year bond,Australian Government 10 year bond",
            "Description,Australian Government 2 year bond,Australian Government 5 year bond,Australian Government 10 year bond",
            "Frequency,Daily,Daily,Daily",
            "Series ID,F2Y,F5Y,F10Y",
            "2026-09-07,3.10,3.40,3.70",
        ])
        p = parse_rba_csv(text)
        self.assertEqual(p["5Y"][date(2026, 9, 7)], 3.4)

    def test_ecb_and_all_45_crosses(self):
        headers = ["Date", "USD", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"]
        rows = [
            ["2026-09-07", "1.20", "180", "0.86", "0.94", "1.60", "1.62", "1.98", "11.2", "10.8"],
            ["2026-09-08", "1.21", "181", "0.87", "0.95", "1.61", "1.63", "1.99", "11.3", "10.9"],
        ]
        text = ",".join(headers) + "\n" + "\n".join(",".join(r) for r in rows) + "\n"
        currencies = parse_ecb_fx_csv(text)
        crosses = build_fx_crosses(currencies, date(2026, 1, 1))
        self.assertEqual(len(crosses), 45)
        self.assertAlmostEqual(crosses["EURUSD"][date(2026, 9, 8)], 1.21)
        self.assertAlmostEqual(crosses["USDCAD"][date(2026, 9, 8)], 1.61 / 1.21)
        self.assertAlmostEqual(crosses["AUDNZD"][date(2026, 9, 8)], 1.99 / 1.63)

    def test_spread_orientation(self):
        d = date(2026, 9, 8)
        self.assertEqual(curve_spread({d: 2.0}, {d: 3.0})[d], 100.0)
        self.assertEqual(rv_spread({d: 3.0}, {d: 4.25})[d], -125.0)

    def test_percentile(self):
        self.assertEqual(percentile_rank([1, 2, 3, 4], 4), 87.5)

    def test_fx_metric_orientation(self):
        m = fx_metrics({date(2026, 1, 1): 1.0, date(2026, 1, 2): 1.1})
        self.assertAlmostEqual(m["ret_1d"], 10.0)

    def test_rbnz_workbook_parser(self):
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append([None, "Secondary market government bond closing yields (%pa)", None, None])
        ws.append(["Date", "2 year", "5 year", "10 year"])
        ws.append([date(2026, 9, 8), 3.6, 4.2, 4.8])
        buf = io.BytesIO()
        wb.save(buf)
        p = parse_rbnz_xlsx(buf.getvalue())
        self.assertEqual(p["2Y"][date(2026, 9, 8)], 3.6)
        self.assertEqual(p["10Y"][date(2026, 9, 8)], 4.8)


if __name__ == "__main__":
    unittest.main()
