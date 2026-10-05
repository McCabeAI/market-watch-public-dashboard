from __future__ import annotations

import unittest

from scripts.run_state.policy import evaluate_policy, reject_post_cutoff
from scripts.run_state.scores import ScoreConflict, bind_scores
from scripts.run_state.schema import (
    SCHEMA_RELEASE_EXPECTATION,
    ContractError,
    expectation_id_from_body,
)
from scripts.run_state.state import assemble_series_run_state
from scripts.temperature_level import component_level


class PolicyScoresTests(unittest.TestCase):
    RUN_ID = "mwl-20261005T100821Z-3f9807cb"

    def _labor_state(self, series_suffix: str, *, reason: str, country: str = "US") -> dict:
        series_id = f"{country}.Labor.{series_suffix}"
        return {
            "run_id": self.RUN_ID,
            "series_id": series_id,
            "state_id": f"{self.RUN_ID}:{series_id}",
            "country": country,
            "trade_critical": True,
            "carry_forward_reason": reason,
        }

    def test_oct5_labor_blocks_only_us(self) -> None:
        states = [
            self._labor_state("payrolls", reason="overdue_unverified"),
            self._labor_state("unemployment", reason="overdue_unverified"),
            self._labor_state("wages", reason="overdue_unverified"),
            self._labor_state("employment", reason="old_but_current", country="CA"),
        ]
        policy = evaluate_policy(states)
        self.assertEqual(policy["blocked_expressions"], ["macro:US"])
        self.assertIn("CA", policy["trade_eligible_countries"])
        self.assertTrue(policy["countries"]["CA"]["eligible"])
        self.assertFalse(policy["countries"]["US"]["eligible"])

    def test_unknown_calendar_listed_not_blocking(self) -> None:
        series_id = "NZ.Inflation.cpi"
        state = {
            "run_id": self.RUN_ID,
            "series_id": series_id,
            "state_id": f"{self.RUN_ID}:{series_id}",
            "country": "NZ",
            "trade_critical": True,
            "carry_forward_reason": "unknown_calendar",
        }
        policy = evaluate_policy([state])
        self.assertIn(series_id, policy["unknown_calendar_series"])
        self.assertEqual(policy["blocked_expressions"], [])
        self.assertTrue(policy["countries"]["NZ"]["eligible"])
        self.assertEqual(policy["carry_forward_reasons"][state["state_id"]], "unknown_calendar")

    def test_bind_scores_matches_component_level(self) -> None:
        spec = {"hot_direction": 1, "anchor": 0, "scale_per_unit": 1}
        cal = {"score_min": 1, "score_max": 100}
        obs = {
            "series_id": "US.Labor.payrolls",
            "observation_id": "ov_test",
            "value": 0,
            "component_spec": spec,
            "calibration": cal,
        }
        bound = bind_scores(observations=[obs])
        expected = component_level(0, spec, cal)
        self.assertEqual(bound["components"][0]["level"], expected)
        self.assertEqual(bound["components"][0]["level"], 50.0)

    def test_failed_observation_does_not_change_score_hash(self) -> None:
        spec = {"hot_direction": 1, "anchor": 0, "scale_per_unit": 1}
        cal = {"score_min": 1, "score_max": 100}
        good = {
            "series_id": "US.Labor.payrolls",
            "observation_id": "ov_good",
            "value": 0,
            "component_spec": spec,
            "calibration": cal,
        }
        first = bind_scores(observations=[good])
        second = bind_scores(
            observations=[
                good,
                {
                    "series_id": "US.Labor.unemployment",
                    "observation_id": "ov_fail",
                    "value": 1,
                    "component_spec": spec,
                    "calibration": cal,
                    "use_for_score": False,
                },
            ]
        )
        self.assertEqual(first["score_state_sha256"], second["score_state_sha256"])

    def test_reject_post_cutoff(self) -> None:
        cutoff = "2026-10-05T06:08:21-04:00"
        reject_post_cutoff({"retrieved_at": "2026-10-05T05:00:00-04:00"}, cutoff_at=cutoff)
        reject_post_cutoff({"publication_time": "2026-10-05"}, cutoff_at=cutoff)
        with self.assertRaises(ValueError) as ctx:
            reject_post_cutoff({"retrieved_at": "2026-10-05T07:00:00-04:00"}, cutoff_at=cutoff)
        self.assertEqual(str(ctx.exception), "post_cutoff")

    def test_assemble_rejects_known_expectation_with_null_occurred_flag(self) -> None:
        expectation = {
            "schema_version": SCHEMA_RELEASE_EXPECTATION,
            "run_id": self.RUN_ID,
            "series_id": "US.Labor.payrolls",
            "calendar_status": "known",
            "scheduled_release_occurred_by_cutoff": None,
            "expectation_satisfied_by_verified_evidence": False,
            "cutoff_at": "2026-10-05T06:08:21-04:00",
        }
        expectation["expectation_id"] = expectation_id_from_body(expectation)
        with self.assertRaises(ContractError):
            assemble_series_run_state(
                run_id=self.RUN_ID,
                series_id="US.Labor.payrolls",
                definition_id="sd_test",
                expectation=expectation,
                attempt_ids=[],
                scheduler_event_ids=[],
                selected_observation_id=None,
                prior_observation_id=None,
            )

    def test_assemble_overdue_unverified_score_input(self) -> None:
        expectation = {
            "schema_version": SCHEMA_RELEASE_EXPECTATION,
            "run_id": self.RUN_ID,
            "series_id": "US.Labor.payrolls",
            "calendar_status": "known",
            "scheduled_release_occurred_by_cutoff": True,
            "expectation_satisfied_by_verified_evidence": False,
            "cutoff_at": "2026-10-05T06:08:21-04:00",
        }
        expectation["expectation_id"] = expectation_id_from_body(expectation)
        state = assemble_series_run_state(
            run_id=self.RUN_ID,
            series_id="US.Labor.payrolls",
            definition_id="sd_test",
            expectation=expectation,
            attempt_ids=["aa_payrolls"],
            scheduler_event_ids=[],
            selected_observation_id=None,
            prior_observation_id="ov_prior",
            trade_critical=True,
            country="US",
        )
        self.assertEqual(state["carry_forward_reason"], "overdue_unverified")
        self.assertEqual(state["score_input_observation_id"], "ov_prior")

    def test_bind_scores_conflict_on_duplicate_observation(self) -> None:
        spec = {"hot_direction": 1, "anchor": 0, "scale_per_unit": 1}
        cal = {"score_min": 1, "score_max": 100}
        observations = [
            {
                "series_id": "US.Labor.payrolls",
                "observation_id": "ov_dup",
                "value": 0,
                "component_spec": spec,
                "calibration": cal,
            },
            {
                "series_id": "US.Labor.wages",
                "observation_id": "ov_dup",
                "value": 1,
                "component_spec": spec,
                "calibration": cal,
            },
        ]
        with self.assertRaises(ScoreConflict):
            bind_scores(observations=observations)


if __name__ == "__main__":
    unittest.main()
