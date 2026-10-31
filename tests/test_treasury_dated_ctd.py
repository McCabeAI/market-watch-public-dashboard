"""Undated TU/FV/TY resolution and refresh_treasury_risk."""

from __future__ import annotations

import copy
import unittest

from scripts.rates import treasury_futures as tf


def _ctd_row(
    *,
    product: str,
    expiry: str,
    futures_price: float = 100.0,
    conversion_factor: float = 0.9,
    mod_duration: float = 5.0,
    dirty: float = 98.0,
    price_source: str = "test_px",
    **extra,
):
    row = {
        "product": product,
        "expiry": expiry,
        "futures_price": futures_price,
        "price_source": price_source,
        "price_as_of": "2026-10-23",
        "conversion_factor": conversion_factor,
        "conversion_factor_source": "test_cf",
        "conversion_factor_as_of": "2026-10-23",
        "ctd_modified_duration": mod_duration,
        "ctd_dirty_price_per_100": dirty,
        "ctd_source": "test_ctd",
        "ctd_as_of": "2026-10-23",
    }
    row.update(extra)
    return row


def _tu_market(*contract_rows, **block_extra):
    contracts = {}
    for cid, row in contract_rows:
        contracts[cid] = row
    block = {"status": "ok", "source": "test", "contracts": contracts}
    block.update(block_extra)
    return {"treasury_futures": block}


class ResolveUndatedTests(unittest.TestCase):
    def test_bare_tu_single_sourced_contract(self) -> None:
        market = _tu_market(
            ("TU_2027-03", _ctd_row(product="TU", expiry="2027-03", futures_price=103.0)),
        )
        verdict = tf.assess_treasury("TU", {"type": "treasury_future"}, market)
        assert verdict is not None
        self.assertEqual(verdict["status"], "ok")
        self.assertEqual(verdict["instrument"], "TU_2027-03")
        self.assertEqual(verdict["expiry"], "2027-03")
        self.assertEqual(verdict["resolved_from"], "TU")
        self.assertTrue(verdict["bookable"])

    def test_bare_tu_zero_contracts_fails_visibly(self) -> None:
        market = {"treasury_futures": {"status": "ok", "source": "t", "contracts": {}}}
        verdict = tf.assess_treasury("TU", {"type": "treasury_future"}, market)
        assert verdict is not None
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        self.assertIn("treasury_futures.contracts.TU", verdict["missing_inputs"])
        with self.assertRaises(ValueError) as ctx:
            tf.build_treasury_position(
                "TU",
                side="long",
                notional_usd=200_000,
                market_state=market,
            )
        self.assertIn("Preflight requires", str(ctx.exception))

    def test_two_sourced_tu_ambiguous(self) -> None:
        market = _tu_market(
            ("TU_2027-03", _ctd_row(product="TU", expiry="2027-03")),
            ("TU_2027-06", _ctd_row(product="TU", expiry="2027-06", futures_price=102.0)),
        )
        verdict = tf.assess_treasury("TU", {"type": "treasury_future"}, market)
        assert verdict is not None
        self.assertEqual(verdict["status"], "missing_input")
        self.assertIn("TU_2027-03", verdict["reason"])
        self.assertIn("TU_2027-06", verdict["reason"])

    def test_front_map_selects_contract(self) -> None:
        market = _tu_market(
            ("TU_2027-03", _ctd_row(product="TU", expiry="2027-03")),
            ("TU_2027-06", _ctd_row(product="TU", expiry="2027-06", futures_price=102.0)),
            front={"TU": "TU_2027-06"},
        )
        verdict = tf.assess_treasury("TU", {"type": "treasury_future"}, market)
        assert verdict is not None
        self.assertEqual(verdict["instrument"], "TU_2027-06")
        self.assertEqual(verdict["expiry"], "2027-06")

    def test_fv_single_contract_resolution(self) -> None:
        market = _tu_market(
            ("FV_2027-03", _ctd_row(product="FV", expiry="2027-03", futures_price=108.0)),
        )
        pos = tf.build_treasury_position(
            "FV",
            side="long",
            notional_usd=100_000,
            market_state=market,
        )
        self.assertEqual(pos["instrument"], "FV_2027-03")

    def test_ty_ambiguous_without_front(self) -> None:
        market = _tu_market(
            ("TY_2027-03", _ctd_row(product="TY", expiry="2027-03")),
            ("TY_2027-06", _ctd_row(product="TY", expiry="2027-06", futures_price=111.0)),
        )
        with self.assertRaises(ValueError) as ctx:
            tf.build_treasury_position(
                "TY",
                side="long",
                notional_usd=100_000,
                market_state=market,
            )
        self.assertIn("Ambiguous", str(ctx.exception))


class RefreshTreasuryRiskTests(unittest.TestCase):
    def _tu_open_market(self) -> dict:
        return _tu_market(
            (
                "TU_2027-03",
                _ctd_row(
                    product="TU",
                    expiry="2027-03",
                    futures_price=103.0,
                    conversion_factor=0.88,
                    mod_duration=4.0,
                    dirty=99.0,
                ),
            ),
        )

    def test_refresh_updates_dv01_not_entry_or_pnl(self) -> None:
        market = self._tu_open_market()
        pos = tf.build_treasury_position(
            "TU",
            side="long",
            notional_usd=200_000,
            market_state=market,
        )
        entry = pos["entry_price"]
        mark = pos["mark_price"]
        dv01_before = pos["futures_dv01_per_contract"]
        pnl_before = tf.treasury_pnl_usd(pos, mark_price=mark)

        market2 = copy.deepcopy(market)
        row = market2["treasury_futures"]["contracts"]["TU_2027-03"]
        row["ctd_modified_duration"] = 5.5
        row["conversion_factor"] = 0.90
        row["ctd_as_of"] = "2026-10-24"

        tf.refresh_treasury_risk(pos, market2)
        self.assertEqual(pos["entry_price"], entry)
        self.assertNotEqual(pos["futures_dv01_per_contract"], dv01_before)
        self.assertEqual(pos["risk_status"], "ok")
        pnl_after = tf.treasury_pnl_usd(pos, mark_price=mark)
        self.assertAlmostEqual(pnl_after, pnl_before or 0.0, places=9)

    def test_one_tick_pnl_after_refresh(self) -> None:
        market = self._tu_open_market()
        pos = tf.build_treasury_position(
            "TU_2027-03",
            side="long",
            notional_usd=200_000,
            market_state=market,
        )
        tf.refresh_treasury_risk(pos, market)
        tick = float(pos["tick_size_points"])
        pnl = tf.treasury_pnl_usd(pos, mark_price=float(pos["entry_price"]) + tick)
        self.assertAlmostEqual(pnl, 7.8125, places=9)

    def test_missing_ctd_on_refresh_nulls_dv01(self) -> None:
        market = self._tu_open_market()
        pos = tf.build_treasury_position(
            "TU_2027-03",
            side="long",
            notional_usd=200_000,
            market_state=market,
        )
        entry_dv01 = pos["futures_dv01_per_contract"]
        self.assertIsNotNone(entry_dv01)

        market2 = copy.deepcopy(market)
        row = market2["treasury_futures"]["contracts"]["TU_2027-03"]
        del row["ctd_modified_duration"]
        del row["ctd_dirty_price_per_100"]

        tf.refresh_treasury_risk(pos, market2)
        self.assertIsNone(pos["futures_dv01_per_contract"])
        self.assertIsNone(pos["dv01_usd"])
        self.assertEqual(pos["risk_status"], "unavailable")
        self.assertIn("ctd_modified_duration", pos["risk_unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
