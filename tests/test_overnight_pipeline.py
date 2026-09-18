#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.overnight.books import apply_action, empty_books, empty_seat, mark_to_market, position_pnl, public_books_view
from scripts.overnight.clock import overnight_run_id, stage_for_time, stage_window
from scripts.overnight.constants import SPOT_SEATS, STANDING_SEATS, STARTING_NAV_USD, UTC_CRON
from scripts.overnight.errors import EvidenceBoundaryError, FreshnessError, PublicationError, SchemaError
from scripts.overnight.expression import expression_rule, validate_expression_memo
from scripts.overnight.freshness import assert_action_allowed, publication_decision
from scripts.overnight.pipeline import dry_run, run_stage
from scripts.overnight.publish import publication_gate
from scripts.overnight.review import dry_run_reviews
from scripts.overnight.store import OvernightStore

NY = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 18, 12, 0, tzinfo=NY)


def _fresh_families() -> dict:
    return {
        "macro_hard": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "m"},
        "news": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "c"},
        "market_state": {"status": "fresh", "as_of": "2026-09-18T00:07:00-04:00", "digest": "s"},
    }


def _spot_memo(instrument: str = "USDCAD") -> dict:
    return {
        "rates_candidate": None,
        "spot_candidate": {"instrument": instrument, "asset_class": "spot_fx", "rationale": "spot"},
        "options_candidate": None,
        "selected": "spot",
        "rationale": "Dedicated spot seat.",
    }


def _rates_memo(selected: str = "rates") -> dict:
    return {
        "rates_candidate": {"instrument": "US 10Y", "asset_class": "rates", "rationale": "duration"},
        "spot_candidate": {"instrument": "USDJPY", "asset_class": "spot_fx", "rationale": "spot alt"},
        "options_candidate": None,
        "selected": selected,
        "rationale": "Rates-first comparison complete.",
    }


class ClockAndScheduleTests(unittest.TestCase):
    def test_run_id_is_ny_date(self):
        self.assertEqual(overnight_run_id(AS_OF), "overnight-20260918")
        self.assertTrue(overnight_run_id(AS_OF, dry_run=True, suffix="ci").startswith("overnight-20260918-dryrun-ci"))

    def test_stage_windows_avoid_top_of_hour(self):
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 0, 7, tzinfo=NY)), "collect")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 1, 40, tzinfo=NY)), "pre_trader_delta")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 1, 50, tzinfo=NY)), "freeze_evidence")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 2, 5, tzinfo=NY)), "trader_review")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 3, 35, tzinfo=NY)), "final_delta")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 3, 50, tzinfo=NY)), "assemble")
        self.assertEqual(stage_for_time(datetime(2026, 9, 18, 4, 7, tzinfo=NY)), "publish")
        self.assertIsNone(stage_for_time(datetime(2026, 9, 18, 0, 0, tzinfo=NY)))
        for stage, window in (
            ("collect", stage_window("collect", AS_OF)),
            ("publish", stage_window("publish", AS_OF)),
        ):
            self.assertFalse(window["et_time"].endswith(":00"), stage)
        self.assertEqual(len(UTC_CRON), 7)


class ExpressionRuleTests(unittest.TestCase):
    def test_spot_seats_and_rates_first_partition(self):
        self.assertEqual(set(SPOT_SEATS), {"dollar-king", "cross-merchant"})
        for seat in STANDING_SEATS:
            rule = expression_rule(seat)
            if seat in SPOT_SEATS:
                self.assertEqual(rule, "spot_only")
            else:
                self.assertEqual(rule, "rates_first")

    def test_spot_seat_cannot_select_rates(self):
        with self.assertRaises(SchemaError):
            validate_expression_memo(_rates_memo("rates"), seat="dollar-king", action="OPEN")

    def test_rates_first_must_compare_both(self):
        with self.assertRaises(SchemaError):
            validate_expression_memo(
                {
                    "rates_candidate": None,
                    "spot_candidate": {"instrument": "AUDUSD", "asset_class": "spot_fx", "rationale": "x"},
                    "options_candidate": None,
                    "selected": "spot",
                    "rationale": "missing rates compare",
                },
                seat="rate-hawk",
                action="OPEN",
            )
        validate_expression_memo(_rates_memo("rates"), seat="rate-hawk", action="OPEN")


