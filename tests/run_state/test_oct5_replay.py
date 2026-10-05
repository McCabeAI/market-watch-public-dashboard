"""N02 first milestone: Oct 5 offline replay packet consistency."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.run_state.replay import (
    LABOR_SERIES,
    reject_unequal_score_copies,
    replay_october5,
)
from scripts.run_state.schema import sha256_json

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "run_state"
OCT5_INCIDENT = FIXTURES / "oct5" / "incident.json"
CUTOFF = "2026-10-05T06:08:21.051325-04:00"


class Oct5ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(OCT5_INCIDENT.read_text(encoding="utf-8"))
        cls.packet = replay_october5(cls.fixture)

    def test_reject_unequal_score_copies_raises(self) -> None:
        copy_a = {"id": "score_copy_a", "level": 50}
        copy_b = {"id": "score_copy_b", "level": 51}
        payload = {"temperature_scores": copy_a, "extra": {"temperature_scores": copy_b}}
        with self.assertRaises(ValueError):
            reject_unequal_score_copies(payload)

    def test_labor_primary_timeout_preserved_in_merge(self) -> None:
        by_id = {row["series_id"]: row for row in self.packet["merged_rows"]}
        for sid in LABOR_SERIES:
            row = by_id[sid]
            self.assertEqual(row["error"], "timed out")
            history = row.get("attempt_history") or []
            self.assertTrue(any(entry.get("result") == "timeout" for entry in history))

    def test_labor_retry_is_skip_not_attempt(self) -> None:
        attempt_series = {doc["series_id"] for doc in self.packet["attempts"]}
        self.assertEqual(attempt_series, set(LABOR_SERIES))
        for doc in self.packet["attempts"]:
            self.assertEqual(doc["kind"], "primary")
            self.assertEqual(doc["result"], "timeout")
        self.assertEqual(len(self.packet["scheduler_events"]), 3)
        for event in self.packet["scheduler_events"]:
            self.assertEqual(event["kind"], "skipped_retry")
            self.assertEqual(event["reason"], "budget_deferred")
            self.assertTrue(event.get("related_attempt_id"))

    def test_expectation_period_and_occurred(self) -> None:
        for exp in self.packet["expectations"]:
            self.assertEqual(exp["expected_period"], "2026-09")
            self.assertTrue(exp["scheduled_release_occurred_by_cutoff"])

    def test_gate_country_split(self) -> None:
        gate = self.packet["gate"]
        self.assertEqual(gate["outcome"], "PASS")
        self.assertIn("macro:US", gate["blocked_expressions"])
        self.assertEqual(gate["trade_eligible_countries"], ["CA", "AU", "NZ", "EA", "JP"])
        self.assertFalse(gate["countries"]["US"]["eligible"])
        for code in ("CA", "AU", "NZ", "EA", "JP"):
            self.assertTrue(gate["countries"][code]["eligible"])

    def test_single_score_hash(self) -> None:
        scores = self.packet["temperature_scores"]
        self.assertEqual(self.packet["score_state_sha256"], sha256_json(scores))

    def test_gate_and_freeze_cutoff_match_fixture(self) -> None:
        self.assertEqual(self.packet["cutoff_at"], CUTOFF)
        self.assertEqual(self.packet["freeze_cutoff"], CUTOFF)
        self.assertEqual(self.packet["gate"]["cutoff_at"], CUTOFF)
        self.assertEqual(self.packet["gate"]["freeze_cutoff"], CUTOFF)

    def test_public_caveat_blocked_us_not_not_due(self) -> None:
        caveat = self.packet["public_caveat"] or ""
        self.assertNotIn("no new release was due", caveat)
        self.assertIn("New risk stays restricted in US", caveat)
        self.assertIn("due release could not be verified", caveat)

    def test_policy_version(self) -> None:
        self.assertEqual(self.packet["policy_version"], "quality-policy/1")


if __name__ == "__main__":
    unittest.main()
