"""ASX 90 Day Bank Bill (IR / BBSW) valuation and structure P&L."""

from __future__ import annotations

import unittest
from decimal import Decimal

from scripts.rates.bbsw_valuation import (
    contract_value_aud,
    contract_value_aud_unrounded,
    ir_pnl_aud,
    ir_pnl_usd,
    variable_bp_value_aud,
    yield_from_index,
)
from scripts.rates.contract_economics import (
    IB_PUBLISHED_BPV_AUD,
    IR,
    dv01_per_contract,
    parse_contract_id,
)
from scripts.rates.structures import leg_pnl_for_contracts


class BbswValuationTests(unittest.TestCase):
    def test_anchor_price_at_five_percent(self):
        self.assertEqual(contract_value_aud(Decimal("5.00")), Decimal("987821.38"))
        self.assertEqual(contract_value_aud("5.00"), Decimal("987821.38"))

    def test_one_bp_symmetry_after_rounding(self):
        row = variable_bp_value_aud("5.00")
        self.assertEqual(row["long_pnl_yield_down_1bp_aud"], Decimal("24.06"))
        self.assertEqual(abs(row["long_pnl_yield_up_1bp_aud"]), Decimal("24.06"))
        down_unrounded = contract_value_aud_unrounded(Decimal("4.99")) - contract_value_aud_unrounded(
            Decimal("5.00")
        )
        self.assertNotEqual(down_unrounded, Decimal("24.06"))
        self.assertNotEqual(row["analytic_dp_per_bp_aud"], Decimal("24.06"))

    def test_five_bp_long_pnl_convexity(self):
        pnl = ir_pnl_aud("5.00", "4.95", 1, "long")
        self.assertEqual(pnl, Decimal("120.32"))
        self.assertNotEqual(pnl, Decimal("5") * Decimal("24.06"))

    def test_short_gains_on_yield_rise(self):
        pnl = ir_pnl_aud("5.00", "5.05", 1, "short")
        self.assertGreater(pnl, Decimal("0"))

    def test_usd_conversion(self):
        usd = ir_pnl_usd("5.00", "4.95", 1, "long", Decimal("0.65"))
        self.assertEqual(usd, Decimal("78.21"))

    def test_yield_from_three_decimal_index(self):
        self.assertEqual(yield_from_index(Decimal("95.050")), Decimal("4.950"))
        self.assertEqual(yield_from_index("95.050"), Decimal("4.950"))

    def test_parse_contract_ids(self):
        for instr in ("IRZ26", "IRZ6", "BBSW_2026-12", "BBSW-2026-12", "IR_2026-12", "IR-2026-12"):
            parsed = parse_contract_id(instr)
            self.assertIsNotNone(parsed, instr)
            self.assertEqual(parsed.spec.curve_id, "BBSW")
            self.assertEqual(parsed.alias, "BBSW_2026-12")
        march = parse_contract_id("IR_2027-03")
        self.assertEqual(march.spec.curve_id, "BBSW")
        self.assertEqual(march.alias, "BBSW_2027-03")
        self.assertIsNone(parse_contract_id("IRZ226"))
        ib = parse_contract_id("IBZ6")
        self.assertEqual(ib.spec.curve_id, "AONIA")
        aonia = parse_contract_id("AONIA_2026-12")
        self.assertEqual(aonia.spec.curve_id, "AONIA")

    def test_dv01_per_contract(self):
        self.assertIsNone(dv01_per_contract(IR))
        self.assertAlmostEqual(dv01_per_contract(IR, implied_rate=5.0), 24.06)
        from scripts.rates.contract_economics import CRA, SR3

        self.assertEqual(dv01_per_contract(SR3), 25.0)
        self.assertEqual(dv01_per_contract(CRA), 25.0)
        from scripts.rates.contract_economics import IB

        self.assertEqual(dv01_per_contract(IB), IB_PUBLISHED_BPV_AUD)

    def test_leg_pnl_ir_usd(self):
        leg = {
            "product_code": "IR",
            "curve_id": "BBSW",
            "side": "long",
            "entry_rate": 5.0,
            "mark_rate": 4.95,
            "mark_fx_usd_per_unit": 0.65,
            "mark_fx_status": "ok",
            "mark_status": "ok",
            "dv01_per_contract_local": 24.06,
        }
        pnl = leg_pnl_for_contracts(leg, 1)
        self.assertAlmostEqual(pnl, 120.32 * 0.65, places=2)

    def test_leg_pnl_sr3_linear_regression(self):
        leg = {
            "product_code": "SR3",
            "curve_id": "SOFR",
            "side": "long",
            "entry_rate": 4.0,
            "mark_rate": 3.99,
            "mark_fx_usd_per_unit": 1.0,
            "mark_fx_status": "ok",
            "mark_status": "ok",
            "dv01_per_contract_local": 25.0,
        }
        pnl = leg_pnl_for_contracts(leg, 2)
        self.assertAlmostEqual(pnl, 50.0, places=6)

    def test_ir_stale_mark_returns_none(self):
        leg = {
            "product_code": "IR",
            "curve_id": "BBSW",
            "side": "long",
            "entry_rate": 5.0,
            "mark_rate": 4.95,
            "mark_fx_usd_per_unit": 0.65,
            "mark_fx_status": "ok",
            "mark_status": "stale",
            "dv01_per_contract_local": 24.06,
        }
        self.assertIsNone(leg_pnl_for_contracts(leg, 1))

    def test_pnl_matches_price_difference_both_directions(self):
        for entry, mark, side in (
            ("5.00", "4.95", "long"),
            ("5.00", "5.05", "long"),
            ("5.00", "5.05", "short"),
        ):
            lots = 3
            expected = (contract_value_aud(mark) - contract_value_aud(entry)) * lots
            if side == "short":
                expected = -expected
            self.assertEqual(ir_pnl_aud(entry, mark, lots, side), expected)


if __name__ == "__main__":
    unittest.main()
