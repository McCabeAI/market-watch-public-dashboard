"""End-to-end booking, marks, and lifecycle for executable rates catalog families."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import apply_action, empty_seat
from scripts.overnight.paper_marks import refresh_positions
from scripts.rates.executable_catalog import assess_expression, select_two_year
from scripts.rates.strips import STRIP_TYPE
from scripts.rates.valuation import shock_risk_usd, value_position
from scripts.trader_room.rates_scan import with_tenor_scan

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 10, 24, 12, 0, tzinfo=NY)


def _curve(rows: list[tuple[str, float]]) -> dict:
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-24"} for expiry, rate in rows],
    }


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
        "fx": {
            "status": "ok",
            "pairs": {
                "USDCAD": {"spot": 1.36, "as_of": "2026-10-24", "status": "ok"},
                "AUDUSD": {"spot": 0.50, "as_of": "2026-10-24", "status": "ok"},
            },
        },
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "SOFR": _curve(
                    [
                        ("2027-03", 4.00),
                        ("2027-06", 4.00),
                        ("2027-09", 4.00),
                        ("2027-12", 4.00),
                    ]
                ),
                "CORRA": _curve([("2026-12", 2.720), ("2027-03", 2.995), ("2027-06", 3.195)]),
            },
        },
    }
    base.update(overrides)
    return base


def _families(market: dict) -> dict:
    return {
        "macro_hard": {"status": "fresh"},
        "news": {"status": "fresh"},
        "central_bank_research": {"status": "fresh"},
        "market_state": {"status": "fresh", "data": market},
    }


def _memo(instrument: str, asset: str, bucket: str) -> dict:
    return with_tenor_scan(
        {
            "rates_candidate": {"instrument": instrument, "asset_class": asset, "rationale": "executable lifecycle fixture"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alternative"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Fixture chooses the expression; the test checks booking and P&L.",
        },
        selected_bucket=bucket,
    )


def _shift_sofr_strip(market: dict, rate: float) -> dict:
    out = deepcopy(market)
    for row in out["tradable_rate_curves"]["curves"]["SOFR"]["contracts"]:
        row["implied_rate"] = rate
    return out


def _shift_corra(market: dict, expiry: str, rate: float) -> dict:
    out = deepcopy(market)
    for row in out["tradable_rate_curves"]["curves"]["CORRA"]["contracts"]:
        if row["expiry"] == expiry:
            row["implied_rate"] = rate
    return out


def _apply(book: dict, action: dict, market: dict, *, run_id: str = "exec-life") -> dict:
    return apply_action(book, action, families=_families(market), run_id=run_id, when=AS_OF, market_state=market)


def _assert_blocked_catalog(case: unittest.TestCase, book: dict, verdict: dict) -> None:
    reason = str(verdict["reason"])
    case.assertEqual(book["history"][-1]["result"], "blocked_admission")
    case.assertTrue(
        any(reason in alert for alert in book["alerts"]),
        msg=f"expected catalog reason {reason!r} in alerts {book['alerts']!r}",
    )


class ExecutableLifecycleTests(unittest.TestCase):
    STRIP_EXPR = {
        "type": STRIP_TYPE,
        "curve_id": "SOFR",
        "expiries": ["2027-03", "2027-06", "2027-09", "2027-12"],
    }

    def test_sofr_strip_book_mark_close(self) -> None:
        market = _market()
        verdict = assess_expression(
            "SOFR_STRIP",
            expression=self.STRIP_EXPR,
            asset_class="rates",
            market_state=market,
            notional_usd=4_000_000,
        )
        self.assertTrue(verdict["bookable"])
        self.assertEqual(verdict["status"], "executable")

        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "SOFR_STRIP",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 4_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": dict(self.STRIP_EXPR),
                "expression_memo": _memo("SOFR_STRIP", "rates", "two_year"),
            },
            market,
        )
        pos = book["positions"][0]
        self.assertEqual(len(pos["legs"]), 4)
        for leg in pos["legs"]:
            self.assertEqual(leg["contracts"], 1)
        self.assertAlmostEqual(shock_risk_usd(pos) or 0.0, 10_000.0, places=2)

        moved = _shift_sofr_strip(market, 3.99)
        refresh_positions(book["positions"], moved)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, 100.0, places=2)

        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": pos["position_id"],
                "notional_usd": 4_000_000,
                "expression_memo": _memo("SOFR_STRIP", "rates", "two_year"),
            },
            moved,
        )
        self.assertEqual(book["positions"], [])
        close_row = book["history"][-1]
        self.assertAlmostEqual(close_row.get("realized_pnl_usd") or 0.0, 100.0, places=0)

    def test_sofr_strip_sub_lot_not_booked(self) -> None:
        market = _market()
        verdict = assess_expression(
            "SOFR_STRIP",
            expression=self.STRIP_EXPR,
            market_state=market,
            notional_usd=1_000_000,
        )
        self.assertFalse(verdict["bookable"])
        self.assertNotEqual(verdict["status"], "unsupported")

        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "SOFR_STRIP",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": dict(self.STRIP_EXPR),
                "expression_memo": _memo("SOFR_STRIP", "rates", "two_year"),
            },
            market,
        )
        self.assertEqual(book["positions"], [])
        _assert_blocked_catalog(self, book, verdict)

    def test_receive_2y_ois_lifecycle(self) -> None:
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
        picked = select_two_year(market, family="usd_sofr_ois")
        self.assertEqual(picked["instrument"], "USD_SOFR_OIS_2Y")
        self.assertTrue(picked["bookable"])

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
                "expression_memo": _memo("USD_SOFR_OIS_2Y", "rates", "two_year"),
            },
            market,
        )
        pos = book["positions"][0]
        self.assertEqual(pos["instrument"], "USD_SOFR_OIS_2Y")
        self.assertAlmostEqual(pos["dv01_usd"], 1950.0, places=6)
        self.assertNotIn("legs", pos)

        moved = deepcopy(market)
        moved["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_2Y"]["par_rate_percent"] = 3.99
        refresh_positions(book["positions"], moved)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, 1950.0, places=2)

        _apply(
            book,
            {"action": "CLOSE", "position_id": pos["position_id"], "notional_usd": 10_000_000, "expression_memo": _memo("USD_SOFR_OIS_2Y", "rates", "two_year")},
            moved,
        )
        self.assertEqual(book["positions"], [])
        self.assertAlmostEqual(book["history"][-1].get("realized_pnl_usd") or 0.0, 1950.0, places=0)

    def test_receive_1y1y_ois_lifecycle(self) -> None:
        market = _market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_1Y1Y={
                    "start_years": 1,
                    "tenor_years": 1,
                    "par_rate_percent": 3.70,
                    "annuity": 0.96,
                    "quote_type": "observed_par",
                    "source": "fixture_1y1y",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
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
                "expression_memo": _memo("USD_SOFR_OIS_1Y1Y", "rates", "two_year"),
            },
            market,
        )
        pos = book["positions"][0]
        moved = deepcopy(market)
        moved["usd_sofr_ois"]["instruments"]["USD_SOFR_OIS_1Y1Y"]["par_rate_percent"] = 3.71
        refresh_positions(book["positions"], moved)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, -480.0, places=2)
        _apply(
            book,
            {"action": "CLOSE", "position_id": pos["position_id"], "notional_usd": 5_000_000, "expression_memo": _memo("USD_SOFR_OIS_1Y1Y", "rates", "two_year")},
            moved,
        )
        self.assertEqual(book["positions"], [])

    def test_ois_missing_block_not_booked(self) -> None:
        market = _market(official_curves={"US": {"2Y": 4.0}})
        expr = {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2}
        verdict = assess_expression("USD_SOFR_OIS_2Y", expression=expr, market_state=market, notional_usd=1_000_000)
        self.assertFalse(verdict["bookable"])
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "USD_SOFR_OIS_2Y",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expr,
                "expression_memo": _memo("USD_SOFR_OIS_2Y", "rates", "two_year"),
            },
            market,
        )
        self.assertEqual(book["positions"], [])
        _assert_blocked_catalog(self, book, verdict)

    def test_corra_calendar_still_books(self) -> None:
        market = _market()
        expression = {
            "type": "calendar_spread",
            "curve_id": "CORRA",
            "near_expiry": "2026-12",
            "far_expiry": "2027-03",
        }
        verdict = assess_expression(
            "CORRA_2026-12",
            expression=expression,
            market_state=market,
            notional_usd=2_000_000,
        )
        self.assertTrue(verdict["bookable"])
        book = empty_seat("rate-dove")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "CORRA_2026-12/2027-03",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 2_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expression,
                "expression_memo": _memo("CORRA_2026-12/2027-03", "curve", "curve"),
            },
            market,
        )
        pos = book["positions"][0]
        self.assertEqual(len(pos["legs"]), 2)
        self.assertEqual(pos.get("structure_label"), "calendar_spread")

        parallel = _shift_corra(_shift_corra(market, "2026-12", 2.730), "2027-03", 3.005)
        refresh_positions(book["positions"], parallel)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, 0.0, places=0)

    def test_tu_future_tick_pnl_and_close(self) -> None:
        tick = 0.125 / 32.0
        market = _market(
            treasury_futures={
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TU_2027-03": {
                        "product": "TU",
                        "expiry": "2027-03",
                        "futures_price": 103.0,
                        "price_source": "test_settle",
                        "price_as_of": "2026-10-24",
                        "conversion_factor": 0.91,
                        "conversion_factor_source": "test_cf",
                        "conversion_factor_as_of": "2026-10-24",
                        "ctd_modified_duration": 1.9,
                        "ctd_dirty_price_per_100": 99.5,
                        "ctd_source": "test_ctd",
                        "ctd_as_of": "2026-10-24",
                    }
                },
            }
        )
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "TU_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 200_000,
                "expected_mark_direction": "higher",
                "paper_expression": {"type": "treasury_future"},
                "expression_memo": _memo("TU_2027-03", "rates", "two_year"),
            },
            market,
        )
        pos = book["positions"][0]
        self.assertEqual(pos["contracts"], 1)
        shock = shock_risk_usd(pos)
        self.assertIsNotNone(shock)
        self.assertGreater(shock or 0.0, 0.0)

        moved = deepcopy(market)
        moved["treasury_futures"]["contracts"]["TU_2027-03"]["futures_price"] = 103.0 + tick
        refresh_positions(book["positions"], moved)
        valued = value_position(pos)
        self.assertAlmostEqual(valued["unrealized_pnl_usd"] or 0.0, 7.8125, places=2)

        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": pos["position_id"],
                "notional_usd": 200_000,
                "expression_memo": _memo("TU_2027-03", "rates", "two_year"),
            },
            moved,
        )
        self.assertEqual(book["positions"], [])

    def test_tu_missing_ctd_not_booked(self) -> None:
        market = _market(
            treasury_futures={
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TU_2027-03": {
                        "futures_price": 103.0,
                        "price_source": "test",
                        "price_as_of": "2026-10-24",
                    }
                },
            }
        )
        verdict = assess_expression(
            "TU_2027-03",
            expression={"type": "treasury_future"},
            market_state=market,
            notional_usd=200_000,
        )
        self.assertEqual(verdict["status"], "missing_input")
        self.assertFalse(verdict["bookable"])
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "TU_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 200_000,
                "expected_mark_direction": "higher",
                "paper_expression": {"type": "treasury_future"},
                "expression_memo": _memo("TU_2027-03", "rates", "two_year"),
            },
            market,
        )
        self.assertEqual(book["positions"], [])
        _assert_blocked_catalog(self, book, verdict)

    def test_silent_substitution_us_2y_ois(self) -> None:
        market = _market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.0,
                    "annuity": 1.95,
                    "quote_type": "observed_par",
                    "source": "x",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            )
        )
        expr = {"type": "usd_sofr_ois", "start_years": 0, "tenor_years": 2}
        verdict = assess_expression("US_2Y", expression=expr, market_state=market, notional_usd=1_000_000)
        self.assertEqual(verdict["status"], "unsupported")
        self.assertTrue(verdict["reason"].startswith("refusing silent substitution"))
        book = empty_seat("trend-follower")
        _apply(
            book,
            {
                "action": "OPEN",
                "instrument": "US_2Y",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 1_000_000,
                "expected_mark_direction": "lower",
                "paper_expression": expr,
                "expression_memo": _memo("US_2Y", "rates", "two_year"),
            },
            market,
        )
        self.assertEqual(book["positions"], [])
        _assert_blocked_catalog(self, book, verdict)

    def test_government_yield_stays_us_2y(self) -> None:
        market = _market(
            usd_sofr_ois=_ois_block(
                USD_SOFR_OIS_2Y={
                    "start_years": 0,
                    "tenor_years": 2,
                    "par_rate_percent": 4.0,
                    "annuity": 1.95,
                    "quote_type": "observed_par",
                    "source": "x",
                    "as_of": "2026-10-24",
                    "curve_kind": "sofr_ois",
                    "status": "ok",
                }
            ),
            treasury_futures={
                "status": "ok",
                "source": "test",
                "contracts": {
                    "TU_2027-03": {
                        "futures_price": 103.0,
                        "price_source": "t",
                        "price_as_of": "2026-10-24",
                        "conversion_factor": 0.91,
                        "conversion_factor_source": "t",
                        "conversion_factor_as_of": "2026-10-24",
                        "ctd_modified_duration": 1.9,
                        "ctd_dirty_price_per_100": 99.5,
                        "ctd_source": "t",
                        "ctd_as_of": "2026-10-24",
                    }
                },
            },
        )
        gov = select_two_year(market, family="government_yield")
        self.assertEqual(gov["instrument"], "US_2Y")
        self.assertEqual(gov["status"], "missing_input")
        self.assertFalse(gov["bookable"])


if __name__ == "__main__":
    unittest.main()
