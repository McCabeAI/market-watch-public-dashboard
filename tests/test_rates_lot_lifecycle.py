"""Outright lot lifecycle, current FX marks, and per-leg structure closes.

These tests pin the accounting identities from review 5640442302. A passing
assertion is a property of the booked lots, not a rewritten expectation of the
old notional proration.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.overnight.books import _projected_risk_capital, apply_action, empty_seat
from scripts.overnight.paper_marks import refresh_positions
from scripts.pm.books import apply_decision, empty_books
from scripts.rates.lifecycle import REMAINING_POLICY, SUB_LOT_POLICY, split_lots
from scripts.rates.valuation import legacy_rate_pnl, shock_risk_usd, value_position
from scripts.risk_capital import book_risk_capital
from scripts.trader_room.rates_scan import with_tenor_scan

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 10, 24, 12, 0, tzinfo=NY)
SR3_FACE = 1_000_000.0


def _curve(rows):
    return {
        "status": "ok",
        "contracts": [{"expiry": expiry, "implied_rate": rate, "as_of": "2026-10-24"} for expiry, rate in rows],
    }


def _market(*, usdcad: float = 1.25, audusd: float = 0.50) -> dict:
    return {
        "generated_at": "2026-10-24T15:00:00Z",
        "fx": {
            "status": "ok",
            "pairs": {
                "USDCAD": {"spot": usdcad, "as_of": "2026-10-24", "status": "ok"},
                "AUDUSD": {"spot": audusd, "as_of": "2026-10-24", "status": "ok"},
            },
        },
        "tradable_rate_curves": {
            "status": "ok",
            "curves": {
                "SOFR": _curve([("2026-12", 3.70), ("2027-03", 3.55), ("2027-06", 3.40)]),
                "CORRA": _curve([("2026-12", 2.720), ("2027-03", 2.995), ("2027-06", 3.195)]),
                "AONIA": _curve([("2026-10", 3.60), ("2026-11", 3.55), ("2027-02", 3.40)]),
            },
        },
    }


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
            "rates_candidate": {"instrument": instrument, "asset_class": asset, "rationale": "lifecycle fixture"},
            "spot_candidate": {"instrument": "USDCAD", "asset_class": "spot_fx", "rationale": "spot alternative"},
            "options_candidate": None,
            "selected": "rates",
            "rationale": "Fixture chooses the expression; the test checks the accounting.",
        },
        selected_bucket=bucket,
    )


def _shift_rate(market: dict, curve_id: str, expiry: str, rate: float) -> dict:
    out = deepcopy(market)
    for row in out["tradable_rate_curves"]["curves"][curve_id]["contracts"]:
        if row["expiry"] == expiry:
            row["implied_rate"] = rate
    return out


def _fx(market: dict, *, usdcad: float | None = None, audusd: float | None = None, pair_status: str | None = None, pair: str = "USDCAD") -> dict:
    out = deepcopy(market)
    if usdcad is not None:
        out["fx"]["pairs"]["USDCAD"]["spot"] = usdcad
    if audusd is not None:
        out["fx"]["pairs"]["AUDUSD"]["spot"] = audusd
    if pair_status is not None:
        out["fx"]["pairs"][pair]["status"] = pair_status
    return out


def _trader(action: dict, market: dict, *, seat: str = "rate-dove", run_id: str = "life") -> dict:
    book = empty_seat(seat)
    apply_action(book, action, families=_families(market), run_id=run_id, when=AS_OF, market_state=market)
    return book


def _apply(book: dict, action: dict, market: dict, run_id: str) -> dict:
    return apply_action(book, action, families=_families(market), run_id=run_id, when=AS_OF, market_state=market)


def _pm(books: dict, pm_id: str, action: dict, market: dict, run_id: str) -> dict:
    return apply_decision(
        books,
        {"pm_id": pm_id, "actions": [action]},
        pm_id=pm_id,
        market_state=market,
        run_id=run_id,
        evidence_cutoff="2026-10-24",
        review_packet_id="pkt",
        review_packet_sha256="abc",
        when=AS_OF,
    )


def _lots_pnl(lots: int, entry: float, mark: float, local: float, fx: float, *, side: str = "long") -> float:
    bp = (mark - entry) * 100.0
    sign = 1.0 if side == "long" else -1.0
    return round(-sign * lots * local * bp * fx, 2)


class LotPolicyTests(unittest.TestCase):
    def test_floor_remaining_closes_the_complement(self) -> None:
        remaining, closed, zero = split_lots(13, 13.0, 6.5)
        self.assertEqual((remaining, closed, zero), (6, 7, False))
        self.assertEqual(remaining + closed, 13)
        remaining, closed, zero = split_lots(100, 100.0, 50.0)
        self.assertEqual((remaining, closed, zero), (50, 50, False))
        remaining, closed, zero = split_lots(100, 100_000_000.0, 98_500_000.0)
        self.assertEqual((remaining, closed, zero), (98, 2, False))
        remaining, closed, zero = split_lots(100, 100.0, 99.6)
        self.assertTrue(zero)
        self.assertEqual((remaining, closed), (100, 0))
        self.assertEqual(SUB_LOT_POLICY, "sub_lot_request_is_not_a_fill")
        self.assertEqual(REMAINING_POLICY, "floor_remaining_lots")


class OutrightLifecycleTests(unittest.TestCase):
    def _open_sr3(self, market: dict, *, lots: int = 100, price: float = 3.55, seat: str = "rate-dove") -> dict:
        book = _trader(
            {
                "action": "OPEN",
                "instrument": "SOFR_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": lots * SR3_FACE,
                "price": price,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
                "expected_mark_direction": "lower",
            },
            market,
            seat=seat,
            run_id="open-sr3",
        )
        self.assertEqual(book["positions"][0]["contracts"], lots)
        self.assertEqual(book["history"][-1]["result"], "applied")
        return book

    def test_one_bp_and_ten_bp_half_reduce_then_close(self) -> None:
        for bp, mark in ((1, 3.54), (10, 3.45)):
            with self.subTest(bp=bp):
                market = _market()
                book = self._open_sr3(market)
                moved = _shift_rate(market, "SOFR", "2027-03", mark)
                full = _lots_pnl(100, 3.55, mark, 25.0, 1.0)
                _apply(
                    book,
                    {
                        "action": "REDUCE",
                        "position_id": book["positions"][0]["position_id"],
                        "notional_usd": 50 * SR3_FACE,
                        "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
                    },
                    moved,
                    f"half-{bp}",
                )
                position = book["positions"][0]
                half = _lots_pnl(50, 3.55, mark, 25.0, 1.0)
                self.assertEqual(position["contracts"], 50)
                self.assertEqual(book["realized_pnl_usd"], half)
                self.assertNotEqual(book["realized_pnl_usd"], full)
                self.assertEqual(position["unrealized_pnl_usd"], half)
                self.assertEqual(book["realized_pnl_usd"] + position["unrealized_pnl_usd"], full)
                self.assertEqual(position["risk_capital_usd"], 50 * 25.0 * 100)
                self.assertEqual(book["history"][-1]["result"], "applied")
                _apply(
                    book,
                    {
                        "action": "CLOSE",
                        "position_id": position["position_id"],
                        "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
                    },
                    moved,
                    f"close-{bp}",
                )
                self.assertEqual(book["positions"], [])
                self.assertEqual(book["realized_pnl_usd"], full)
                self.assertEqual(book["unrealized_pnl_usd"], 0.0)
                self.assertEqual(book["risk_capital_usd"], 0.0)
                self.assertEqual(book["history"][-1]["result"], "applied")

    def test_open_add_reduce_close_conserves_lots_and_pnl(self) -> None:
        market = _market()
        book = self._open_sr3(market, seat="carry-is-king")
        moved = _shift_rate(market, "SOFR", "2027-03", 3.54)
        _apply(
            book,
            {
                "action": "ADD",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 100 * SR3_FACE,
                "price": 3.54,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "add",
        )
        position = book["positions"][0]
        self.assertEqual(position["contracts"], 200)
        self.assertAlmostEqual(position["entry_price"], (3.55 * 100 + 3.54 * 100) / 200)
        self.assertEqual(position["unrealized_pnl_usd"], _lots_pnl(200, position["entry_price"], 3.54, 25.0, 1.0))
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 100 * SR3_FACE,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "reduce",
        )
        position = book["positions"][0]
        realized = _lots_pnl(100, (3.55 * 100 + 3.54 * 100) / 200, 3.54, 25.0, 1.0)
        self.assertEqual(position["contracts"], 100)
        self.assertEqual(book["realized_pnl_usd"], realized)
        self.assertEqual(position["unrealized_pnl_usd"], realized)
        self.assertEqual(book["realized_pnl_usd"] + position["unrealized_pnl_usd"], _lots_pnl(100, 3.55, 3.54, 25.0, 1.0))
        self.assertNotEqual(book["realized_pnl_usd"], _lots_pnl(200, position["entry_price"], 3.54, 25.0, 1.0))
        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": position["position_id"],
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "close",
        )
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(100, 3.55, 3.54, 25.0, 1.0))
        self.assertEqual(book["risk_capital_usd"], 0.0)
        self.assertEqual(book["unrealized_pnl_usd"], 0.0)

    def test_uneven_fraction_and_zero_lot_reduction(self) -> None:
        market = _market()
        book = self._open_sr3(market, seat="value-guy")
        moved = _shift_rate(market, "SOFR", "2027-03", 3.54)
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 400_000,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "dust",
        )
        position = book["positions"][0]
        self.assertEqual(position["contracts"], 100)
        self.assertEqual(position["notional_usd"], 100 * SR3_FACE)
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        self.assertEqual(book["history"][-1]["result"], "zero_lot")
        self.assertNotEqual(book["history"][-1]["result"], "applied")
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 1_500_000,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "uneven",
        )
        position = book["positions"][0]
        self.assertEqual(position["contracts"], 98)
        self.assertAlmostEqual(position["residual_contracts"], 0.5)
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(2, 3.55, 3.54, 25.0, 1.0))
        self.assertEqual(position["unrealized_pnl_usd"], _lots_pnl(98, 3.55, 3.54, 25.0, 1.0))
        self.assertEqual(
            book["realized_pnl_usd"] + position["unrealized_pnl_usd"],
            _lots_pnl(100, 3.55, 3.54, 25.0, 1.0),
        )
        self.assertNotEqual(book["realized_pnl_usd"], _lots_pnl(1, 3.55, 3.54, 25.0, 1.0))

    def test_pm_open_add_reduce_close_matches_trader_lots(self) -> None:
        market = _market()
        books = _pm(
            empty_books(),
            "pragmatist",
            {
                "action": "OPEN",
                "instrument": "SOFR_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 100 * SR3_FACE,
                "price": 3.55,
                "expected_mark_direction": "lower",
            },
            market,
            "pm-open",
        )
        book = books["pms"]["pragmatist"]
        self.assertEqual(book["positions"][0]["contracts"], 100)
        moved = _shift_rate(market, "SOFR", "2027-03", 3.45)
        books = _pm(
            books,
            "pragmatist",
            {
                "action": "ADD",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 100 * SR3_FACE,
                "price": 3.45,
            },
            moved,
            "pm-add",
        )
        book = books["pms"]["pragmatist"]
        position = book["positions"][0]
        self.assertEqual(position["contracts"], 200)
        self.assertAlmostEqual(position["entry_price"], (3.55 * 100 + 3.45 * 100) / 200)
        books = _pm(
            books,
            "pragmatist",
            {
                "action": "REDUCE",
                "position_id": position["position_id"],
                "notional_usd": 100 * SR3_FACE,
            },
            moved,
            "pm-reduce",
        )
        book = books["pms"]["pragmatist"]
        self.assertEqual(book["positions"][0]["contracts"], 100)
        half = _lots_pnl(100, (3.55 + 3.45) / 2, 3.45, 25.0, 1.0)
        self.assertEqual(book["realized_pnl_usd"], half)
        self.assertEqual(book["positions"][0]["unrealized_pnl_usd"], half)
        self.assertEqual(book["history"][-1]["result"], "applied")
        books = _pm(
            books,
            "pragmatist",
            {"action": "CLOSE", "position_id": book["positions"][0]["position_id"]},
            moved,
            "pm-close",
        )
        book = books["pms"]["pragmatist"]
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(100, 3.55, 3.45, 25.0, 1.0))
        self.assertEqual(book_risk_capital(book)["risk_capital_usd"], 0.0)
        self.assertEqual(book["unrealized_pnl_usd"], 0.0)

    def test_historical_unstamped_row_stays_on_duration_one(self) -> None:
        historical = {
            "position_id": "pos-historical-sr3",
            "instrument": "SOFR_2027-03",
            "asset_class": "rates",
            "side": "long",
            "notional_usd": 100_000_000,
            "entry_price": 4.76,
            "mark_price": 4.75,
            "opened_at": "2026-01-01T00:00:00Z",
        }
        before = legacy_rate_pnl(historical)
        valued = value_position(historical)
        self.assertEqual(valued["unrealized_pnl_usd"], before["unrealized_pnl_usd"])
        self.assertEqual(valued["valuation_method"], "legacy_duration_one")
        self.assertEqual(before["unrealized_pnl_usd"], 10_000.0)
        self.assertNotIn("contracts", historical)
        market = _market()
        book = empty_seat("rate-dove")
        book["positions"].append(deepcopy(historical))
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": "pos-historical-sr3",
                "notional_usd": 50_000_000,
                "price": 4.75,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
            },
            market,
            "hist",
        )
        self.assertEqual(book["realized_pnl_usd"], 5_000.0)
        self.assertNotIn("contracts", book["positions"][0])
        self.assertEqual(book["positions"][0]["notional_usd"], 50_000_000)
        self.assertNotEqual(book["positions"][0].get("valuation_method"), "instrument_dv01")


class OutrightFxTests(unittest.TestCase):
    def test_cad_and_aud_refresh_current_fx_and_keep_entry_fx(self) -> None:
        cases = (
            ("CORRA_2027-03", "CORRA", "2027-03", 2.995, 2.985, 25.0, 1_000_000.0, "USDCAD", 1.25, 1.00),
            ("AONIA_2026-10", "AONIA", "2026-10", 3.60, 3.59, 24.66, 3_000_000.0, "AUDUSD", 0.50, 0.80),
        )
        for instrument, curve, expiry, entry, mark, local, face_local, pair, fx_spot, later_spot in cases:
            with self.subTest(instrument=instrument):
                if pair == "USDCAD":
                    market = _market(usdcad=fx_spot)
                    entry_fx = 1.0 / fx_spot
                    later_fx = 1.0 / later_spot
                    later = _fx(_shift_rate(market, curve, expiry, mark), usdcad=later_spot)
                else:
                    market = _market(audusd=fx_spot)
                    entry_fx = fx_spot
                    later_fx = later_spot
                    later = _fx(_shift_rate(market, curve, expiry, mark), audusd=later_spot)
                notional = 10 * face_local * entry_fx
                book = _trader(
                    {
                        "action": "OPEN",
                        "instrument": instrument,
                        "asset_class": "rates",
                        "side": "long",
                        "notional_usd": notional,
                        "price": entry,
                        "expression_memo": _memo(instrument, "rates", "stir_policy_path"),
                        "expected_mark_direction": "lower",
                    },
                    market,
                    run_id=f"open-{instrument}",
                )
                position = book["positions"][0]
                self.assertEqual(position["contracts"], 10)
                self.assertAlmostEqual(position["entry_fx_usd_per_unit"], entry_fx)
                refresh_positions([position], later)
                self.assertAlmostEqual(position["entry_fx_usd_per_unit"], entry_fx)
                self.assertAlmostEqual(position["mark_fx_usd_per_unit"], later_fx)
                self.assertEqual(position["mark_fx_status"], "ok")
                self.assertEqual(position["mark_fx_pair"], pair)
                self.assertTrue(position["mark_fx_as_of"])
                self.assertTrue(position["mark_fx_source"])
                self.assertEqual(position["mark_price"], mark)
                expected = _lots_pnl(10, entry, mark, local, later_fx)
                stale = _lots_pnl(10, entry, mark, local, entry_fx)
                self.assertEqual(position["unrealized_pnl_usd"] if book.get("unrealized_pnl_usd") else value_position(position)["unrealized_pnl_usd"], expected)
                self.assertNotEqual(expected, stale)
                self.assertEqual(shock_risk_usd(position), round(10 * local * later_fx * 100, 2))
                _apply(
                    book,
                    {
                        "action": "REDUCE",
                        "position_id": position["position_id"],
                        "notional_usd": notional / 2,
                        "expression_memo": _memo(instrument, "rates", "stir_policy_path"),
                    },
                    later,
                    f"half-{instrument}",
                )
                position = book["positions"][0]
                realized = _lots_pnl(5, entry, mark, local, later_fx)
                unrealized = _lots_pnl(5, entry, mark, local, later_fx)
                self.assertEqual(position["contracts"], 5)
                self.assertEqual(book["realized_pnl_usd"], realized)
                self.assertEqual(position["unrealized_pnl_usd"], unrealized)
                self.assertEqual(book["realized_pnl_usd"] + position["unrealized_pnl_usd"], expected)
                self.assertAlmostEqual(position["entry_fx_usd_per_unit"], entry_fx)
                self.assertAlmostEqual(position["mark_fx_usd_per_unit"], later_fx)
                _apply(
                    book,
                    {
                        "action": "CLOSE",
                        "position_id": position["position_id"],
                        "expression_memo": _memo(instrument, "rates", "stir_policy_path"),
                    },
                    later,
                    f"close-{instrument}",
                )
                self.assertEqual(book["positions"], [])
                self.assertEqual(book["realized_pnl_usd"], expected)
                self.assertEqual(book["risk_capital_usd"], 0.0)

    def test_missing_and_stale_fx_block_pnl_risk_and_close_then_recover(self) -> None:
        market = _market(usdcad=1.25)
        book = _trader(
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10 * 1_000_000 / 1.25,
                "price": 2.995,
                "expression_memo": _memo("CORRA_2027-03", "rates", "stir_policy_path"),
                "expected_mark_direction": "lower",
            },
            market,
            seat="rate-hawk",
            run_id="cad-open",
        )
        position = book["positions"][0]
        entry_fx = position["entry_fx_usd_per_unit"]
        moved = _fx(_shift_rate(market, "CORRA", "2027-03", 2.985), usdcad=1.00)
        for status in ("stale", "missing"):
            broken = _fx(moved, pair_status=status, pair="USDCAD")
            refresh_positions([position], broken)
            self.assertIsNone(position["mark_price"])
            self.assertIsNone(position["mark_fx_usd_per_unit"])
            self.assertEqual(position["mark_fx_status"], status)
            self.assertAlmostEqual(position["entry_fx_usd_per_unit"], entry_fx)
            self.assertIsNone(value_position(position)["unrealized_pnl_usd"])
            self.assertIsNone(shock_risk_usd(position))
            _apply(
                book,
                {
                    "action": "CLOSE",
                    "position_id": position["position_id"],
                    "expression_memo": _memo("CORRA_2027-03", "rates", "stir_policy_path"),
                },
                broken,
                f"pending-{status}",
            )
            self.assertEqual(book["positions"][0]["contracts"], 10)
            self.assertEqual(book["realized_pnl_usd"], 0.0)
            self.assertEqual(book["history"][-1]["result"], "pending_mark")
            self.assertIsNone(book["history"][-1]["realized_pnl_usd"])
        refresh_positions([book["positions"][0]], moved)
        recovered = book["positions"][0]
        self.assertEqual(recovered["mark_price"], 2.985)
        self.assertAlmostEqual(recovered["mark_fx_usd_per_unit"], 1.0)
        self.assertEqual(recovered["mark_status"], "ok")
        self.assertEqual(value_position(recovered)["unrealized_pnl_usd"], _lots_pnl(10, 2.995, 2.985, 25.0, 1.0))
        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": recovered["position_id"],
                "expression_memo": _memo("CORRA_2027-03", "rates", "stir_policy_path"),
            },
            moved,
            "recovered-close",
        )
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(10, 2.995, 2.985, 25.0, 1.0))
        self.assertEqual(book["risk_capital_usd"], 0.0)

    def test_pm_cad_close_uses_refreshed_fx_and_refuses_a_stale_one(self) -> None:
        market = _market(usdcad=1.25)
        books = _pm(
            empty_books(),
            "grinder",
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10 * 1_000_000 / 1.25,
                "price": 2.995,
                "expected_mark_direction": "lower",
            },
            market,
            "pm-cad-open",
        )
        book = books["pms"]["grinder"]
        entry_fx = book["positions"][0]["entry_fx_usd_per_unit"]
        stale = _fx(_shift_rate(market, "CORRA", "2027-03", 2.985), usdcad=1.00, pair_status="stale")
        books = _pm(
            books,
            "grinder",
            {"action": "CLOSE", "position_id": book["positions"][0]["position_id"]},
            stale,
            "pm-cad-stale",
        )
        book = books["pms"]["grinder"]
        self.assertEqual(book["positions"][0]["contracts"], 10)
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        self.assertEqual(book["history"][-1]["result"], "pending_mark")
        self.assertAlmostEqual(book["positions"][0]["entry_fx_usd_per_unit"], entry_fx)
        self.assertIsNone(book["positions"][0]["mark_fx_usd_per_unit"])
        fresh = _fx(_shift_rate(market, "CORRA", "2027-03", 2.985), usdcad=1.00)
        books = _pm(
            books,
            "grinder",
            {"action": "CLOSE", "position_id": book["positions"][0]["position_id"]},
            fresh,
            "pm-cad-close",
        )
        book = books["pms"]["grinder"]
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(10, 2.995, 2.985, 25.0, 1.0))
        self.assertEqual(book_risk_capital(book)["risk_capital_usd"], 0.0)

    def test_usd_sr3_is_unchanged_by_an_fx_move(self) -> None:
        market = _market(usdcad=1.25)
        book = _trader(
            {
                "action": "OPEN",
                "instrument": "SOFR_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10 * SR3_FACE,
                "price": 3.55,
                "expression_memo": _memo("SOFR_2027-03", "rates", "stir_policy_path"),
                "expected_mark_direction": "lower",
            },
            market,
            seat="mean-reverter",
            run_id="sr3-fx",
        )
        moved = _fx(_shift_rate(market, "SOFR", "2027-03", 3.54), usdcad=1.00)
        refresh_positions(book["positions"], moved)
        position = book["positions"][0]
        self.assertEqual(value_position(position)["unrealized_pnl_usd"], 250.0)
        self.assertEqual(shock_risk_usd(position), 25_000.0)
        self.assertEqual(position["contracts"], 10)
        self.assertEqual(position.get("mark_fx_usd_per_unit"), 1.0)

    def test_add_projection_matches_booked_lots_at_the_current_fx(self) -> None:
        market = _market(usdcad=1.25)
        book = _trader(
            {
                "action": "OPEN",
                "instrument": "CORRA_2027-03",
                "asset_class": "rates",
                "side": "long",
                "notional_usd": 10 * 1_000_000 / 1.25,
                "price": 2.995,
                "expression_memo": _memo("CORRA_2027-03", "rates", "stir_policy_path"),
                "expected_mark_direction": "lower",
            },
            market,
            seat="positioning-cynic",
            run_id="proj-open",
        )
        later = _fx(_shift_rate(market, "CORRA", "2027-03", 2.985), usdcad=1.00)
        action = {
            "action": "ADD",
            "position_id": book["positions"][0]["position_id"],
            "notional_usd": 5.4 * 1_000_000,
            "price": 2.985,
            "expression_memo": _memo("CORRA_2027-03", "rates", "stir_policy_path"),
        }
        projected = _projected_risk_capital(book, action, later)
        _apply(book, action, later, "proj-add")
        position = book["positions"][0]
        self.assertEqual(position["contracts"], 15)
        self.assertEqual(book["history"][-1]["result"], "applied")
        self.assertAlmostEqual(position["entry_price"], (2.995 * 10 + 2.985 * 5) / 15)
        notional_weighted = (2.995 * (10 * 1_000_000 / 1.25) + 2.985 * 5_400_000) / ((10 * 1_000_000 / 1.25) + 5_400_000)
        self.assertNotAlmostEqual(position["entry_price"], notional_weighted, places=6)
        self.assertAlmostEqual(position["mark_fx_usd_per_unit"], 1.0)
        self.assertAlmostEqual(position["entry_fx_usd_per_unit"], 0.8)
        self.assertEqual(book["risk_capital_usd"], round(15 * 25.0 * 1.0 * 100, 2))
        self.assertEqual(projected, book["risk_capital_usd"])
        self.assertNotEqual(position["contracts"], 16)


class StructureLotTests(unittest.TestCase):
    def _open_structure(self, market, expression, instrument, asset, bucket, notional, seat="rate-dove"):
        return _trader(
            {
                "action": "OPEN",
                "instrument": instrument,
                "asset_class": asset,
                "side": "long",
                "notional_usd": notional,
                "paper_expression": expression,
                "expression_memo": _memo(instrument, asset, bucket),
                "expected_mark_direction": "lower",
            },
            market,
            seat=seat,
            run_id=f"open-{instrument}",
        )

    def test_thirteen_lot_calendar_realizes_seven_lots_not_six_and_a_half(self) -> None:
        market = _market()
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        book = self._open_structure(market, expression, "SOFR_2026-12/2027-06", "curve", "curve", 13 * SR3_FACE)
        legs = {leg["role"]: leg for leg in book["positions"][0]["legs"]}
        self.assertEqual(legs["near"]["contracts"], 13)
        self.assertEqual(legs["far"]["contracts"], 13)
        near_entry = legs["near"]["entry_rate"]
        moved = _shift_rate(market, "SOFR", "2026-12", 3.80)
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 6.5 * SR3_FACE,
                "expression_memo": _memo("SOFR_2026-12/2027-06", "curve", "curve"),
            },
            moved,
            "cal-half",
        )
        position = book["positions"][0]
        legs = {leg["role"]: leg for leg in position["legs"]}
        self.assertEqual(legs["near"]["contracts"], 6)
        self.assertEqual(legs["near"]["lots_closed_last"], 7)
        self.assertEqual(legs["far"]["contracts"], 6)
        self.assertEqual(legs["far"]["lots_closed_last"], 7)
        self.assertEqual(legs["near"]["contracts"] + legs["near"]["lots_closed_last"], 13)
        realized = _lots_pnl(7, near_entry, 3.80, 25.0, 1.0, side="short")
        prorated = _lots_pnl(6.5, near_entry, 3.80, 25.0, 1.0, side="short")
        self.assertEqual(book["realized_pnl_usd"], round(realized, 2))
        self.assertNotEqual(book["realized_pnl_usd"], round(prorated, 2))
        self.assertEqual(position["unrealized_pnl_usd"], _lots_pnl(6, near_entry, 3.80, 25.0, 1.0, side="short"))
        self.assertEqual(
            book["realized_pnl_usd"] + position["unrealized_pnl_usd"],
            _lots_pnl(13, near_entry, 3.80, 25.0, 1.0, side="short"),
        )
        self.assertAlmostEqual(legs["near"]["entry_rate"], near_entry)
        self.assertAlmostEqual(legs["near"]["residual_contracts"], 0.5)
        self.assertGreater(position["residual_dv01_usd"], 0)
        self.assertEqual(book["history"][-1]["result"], "applied")

    def test_butterfly_and_four_leg_close_each_leg_on_its_own_lots(self) -> None:
        market = _market()
        fly = {
            "type": "butterfly",
            "curve_id": "SOFR",
            "wing1_expiry": "2026-12",
            "body_expiry": "2027-03",
            "wing2_expiry": "2027-06",
        }
        book = self._open_structure(market, fly, "SOFR_fly", "curve", "curve", 13 * SR3_FACE, seat="rate-hawk")
        opened = {leg["role"]: leg["contracts"] for leg in book["positions"][0]["legs"]}
        self.assertEqual(opened["wing1"], 13)
        self.assertEqual(opened["body"], 26)
        self.assertEqual(opened["wing2"], 13)
        moved = _shift_rate(market, "SOFR", "2026-12", 3.71)
        wing_entry = next(leg["entry_rate"] for leg in book["positions"][0]["legs"] if leg["role"] == "wing1")
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 6.5 * SR3_FACE,
                "expression_memo": _memo("SOFR_fly", "curve", "curve"),
            },
            moved,
            "fly-half",
        )
        legs = {leg["role"]: leg for leg in book["positions"][0]["legs"]}
        self.assertEqual((legs["wing1"]["contracts"], legs["wing1"]["lots_closed_last"]), (6, 7))
        self.assertEqual((legs["body"]["contracts"], legs["body"]["lots_closed_last"]), (13, 13))
        self.assertEqual((legs["wing2"]["contracts"], legs["wing2"]["lots_closed_last"]), (6, 7))
        self.assertNotEqual(legs["wing1"]["lots_closed_last"], legs["body"]["lots_closed_last"])
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(7, wing_entry, 3.71, 25.0, 1.0, side="short"))
        self.assertNotEqual(book["realized_pnl_usd"], _lots_pnl(6.5, wing_entry, 3.71, 25.0, 1.0, side="short"))

        curve = {
            "type": "curve_rv",
            "long_calendar": {"curve_id": "CORRA", "near_expiry": "2026-12", "far_expiry": "2027-06"},
            "short_calendar": {"curve_id": "SOFR", "near_expiry": "2026-12", "far_expiry": "2027-06"},
        }
        other = self._open_structure(
            market,
            curve,
            "CORRA-SOFR_2026-12/2027-06",
            "rates_rv",
            "cross_market_rv",
            13 * 1_000_000 / 1.25,
            seat="catalyst-junkie",
        )
        before = {leg["role"]: leg["contracts"] for leg in other["positions"][0]["legs"]}
        self.assertEqual(before["long_calendar_near"], 13)
        self.assertEqual(before["short_calendar_near"], 10)
        cad_entry = next(leg["entry_rate"] for leg in other["positions"][0]["legs"] if leg["role"] == "long_calendar_near")
        shifted = _shift_rate(market, "CORRA", "2026-12", 2.820)
        _apply(
            other,
            {
                "action": "REDUCE",
                "position_id": other["positions"][0]["position_id"],
                "notional_usd": (13 * 1_000_000 / 1.25) / 2,
                "expression_memo": _memo("CORRA-SOFR_2026-12/2027-06", "rates_rv", "cross_market_rv"),
            },
            shifted,
            "rv-half",
        )
        after = {leg["role"]: leg for leg in other["positions"][0]["legs"]}
        self.assertEqual(after["long_calendar_near"]["lots_closed_last"], 7)
        self.assertEqual(after["long_calendar_far"]["lots_closed_last"], 7)
        self.assertEqual(after["short_calendar_near"]["lots_closed_last"], 5)
        self.assertEqual(after["short_calendar_far"]["lots_closed_last"], 5)
        self.assertEqual(after["long_calendar_near"]["contracts"], 6)
        self.assertEqual(after["short_calendar_near"]["contracts"], 5)
        for role, old in before.items():
            self.assertEqual(after[role]["contracts"] + after[role]["lots_closed_last"], old)
        fx = 1.0 / 1.25
        realized = _lots_pnl(7, cad_entry, 2.820, 25.0, fx, side="short")
        prorated = _lots_pnl(6.5, cad_entry, 2.820, 25.0, fx, side="short")
        self.assertEqual(other["realized_pnl_usd"], realized)
        self.assertNotEqual(other["realized_pnl_usd"], prorated)

    def test_structure_add_scales_each_leg_and_missing_marks_do_not_fill(self) -> None:
        market = _market()
        fly = {
            "type": "butterfly",
            "curve_id": "SOFR",
            "wing1_expiry": "2026-12",
            "body_expiry": "2027-03",
            "wing2_expiry": "2027-06",
        }
        book = self._open_structure(market, fly, "SOFR_fly", "curve", "curve", 13 * SR3_FACE, seat="trend-follower")
        position = book["positions"][0]
        moved = _shift_rate(market, "SOFR", "2027-03", 3.50)
        _apply(
            book,
            {
                "action": "ADD",
                "position_id": position["position_id"],
                "notional_usd": 6.5 * SR3_FACE,
                "expression_memo": _memo("SOFR_fly", "curve", "curve"),
            },
            moved,
            "fly-add",
        )
        legs = {leg["role"]: leg for leg in book["positions"][0]["legs"]}
        self.assertEqual(legs["wing1"]["lots_added_last"], 6)
        self.assertEqual(legs["body"]["lots_added_last"], 13)
        self.assertEqual(legs["wing1"]["contracts"], 19)
        self.assertEqual(legs["body"]["contracts"], 39)
        self.assertNotEqual(legs["wing1"]["lots_added_last"], legs["body"]["lots_added_last"])
        body_entry = legs["body"]["entry_rate"]
        self.assertAlmostEqual(body_entry, (3.55 * 26 + 3.50 * 13) / 39)
        dust = deepcopy(book)
        _apply(
            book,
            {
                "action": "REDUCE",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 1.0,
                "expression_memo": _memo("SOFR_fly", "curve", "curve"),
            },
            moved,
            "fly-dust",
        )
        self.assertEqual(book["history"][-1]["result"], "zero_lot")
        self.assertEqual(book["positions"][0]["legs"][0]["contracts"], dust["positions"][0]["legs"][0]["contracts"])
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        missing = deepcopy(moved)
        missing["tradable_rate_curves"]["curves"]["SOFR"] = {"status": "unavailable", "contracts": []}
        before = {leg["role"]: leg["contracts"] for leg in book["positions"][0]["legs"]}
        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": book["positions"][0]["position_id"],
                "expression_memo": _memo("SOFR_fly", "curve", "curve"),
            },
            missing,
            "fly-pending",
        )
        self.assertEqual(book["history"][-1]["result"], "pending_mark")
        self.assertEqual({leg["role"]: leg["contracts"] for leg in book["positions"][0]["legs"]}, before)
        self.assertEqual(book["realized_pnl_usd"], 0.0)
        self.assertIsNone(book["history"][-1]["realized_pnl_usd"])
        _apply(
            book,
            {
                "action": "CLOSE",
                "position_id": book["positions"][0]["position_id"],
                "expression_memo": _memo("SOFR_fly", "curve", "curve"),
            },
            moved,
            "fly-close",
        )
        self.assertEqual(book["positions"], [])
        self.assertEqual(book["risk_capital_usd"], 0.0)

    def test_pm_calendar_half_matches_the_trader_close_count(self) -> None:
        market = _market()
        expression = {
            "type": "calendar_spread",
            "curve_id": "SOFR",
            "near_expiry": "2026-12",
            "far_expiry": "2027-06",
        }
        books = _pm(
            empty_books(),
            "pragmatist",
            {
                "action": "OPEN",
                "instrument": "SOFR_2026-12/2027-06",
                "asset_class": "curve",
                "side": "long",
                "notional_usd": 13 * SR3_FACE,
                "price": 1.0,
                "paper_expression": expression,
                "expected_mark_direction": "lower",
            },
            market,
            "pm-cal-open",
        )
        book = books["pms"]["pragmatist"]
        self.assertEqual(book["positions"][0]["legs"][0]["contracts"], 13)
        near_entry = next(leg["entry_rate"] for leg in book["positions"][0]["legs"] if leg["role"] == "near")
        moved = _shift_rate(market, "SOFR", "2026-12", 3.80)
        books = _pm(
            books,
            "pragmatist",
            {
                "action": "REDUCE",
                "position_id": book["positions"][0]["position_id"],
                "notional_usd": 6.5 * SR3_FACE,
            },
            moved,
            "pm-cal-half",
        )
        book = books["pms"]["pragmatist"]
        legs = {leg["role"]: leg for leg in book["positions"][0]["legs"]}
        self.assertEqual(legs["near"]["contracts"], 6)
        self.assertEqual(legs["near"]["lots_closed_last"], 7)
        self.assertEqual(book["realized_pnl_usd"], _lots_pnl(7, near_entry, 3.80, 25.0, 1.0, side="short"))
        self.assertEqual(book["history"][-1]["result"], "applied")
        self.assertNotEqual(book["history"][-1]["result"], "pending_mark")


if __name__ == "__main__":
    unittest.main()
