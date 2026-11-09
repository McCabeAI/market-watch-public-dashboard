"""Regression: US SR1 must not invent 0% for a missing predecessor (Nov 9 2026 vintage)."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date
from pathlib import Path

from scripts.policy_meeting_pricing import (
    _sr1_month_pre_meeting_known_sum,
    build_policy_meeting_prices,
)

EVIDENCE = Path(
    "data/overnight/runs/overnight-20261109/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_PACKET_SHA256 = (
    "36b651b69a9e2951d8f7c97819999a9354668967f97c455af200a46c3662fb11"
)

FOMC_ROWS = (
    "2026-12-09",
    "2027-01-27",
    "2027-03-17",
    "2027-04-28",
    "2027-06-09",
)


class Sr1PredecessorKnownSumTests(unittest.TestCase):
    def test_missing_prev_post_sofr_fails_without_zero_fill(self) -> None:
        obs = date(2026, 11, 9)
        fixings = [(date(2026, 11, 7), 3.92), (date(2026, 11, 6), 3.91)]
        month_start = date(2027, 3, 1)
        month_end = date(2027, 4, 1)
        k_eff = date(2027, 3, 18)
        prev_eff = date(2027, 1, 28)
        total, ok = _sr1_month_pre_meeting_known_sum(
            month_start=month_start,
            month_end=month_end,
            k_eff=k_eff,
            observation_date=obs,
            fixings_sorted=fixings,
            f_baseline=4.15,
            prev_meeting_eff=prev_eff,
            prev_f_sofr_post=None,
            unsolved_predecessor_eff=prev_eff,
        )
        self.assertFalse(ok)
        self.assertEqual(total, 0.0)


class Nov9FomcSr1RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with EVIDENCE.open(encoding="utf-8") as handle:
            cls.evidence = json.load(handle)
        cls.ms = cls.evidence["families"]["market_state"]["data"]
        cls.policy_paths = cls.ms["policy_paths"]
        with Path("data/policy_state.json").open(encoding="utf-8") as handle:
            cls.policy_state = json.load(handle)
        with Path("data/policy_meetings.json").open(encoding="utf-8") as handle:
            cls.calendar = json.load(handle)

    def test_evidence_packet_unchanged(self) -> None:
        before = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
        self.assertEqual(
            self.evidence.get("packet_sha256"),
            EXPECTED_PACKET_SHA256,
        )
        after = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
        self.assertEqual(before, after, "evidence_snapshot.json must not be rewritten")

    def test_nov9_us_path_no_phantom_after_january_gap(self) -> None:
        as_of = date(2026, 11, 9)
        snapshot = build_policy_meeting_prices(
            as_of=as_of,
            calendar=self.calendar,
            policy_state=self.policy_state,
            policy_paths=self.policy_paths,
        )
        us = snapshot["banks"]["US"]
        by_decision = {m["decision_date"]: m for m in us["meetings"]}

        jan = by_decision["2027-01-27"]
        self.assertEqual(jan["method"], "unavailable")
        self.assertIsNone(jan["post_rate"])

        mar = by_decision["2027-03-17"]
        self.assertEqual(mar["method"], "unavailable")
        self.assertIsNone(mar["post_rate"])
        self.assertIsNone(mar["incremental_bp"])
        self.assertIsNone(mar["cumulative_bp"])
        self.assertIn("underdetermined", (mar.get("reason") or "").lower())
        if mar.get("post_rate") is not None:
            self.fail("March post must be absent")
        post = mar.get("post_rate")
        if post is not None:
            self.assertNotAlmostEqual(post, 9.26, places=1)
        cum = mar.get("cumulative_bp")
        if cum is not None:
            self.assertNotAlmostEqual(cum, 538.0, delta=5.0)
        inc = mar.get("incremental_bp")
        if inc is not None:
            self.assertNotAlmostEqual(inc, 516.0, delta=5.0)

        dec = by_decision["2026-12-09"]
        self.assertEqual(dec["method"], "identified")
        self.assertIsNotNone(dec["post_rate"])
        self.assertLess(dec["post_rate"], 6.0)
        self.assertLess(abs(dec["cumulative_bp"]), 100.0)

        gap_started = False
        for decision_date in sorted(by_decision):
            row = by_decision[decision_date]
            if _parse_future(as_of, row["effective_date"]) is False:
                continue
            if decision_date == "2027-01-27":
                gap_started = True
                continue
            if gap_started and decision_date > "2027-01-27":
                self.assertEqual(
                    row["method"],
                    "unavailable",
                    f"{decision_date} must be unavailable after January gap",
                )
                self.assertIsNone(row["post_rate"])
                self.assertIsNone(row["incremental_bp"])
                self.assertIsNone(row["cumulative_bp"])

    def test_repriced_row_snapshot_for_report(self) -> None:
        """Materialize rows requested in worker handoff (not asserted here)."""
        as_of = date(2026, 11, 9)
        snapshot = build_policy_meeting_prices(
            as_of=as_of,
            calendar=self.calendar,
            policy_state=self.policy_state,
            policy_paths=self.policy_paths,
        )
        by_decision = {
            m["decision_date"]: m for m in snapshot["banks"]["US"]["meetings"]
        }
        cls = type(self)
        cls._report_rows = {
            d: {
                "method": by_decision[d].get("method"),
                "post_rate": by_decision[d].get("post_rate"),
                "incremental_bp": by_decision[d].get("incremental_bp"),
                "cumulative_bp": by_decision[d].get("cumulative_bp"),
                "reason": by_decision[d].get("reason"),
            }
            for d in FOMC_ROWS
            if d in by_decision
        }


def _parse_future(as_of: date, eff_s: str) -> bool:
    return date.fromisoformat(eff_s) > as_of


if __name__ == "__main__":
    unittest.main()
