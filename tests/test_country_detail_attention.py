from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.country_detail import policy

try:
    from scripts.country_detail.attention import evaluate_observations
except ImportError:  # pragma: no cover - reported in test summary when missing
    evaluate_observations = None

MATRIX_PATH = Path(__file__).resolve().parent / "fixtures" / "country_detail" / "acceptance_matrix.json"
ADVERSARIAL_DIR = MATRIX_PATH.parent / "adversarial"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _require_attention(self: unittest.TestCase):
    if evaluate_observations is None:
        self.skipTest("scripts.country_detail.attention is not importable")


def call_evaluate_observations(case: dict, snapshot: dict) -> dict:
    assert evaluate_observations is not None
    kwargs = {
        "country": case["country"],
        "observations": snapshot["observations"],
        "score_state": copy.deepcopy(case.get("score_state")),
        "as_of": snapshot.get("as_of") or case.get("as_of"),
        "stale_after_days": case.get("stale_after_days"),
        "prior_attention_snapshot": snapshot.get("prior_attention_snapshot"),
        "frozen_packet": case.get("frozen_packet"),
        "release_aware": case.get("release_aware"),
    }
    try:
        return evaluate_observations(**{key: value for key, value in kwargs.items() if value is not None})
    except TypeError:
        return evaluate_observations(
            case["country"],
            snapshot,
            copy.deepcopy(case.get("score_state")),
        )


def assert_snapshot_expected(test: unittest.TestCase, case: dict, snapshot: dict) -> None:
    expected = snapshot["expected"]
    result = call_evaluate_observations(case, snapshot)

    test.assertEqual(result.get("finding_count"), expected["finding_count"])
    test.assertEqual(result.get("withheld_by_cap", []), expected.get("withheld_by_cap", []))

    findings = result.get("findings") or []
    expected_findings = expected.get("findings") or []
    test.assertEqual(len(findings), len(expected_findings))

    if expected_findings:
        leader = findings[0]
        expected_leader = expected_findings[0]
        test.assertEqual(leader.get("observation_id"), expected_leader["observation_id"])
        test.assertEqual(leader.get("attention_status"), expected_leader["attention_status"])
        test.assertEqual(leader.get("ineligibility"), expected_leader["ineligibility"])
        test.assertEqual(
            leader.get("related_observation_ids"),
            expected_leader.get("related_observation_ids", []),
        )
        test.assertEqual(
            leader.get("headline_transformation"),
            expected_leader.get("headline_transformation"),
        )
        test.assertEqual(leader.get("headline_text"), expected_leader.get("headline_text"))

    leader_label = expected.get("leader_label")
    if leader_label and findings:
        expected_leader_id = expected["observations"][leader_label]["observation_id"]
        test.assertEqual(findings[0]["observation_id"], expected_leader_id)

    result_observations = result.get("observations")
    if isinstance(result_observations, dict):
        obs_lookup = result_observations
    else:
        obs_lookup = {}
        for row in result.get("members", []):
            label = row.get("label")
            if label:
                obs_lookup[label] = row

    for label, expected_row in expected.get("observations", {}).items():
        actual = obs_lookup.get(label)
        test.assertIsNotNone(actual, msg=f"missing observation label {label}")
        for field in (
            "observation_id",
            "attention_status",
            "badge_text",
            "percentile",
            "comparable_n",
            "ineligibility",
            "reason",
            "data_state",
            "display_label",
            "alert_freshness",
            "related_observation_ids",
            "what_matters_now_slot",
        ):
            if field in expected_row:
                test.assertEqual(actual.get(field), expected_row[field], msg=f"{label}.{field}")


class CountryDetailAttentionMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = load_json(MATRIX_PATH)
        cls.cases_by_id = {case["id"]: case for case in cls.matrix["cases"]}

    def setUp(self) -> None:
        _require_attention(self)

    def test_acceptance_matrix_snapshots(self) -> None:
        for case in self.matrix["cases"]:
            for snapshot in case["snapshots"]:
                with self.subTest(case=case["id"], snapshot=snapshot["id"]):
                    if case["id"] == "unscored_zero_weight_leads":
                        score_before = copy.deepcopy(case["score_state"])
                    assert_snapshot_expected(self, case, snapshot)
                    if case["id"] == "unscored_zero_weight_leads":
                        self.assertEqual(case["score_state"], score_before)
                        result = call_evaluate_observations(case, snapshot)
                        leader = (result.get("findings") or [None])[0]
                        self.assertIsNotNone(leader)
                        self.assertEqual(leader.get("score_role"), "unscored")
                        self.assertEqual(leader.get("weight"), 0)

    def test_quiet_country_has_zero_findings(self) -> None:
        case = self.cases_by_id["quiet_country"]
        snapshot = case["snapshots"][0]
        result = call_evaluate_observations(case, snapshot)
        self.assertEqual(result["finding_count"], 0)
        self.assertEqual(result.get("findings"), [])

    def test_au_spending_headline_keeps_distinct_directions(self) -> None:
        case = self.cases_by_id["au_spending_headline"]
        snapshot = case["snapshots"][0]
        result = call_evaluate_observations(case, snapshot)
        self.assertEqual(result["finding_count"], 2)
        finding = result["findings"][0]
        expected = snapshot["expected"]["findings"][0]
        self.assertEqual(finding["observation_id"], expected["observation_id"])
        self.assertEqual(finding["attention_status"], "notable")
        self.assertEqual(
            finding.get("related_observation_ids"),
            expected.get("related_observation_ids"),
        )
        self.assertIn("Confirmed divergence", finding["reason"])
        self.assertIn("Confirmed divergence", result["findings"][1]["reason"])

    def test_dedup_and_unchanged_correlated_pair(self) -> None:
        case = self.cases_by_id["dedup_and_unchanged"]
        initial = call_evaluate_observations(case, case["snapshots"][0])
        self.assertEqual(initial["finding_count"], 1)
        reprint = call_evaluate_observations(case, case["snapshots"][1])
        self.assertEqual(reprint["finding_count"], 2)
        cpi_findings = [
            finding
            for finding in reprint["findings"]
            if finding.get("release_family") == "au_cpi"
            or finding.get("topic") == "inflation"
        ]
        self.assertEqual(len(cpi_findings), 1)


