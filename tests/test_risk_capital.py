from __future__ import annotations

import unittest

from scripts.overnight.books import position_pnl
from scripts.risk_capital import (
    RATE_SHOCK_PERCENTAGE_POINTS,
    RISK_CAPITAL_METHOD,
    book_risk_capital,
    position_risk_capital,
)


class RiskCapitalTests(unittest.TestCase):
    def test_equal_standard_shock_pnl_is_equal_risk_capital(self) -> None:
        spot = {"asset_class": "spot_fx", "notional_usd": 100_000_000, "entry_price": 1.40, "mark_price": 1.40}
        rates = {"asset_class": "rates", "notional_usd": 100_000_000, "entry_price": 3.25, "mark_price": 3.25}
        curve = {"asset_class": "curve", "notional_usd": 100_000_000, "entry_price": 25.0, "mark_price": 25.0}
        rv = {"asset_class": "rates_rv", "notional_usd": 100_000_000, "entry_price": 35.0, "mark_price": 35.0}
        self.assertEqual(position_risk_capital(spot), 1_000_000.0)
        self.assertEqual(position_risk_capital(rates), 1_000_000.0)
        self.assertEqual(position_risk_capital(curve), 1_000_000.0)
        self.assertEqual(position_risk_capital(rv), 1_000_000.0)

    def test_rates_shock_is_100bp_not_percent_of_rate_level(self) -> None:
        rates = {
            "side": "long",
            "asset_class": "rates",
            "notional_usd": 100_000_000,
            "entry_price": 5.00,
            "mark_price": 5.00,
        }
        self.assertEqual(RATE_SHOCK_PERCENTAGE_POINTS, 1.0)
        self.assertEqual(position_risk_capital(rates), 1_000_000.0)
        percent_of_level = round(100_000_000 * 0.05 * 0.01, 2)
        self.assertEqual(percent_of_level, 50_000.0)
        self.assertNotEqual(position_risk_capital(rates), percent_of_level)
        shocked = dict(rates)
        shocked["mark_price"] = 6.00  # +100bp in percentage-point marks
        pnl = position_pnl(shocked)
        self.assertEqual(pnl["unrealized_pnl_usd"], -1_000_000.0)
        self.assertEqual(abs(pnl["unrealized_pnl_usd"]), position_risk_capital(rates))

    def test_curve_100bp_matches_trusted_pnl_convention(self) -> None:
        curve = {
            "side": "long",
            "asset_class": "curve",
            "notional_usd": 100_000_000,
            "entry_price": 25.0,
            "mark_price": 125.0,  # +100bp in spread marks
        }
        pnl = position_pnl(curve)
        self.assertEqual(pnl["unrealized_pnl_usd"], -1_000_000.0)
        self.assertEqual(position_risk_capital(curve), 1_000_000.0)

    def test_book_risk_capital_is_gross_across_positions(self) -> None:
        book = {
            "positions": [
                {"position_id": "fx", "asset_class": "spot_fx", "notional_usd": 250_000_000},
                {"position_id": "rates", "asset_class": "rates", "notional_usd": 750_000_000},
            ]
        }
        metrics = book_risk_capital(book)
        self.assertEqual(metrics["risk_capital_usd"], 10_000_000.0)
        self.assertEqual(metrics["risk_capital_method"], RISK_CAPITAL_METHOD)
        self.assertEqual(metrics["risk_capital_status"], "ok")

    def test_options_fail_closed_without_deterministic_shocked_mtm(self) -> None:
        option = {"position_id": "opt", "asset_class": "options", "notional_usd": 100_000_000}
        self.assertIsNone(position_risk_capital(option))
        option["shock_1pct_pnl_usd"] = -375_000
        self.assertEqual(position_risk_capital(option), 375_000.0)


if __name__ == "__main__":
    unittest.main()