class BookTransitionTests(unittest.TestCase):
    def setUp(self):
        self.seat = empty_seat("dollar-king")
        self.families = _fresh_families()

    def test_open_add_hold_reduce_hedge_close_and_pnl(self):
        apply_action(
            self.seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 10_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        pos = self.seat["positions"][0]
        pos["mark_price"] = 1.3736
        mark_to_market(self.seat)
        self.assertAlmostEqual(self.seat["unrealized_pnl_usd"], 100_000.0, places=1)
        self.assertAlmostEqual(self.seat["nav_usd"], STARTING_NAV_USD + 100_000.0, places=1)

        apply_action(
            self.seat,
            {
                "action": "ADD",
                "position_id": pos["position_id"],
                "notional_usd": 2_000_000,
                "price": 1.36,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertAlmostEqual(self.seat["positions"][0]["notional_usd"], 12_000_000)
        apply_action(
            self.seat,
            {"action": "HOLD", "expression_memo": _spot_memo()},
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        apply_action(
            self.seat,
            {
                "action": "HEDGE",
                "hedge_of": pos["position_id"],
                "notional_usd": 1_000_000,
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertEqual(len(self.seat["positions"]), 2)
        self.assertEqual(self.seat["positions"][1]["hedge_of"], pos["position_id"])
        apply_action(
            self.seat,
            {
                "action": "REDUCE",
                "position_id": pos["position_id"],
                "notional_usd": 2_000_000,
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertGreater(self.seat["realized_pnl_usd"], 0)
        apply_action(
            self.seat,
            {
                "action": "CLOSE",
                "position_id": pos["position_id"],
                "price": 1.3736,
                "expression_memo": _spot_memo(),
            },
            families=self.families,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertFalse(any(p["position_id"] == pos["position_id"] for p in self.seat["positions"]))
        self.assertEqual({row["action"] for row in self.seat["history"]}, {"OPEN", "ADD", "HOLD", "HEDGE", "REDUCE", "CLOSE"})

    def test_missing_mark_does_not_invent_pnl(self):
        pos = {
            "side": "long",
            "notional_usd": 5_000_000,
            "entry_price": 148.0,
            "mark_price": None,
            "asset_class": "spot_fx",
        }
        pnl = position_pnl(pos)
        self.assertTrue(pnl["pnl_unavailable"])
        self.assertIsNone(pnl["unrealized_pnl_usd"])


class FreshnessMatrixTests(unittest.TestCase):
    def test_stale_blocks_open_add_but_allows_hold_reduce_close(self):
        stale = _fresh_families()
        stale["news"]["status"] = "stale"
        assert_action_allowed("HOLD", stale, seat="dollar-king")
        assert_action_allowed("REDUCE", stale, seat="dollar-king")
        assert_action_allowed("CLOSE", stale, seat="dollar-king")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", stale, seat="dollar-king")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("ADD", stale, seat="dollar-king")

    def test_open_records_block_on_the_book(self):
        seat = empty_seat("dollar-king")
        stale = _fresh_families()
        stale["macro_hard"]["status"] = "stale"
        apply_action(
            seat,
            {
                "action": "OPEN",
                "instrument": "USDCAD",
                "side": "long",
                "notional_usd": 1_000_000,
                "price": 1.36,
                "asset_class": "spot_fx",
                "expression_memo": _spot_memo(),
            },
            families=stale,
            run_id="overnight-20260918-dryrun-t",
            when=AS_OF,
        )
        self.assertEqual(seat["positions"], [])
        self.assertEqual(seat["history"][-1]["result"], "blocked_freshness")

    def test_catastrophic_core_blocks_publish_stale_review_does_not(self):
        ok = publication_decision(families=_fresh_families(), trader_review_status="failed", last_successful_review_run_id="overnight-20260917")
        self.assertTrue(ok["may_publish"])
        self.assertEqual(ok["trader_books_status"], "failed")
        self.assertEqual(ok["last_successful_review_run_id"], "overnight-20260917")
        bad = _fresh_families()
        bad["news"]["status"] = "invalid"
        blocked = publication_decision(families=bad, trader_review_status="fresh")
        self.assertFalse(blocked["may_publish"])
        self.assertEqual(blocked["core_status"], "catastrophic_fail")


class PipelineDryRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="overnight-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_complete_dry_run_no_model_calls(self):
        result = dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="test")
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(result["dry_run"])
        self.assertEqual([row["status"] for row in result["stages"]], ["succeeded"] * 7)
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = result["overnight_run_id"]
        run = store.read_artifact(run_id, "run.json")
        self.assertEqual(run["overnight_run_id"], run_id)
        self.assertEqual(set(run["stages"]), set(UTC_CRON))
        snapshot = store.read_artifact(run_id, "evidence_snapshot.json")
        review = store.read_artifact(run_id, "trader_review.json")
        self.assertEqual(review["packet_sha256"], snapshot["packet_sha256"])
        self.assertFalse(review["full_trader_room"])
        self.assertEqual(review["model_calls"], 0)
        books = store.read_books()
        self.assertEqual(set(books["seats"]), set(STANDING_SEATS))
        self.assertGreater(len(books["seats"]["dollar-king"]["positions"]), 0)
        self.assertEqual(books["seats"]["dollar-king"]["positions"][0]["asset_class"], "spot_fx")
        self.assertEqual(books["seats"]["rate-hawk"]["positions"][0]["asset_class"], "rates")
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        self.assertEqual(dataset["trader_books"]["seat_count"], 14)
        self.assertTrue(dataset["publication"]["may_publish"])
        self.assertTrue(dataset["preservation"]["sep18_news_fixes"])
        view = public_books_view(books)
        self.assertIn("overnight_changes", view)

    def test_failed_review_still_publishes_stale(self):
        run_id = "overnight-20260918-dryrun-fail"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        store.write_artifact(
            run_id,
            "trader_review.json",
            {
                "schema_version": 1,
                "type": "OVERNIGHT_TRADER_REVIEW",
                "overnight_run_id": run_id,
                "status": "failed",
                "errors": ["cursor review crashed"],
                "model_calls": 0,
                "full_trader_room": False,
                "books": empty_books(overnight_run_id=run_id, when=AS_OF),
            },
        )
        store.write_books(empty_books(overnight_run_id="overnight-20260917", when=AS_OF))
        books = store.read_books()
        books["last_successful_review_run_id"] = "overnight-20260917"
        store.write_books(books)
        for stage in ("final_delta", "assemble"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        self.assertTrue(dataset["publication"]["may_publish"])
        self.assertEqual(dataset["publication"]["trader_books_status"], "failed")
        self.assertEqual(dataset["publication"]["last_successful_review_run_id"], "overnight-20260917")
        gate = publication_gate(store, run_id=run_id, require_dataset=True)
        self.assertTrue(gate["may_publish"])

    def test_catastrophic_news_fails_publication(self):
        result = dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="boom")
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = result["overnight_run_id"]
        dataset = store.read_artifact(run_id, "assembled_dataset.json")
        dataset["core"]["news"]["status"] = "invalid"
        dataset["publication"] = publication_decision(families={
            "macro_hard": dataset["core"]["macro_hard"],
            "news": dataset["core"]["news"],
            "central_bank_research": dataset["core"]["central_bank_research"],
            "market_state": dataset["core"]["market_state"],
        }, trader_review_status="fresh")
        store.write_artifact(run_id, "assembled_dataset.json", dataset)
        with self.assertRaises(PublicationError):
            publication_gate(store, run_id=run_id, require_dataset=True)

    def test_manage_scenario_add_reduce_hedge_close(self):
        first = dry_run(root=ROOT, state_root=self.tmp, when=AS_OF, suffix="open")
        store = OvernightStore(root=ROOT, state_root=self.tmp)
        run_id = first["overnight_run_id"]
        opened = store.read_books()
        hawk_id = opened["seats"]["rate-hawk"]["positions"][0]["position_id"]
        dollar_id = opened["seats"]["dollar-king"]["positions"][0]["position_id"]
        bull_id = opened["seats"]["perma-bull"]["positions"][0]["position_id"]
        trend_id = opened["seats"]["trend-follower"]["positions"][0]["position_id"]
        reviews = dry_run_reviews(scenario="manage")
        reviews["dollar-king"]["actions"][0]["position_id"] = dollar_id
        reviews["rate-hawk"]["actions"][0]["position_id"] = hawk_id
        reviews["perma-bull"]["actions"][0]["position_id"] = bull_id
        reviews["trend-follower"]["actions"][0]["position_id"] = trend_id
        reviews["trend-follower"]["actions"][0]["hedge_of"] = trend_id
        from scripts.overnight.review import run_trader_review

        result = run_trader_review(
            store,
            run_id=run_id,
            when=AS_OF,
            dry_run=False,
            live_reviews=reviews,
        )
        self.assertEqual(result["status"], "succeeded")
        books = store.read_books()
        self.assertAlmostEqual(books["seats"]["dollar-king"]["positions"][0]["notional_usd"], 12_000_000)
        self.assertAlmostEqual(books["seats"]["rate-hawk"]["positions"][0]["notional_usd"], 10_000_000)
        self.assertEqual(books["seats"]["perma-bull"]["positions"], [])
        self.assertTrue(any(p.get("hedge_of") == trend_id for p in books["seats"]["trend-follower"]["positions"]))

    def test_review_cannot_fetch_new_evidence(self):
        run_id = "overnight-20260918-dryrun-bound"
        for stage in ("collect", "pre_trader_delta", "freeze_evidence"):
            run_stage(stage, root=ROOT, state_root=self.tmp, run_id=run_id, when=AS_OF, dry_run=True)
        reviews = dry_run_reviews()
        reviews["dollar-king"]["web_search"] = True
        with self.assertRaises(EvidenceBoundaryError):
            run_stage(
                "trader_review",
                root=ROOT,
                state_root=self.tmp,
                run_id=run_id,
                when=AS_OF,
                dry_run=False,
                live_reviews=reviews,
            )


class TraderBookTabTests(unittest.TestCase):
    def test_tab_is_additive_and_keeps_existing_markers(self):
        html = """
        <style>
        #p-feed:checked~.app .nav label[for=p-feed],
        #p-marketdata:checked~.app .nav label[for=p-marketdata],
        {color:red}
        #p-feed:checked~.app .feed,
        #p-marketdata:checked~.app .marketdata,
        {display:block}
        </style>
        <input id="p-marketdata" name="page" type="radio"/>
        <input id="p-feed" name="page" type="radio"/>
        <label for="p-marketdata">Market Data</label>
        <label for="p-feed">Feed &amp; Momentum</label>
        <section class="page marketdata">Market Data · official snapshot</section>
        <section class="page relative"></section>
        <div>Last 24 Hours · Desk Summary</div>
        <div>7-Day Quick Digest</div>
        <div>Live 1–100 Score Board</div>
        """
        tmp = Path(tempfile.mkdtemp(prefix="tb-tab-"))
        self.addCleanup(shutil.rmtree, tmp)
        target = tmp / "index.html"
        target.write_text(html)
        from scripts.apply_trader_book_tab import apply_trader_book_tab

        apply_trader_book_tab(target, repo_root=ROOT)
        out = target.read_text()
        self.assertIn('id="p-traderbook"', out)
        self.assertIn("Trader Book · paper P&L", out)
        self.assertIn("Last 24 Hours · Desk Summary", out)
        self.assertIn("Live 1–100 Score Board", out)
        self.assertIn("Market Data · official snapshot", out)
        self.assertIn("7-Day Quick Digest", out)
        self.assertTrue((tmp / "trader-book.js").is_file())


class SeedBooksTests(unittest.TestCase):
    def test_repo_seed_has_fourteen_empty_books(self):
        books = json.loads((ROOT / "data" / "overnight" / "books" / "latest.json").read_text())
        self.assertEqual(set(books["seats"]), set(STANDING_SEATS))
        self.assertEqual(books["starting_nav_usd"], STARTING_NAV_USD)
        for seat in books["seats"].values():
            self.assertEqual(seat["positions"], [])
            self.assertEqual(seat["nav_usd"], STARTING_NAV_USD)


if __name__ == "__main__":
    unittest.main()
