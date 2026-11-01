"""Treasury note futures economics, CTD DV01, P&L, and roll quotes."""

from __future__ import annotations

import unittest

from scripts.rates import treasury_futures as tf


def _ty_market(**overrides):
    base = {
        "status": "ok",
        "source": "test",
        "contracts": {
            "TY_2027-03": {
                "product": "TY",
                "expiry": "2027-03",
                "futures_price": 112.0,
                "price_source": "test_settle",
                "price_as_of": "2026-10-23",
                "conversion_factor": 0.8500,
                "conversion_factor_source": "test_cf",
                "conversion_factor_as_of": "2026-10-23",
                "ctd_modified_duration": 6.0,
                "ctd_dirty_price_per_100": 99.0,
                "ctd_source": "test_ctd",
                "ctd_as_of": "2026-10-23",
            },
        },
    }
    base["contracts"]["TY_2027-03"].update(overrides)
    return {"treasury_futures": base}


class ContractSpecTests(unittest.TestCase):
    def test_tu_fv_ty_static_economics(self) -> None:
        tu = tf.contract_spec("TU")
        self.assertEqual(tu["face_notional_usd"], 200_000)
        self.assertEqual(tu["point_value_usd"], 2_000)
        self.assertEqual(tu["tick_value_usd"], 7.8125)

        fv = tf.contract_spec("FV")
        self.assertEqual(fv["face_notional_usd"], 100_000)
        self.assertEqual(fv["tick_value_usd"], 7.8125)

        ty = tf.contract_spec("TY")
        self.assertEqual(ty["tick_value_usd"], 15.625)


class ParseTests(unittest.TestCase):
    def test_invalid_delivery_month(self) -> None:
        parsed = tf.parse_treasury_id("TU_2027-04")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["status"], "unsupported")
        self.assertEqual(parsed["reason"], "invalid delivery month")

    def test_coded_invalid_month_fails_after_parse(self) -> None:
        parsed = tf.parse_treasury_id("ZTJ7")
        self.assertEqual(parsed["status"], "unsupported")
        self.assertEqual(parsed["reason"], "invalid delivery month")
        self.assertEqual(parsed["month"], 4)


class PnlTests(unittest.TestCase):
    def test_one_tick_long_pnl_equals_tick_value(self) -> None:
        cases = [
            ("TU", 2_000.0, 0.125 / 32.0, 7.8125),
            ("FV", 1_000.0, 0.25 / 32.0, 7.8125),
            ("TY", 1_000.0, 0.5 / 32.0, 15.625),
        ]
        for product, point_value, tick_pts, tick_usd in cases:
            with self.subTest(product=product):
                entry = 100.0
                pos = {
                    "side": "long",
                    "contracts": 1,
                    "entry_price": entry,
                    "point_value_usd": point_value,
                }
                pnl = tf.treasury_pnl_usd(pos, mark_price=entry + tick_pts)
                self.assertAlmostEqual(pnl, tick_usd, places=9)


class Dv01Tests(unittest.TestCase):
    def test_ty_ctd_futures_dv01_hand_calc(self) -> None:
        ctd_per_100 = 6.0 * 99.0 * 0.0001
        self.assertAlmostEqual(ctd_per_100, 0.0594, places=12)
        futures_dv01 = tf.futures_dv01_per_contract(
            "TY",
            conversion_factor=0.8500,
            ctd_dv01_per_100=ctd_per_100,
        )
        expected = 0.0594 * (100_000 / 100) / 0.8500
        self.assertAlmostEqual(futures_dv01, expected, places=6)
        self.assertAlmostEqual(futures_dv01, 69.88235294117647, places=6)

        market = _ty_market()
        pos = tf.build_treasury_position(
            "TY_2027-03",
            side="long",
            notional_usd=100_000,
            market_state=market,
        )
        self.assertAlmostEqual(pos["futures_dv01_per_contract"], expected, places=6)
        shock = tf.treasury_shock_risk_usd(pos)
        self.assertAlmostEqual(shock, pos["contracts"] * expected * 100, places=4)

    def test_price_without_cf_or_ctd_not_bookable(self) -> None:
        market = {
            "treasury_futures": {
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TY_2027-03": {
                        "product": "TY",
                        "expiry": "2027-03",
                        "futures_price": 112.0,
                        "price_source": "test",
                        "price_as_of": "2026-10-23",
                    },
                },
            },
        }
        verdict = tf.assess_treasury(
            "TY_2027-03",
            {"type": "treasury_future"},
            market,
        )
        assert verdict is not None
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        self.assertEqual(verdict["mark_status"], "ok")
        self.assertIsNone(verdict["futures_dv01_per_contract"])
        self.assertNotIn("ctd_modified_duration", verdict)
        self.assertNotIn("modified_duration", verdict)
        for key in verdict:
            self.assertNotIn("duration", key.lower())
        with self.assertRaises(ValueError):
            tf.build_treasury_position(
                "TY_2027-03",
                side="long",
                notional_usd=100_000,
                market_state=market,
            )

    def test_missing_price_path(self) -> None:
        market = {"treasury_futures": {"status": "ok", "source": "t", "contracts": {}}}
        verdict = tf.assess_treasury("TY_2027-03", {"type": "treasury_future"}, market)
        assert verdict is not None
        self.assertIn("treasury_futures.contracts.TY_2027-03.futures_price", verdict["missing_inputs"])


class RollTests(unittest.TestCase):
    def test_roll_with_both_prices(self) -> None:
        market = {
            "treasury_futures": {
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TY_2027-03": {
                        "futures_price": 112.0,
                        "price_source": "a",
                        "price_as_of": "d1",
                    },
                    "TY_2027-06": {
                        "futures_price": 111.5,
                        "price_source": "b",
                        "price_as_of": "d2",
                    },
                },
            },
        }
        roll = tf.roll_quote(market, "TY_2027-03", "TY_2027-06")
        self.assertEqual(roll["status"], "ok")
        self.assertAlmostEqual(roll["roll_points"], -0.5, places=9)

    def test_roll_missing_back_price(self) -> None:
        market = {
            "treasury_futures": {
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TY_2027-03": {
                        "futures_price": 112.0,
                        "price_source": "a",
                        "price_as_of": "d1",
                    },
                },
            },
        }
        roll = tf.roll_quote(market, "TY_2027-03", "TY_2027-06")
        self.assertEqual(roll["status"], "missing_input")
        self.assertIn("treasury_futures.contracts.TY_2027-06.futures_price", roll["missing_inputs"])
        self.assertNotIn("back_price", roll)


class AssessSubstitutionTests(unittest.TestCase):
    def test_usd_sofr_ois_returns_none(self) -> None:
        self.assertIsNone(
            tf.assess_treasury(
                "SOFR_2027-03",
                {"type": "usd_sofr_ois"},
                {},
            )
        )


if __name__ == "__main__":
    unittest.main()
