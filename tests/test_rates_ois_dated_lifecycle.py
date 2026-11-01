"""SOFR OIS open marks, ADD/REDUCE, and fixed effective/maturity lifecycle."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import apply_action, empty_seat
from scripts.overnight.paper_marks import refresh_positions
from scripts.rates.ois import ois_pnl_usd
from scripts.rates.valuation import value_position
from scripts.trader_room.rates_scan import with_tenor_scan

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 10, 24, 12, 0, tzinfo=NY)


def _ois_block(**instruments: dict) -> dict:
    return {
        "status": "ok",
        "curve_kind": "sofr_ois",
        "source": "test_fixture",
        "as_of": "2026-10-24",
        "day_count": "ACT/360",
        "instruments": instruments,
    }


def _market(**overrides) -> dict:
    base = {
        "generated_at": "2026-10-24T15:00:00Z",
        "fx": {"status": "ok", "pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-10-24", "status": "ok"}}},
        "tradable_rate_curves": {"status": "ok", "curves": {}},
    }
    base.update(overrides)
    return base


def _memo(instrument: str) -> dict:
    return with_tenor_scan(
        {
            "rates_candidate": {"instrument": instrument, "asset_class": "rates", "rationale": "ois dated fixture"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alternative"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Fixture",
        },
        selected_bucket="two_year",
    )


def _families(market: dict) -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": "fresh", "data": market},
    }


def _apply(book: dict, action: dict, market: dict) -> dict:
    return apply_action(
        book,
        action,
        families=_families(market),
        run_id="ois-dated",
        when=AS_OF,
        market_state=market,
    )


class OisDatedLifecycleTests(unittest.TestCase):
    def test_spot_2y_open_add_blend_entry_and_dv01(self) -> None:
        market = _market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.00,
                    "annuity": 1.95,
                    "quote_type": "observed_par",
                    "source": "fixture_2y",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        )
        expr = {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2}
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "USD_SOFR_OIS_2Y",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expr,
                "expression_memo": _memo("USD_SOFR_OIS_2Y"),
            },
            market,
        )
        pos = book["positions"][0]
        self.assertAlmostEqual(pos["entry_rate"], 4.00, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 1950.0, places=6)

        moved = deepcopy(market)
        moved["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_2Y"]["par_rate_percent"] = 3.98
        refresh_positions(book["positions"], moved)
        self.assertAlmostEqual(pos["mark_rate"], 3.98, places=8)

        _apply(
            book,
            {
                "action": "ADD",
                "position_id": pos["position_id"],
                "notional_usd": 5_000_000,
                "expression_memo": _memo("USD_SOFR_OIS_2Y"),
            },
            moved,
        )
        self.assertAlmostEqual(pos["notional_usd"], 15_000_000, places=2)
        expected_entry = (4.00 * 10_000_000 + 3.98 * 5_000_000) / 15_000_000
        self.assertAlmostEqual(pos["entry_rate"], expected_entry, places=8)
        self.assertAlmostEqual(pos["entry_price"], expected_entry, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 15_000_000 * 1.95 * 0.0001, places=4)
        add_row = book["history"][-1]
        self.assertAlmostEqual(add_row.get("realized_pnl_usd") or 0.0, 0.0, places=2)

    def test_partial_reduce_realizes_closed_slice_only(self) -> None:
        market = _market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.00,
                    "annuity": 1.95,
                    "quote_type": "observed_par",
                    "source": "fixture_2y",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        )
        expr = {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2}
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "USD_SOFR_OIS_2Y",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expr,
                "expression_memo": _memo("USD_SOFR_OIS_2Y"),
            },
            market,
        )
        pos = book["positions"][0]
        moved = deepcopy(market)
        moved["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_2Y"]["par_rate_percent"] = 3.99
        refresh_positions(book["positions"], moved)

        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": pos["position_id"],
                "notional_usd": 4_000_000,
                "expression_memo": _memo("USD_SOFR_OIS_2Y"),
            },
            moved,
        )
        self.assertAlmostEqual(pos["notional_usd"], 6_000_000, places=2)
        self.assertAlmostEqual(pos["entry_rate"], 4.00, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 6_000_000 * 1.95 * 0.0001, places=4)
        reduce_row = book["history"][-1]
        closed_dv01 = 4_000_000 * 1.95 * 0.0001
        expected_realized = -1.0 * closed_dv01 * (3.99 - 4.00) * 100.0
        self.assertAlmostEqual(reduce_row.get("realized_pnl_usd") or 0.0, expected_realized, places=0)

    def test_dated_1y1y_uses_dated_row_not_rolling(self) -> None:
        eff, mat = "2027-10-26", "2028-10-26"
        market = _market(
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
        _apply(
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
            market,
        )
        pos = book["positions"][0]
        self.assertEqual(pos.get("effective_date"), eff)
        self.assertEqual(pos.get("maturity_date"), mat)

        later = deepcopy(market)
        later["usd_sofr_ois"]["as_of"] = "2026-11-01"
        later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"] = {
            **later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"],
            "par_rate_percent": 3.50,
            "annuity": 0.96,
            "as_of": "2026-11-01",
            "source": "rolling_cm",
        }
        later["usd_sofr_ois"]["dated"] = {
            f"{eff}|{mat}": {
                "par_rate_percent": 3.65,
                "annuity": 0.88,
                "quote_type": "observed_par",
                "source": "dated_fix",
                "as_of": "2026-11-01",
                "curve_kind": "sofr_ois",
                "status": "ok",
            }
        }
        refresh_positions(book["positions"], later)
        self.assertAlmostEqual(pos["mark_rate"], 3.65, places=8)
        self.assertAlmostEqual(pos["dv01_usd"], 5_000_000 * 0.88 * 0.0001, places=4)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, ois_pnl_usd(pos) or 0.0, places=2)
        rolling_pnl = -1.0 * (5_000_000 * 0.96 * 0.0001) * (3.50 - 3.70) * 100.0
        self.assertNotAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, rolling_pnl, places=0)

    def test_dated_position_refuses_rolling_when_no_dated_row(self) -> None:
        eff, mat = "2027-10-26", "2028-10-26"
        market = _market(
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
        _apply(
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
            market,
        )
        pos = book["positions"][0]
        later = deepcopy(market)
        later["usd_sofr_ois"]["as_of"] = "2026-11-01"
        rolled = {
            **later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"],
            "par_rate_percent": 3.50,
            "as_of": "2026-11-01",
        }
        rolled.pop("effective_date", None)
        rolled.pop("maturity_date", None)
        later["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"] = rolled
        refresh_positions(book["positions"], later)
        self.assertEqual(pos.get("mark_status"), "unavailable")
        self.assertIsNone(pos.get("mark_rate"))
        valued = value_position(pos)
        self.assertTrue(valued.get("pnl_unavailable"))

    def test_close_on_dated_mark_realizes_dated_pnl(self) -> None:
        eff, mat = "2027-10-26", "2028-10-26"
        market = _market(
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
        _apply(
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
            market,
        )
        pos = book["positions"][0]
        later = deepcopy(market)
        later["usd_sofr_ois"]["as_of"] = "2026-11-01"
        later["usd_sofr_ois"]["dated"] = {
            f"{eff}|{mat}": {
                "par_rate_percent": 3.71,
                "annuity": 0.88,
                "quote_type": "observed_par",
                "source": "dated_fix",
                "as_of": "2026-11-01",
                "curve_kind": "sofr_ois",
                "status": "ok",
            }
        }
        refresh_positions(book["positions"], later)
        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": pos["position_id"],
                "notional_usd": 5_000_000,
                "expression_memo": _memo("USD_SOFR_OIS_1Y1Y"),
            },
            later,
        )
        close_row = book["history"][-1]
        expected = ois_pnl_usd(
            {
                "side": "long",
                "entry_rate": 3.70,
                "mark_rate": 3.71,
                "dv01_usd": 5_000_000 * 0.88 * 0.0001,
            }
        )
        self.assertAlmostEqual(close_row.get("realized_pnl_usd") or 0.0, expected or 0.0, places=0)


if __name__ == "__main__":
    unittest.main()
