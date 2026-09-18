from __future__ import annotations

import unittest
from datetime import date, timedelta

from scripts.positioning_data import (
    build_positioning,
    parse_cftc_tff_rows,
    parse_cme_fx_bulletin,
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

    def test_cme_summary_parses_futures_and_monthly_options(self):
        text = """
PG01B BULLETIN # 179@ Thu, Sep 17, 2026
EC EURO FX FUTURES 167803 8331 176134 818433 - 303 204770 852084
JY JAPANESE YEN FUTURE 157840 3650 161490 431866 - 337 174853 306173
BP BRITISH POUND FUTURE 108581 4620 113201 233149 + 2648 85390 235552
AD AUSTRALIAN DLR FUTURES 63812 2758 66570 314753 - 2889 104976 153753
CD CANADIAN DOLLAR FUTURE 60137 3456 63593 292853 + 6383 50958 207017
NE NEW ZEALAND DOLLAR FUTURES 35743 4734 40477 95408 + 1773 52708 53206
SF SWISS FRANC FUTURES 23635 540 24175 133267 + 1703 26133 70776
SE SKR/USD CROSS RATE FUTURES 430 755 1185 5946 + 335 354 3211
UN NKR/USD CROSS RATE FUTURES 272 309 581 8780 + 215 726 7101
FUTURES ONLY-
 FX 746227 30381 776608 2877512 - 52542 844981 2326354
OPTIONS ONLY-
 FX 35036 5600 40636 793885 + 11550 43045 732755
ADU AUD/USD Monthly Options C 1441 1441 21182 + 1262 724 59533
ADU AUD/USD Monthly Options P 2520 2520 27769 + 2366 731 20047
CAU CAD/USD Monthly Options C 221 221 25996 + 193 163 35271
CAU CAD/USD Monthly Options P 91 91 14904 + 40 567 19631
EUU EUR/USD Monthly Options C 6631 600 7231 182584 + 3435 4454 157350
EUU EUR/USD Monthly Options P 7198 5000 12198 185338 + 5468 8722 111248
GBU GBP/USD Monthly Options C 770 770 32322 + 337 314 30156
GBU GBP/USD Monthly Options P 1046 1046 33875 + 481 3464 54449
JPU JPY/USD Monthly Options C 2286 2286 68096 - 233 4390 62516
JPU JPY/USD Monthly Options P 1293 1293 49553 - 133 1898 45754
CHU CHF/USD Monthly Options C 22 22 12861 + 10 111 17184
CHU CHF/USD Monthly Options P 113 113 7198 + 102 66 6541
ZN NZD/USD Monthly Options C 10 10 6317 + 10 2
ZN NZD/USD Monthly Options P 9139
"""
        result = parse_cme_fx_bulletin(text, today=date(2026, 9, 18))
        self.assertEqual(result["trade_date"], "2026-09-17")
        self.assertEqual(result["futures"]["AUD"]["open_interest"], 314753)
        self.assertEqual(result["futures"]["AUD"]["daily_change"], -2889)
        self.assertEqual(result["futures"]["NOK"]["open_interest"], 8780)
        self.assertEqual(result["monthly_options"]["AUD"]["call_open_interest"], 21182)
        self.assertEqual(result["monthly_options"]["AUD"]["put_open_interest"], 27769)
        self.assertGreater(result["monthly_options"]["AUD"]["put_call_oi_ratio"], 1.0)
        self.assertEqual(result["monthly_options"]["NZD"]["put_open_interest"], 9139)
        self.assertEqual(result["aggregate_fx"]["futures"]["open_interest"], 2877512)
        self.assertEqual(result["aggregate_fx"]["options"]["open_interest"], 793885)

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