class CountryDetailAttentionAdversarialTest(unittest.TestCase):
    def setUp(self) -> None:
        _require_attention(self)

    def test_short_seasonal_fixture(self) -> None:
        fixture = load_json(ADVERSARIAL_DIR / "short_seasonal.json")
        case = {"country": fixture["country"]}
        snapshot = {
            "id": "only",
            "as_of": fixture.get("as_of"),
            "observations": fixture["observations"],
        }
        result = call_evaluate_observations(case, snapshot)
        label = fixture["expect"]["label"]
        row = result["observations"][label] if "observations" in result else None
        if row is None:
            row = next(m for m in result["members"] if m["label"] == label)
        self.assertEqual(row["attention_status"], fixture["expect"]["attention_status"])
        self.assertIn(fixture["expect"]["ineligibility_includes"], row["ineligibility"])
        self.assertEqual(row.get("badge_text"), fixture["expect"]["badge_text"])
        self.assertNotEqual(row.get("badge_text"), "Outlier")
        self.assertNotEqual(row.get("badge_text"), "Notable")
        self.assertNotIn(fixture["expect"]["reason_must_not_contain"], row.get("reason", ""))

    def test_unchanged_reprint_fixture(self) -> None:
        fixture = load_json(ADVERSARIAL_DIR / "unchanged_reprint.json")
        case = {
            "country": fixture["country"],
            "score_state": fixture["score_state"],
        }
        first = call_evaluate_observations(case, fixture["snapshots"][0])
        first_count = first["finding_count"]
        prior = []
        for finding in first.get("findings", []):
            prior.append(
                {
                    "observation_id": finding["observation_id"],
                    "value": next(
                        o["value"]
                        for o in fixture["snapshots"][0]["observations"]
                        if o["label"] == "cpi_solo"
                    ),
                    "reference_period": finding.get("reference_period", "2024-06"),
                    "transformation": finding.get("headline_transformation", "yoy_pct"),
                    "revision_status": "final",
                    "vintage": "adv-v1",
                }
            )
        second_snapshot = copy.deepcopy(fixture["snapshots"][1])
        second_snapshot["prior_attention_snapshot"] = prior
        second = call_evaluate_observations(case, second_snapshot)
        self.assertEqual(second["finding_count"], fixture["expect"]["finding_count_after_second"])
        self.assertLessEqual(second["finding_count"], first_count + 1)
        cpi_finding = second["findings"][-1]
        self.assertEqual(cpi_finding.get("alert_freshness"), fixture["expect"]["second_alert_freshness"])

    def test_states_fixture(self) -> None:
        fixture = load_json(ADVERSARIAL_DIR / "states.json")
        case = {
            "country": fixture["country"],
            "as_of": fixture["as_of"],
            "stale_after_days": fixture["stale_after_days"],
        }
        snapshot = {"id": "only", "observations": fixture["observations"], "as_of": fixture["as_of"]}
        # The fixture's "stale" row is an old clock-TTL case. Move its period so a
        # successor is actually due, and review it on the release calendar.
        for obs in snapshot["observations"]:
            if obs.get("label") == "stale":
                obs["reference_period"] = "2024-03"
        case["release_aware"] = True
        result = call_evaluate_observations(case, snapshot)
        obs_lookup = result.get("observations") or {
            row["label"]: row for row in result.get("members", []) if row.get("label")
        }
        state_by_label = {
            "missing": "missing",
            "stale": "due_late",
            "revised": "revised",
            "not_comparable": "structurally_non_comparable",
            "failed_fetch": "failed_fetch",
        }
        for label, expected_label in fixture["expect"]["display_labels"].items():
            row = obs_lookup[label]
            self.assertEqual(row["data_state"], state_by_label[label])
            if label == "stale":
                self.assertEqual(row.get("display_label"), "Due")
                self.assertNotEqual(row.get("display_label"), "Stale")
                self.assertGreater(row.get("retrieval_age_days"), fixture["stale_after_days"])
            else:
                self.assertEqual(row.get("display_label"), expected_label)

        failed = obs_lookup["failed_fetch"]
        expected_retrieved = policy.next_retrieved_at(
            previous=fixture["failed_fetch_timestamps"]["previous_successful_retrieved_at"],
            attempted=fixture["failed_fetch_timestamps"]["attempted_retrieved_at"],
            data_state="failed_fetch",
        )
        self.assertEqual(expected_retrieved, fixture["expect"]["failed_fetch_retrieved_at"])
        self.assertEqual(failed.get("retrieved_at"), fixture["expect"]["failed_fetch_retrieved_at"])
        self.assertNotEqual(failed.get("retrieved_at"), fixture["failed_fetch_timestamps"]["attempted_retrieved_at"])

    def test_revised_or_preliminary_stale_extreme_is_not_outlier(self) -> None:
        """A due successor blocks a revised extreme. Retrieval age does not.

        Invented 60-point monthly SA sample. The latest value is the unique
        maximum, so a current revised row can still be an outlier. The same
        print stays eligible when it was retrieved 10 days earlier and the
        next monthly release is not yet due.
        """
        as_of = "2024-07-01"
        current_as_of = "2024-01-20"
        aged_retrieved_at = "2024-01-10T00:00:00Z"  # 10 days before current_as_of
        fresh_retrieved_at = "2024-01-20T00:00:00Z"

        def observation(*, data_state: str, revision_status: str, retrieved_at: str) -> dict:
            history = []
            year, month = 2019, 1
            for index in range(59):
                history.append(
                    {
                        "reference_period": f"{year:04d}-{month:02d}",
                        "value": index + 1,
                    }
                )
                month += 1
                if month == 13:
                    month = 1
                    year += 1
            return {
                "label": "fixture_extreme",
                "methodology_breaks": [],
                "comparison_broken": False,
                "revision_status": revision_status,
                "vintage": "fixture-v1",
                "retrieved_at": retrieved_at,
                "observed_at": retrieved_at,
                "source_url": "https://example.invalid/country-detail-fixture/revised-stale",
                "country": "US",
                "series_id": "FIXTURE_REVISED_STALE_EXTREME",
                "reference_period": "2023-12",
                "transformation": "mom_pct",
                "geography": "US",
                "seasonal_adjustment": True,
                "units": "index points",
                "nominal_basis": "index",
                "score_role": "context",
                "weight": 0,
                "topic": "activity",
                "cadence": "monthly",
                "release_family": "fixture_revised_stale_extreme",
                "data_state": data_state,
                "value": 500,
                "history": history,
            }

        def evaluate(obs: dict, *, when: str, release_aware: bool) -> dict:
            assert evaluate_observations is not None
            return evaluate_observations(
                [obs],
                as_of=when,
                stale_after_days=4,
                release_aware=release_aware,
            )

        def assert_due_not_finding(result: dict) -> None:
            self.assertEqual(result["finding_count"], 0)
            self.assertEqual(result["findings"], [])
            row = result["members"][0]
            self.assertEqual(row["comparable_n"], 60)
            self.assertEqual(row["data_state"], "due_late")
            self.assertEqual(row["release_state"], "due_late")
            self.assertEqual(row["display_label"], "Due")
            self.assertNotEqual(row["display_label"], "Stale")
            self.assertEqual(row["attention_status"], "none")
            self.assertIsNone(row["badge_text"])
            self.assertIn("due_late", row["ineligibility"])
            self.assertNotIn("stale", row["ineligibility"])
            self.assertNotEqual(row["badge_text"], "Outlier")
            self.assertNotEqual(row["badge_text"], "Notable")

        revised_due = evaluate(
            observation(
                data_state="revised",
                revision_status="revised",
                retrieved_at=fresh_retrieved_at,
            ),
            when=as_of,
            release_aware=True,
        )
        assert_due_not_finding(revised_due)

        preliminary_due = evaluate(
            observation(
                data_state="revised",
                revision_status="preliminary",
                retrieved_at=fresh_retrieved_at,
            ),
            when=as_of,
            release_aware=True,
        )
        assert_due_not_finding(preliminary_due)

        ok_due = evaluate(
            observation(
                data_state="ok",
                revision_status="final",
                retrieved_at=fresh_retrieved_at,
            ),
            when=as_of,
            release_aware=True,
        )
        assert_due_not_finding(ok_due)

        aged_current = evaluate(
            observation(
                data_state="ok",
                revision_status="final",
                retrieved_at=aged_retrieved_at,
            ),
            when=current_as_of,
            release_aware=True,
        )
        aged_row = aged_current["members"][0]
        self.assertEqual(aged_current["finding_count"], 1)
        self.assertEqual(aged_row["data_state"], "ok")
        self.assertEqual(aged_row["release_state"], "current")
        self.assertNotEqual(aged_row["display_label"], "Stale")
        self.assertNotIn("stale", aged_row["ineligibility"])
        self.assertGreater(aged_row["retrieval_age_days"], 4)
        self.assertEqual(aged_row["attention_status"], "outlier")

        fresh_revised = evaluate(
            observation(
                data_state="revised",
                revision_status="revised",
                retrieved_at=fresh_retrieved_at,
            ),
            when=current_as_of,
            release_aware=True,
        )
        self.assertEqual(fresh_revised["finding_count"], 1)
        row = fresh_revised["members"][0]
        self.assertEqual(row["comparable_n"], 60)
        self.assertEqual(row["data_state"], "revised")
        self.assertEqual(row["attention_status"], "outlier")
        self.assertEqual(row["badge_text"], "Outlier")
        self.assertNotIn("stale", row["ineligibility"])


if __name__ == "__main__":
    unittest.main()
