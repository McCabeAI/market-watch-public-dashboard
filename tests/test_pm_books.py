from __future__ import annotations

import unittest
from copy import deepcopy

from scripts.pm.books import (
    apply_action,
    apply_decision,
    empty_books,
    empty_pm_book,
    mark_pm_book,
    validate_books,
)
from scripts.pm.constants import AUTOMATED_PM_IDS, CASH_CAPITAL_USD, GROSS_NOTIONAL_LIMIT_USD, RISK_CAPITAL_LIMIT_USD, MAX_DRAWDOWN_USD, PM_IDS
from scripts.pm.errors import CapError, CurveLockError, MarkError, SchemaError


MARKET = {
    "generated_at": "2026-09-19T12:00:00Z",
    "fx": {"pairs": {"USDCAD": {"spot": 1.36, "as_of": "2026-09-19"}, "AUDUSD": {"spot": 0.66}}},
    "rates": {"US": {"tenors": {"10Y": {"value": 4.20}}}},
    "tradable_rate_curves": {
        "status": "ok",
        "curves": {
            "SOFR": {
                "status": "ok",
                "contracts": [{"code": "SR3H7", "expiry": "2027-03", "implied_rate": 3.55}],
            },
            "CORRA": {
                "status": "ok",
                "contracts": [{"code": "CRAH7", "expiry": "2027-03", "implied_rate": 2.80}],
            },
        },
    },
}


def _open(instrument="USDCAD", notional=100_000_000, asset_class="spot_fx", **extra):
    action = {
        "action": "OPEN",
        "instrument": instrument,
        "side": "long",
        "notional_usd": notional,
        "asset_class": asset_class,
    }
    action.update(extra)
    return action


