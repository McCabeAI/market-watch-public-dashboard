import unittest
from datetime import date

from scripts import run_sal_market_data as run_sal


class TwelveDataFXTests(unittest.TestCase):
    def test_direct_fx_symbol_universe_is_all_45_g10_pairs(self):
        symbols = run_sal.direct_fx_symbols()
        self.assertEqual(len(symbols), 45)
        self.assertEqual(len(set(symbols)), 45)
        self.assertIn("AUD/NZD", symbols)
        self.assertIn("NOK/SEK", symbols)
        self.assertIn("GBP/NZD", symbols)
        self.assertIn("USD/CAD", symbols)

    def test_parse_batch_uses_direct_pair_series(self):
        payload = {
            "AUD/NZD": {
                "status": "ok",
                "values": [
                    {"datetime": "2026-09-08", "close": "1.2345"},
                    {"datetime": "2026-09-09", "close": "1.2400"},
                ],
            },
            "USD/CAD": {
                "status": "ok",
                "values": [
                    {"datetime": "2026-09-08", "close": "1.3750"},
                    {"datetime": "2026-09-09", "close": "1.3800"},
                ],
            },
        }
        out = run_sal.parse_twelve_batch(payload, ["AUD/NZD", "USD/CAD"], date(2026, 1, 1))
        self.assertEqual(out["AUDNZD"][date(2026, 9, 9)], 1.24)
        self.assertEqual(out["USDCAD"][date(2026, 9, 9)], 1.38)

    def test_single_symbol_shape_is_supported(self):
        payload = {
            "status": "ok",
            "values": [
                {"datetime": "2026-09-09", "close": "153.25"},
            ],
        }
        out = run_sal.parse_twelve_batch(payload, ["USD/JPY"], date(2026, 1, 1))
        self.assertEqual(out["USDJPY"][date(2026, 9, 9)], 153.25)

    def test_error_block_fails_loudly(self):
        payload = {"AUD/NZD": {"status": "error", "message": "bad symbol"}}
        with self.assertRaisesRegex(Exception, "Twelve Data error"):
            run_sal.parse_twelve_batch(payload, ["AUD/NZD"], date(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
