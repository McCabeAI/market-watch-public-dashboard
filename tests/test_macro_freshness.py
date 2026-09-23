"""Offline fixtures for release-aware macro freshness.

These tests do not call trader or PM models and do not read live official
sources. They use the committed six-country ledger plus injected check results.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_freshness import (
    add_business_days,
    assess_macro_family,
    check_covers,
    is_non_business_day,
    macro_expression_block,
    release_due,
    roll_to_business_day,
)
from scripts.macro_source_refresh import (
    apply_verified_observation,
    parse_fred_csv,
    parse_statcan_vector_payload,
    refresh_macro_sources,
    relate_periods,
)
from scripts.overnight.clock import isoformat, parse_iso
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import REQUIRED_OPEN_FAMILIES
from scripts.overnight.errors import FreshnessError
from scripts.overnight.freshness import assert_action_allowed, publication_decision
from scripts.overnight.store import OvernightStore
from scripts.temperature_level import load_calibration, load_state

NY = ZoneInfo("America/New_York")
SEP18 = datetime(2026, 9, 18, 12, 0, tzinfo=NY)
SEP23 = datetime(2026, 9, 23, 0, 7, tzinfo=NY)
FROZEN_PACKET = "2c78eb3ff22353eab98e808cbd49cf4f29693c415744a9d4d6b28186f8ab9645"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _confirmed(when: datetime):
    stamp = isoformat(when)

    def fetch(entry: dict) -> dict:
        return {
            "ok": True,
            "check_result": "confirmed_unchanged",
            "checked_at": stamp,
            "reference_period": entry.get("latest_period"),
            "value": entry.get("latest_value"),
            "series_id": entry.get("series_id"),
            "source_url": entry.get("source_url"),
        }

    return fetch


def _families(macro: dict) -> dict:
    return {
        "macro_hard": macro,
        "news": {"status": "fresh", "as_of": isoformat(SEP23), "digest": "n"},
        "central_bank_research": {"status": "fresh", "as_of": isoformat(SEP23), "digest": "c"},
        "market_state": {"status": "fresh", "as_of": isoformat(SEP23), "digest": "s", "data": {}},
    }


class CalendarTests(unittest.TestCase):
    def test_weekend_and_holiday_do_not_consume_the_check_window(self) -> None:
        friday = datetime(2026, 9, 18, 0, 7, tzinfo=NY)
        self.assertEqual(friday.strftime("%A"), "Friday")
        self.assertTrue(check_covers(friday, datetime(2026, 9, 19, 12, 0, tzinfo=NY)))
        self.assertTrue(check_covers(friday, datetime(2026, 9, 21, 0, 7, tzinfo=NY)))
        self.assertFalse(check_covers(friday, datetime(2026, 9, 21, 18, 0, tzinfo=NY)))
        labor_day = datetime(2026, 9, 7, 0, 7, tzinfo=NY).date()
        self.assertTrue(is_non_business_day(labor_day))
        before = datetime(2026, 9, 4, 0, 7, tzinfo=NY)
        self.assertTrue(check_covers(before, datetime(2026, 9, 8, 0, 7, tzinfo=NY)))

    def test_release_due_on_saturday_rolls_to_monday(self) -> None:
        self.assertEqual(roll_to_business_day(datetime(2026, 9, 26).date()).isoformat(), "2026-09-28")
        entry = {"expected_release_date": "2026-09-26"}
        self.assertFalse(release_due(entry, datetime(2026, 9, 26, 12, 0, tzinfo=NY)))
        self.assertTrue(release_due(entry, datetime(2026, 9, 28, 0, 7, tzinfo=NY)))
        self.assertGreater(add_business_days(datetime(2026, 9, 21).date(), 12).isoformat(), "2026-09-26")


class LedgerFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scores = ROOT / "data" / "temperature_scores.json"
        self.calibration = ROOT / "data" / "temperature_calibration.json"
        self.scores_sha = _sha(self.scores)
        self.calibration_sha = _sha(self.calibration)

    def tearDown(self) -> None:
        self.assertEqual(_sha(self.scores), self.scores_sha)
        self.assertEqual(_sha(self.calibration), self.calibration_sha)
        self.assertEqual(load_calibration()["as_of"], "2026-09-21")

    def test_structural_anchor_is_not_the_sep18_freshness_clock(self) -> None:
        assessed = assess_macro_family(ROOT, when=SEP18)
        self.assertEqual(assessed["status"], "fresh")
        self.assertEqual(assessed["calibration_as_of"], "2026-09-21")
        self.assertNotEqual(assessed["as_of"], "2026-09-21")
        self.assertTrue(any(ch in str(assessed["as_of"]) for ch in ("T", "+")))
        self.assertEqual(assessed["model_calls"], 0)
        state = load_state()
        self.assertEqual(state["as_of"], "2026-09-21")
        self.assertEqual(state["last_refresh_date"], "2026-09-21")

    def test_sep23_without_a_new_check_is_not_stamped_fresh(self) -> None:
        at_collect = assess_macro_family(ROOT, when=SEP23)
        self.assertEqual(at_collect["calibration_as_of"], "2026-09-21")
        self.assertNotEqual(at_collect["as_of"], "2026-09-21")
        self.assertNotEqual(str(at_collect.get("as_of") or "")[:10], "2026-09-23")
        self.assertIn("US", at_collect["stale_countries"])
        self.assertIn("EA", at_collect["fresh_countries"])
        families = _families(at_collect)
        assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="EURJPY", asset_class="spot_fx")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD", asset_class="spot_fx")
        expired = assess_macro_family(ROOT, when=datetime(2026, 9, 23, 12, 0, tzinfo=NY))
        self.assertEqual(expired["status"], "stale")
        self.assertIsNone(expired["as_of"])
        self.assertEqual(expired["fresh_countries"], [])

    def test_no_release_due_on_the_next_several_days_when_checks_are_healthy(self) -> None:
        for day in ("2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"):
            when = datetime.fromisoformat(f"{day}T00:07:00-04:00")
            result = refresh_macro_sources(ROOT, when=when, fetcher=_confirmed(when), persist=False)
            self.assertEqual(result["status"], "fresh", msg=day)
            self.assertEqual(result["calibration_as_of"], "2026-09-21")
            self.assertEqual(result["ingested"], [])
            self.assertFalse(result["stale_countries"], msg=day)
            scored = [row for row in result["components"] if row.get("weight")]
            self.assertTrue(scored)
            self.assertTrue(all(not row["release_due"] for row in scored), msg=day)
            self.assertTrue(all(row["expected_release_date"] > "2026-09-26" for row in scored if row["expected_release_date"]))
            self.assertTrue(any(row["status"] == "explicit_gap" for row in result["components"]))
            confidence = next(row for row in result["components"] if row["id"] == "CA.Consumer.confidence")
            self.assertEqual(confidence["status"], "explicit_gap")
            self.assertIn("CA", result["fresh_countries"])

    def test_quiet_calendar_does_not_keep_an_old_check_fresh_for_days(self) -> None:
        early = refresh_macro_sources(ROOT, when=SEP23, fetcher=_confirmed(SEP23), persist=False)
        later = datetime(2026, 9, 26, 0, 7, tzinfo=NY)
        carried = {
            row["id"]: {
                "check_result": row["check_result"],
                "checked_at": row["checked_at"],
                "reference_period": row["reference_period"],
                "value": row["observation_value"],
                "ok": row["status"] == "fresh",
            }
            for row in early["components"]
            if row.get("checked_at")
        }
        aged = assess_macro_family(ROOT, when=later, checks=carried)
        self.assertNotEqual(aged["status"], "fresh")
        self.assertIn("US", aged["stale_countries"])

    def test_due_release_missed_blocks_only_that_country(self) -> None:
        when = SEP23
        result = refresh_macro_sources(
            ROOT,
            when=when,
            fetcher=_confirmed(when),
            persist=False,
            due_overrides={"US.Labor.unemployment": "2026-09-22"},
        )
        missed = next(row for row in result["components"] if row["id"] == "US.Labor.unemployment")
        self.assertEqual(missed["status"], "due_missing")
        self.assertEqual(missed["reference_period"], "2026-08")
        self.assertIn("US", result["stale_countries"])
        self.assertNotIn("AU", result["stale_countries"])
        self.assertNotIn("NZ", result["stale_countries"])
        self.assertEqual(result["status"], "fresh")
        families = _families(result)
        assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="AUDNZD", asset_class="spot_fx")
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="AONIA_2026-11", asset_class="rates")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD", asset_class="spot_fx")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="US 10Y", asset_class="rates")

    def test_failed_source_and_partial_transform_stay_visible(self) -> None:
        when = SEP23

        def fetch(entry: dict) -> dict:
            if entry["id"] == "CA.Labor.unemployment":
                raise TimeoutError("statcan timed out")
            if entry["id"] == "US.Inflation.core_pce":
                return {
                    "ok": True,
                    "points": [("2026-08", 131.0), ("2026-09", 131.4)],
                    "transformation": "source_level",
                    "series_id": "PCEPILFE",
                }
            return _confirmed(when)(entry)

        result = refresh_macro_sources(ROOT, when=when, fetcher=fetch, persist=False, ingest=False)
        canada = next(row for row in result["components"] if row["id"] == "CA.Labor.unemployment")
        pce = next(row for row in result["components"] if row["id"] == "US.Inflation.core_pce")
        self.assertEqual(canada["status"], "unavailable")
        self.assertIn("timed out", str(canada["error"]))
        self.assertEqual(pce["status"], "partial")
        self.assertEqual(result["ingested"], [])
        self.assertIn("CA", result["stale_countries"])
        self.assertIn("US", result["stale_countries"])
        self.assertNotIn("AU", result["stale_countries"])
        families = _families(result)
        assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="AUDNZD", asset_class="spot_fx")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="carry-is-king", instrument="CORRA_2027-03", asset_class="rates")

    def test_unexpected_revision_is_not_written_into_the_ledger(self) -> None:
        when = SEP23
        before = json.loads((ROOT / "data" / "temperature_history" / "us.json").read_text(encoding="utf-8"))

        def fetch(entry: dict) -> dict:
            if entry["id"] == "US.Labor.unemployment":
                return {
                    "ok": True,
                    "reference_period": entry["latest_period"],
                    "value": float(entry["latest_value"]) + 1.5,
                }
            return _confirmed(when)(entry)

        result = refresh_macro_sources(ROOT, when=when, fetcher=fetch, persist=False)
        row = next(item for item in result["components"] if item["id"] == "US.Labor.unemployment")
        self.assertEqual(row["status"], "unexpected_change")
        self.assertEqual(result["ingested"], [])
        after = json.loads((ROOT / "data" / "temperature_history" / "us.json").read_text(encoding="utf-8"))
        self.assertEqual(before, after)
        self.assertIn("US", result["stale_countries"])

    def test_verified_new_release_updates_only_that_series(self) -> None:
        when = SEP23
        before = load_state()

        def fetch(entry: dict) -> dict:
            if entry["id"] == "US.Labor.unemployment":
                return {
                    "ok": True,
                    "reference_period": "2026-09",
                    "value": 6.5,
                    "transformation": "percent",
                    "series_id": "UNRATE",
                    "source_url": entry.get("source_url"),
                }
            return _confirmed(when)(entry)

        result = refresh_macro_sources(ROOT, when=when, fetcher=fetch, persist=False)
        self.assertEqual(result["ingested"], ["US.Labor.unemployment"])
        state = result["score_state"]
        self.assertEqual(state["as_of"], "2026-09-21")
        self.assertEqual(state["last_refresh_date"], "2026-09-21")
        self.assertNotEqual(state["countries"]["US"]["Labor"]["level"], before["countries"]["US"]["Labor"]["level"])
        self.assertEqual(state["countries"]["US"]["Labor"]["components"], before["countries"]["US"]["Labor"]["components"])
        self.assertEqual(state["countries"]["US"]["Inflation"]["level"], before["countries"]["US"]["Inflation"]["level"])
        self.assertEqual(state["countries"]["CA"]["Labor"]["level"], before["countries"]["CA"]["Labor"]["level"])
        self.assertEqual(state["countries"]["US"]["Labor"]["coverage"], before["countries"]["US"]["Labor"]["coverage"])
        updated = next(row for row in result["components"] if row["id"] == "US.Labor.unemployment")
        self.assertEqual(updated["reference_period"], "2026-09")
        self.assertEqual(updated["series_id"], "UNRATE")
        self.assertNotEqual(updated["checked_at"], "2026-09-21")

        again = apply_verified_observation(
            {"US": json.loads((ROOT / "data" / "temperature_history" / "us.json").read_text(encoding="utf-8"))},
            {"country": "US", "history_key": "Labor.unemployment", "series_id": "UNRATE", "source_transformation": "percent"},
            {"reference_period": "2026-08", "value": 1.0, "transformation": "percent", "series_id": "UNRATE", "checked_at": isoformat(when)},
        )
        self.assertFalse(again)

    def test_same_session_catch_up_is_idempotent_and_a_later_session_rechecks(self) -> None:
        calls = {"n": 0}

        def fetch(entry: dict) -> dict:
            calls["n"] += 1
            return _confirmed(SEP23)(entry)

        first = refresh_macro_sources(ROOT, when=SEP23, fetcher=fetch, persist=False)
        first_calls = calls["n"]
        self.assertGreater(first_calls, 0)
        second = refresh_macro_sources(ROOT, when=SEP23, fetcher=fetch, persist=False, prior=first)
        self.assertEqual(calls["n"], first_calls)
        self.assertEqual(second["status"], "fresh")
        self.assertEqual(second["ingested"], [])
        calls["n"] = 0
        monday = datetime(2026, 9, 28, 0, 7, tzinfo=NY)
        refresh_macro_sources(ROOT, when=monday, fetcher=fetch, persist=False, prior=first)
        self.assertGreater(calls["n"], 0)

    def test_delayed_friday_check_covers_weekend_then_monday_catch_up_refreshes(self) -> None:
        friday = datetime(2026, 9, 18, 0, 7, tzinfo=NY)
        friday_result = refresh_macro_sources(ROOT, when=friday, fetcher=_confirmed(friday), persist=False)
        carried = {
            row["id"]: {
                "check_result": "confirmed_unchanged",
                "checked_at": row["checked_at"],
                "reference_period": row["reference_period"],
                "value": row["observation_value"],
                "ok": True,
            }
            for row in friday_result["components"]
            if row.get("status") == "fresh"
        }
        weekend = assess_macro_family(ROOT, when=datetime(2026, 9, 19, 15, 0, tzinfo=NY), checks=carried)
        self.assertEqual(weekend["status"], "fresh")
        self.assertEqual(weekend["calibration_as_of"], "2026-09-21")
        stale_monday = assess_macro_family(ROOT, when=datetime(2026, 9, 21, 18, 0, tzinfo=NY), checks=carried)
        self.assertNotEqual(stale_monday["status"], "fresh")
        caught_up = refresh_macro_sources(
            ROOT,
            when=datetime(2026, 9, 21, 18, 0, tzinfo=NY),
            fetcher=_confirmed(datetime(2026, 9, 21, 18, 0, tzinfo=NY)),
            persist=False,
        )
        self.assertEqual(caught_up["status"], "fresh")
        self.assertEqual(caught_up["ingested"], [])

    def test_collect_uses_the_release_check_before_freeze_inputs(self) -> None:
        self.assertIn("macro_hard", REQUIRED_OPEN_FAMILIES)
        with tempfile.TemporaryDirectory() as tmp:
            store = OvernightStore(root=ROOT, state_root=Path(tmp))
            collected = collect_inputs(
                store,
                when=SEP23,
                run_id="overnight-20260923-macro-test",
                offline=True,
                refresh_macro=True,
                macro_fetcher=_confirmed(SEP23),
                persist_macro=False,
            )
        macro = collected["families"]["macro_hard"]
        self.assertEqual(macro["status"], "fresh")
        self.assertEqual(macro["calibration_as_of"], "2026-09-21")
        self.assertNotEqual(macro["as_of"], "2026-09-21")
        self.assertTrue(macro["components"])
        self.assertEqual(macro["ingested"], [])
        families = _families(macro)
        assert_action_allowed("OPEN", families, seat="dollar-king", instrument="USDCAD", asset_class="spot_fx")
        blocked = publication_decision(families={**families, "news": {"status": "stale", "as_of": None, "digest": "n"}}, trader_review_status="fresh")
        self.assertFalse(blocked["may_publish"])
        curve = _families(macro)
        curve["market_state"] = {
            "status": "fresh",
            "data": {"rates": {"US": {"status": "stale"}}, "fx": {"status": "ok"}},
        }
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", curve, seat="dollar-king", instrument="EURUSD", asset_class="spot_fx")

    def test_missing_preserved_component_blocks_only_its_country_when_due(self) -> None:
        result = refresh_macro_sources(
            ROOT,
            when=SEP23,
            fetcher=_confirmed(SEP23),
            persist=False,
            due_overrides={"AU.Consumer.retail": "2026-09-22"},
        )
        retail = next(row for row in result["components"] if row["id"] == "AU.Consumer.retail")
        self.assertEqual(retail["status"], "due_missing")
        self.assertIn("AU", result["stale_countries"])
        self.assertNotIn("US", result["stale_countries"])
        families = _families(result)
        assert_action_allowed("OPEN", families, seat="rate-hawk", instrument="US 10Y", asset_class="rates")
        with self.assertRaises(FreshnessError):
            assert_action_allowed("OPEN", families, seat="cross-merchant", instrument="AUDNZD", asset_class="spot_fx")
        self.assertIsNone(macro_expression_block(families, instrument="US 10Y"))


class FrozenSessionTests(unittest.TestCase):
    def test_sep23_immutable_evidence_survives_review_acceptance(self) -> None:
        # Review status and latest books legitimately advance when trusted
        # acceptance merges. Pin the immutable frozen evidence instead of
        # treating mutable operational state as a fixture.
        review_path = ROOT / "data" / "overnight" / "runs" / "overnight-20260923" / "reviews" / "review-001" / "review.json"
        index_path = ROOT / "data" / "overnight" / "runs" / "overnight-20260923" / "reviews" / "index.json"
        snapshot_path = ROOT / "data" / "overnight" / "runs" / "overnight-20260923" / "reviews" / "review-001" / "evidence_snapshot.json"
        books_path = ROOT / "data" / "overnight" / "books" / "latest.json"
        pm_path = ROOT / "data" / "pm" / "books" / "latest.json"

        review = json.loads(review_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(review["review_id"], "review-001")
        self.assertEqual(review["overnight_run_id"], "overnight-20260923")
        self.assertIn(review["status"], {"frozen", "accepted"})
        self.assertTrue(review["immutable"])
        self.assertEqual(review["packet_sha256"], FROZEN_PACKET)
        self.assertEqual(
            _sha(snapshot_path),
            "41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b",
        )

        indexed_review = next(
            item for item in index["reviews"] if item["review_id"] == "review-001"
        )
        for field in (
            "packet_sha256",
            "frozen_at",
            "starting_trader_books_sha256",
            "starting_pm_books_sha256",
            "status",
        ):
            self.assertEqual(review[field], indexed_review[field])
        if review["status"] == "accepted":
            self.assertTrue(review["accepted_at"])
            self.assertTrue(review["agent_packet_sha256"])
            self.assertEqual(review["accepted_at"], indexed_review["accepted_at"])
            self.assertEqual(
                review["agent_packet_sha256"], indexed_review["agent_packet_sha256"]
            )
        else:
            self.assertIsNone(review["accepted_at"])
            self.assertIsNone(review["agent_packet_sha256"])

        # The latest operational books can move forward with trusted daily
        # runs. When they point at this accepted review, verify their binding
        # without pinning mutable book bytes to yesterday's baseline.
        books = json.loads(books_path.read_text(encoding="utf-8"))
        pm = json.loads(pm_path.read_text(encoding="utf-8"))
        if books.get("last_successful_review_run_id") == "overnight-20260923":
            self.assertEqual(review["status"], "accepted")
            self.assertEqual(books["last_successful_review_id"], "review-001")
        if pm.get("last_successful_automated_pm_run_id") == "overnight-20260923":
            self.assertEqual(review["status"], "accepted")
            self.assertEqual(pm["last_successful_review_id"], "review-001")

class ParserTests(unittest.TestCase):
    def test_fred_and_statcan_fixtures_keep_period_and_value(self) -> None:
        rows = parse_fred_csv("observation_date,UNRATE\n2026-08-01,4.3\n2026-09-01,4.1\n")
        self.assertEqual(rows[-1], ("2026-09", 4.1))
        parsed = parse_statcan_vector_payload(
            [{"object": {"vectorDataPoint": [{"refPer": "2026-08-01", "value": 6.5}]}}]
        )
        self.assertEqual(parsed, [("2026-08", 6.5)])
        self.assertEqual(relate_periods("2026-04", "2026-Q2"), "same")
        self.assertEqual(relate_periods("2026-07", "2026-Q2"), "newer")
        self.assertEqual(relate_periods("2026-03", "2026-Q2"), "older")
        self.assertIsNotNone(parse_iso("2026-09-21T14:41:19Z"))


class ScoreCutoffTests(unittest.TestCase):
    def test_disk_scores_remain_the_engine_output(self) -> None:
        state = load_state()
        self.assertEqual(state["as_of"], "2026-09-21")
        self.assertEqual(state["countries"]["US"]["Labor"]["level"], 52.8)


if __name__ == "__main__":
    unittest.main()