class PMBookTests(unittest.TestCase):
    def test_initial_books_are_four_empty_billion_sleeves(self) -> None:
        books = validate_books(empty_books(trader_room_run_id="tr-test"))
        self.assertEqual(set(books["pms"]), set(PM_IDS))
        for pm_id, book in books["pms"].items():
            self.assertEqual(book["gross_notional_limit_usd"], GROSS_NOTIONAL_LIMIT_USD)
            self.assertFalse(book["gross_notional_limit_enforced"])
            self.assertEqual(book["risk_capital_limit_usd"], RISK_CAPITAL_LIMIT_USD)
            self.assertEqual(book["max_drawdown_usd"], MAX_DRAWDOWN_USD)
            self.assertEqual(book["positions"], [])
            self.assertEqual(book["gross_utilization_usd"], 0)
            self.assertIn("awaiting", book["decision_status"])
            self.assertIn("funding_cost_usd", book)
            self.assertEqual(book["funding_cost_usd"], 0.0)
            self.assertEqual(book["funded_draw_usd"], 0.0)
            self.assertNotEqual(book["funded_draw_usd"], book["gross_notional_limit_usd"])
            self.assertNotEqual(book["decision_status"], books["pms"]["chatgpt"]["decision_status"] if pm_id != "chatgpt" else "x")

    def test_chatgpt_and_automated_awaiting_statuses_differ(self) -> None:
        books = empty_books()
        self.assertEqual(books["pms"]["chatgpt"]["decision_status"], "awaiting_chatgpt_decision")
        for pm_id in AUTOMATED_PM_IDS:
            self.assertEqual(books["pms"][pm_id]["decision_status"], "awaiting_automated_pm_review")

    def test_cap_fails_closed(self) -> None:
        books = empty_books()
        with self.assertRaises(CapError):
            apply_decision(
                books,
                {"pm_id": "chatgpt", "actions": [_open(notional=10_000_000_001)]},
                pm_id="chatgpt",
                market_state=MARKET,
                run_id="r1",
                evidence_cutoff="2026-09-19T12:00:00Z",
                review_packet_id="p",
                review_packet_sha256="h",
            )

    def test_gross_notional_can_exceed_legacy_one_billion_when_risk_is_inside_cap(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [_open(notional=2_000_000_000)]},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r-notional",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        book = books["pms"]["chatgpt"]
        self.assertEqual(book["gross_utilization_usd"], 2_000_000_000)
        self.assertEqual(book["risk_capital_usd"], 20_000_000)
        self.assertLess(book["risk_capital_usd"], book["risk_capital_limit_usd"])

    def test_independence_each_pm_sees_only_own_book(self) -> None:
        books = empty_books()
        after_swinger = apply_decision(
            books,
            {"pm_id": "swinger", "actions": [_open(notional=200_000_000)], "conviction": 80, "thesis": "swing"},
            pm_id="swinger",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="ps",
            review_packet_sha256="hs",
        )
        after_both = apply_decision(
            after_swinger,
            {"pm_id": "pragmatist", "actions": [_open(instrument="AUDUSD", notional=50_000_000)], "thesis": "grind"},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="pp",
            review_packet_sha256="hp",
        )
        self.assertEqual(len(after_both["pms"]["swinger"]["positions"]), 1)
        self.assertEqual(after_both["pms"]["swinger"]["positions"][0]["instrument"], "USDCAD")
        self.assertEqual(len(after_both["pms"]["pragmatist"]["positions"]), 1)
        self.assertEqual(after_both["pms"]["pragmatist"]["positions"][0]["instrument"], "AUDUSD")
        self.assertEqual(after_both["pms"]["chatgpt"]["positions"], [])
        self.assertEqual(after_both["pms"]["grinder"]["positions"], [])

    def test_rates_expected_mark_direction_rejects_wrong_side(self) -> None:
        bad = _open(
            instrument="SOFR_2027-03",
            asset_class="rates",
            notional=50_000_000,
            expected_mark_direction="higher",
        )
        with self.assertRaises(SchemaError):
            apply_decision(
                empty_books(),
                {"pm_id": "pragmatist", "actions": [bad]},
                pm_id="pragmatist",
                market_state=MARKET,
                run_id="r1",
                evidence_cutoff="c",
                review_packet_id="p",
                review_packet_sha256="h",
            )

        good = deepcopy(bad)
        good["side"] = "short"
        books = apply_decision(
            empty_books(),
            {"pm_id": "pragmatist", "actions": [good]},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        self.assertEqual(books["pms"]["pragmatist"]["positions"][0]["side"], "short")

    def test_swinger_hedge_fails(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "swinger", "actions": [_open()]},
            pm_id="swinger",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        pos_id = books["pms"]["swinger"]["positions"][0]["position_id"]
        with self.assertRaises(SchemaError):
            apply_decision(
                books,
                {"pm_id": "swinger", "actions": [{"action": "HEDGE", "hedge_of": pos_id, "notional_usd": 10_000_000}]},
                pm_id="swinger",
                market_state=MARKET,
                run_id="r1",
                evidence_cutoff="c",
                review_packet_id="p",
                review_packet_sha256="h",
            )

    def test_hold_and_no_trade_do_not_invent_positions(self) -> None:
        hold = apply_decision(
            empty_books(),
            {"pm_id": "grinder", "actions": [{"action": "HOLD"}], "thesis": "wait"},
            pm_id="grinder",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        self.assertEqual(hold["pms"]["grinder"]["decision_status"], "hold")
        self.assertEqual(hold["pms"]["grinder"]["positions"], [])
        no_trade = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [{"action": "NO_TRADE"}], "thesis": "no edge"},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        self.assertEqual(no_trade["pms"]["chatgpt"]["decision_status"], "no_trade")
        self.assertEqual(no_trade["pms"]["chatgpt"]["positions"], [])

    def test_deterministic_mid_overrides_model_price(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [_open(price=9.99)]},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        pos = books["pms"]["chatgpt"]["positions"][0]
        self.assertEqual(pos["entry_price"], 1.36)
        self.assertEqual(pos["mark_price"], 1.36)
        self.assertIn("USDCAD", pos["entry_price_source"])

    def test_mark_refresh_and_missing_mark_isolation(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "pragmatist", "actions": [_open(), _open(instrument="AUDUSD", notional=20_000_000)]},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        moved = deepcopy(MARKET)
        moved["fx"]["pairs"]["USDCAD"]["spot"] = 1.40
        del moved["fx"]["pairs"]["AUDUSD"]
        from scripts.pm.books import refresh_pm_book

        refresh_pm_book(books["pms"]["pragmatist"], moved)
        cad = next(p for p in books["pms"]["pragmatist"]["positions"] if p["instrument"] == "USDCAD")
        aud = next(p for p in books["pms"]["pragmatist"]["positions"] if p["instrument"] == "AUDUSD")
        self.assertEqual(cad["mark_price"], 1.40)
        self.assertIsNone(aud["mark_price"])
        self.assertTrue(aud["pnl_unavailable"])
        self.assertTrue(books["pms"]["pragmatist"]["pnl_unavailable"])

    def test_curve_family_lock_rejects_silent_switch(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "swinger", "actions": [_open(instrument="SOFR_2027-03", asset_class="rates", notional=50_000_000)]},
            pm_id="swinger",
            market_state=MARKET,
            run_id="r1",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        pos = books["pms"]["swinger"]["positions"][0]
        self.assertEqual(pos["locked_expression_family"], "sofr")
        with self.assertRaises(CurveLockError):
            apply_decision(
                books,
                {
                    "pm_id": "swinger",
                    "actions": [{
                        "action": "ADD",
                        "position_id": pos["position_id"],
                        "notional_usd": 10_000_000,
                        "paper_expression": {"type": "forward_swap", "curve_country": "US", "start_years": 2, "tenor_years": 2},
                    }],
                },
                pm_id="swinger",
                market_state=MARKET,
                run_id="r1",
                evidence_cutoff="c",
                review_packet_id="p",
                review_packet_sha256="h",
            )

    def test_missing_mark_fails_closed_on_open(self) -> None:
        with self.assertRaises(MarkError):
            apply_decision(
                empty_books(),
                {"pm_id": "chatgpt", "actions": [_open(instrument="NOFXPAIR")]},
                pm_id="chatgpt",
                market_state=MARKET,
                run_id="r1",
                evidence_cutoff="c",
                review_packet_id="p",
                review_packet_sha256="h",
            )

    def test_pm_books_have_zero_risk_funding_when_flat(self) -> None:
        book = empty_pm_book("grinder")
        marked = mark_pm_book(book)
        self.assertEqual(marked["funding_cost_usd"], 0.0)
        self.assertEqual(marked["cash_yield_usd"], 0.0)
        self.assertEqual(marked["funded_draw_usd"], 0.0)
        self.assertEqual(marked["unused_cash_usd"], marked["cash_capital_usd"])
        self.assertNotEqual(marked["gross_utilization_usd"], marked["cash_capital_usd"])
        self.assertEqual(marked["risk_capital_usd"], 0.0)
        self.assertEqual(marked["risk_capital_limit_usd"], RISK_CAPITAL_LIMIT_USD)
        self.assertEqual(marked["total_pnl_usd"], 0)
    def test_pm_hard_drawdown_forces_flat_and_blocks_reentry(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [_open(notional=10_000_000_000)]},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r-stop-open",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        book = books["pms"]["chatgpt"]
        self.assertEqual(book["risk_capital_usd"], RISK_CAPITAL_LIMIT_USD)
        book["positions"][0]["mark_price"] = 1.36 * 0.994
        mark_pm_book(book, run_id="r-stop-mark")
        self.assertTrue(book["risk_stopped"])
        self.assertEqual(book["decision_status"], "risk_stopped")
        self.assertEqual(book["positions"], [])
        self.assertAlmostEqual(book["realized_pnl_usd"], -60_000_000.0, places=2)
        self.assertGreaterEqual(book["drawdown_usd"], MAX_DRAWDOWN_USD)
        with self.assertRaises(CapError):
            apply_decision(
                books,
                {"pm_id": "chatgpt", "actions": [_open(notional=10_000_000)]},
                pm_id="chatgpt",
                market_state=MARKET,
                run_id="r-stop-reentry",
                evidence_cutoff="c2",
                review_packet_id="p2",
                review_packet_sha256="h2",
            )
        hold = apply_decision(
            books,
            {"pm_id": "chatgpt", "actions": [{"action": "HOLD"}], "thesis": "research continues"},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r-stop-hold",
            evidence_cutoff="c3",
            review_packet_id="p3",
            review_packet_sha256="h3",
        )
        held = hold["pms"]["chatgpt"]
        self.assertTrue(held["risk_stopped"])
        self.assertEqual(held["decision_status"], "risk_stopped")
        self.assertEqual(held["positions"], [])
        realized = held["realized_pnl_usd"]
        mark_pm_book(held, run_id="r-stop-repeat")
        mark_pm_book(held, run_id="r-stop-repeat-2")
        self.assertEqual(held["realized_pnl_usd"], realized)
        self.assertEqual(len([row for row in held["history"] if row.get("action") == "RISK_STOP"]), 1)

    def test_pm_exact_risk_cap_and_over_cap(self) -> None:
        ok = apply_decision(
            empty_books(),
            {"pm_id": "chatgpt", "actions": [_open(notional=10_000_000_000)]},
            pm_id="chatgpt",
            market_state=MARKET,
            run_id="r-cap-ok",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        self.assertEqual(ok["pms"]["chatgpt"]["risk_capital_usd"], RISK_CAPITAL_LIMIT_USD)
        with self.assertRaises(CapError):
            apply_decision(
                ok,
                {"pm_id": "chatgpt", "actions": [_open(instrument="AUDUSD", notional=1)]},
                pm_id="chatgpt",
                market_state=MARKET,
                run_id="r-cap-over",
                evidence_cutoff="c",
                review_packet_id="p",
                review_packet_sha256="h",
            )

    def test_pm_high_water_ratchets_then_stops_from_peak(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "swinger", "actions": [_open(notional=1_000_000_000)]},
            pm_id="swinger",
            market_state=MARKET,
            run_id="r-hw-open",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        book = books["pms"]["swinger"]
        book["positions"][0]["mark_price"] = 1.36 * 1.06
        mark_pm_book(book, run_id="r-hw-gain")
        peak = book["high_water_nav_usd"]
        self.assertGreater(peak, CASH_CAPITAL_USD)
        self.assertEqual(book["drawdown_usd"], 0.0)
        book["positions"][0]["mark_price"] = 1.36 * 1.06 * (1 - 0.055)
        mark_pm_book(book, run_id="r-hw-dd")
        self.assertEqual(book["high_water_nav_usd"], peak)
        self.assertGreaterEqual(book["drawdown_usd"], MAX_DRAWDOWN_USD)
        self.assertTrue(book["risk_stopped"])
        self.assertEqual(book["positions"], [])

    def test_pm_missing_exit_mark_pending_stop(self) -> None:
        books = apply_decision(
            empty_books(),
            {"pm_id": "pragmatist", "actions": [_open(notional=5_000_000_000), _open(instrument="AUDUSD", notional=100_000_000)]},
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r-pend-open",
            evidence_cutoff="c",
            review_packet_id="p",
            review_packet_sha256="h",
        )
        book = books["pms"]["pragmatist"]
        cad = next(p for p in book["positions"] if p["instrument"] == "USDCAD")
        aud = next(p for p in book["positions"] if p["instrument"] == "AUDUSD")
        cad["mark_price"] = 1.36 * 0.989
        aud["mark_price"] = None
        mark_pm_book(book, run_id="r-pend-stop")
        self.assertTrue(book["risk_stopped"])
        self.assertTrue(book["risk_stop_pending"])
        self.assertEqual(book["decision_status"], "risk_stopped")
        self.assertEqual(len(book["positions"]), 1)
        self.assertEqual(book["positions"][0]["instrument"], "AUDUSD")
        self.assertIsNone(book["positions"][0]["mark_price"])
        remaining = book["positions"][0]["position_id"]
        apply_action(
            book,
            {"action": "CLOSE", "position_id": remaining, "price": 0.66},
            run_id="r-pend-close",
        )
        self.assertEqual(book["positions"], [])
        self.assertTrue(book["risk_stopped"])
        after = apply_decision(
            books,
            {
                "pm_id": "pragmatist",
                "actions": [
                    {"action": "HOLD"},
                    _open(instrument="AUDUSD", notional=10_000_000),
                ],
            },
            pm_id="pragmatist",
            market_state=MARKET,
            run_id="r-pend-mixed",
            evidence_cutoff="c2",
            review_packet_id="p2",
            review_packet_sha256="h2",
        )
        mixed = after["pms"]["pragmatist"]
        self.assertTrue(mixed["risk_stopped"])
        self.assertEqual(mixed["decision_status"], "risk_stopped")
        self.assertEqual(mixed["positions"], [])
        self.assertTrue(any(row.get("result") == "blocked_risk_stop" for row in mixed["history"]))

    def test_canonical_pm_books_migrate_without_rewriting_trades(self) -> None:
        import json
        from pathlib import Path
        from scripts.pm.books import public_pm_view

        raw = json.loads((Path(__file__).resolve().parents[1] / "data" / "pm" / "books" / "latest.json").read_text())
        before = deepcopy(raw)
        validated = validate_books(deepcopy(raw))
        view = public_pm_view(deepcopy(raw))
        for pm_id, item in validated["pms"].items():
            orig = before["pms"][pm_id]
            self.assertEqual(item["risk_capital_limit_usd"], RISK_CAPITAL_LIMIT_USD)
            self.assertEqual(item["max_drawdown_usd"], MAX_DRAWDOWN_USD)
            self.assertEqual(item["realized_pnl_usd"], orig["realized_pnl_usd"])
            self.assertEqual(len(item["positions"]), len(orig["positions"]))
            self.assertLessEqual(item["risk_capital_usd"], item["risk_capital_limit_usd"])
            for pos, old in zip(item["positions"], orig["positions"]):
                self.assertEqual(pos["position_id"], old["position_id"])
                self.assertEqual(pos["notional_usd"], old["notional_usd"])
                self.assertIsNotNone(pos["risk_capital_usd"])
        self.assertIn("risk_capital_usd", view["pms"][0])
        self.assertIn("drawdown_usd", view["pms"][0])
        self.assertIn("risk_stopped", view["pms"][0])
        self.assertFalse(view["gross_notional_limit_enforced"])
        public_with_pos = next(row for row in view["pms"] if row["positions"])
        self.assertIn("risk_capital_usd", public_with_pos["positions"][0])


if __name__ == "__main__":
    unittest.main()
