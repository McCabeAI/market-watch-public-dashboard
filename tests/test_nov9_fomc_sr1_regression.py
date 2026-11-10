"""Regression: US SR1 cross-month identification for Jan 2027 and onward path (Nov 9 vintage)."""

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
        cls.us_contracts = cls.policy_paths["countries"]["US"]["contracts_1m"]
        with Path("data/policy_state.json").open(encoding="utf-8") as handle:
            cls.policy_state = json.load(handle)
        with Path("data/policy_meetings.json").open(encoding="utf-8") as handle:
            cls.calendar = json.load(handle)

    def _snapshot(self) -> dict:
        return build_policy_meeting_prices(
            as_of=date(2026, 11, 9),
            calendar=self.calendar,
            policy_state=self.policy_state,
            policy_paths=self.policy_paths,
        )

    def test_evidence_packet_unchanged(self) -> None:
        before = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
        self.assertEqual(
            self.evidence.get("packet_sha256"),
            EXPECTED_PACKET_SHA256,
        )
        after = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
        self.assertEqual(before, after, "evidence_snapshot.json must not be rewritten")

    def test_november_sr1_contracts_match_evidence(self) -> None:
        by_exp = {str(c["expiry"]): float(c["implied_rate"]) for c in self.us_contracts}
        self.assertAlmostEqual(by_exp["2026-12"], 4.04, places=4)
        self.assertAlmostEqual(by_exp["2027-01"], 4.1125, places=4)
        self.assertAlmostEqual(by_exp["2027-02"], 4.1475, places=4)
        for exp in ("2026-12", "2027-01", "2027-02"):
            obs = next(
                c.get("observation_date") for c in self.us_contracts if c["expiry"] == exp
            )
            self.assertEqual(obs, "2026-11-09")

    def test_january_cross_month_estimated_with_strip_residual(self) -> None:
        snapshot = self._snapshot()
        us = snapshot["banks"]["US"]
        by_decision = {m["decision_date"]: m for m in us["meetings"]}

        dec = by_decision["2026-12-09"]
        self.assertEqual(dec["method"], "identified")
        self.assertAlmostEqual(dec["sofr_post_rate"], 4.1041, places=4)

        jan = by_decision["2027-01-27"]
        self.assertEqual(jan["method"], "estimated")
        self.assertAlmostEqual(jan["sofr_post_rate"], 4.1475, places=4)
        self.assertAlmostEqual(jan["strip_identity_residual_bp"], -0.28, places=2)
        self.assertIsNotNone(jan.get("estimate_note"))
        self.assertEqual(jan.get("n_post"), 4)

        by_exp = {str(c["expiry"]): float(c["implied_rate"]) for c in self.us_contracts}
        f_jan = by_exp["2027-01"]
        recon_avg = f_jan + jan["strip_identity_residual_bp"] / 100.0
        self.assertAlmostEqual(f_jan, 4.1125, places=4)
        self.assertAlmostEqual(recon_avg, 4.1097, places=3)
        self.assertAlmostEqual(by_exp["2027-02"], jan["sofr_post_rate"], places=4)

        self.assertAlmostEqual(jan["incremental_bp"], 4.34, places=2)
        self.assertLess(abs(jan["cumulative_bp"]), 50.0)

    def test_march_onward_identified_without_phantom_tail(self) -> None:
        snapshot = self._snapshot()
        us = snapshot["banks"]["US"]
        by_decision = {m["decision_date"]: m for m in us["meetings"]}

        mar = by_decision["2027-03-17"]
        self.assertEqual(mar["method"], "identified")
        self.assertIsNotNone(mar["post_rate"])
        self.assertLess(abs(mar.get("cumulative_bp") or 0.0), 100.0)
        self.assertNotAlmostEqual(mar.get("cumulative_bp") or 0.0, 538.0, delta=5.0)

        jun = by_decision["2027-06-09"]
        self.assertEqual(jun["method"], "identified")
        self.assertIsNotNone(jun["post_rate"])

    def test_us_bank_status_ok_when_future_path_identified(self) -> None:
        snapshot = self._snapshot()
        us = snapshot["banks"]["US"]
        self.assertEqual(us["status"], "ok")
        future = [
            m
            for m in us["meetings"]
            if date.fromisoformat(m["effective_date"]) > date(2026, 11, 9)
        ]
        self.assertTrue(
            all(m["method"] in {"identified", "estimated"} for m in future),
            "no future FOMC step should be unavailable after Jan cross-month fix",
        )


if __name__ == "__main__":
    unittest.main()
