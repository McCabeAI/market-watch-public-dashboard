"""Cross-module integration after rates repair worktrees (catalog, OIS dated, treasury refresh)."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import apply_action, empty_seat
from scripts.overnight.paper_marks import refresh_positions
from scripts.rates.executable_catalog import (
    build_executable_catalog,
    select_two_year,
    two_year_choices,
)
from scripts.rates import treasury_futures as tf
from scripts.rates.valuation import value_position
from scripts.trader_room.rates_scan import with_tenor_scan
from tests.test_rates_engine import MARKET

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 10, 24, 12, 0, tzinfo=NY)


def _ctd_row(**kwargs):
    row = {
        "product": "TU",
        "expiry": "2027-03",
        "futures_price": 103.0,
        "price_source": "test_px",
        "price_as_of": "2026-10-23",
        "conversion_factor": 0.88,
        "conversion_factor_source": "test_cf",
        "conversion_factor_as_of": "2026-10-23",
        "ctd_modified_duration": 4.0,
        "ctd_dirty_price_per_100": 99.0,
        "ctd_source": "test_ctd",
        "ctd_as_of": "2026-10-23",
    }
    row.update(kwargs)
    return row


def _tu_integration_market() -> dict:
    return {
        **MARKET,
        "treasury_futures": {
            "status": "ok",
            "source": "integration_test",
            "contracts": {"TU_2027-03": _ctd_row()},
        },
    }


def _families(market: dict) -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": "fresh", "data": market},
    }


def _memo(instrument: str) -> dict:
    return with_tenor_scan(
        {
            "rates_candidate": {"instrument": instrument, "asset_class": "rates", "rationale": "repair integration"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alternative"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Fixture",
        },
        selected_bucket="two_year",
    )


def _ois_block(**instruments: dict) -> dict:
    return {
        "status": "ok",
        "curve_kind": "sofr_ois",
        "source": "test_fixture",
        "as_of": "2026-10-24",
        "day_count": "ACT/360",
        "instruments": instruments,
    }


def _ois_market(**overrides) -> dict:
    base = {
        "generated_at": "2026-10-24T15:00:00Z",
        "fx": {"status": "ok", "pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-10-24", "status": "ok"}}},
        "tradable_rate_curves": {"status": "ok", "curves": {}},
    }
    base.update(overrides)
    return base


class RatesRepairIntegrationTests(unittest.TestCase):
    def test_treasury_catalog_refresh_risk_and_tick_pnl(self) -> None:
        market = _tu_integration_market()
        choices = two_year_choices(market)
        tu_choice = next(c for c in choices if c.get("family") == "treasury_future")
        self.assertEqual(tu_choice["instrument"], "TU_2027-03")
        self.assertEqual(tu_choice.get("expiry"), "2027-03")
        self.assertNotEqual(tu_choice["instrument"], "TU")

        picked = select_two_year(market, family="treasury_future")
        self.assertEqual(picked["instrument"], "TU_2027-03")
        self.assertEqual(picked.get("expiry"), "2027-03")

        catalog = build_executable_catalog(market)
        tu_rows = [r for r in catalog["rows"] if r.get("family") == "treasury_future"]
        self.assertEqual(len(tu_rows), 1)
        self.assertEqual(tu_rows[0]["instrument"], "TU_2027-03")
        self.assertEqual(tu_rows[0].get("expiry"), "2027-03")

        book = empty_seat("trend-follower")
        apply_action(
            book,
            {
                "action": "OPEN",
                "instrument": "TU",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 200_000,
                "expected_mark_direction": "higher",
                "paper_expression": {"type": "treasury_future"},
                "expression_memo": _memo("TU"),
            },
            families=_families(market),
            run_id="repair-int",
            when=AS_OF,
            market_state=market,
        )
        pos = book["positions"][0]
        self.assertEqual(pos["instrument"], "TU_2027-03")
        entry = pos["entry_price"]
        mark = pos["mark_price"]
        dv01_before = pos["futures_dv01_per_contract"]
        pnl_before = tf.treasury_pnl_usd(pos, mark_price=mark)
        valued_before = value_position(pos)

        ctd_only = copy.deepcopy(market)
        row = ctd_only["treasury_futures"]["contracts"]["TU_2027-03"]
        row["ctd_modified_duration"] = 5.5
        row["conversion_factor"] = 0.90
        row["ctd_as_of"] = "2026-10-24"
        refresh_positions(book["positions"], ctd_only)
        self.assertEqual(pos["entry_price"], entry)
        self.assertEqual(pos["mark_price"], mark)
        self.assertNotEqual(pos["futures_dv01_per_contract"], dv01_before)
        pnl_after_ctd = tf.treasury_pnl_usd(pos, mark_price=pos["mark_price"])
        self.assertAlmostEqual(pnl_after_ctd or 0.0, pnl_before or 0.0, places=9)
        valued_after_ctd = value_position(pos)
        self.assertAlmostEqual(
            valued_after_ctd["unrealized_pnl_usd"] or 0.0,
            valued_before["unrealized_pnl_usd"] or 0.0,
            places=9,
        )

        tick = float(pos["tick_size_points"])
        contracts = int(pos["contracts"])
        tick_move = copy.deepcopy(ctd_only)
        tick_move["treasury_futures"]["contracts"]["TU_2027-03"]["futures_price"] = float(mark) + tick
        refresh_positions(book["positions"], tick_move)
        valued_tick = value_position(pos)
        self.assertAlmostEqual(valued_tick["unrealized_pnl_usd"] or 0.0, 7.8125 * contracts, places=2)

    def test_ois_dated_only_packet_and_rolling_without_dated(self) -> None:
        eff, mat = "2027-10-26", "2028-10-26"
        market = _ois_market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_1Y1Y={
                    "start_years": 1,
                    "tenor_years": 1,
                    "par_rate_percent": 3.70,
                    "annuity": 0.96,
                    "quote_type": "observed_par",
                    "source": "fixture_1y1y_open",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                    "effective_date": eff,
                    "maturity_date": mat,
                }
            )
        )
        expr = {"type": "usd_sofr_ois", "start_years": 1, "tenor_years": 1}
        book = empty_seat("trend-follower")
        apply_action(
            book,
            {
                "action": "OPEN",
                "instrument": "USD_SOFR_OIS_1Y1Y",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 5_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expr,
                "expression_memo": _memo("USD_SOFR_OIS_1Y1Y"),
            },
            families=_families(market),
            run_id="repair-int-ois",
            when=AS_OF,
            market_state=market,
        )
        pos = book["positions"][0]
        self.assertEqual(pos.get("effective_date"), eff)
        self.assertEqual(pos.get("maturity_date"), mat)

        dated_only = copy.deepcopy(market)
        dated_only["usd_sofr_ois"]["as_of"] = "2026-11-01"
        dated_only["usd_sofr_ois"]["instruments"] = {}
        dated_only["usd_sofr_ois"]["dated"] = {
            f"{eff}|{mat}": {
                "par_rate_percent": 3.62,
                "annuity": 0.87,
                "quote_type": "observed_par",
                "source": "dated_only_packet",
                "as_of": "2026-11-01",
                "curve_kind": "sofr_ois",
                "status": "ok",
            }
        }
        refresh_positions(book["positions"], dated_only)
        self.assertAlmostEqual(pos["mark_rate"], 3.62, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 5_000_000 * 0.87 * 0.0001, places=4)

        same_swap_later = copy.deepcopy(market)
        same_swap_later["usd_sofr_ois"]["as_of"] = "2026-11-02"
        same_swap_later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"] = {
            **same_swap_later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"],
            "par_rate_percent": 3.55,
            "annuity": 0.90,
            "as_of": "2026-11-02",
            "source": "same_fixed_maturity",
            "effective_date": eff,
            "maturity_date": mat,
        }
        same_swap_later["usd_sofr_ois"].pop("dated", None)
        refresh_positions(book["positions"], same_swap_later)
        self.assertAlmostEqual(pos["mark_rate"], 3.55, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 5_000_000 * 0.90 * 0.0001, places=4)
        self.assertEqual(pos.get("effective_date"), eff)
        self.assertEqual(pos.get("maturity_date"), mat)

        rolling_only = copy.deepcopy(market)
        rolling_only["usd_sofr_ois"]["as_of"] = "2026-11-03"
        rolled = {
            **rolling_only["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"],
            "par_rate_percent": 3.40,
            "as_of": "2026-11-03",
            "source": "rolling_cm",
        }
        rolled.pop("effective_date", None)
        rolled.pop("maturity_date", None)
        rolling_only["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"] = rolled
        rolling_only["usd_sofr_ois"].pop("dated", None)
        refresh_positions(book["positions"], rolling_only)
        self.assertEqual(pos.get("mark_status"), "unavailable")
        self.assertIsNone(pos.get("mark_rate"))
        valued = value_position(pos)
        self.assertTrue(valued.get("pnl_unavailable"))


if __name__ == "__main__":
    unittest.main()
