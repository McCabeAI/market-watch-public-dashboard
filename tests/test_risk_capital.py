from __future__ import annotations

import unittest

from scripts.risk_capital import (
    RISK_CAPITAL_METHOD,
    book_risk_capital,
    position_risk_capital,
)


class RiskCapitalTests(unittest.TestCase):
    def test_equal_standard_shock_pnl_is_equal_risk_capital(self) -> None:
        spot = {"asset_class": "spot_fx", "notional_usd": 100_000_000, "entry_price": 1.40, "mark_price": 1.40}
        rates = {"asset_class": "rates", "notional_usd": 100_000_000, "entry_price": 3.25, "mark_price": 3.25}
        curve = {"asset_class": "rates_rv", "notional_usd": 100_000_000, "entry_price": 35.0, "mark_price": 35.0}
        self.assertEqual(position_risk_capital(spot), 1_000_000.0)
        self.assertEqual(position_risk_capital(rates), 1_000_000.0)
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
