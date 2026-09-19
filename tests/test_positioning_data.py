from __future__ import annotations

import unittest
from datetime import date, timedelta

from scripts.positioning_data import (
    build_positioning,
    parse_cftc_tff_rows,
    parse_cme_last_totals,
    validate_positioning,
)


def _cftc_row(d: date, name: str, code: str, oi: int, lev_long: int, lev_short: int) -> dict:
    return {
        "market_and_exchange_names": f"{name} - CHICAGO MERCANTILE EXCHANGE",
        "report_date_as_yyyy_mm_dd": d.isoformat() + "T00:00:00.000",
        "contract_market_name": name,
        "cftc_contract_market_code": code,
        "cftc_market_code": "CME",
        "cftc_commodity_code": code[:3],
        "commodity_name": name,
        "open_interest_all": str(oi),
        "dealer_positions_long_all": "20000",
        "dealer_positions_short_all": "25000",
        "dealer_positions_spread_all": "5000",
        "asset_mgr_positions_long": "30000",
        "asset_mgr_positions_short": "18000",
        "asset_mgr_positions_spread": "4000",
        "lev_money_positions_long": str(lev_long),
        "lev_money_positions_short": str(lev_short),
        "lev_money_positions_spread": "3000",
        "other_rept_positions_long": "10000",
        "other_rept_positions_short": "9000",
        "other_rept_positions_spread": "1000",
        "nonrept_positions_long_all": "8000",
        "nonrept_positions_short_all": "7000",
    }


class PositioningDataTests(unittest.TestCase):
    def test_cftc_tff_builds_crowding_context(self):
        end = date(2026, 9, 15)
        rows = []
        for i in range(60):
            d = end - timedelta(days=7 * (59 - i))
            rows.append(
                _cftc_row(
                    d,
                    "AUSTRALIAN DOLLAR",
                    "232741",
                    100000 + i * 500,
                    25000 + i * 700,
                    22000 + i * 100,
                )
            )
        # The mapping must reject micros rather than silently blending them.
        rows.append(
            _cftc_row(
                end,
                "MICRO AUSTRALIAN DOLLAR",
                "232742",
                999999,
                900000,
                1,
            )
        )
        result = parse_cftc_tff_rows(rows, today=date(2026, 9, 18))
        aud = result["instruments"]["AUD"]
        lev = aud["trader_classes"]["leveraged_funds"]
        self.assertEqual(result["report_date"], "2026-09-15")
        self.assertEqual(aud["cftc_contract_market_code"], "232741")
        self.assertGreater(lev["net"], 0)
        self.assertGreater(lev["weekly_change_net"], 0)
        self.assertIsNotNone(lev["pctile_1y"])
        self.assertIsNotNone(lev["z_1y"])
        self.assertEqual(lev["sample_weeks_1y"], 52)
        validate_positioning(
            {
                "status": "partial",
                "cftc_tff": result,
                "cme": {"status": "unavailable"},
                "method": {"model_calls": 0, "credentials_required": []},
            }
        )

    def test_cftc_treasury_contract_code_mapping(self):
        d = date(2026, 9, 15)
        rows = [
            _cftc_row(d, "2-YEAR U.S. TREASURY NOTES", "042601", 3000000, 400000, 800000),
            _cftc_row(d, "5-YEAR U.S. TREASURY NOTES", "044601", 3500000, 500000, 900000),
            _cftc_row(d, "10-YEAR U.S. TREASURY NOTES", "043602", 4000000, 600000, 1000000),
            _cftc_row(d, "U.S. TREASURY BONDS", "020601", 1000000, 100000, 250000),
        ]
        result = parse_cftc_tff_rows(rows, today=date(2026, 9, 18))
        self.assertEqual(
            {"US2Y", "US5Y", "US10Y", "US30Y"},
            set(result["instruments"]),
        )
        self.assertEqual(
            result["instruments"]["US2Y"]["cftc_contract_market_code"], "042601"
        )

    def test_cme_last_totals_parses_daily_futures_and_options_oi(self):
        payload = {
            "vdate": [
                {
                    "formattedDate": "20260915",
                    "futureVolume": "70000",
                    "optionVolume": "10000",
                    "futureOi": "300000",
                    "optionOi": "150000",
                },
                {
                    "formattedDate": "20260916",
                    "futureVolume": "80000",
                    "optionVolume": "12000",
                    "futureOi": "305000",
                    "optionOi": "152000",
                },
                {
                    "formattedDate": "20260917",
                    "futureVolume": "90000",
                    "optionVolume": "14000",
                    "futureOi": "314753",
                    "optionOi": "153753",
                },
            ]
        }
        result = parse_cme_last_totals(payload, ccy="AUD", today=date(2026, 9, 18))
        self.assertEqual(result["trade_date"], "2026-09-17")
        self.assertEqual(result["product_id"], "37")
        self.assertEqual(result["future_open_interest"], 314753)
        self.assertEqual(result["future_oi_daily_change"], 9753)
        self.assertEqual(result["option_open_interest"], 153753)
        self.assertEqual(result["option_oi_daily_change"], 1753)
        self.assertEqual(result["future_volume"], 90000)
        self.assertEqual(result["option_volume"], 14000)
        self.assertGreater(result["options_to_futures_oi_ratio"], 0)
        self.assertEqual(len(result["history"]), 3)

    def test_build_positioning_fails_soft_by_source(self):
        def broken_fetch(url: str, **_kwargs) -> bytes:
            raise RuntimeError(f"blocked {url}")

        result = build_positioning(
            today=date(2026, 9, 18),
            start=date(2023, 1, 1),
            fetch_bytes=broken_fetch,
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["cftc_tff"]["status"], "unavailable")
        self.assertEqual(result["cme"]["status"], "unavailable")
        validate_positioning(result)


if __name__ == "__main__":
    unittest.main()
