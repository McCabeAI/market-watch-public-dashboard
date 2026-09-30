from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.country_detail import policy

MATRIX_PATH = Path(__file__).resolve().parent / "fixtures" / "country_detail" / "acceptance_matrix.json"
TOLERANCE = 1e-9


def independent_percentile(sample, x):
    n = len(sample)
    r = 1 + sum(v < x for v in sample) + 0.5 * sum(v == x for v in sample)
    return (r - 0.5) / n * 100


def load_acceptance_matrix() -> dict:
    with MATRIX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def comparable_sample_values(observation: dict) -> list[float] | None:
    if observation.get("comparison_broken"):
        return None
    if observation.get("value") is None:
        return None
    if observation.get("data_state") in {"missing", "failed_fetch"}:
        return None
    cadence = observation.get("cadence")
    if cadence not in policy.KNOWN_CADENCES:
        return None
    history = observation.get("history") or []
    if not history:
        return None
    filtered = policy.filter_comparable_history(
        history,
        latest_period=observation["reference_period"],
        cadence=cadence,
        seasonal_adjustment=observation.get("seasonal_adjustment"),
        methodology_breaks=observation.get("methodology_breaks") or [],
        comparison_broken=observation.get("comparison_broken", False),
    )
    if filtered.get("comparison_broken"):
        return None
    comparable = filtered.get("comparable") or []
    if not comparable:
        return None
    return [float(item["value"]) for item in comparable]


def build_rank_carrier_sample(n: int, latest_rank: int) -> list[float]:
    return [float(value) for value in range(1, n + 1)]


class CountryDetailContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = load_acceptance_matrix()

    def test_sample_minima_match_contract(self) -> None:
        self.assertEqual(policy.SAMPLE_MINIMA["monthly"]["notable"], 36)
        self.assertEqual(policy.SAMPLE_MINIMA["monthly"]["outlier"], 60)
        self.assertEqual(policy.SAMPLE_MINIMA["quarterly"]["notable"], 16)
        self.assertEqual(policy.SAMPLE_MINIMA["quarterly"]["outlier"], 24)
        self.assertEqual(dict(policy.SAMPLE_MINIMA["monthly"]), self.matrix["sample_minima"]["monthly"])
        self.assertEqual(dict(policy.SAMPLE_MINIMA["quarterly"]), self.matrix["sample_minima"]["quarterly"])

    def test_independent_percentile_matches_policy_on_matrix_histories(self) -> None:
        for case in self.matrix["cases"]:
            for snapshot in case.get("snapshots", []):
                expected_obs = snapshot.get("expected", {}).get("observations") or {}
                for observation in snapshot.get("observations", []):
                    label = observation.get("label")
                    if label not in expected_obs:
                        continue
                    expected_percentile = expected_obs[label].get("percentile")
                    if expected_percentile is None:
                        continue
                    sample = comparable_sample_values(observation)
                    if sample is None:
                        continue
                    latest = float(observation["value"])
                    independent = independent_percentile(sample, latest)
                    reference = policy.inclusive_midrank_percentile(sample, latest)
                    self.assertAlmostEqual(independent, reference, delta=TOLERANCE)
                    self.assertAlmostEqual(reference, expected_percentile, delta=TOLERANCE)

    def test_value_unchanged_probes(self) -> None:
        for probe in self.matrix.get("value_unchanged_probes", []):
            result = policy.value_unchanged(probe["units"], probe["previous"], probe["current"])
            self.assertEqual(result, probe["unchanged"], msg=probe)

    def test_boundary_probes_strict_edges_and_sample_cutoffs(self) -> None:
        for probe in self.matrix["boundary_probes"]:
            percentile = probe["percentile"]
            cadence = probe["cadence"]
            comparable_n = probe["comparable_n"]
            seasonal_adjustment = probe.get("seasonal_adjustment")
            if "latest_rank_in_1_to_n" in probe:
                sample = build_rank_carrier_sample(comparable_n, probe["latest_rank_in_1_to_n"])
                latest = float(probe["latest_rank_in_1_to_n"])
                self.assertAlmostEqual(
                    independent_percentile(sample, latest),
                    percentile,
                    delta=TOLERANCE,
                )
                self.assertAlmostEqual(
                    policy.inclusive_midrank_percentile(sample, latest),
                    percentile,
                    delta=TOLERANCE,
                )
            classified = policy.classify_attention(
                cadence=cadence,
                comparable_n=comparable_n,
                percentile=percentile,
                seasonal_adjustment=seasonal_adjustment,
            )
            self.assertEqual(classified["attention_status"], probe["attention_status"])
            self.assertEqual(classified["ineligibility"], probe["ineligibility"])
            self.assertEqual(classified["badge_text"], probe["badge_text"])
            self.assertEqual(classified["reason"], probe["reason"])

    def test_exact_band_edges_are_not_breaches(self) -> None:
        for edge in (5.0, 95.0, 1.0, 99.0):
            classified = policy.classify_attention(
                cadence="monthly",
                comparable_n=100,
                percentile=edge,
                seasonal_adjustment=True,
            )
            if edge in (5.0, 95.0):
                self.assertEqual(classified["attention_status"], "none")
                self.assertIn("not_material", classified["ineligibility"])
            else:
                self.assertEqual(classified["attention_status"], "notable")
                self.assertEqual(classified["badge_text"], "Notable")

    def test_packet_contains_attention_firewall(self) -> None:
        self.assertTrue(policy.packet_contains_attention({"attention_status": "none"}))
        self.assertFalse(policy.packet_contains_attention({"hash": "abc", "scores": {"US": 1}}))

    def test_trader_room_firewall_has_no_country_detail_references(self) -> None:
        roots = (
            Path("scripts/trader_room"),
            Path("scripts/trading"),
            Path("scripts/pm"),
        )
        for root in roots:
            self.assertTrue(root.is_dir(), msg=f"missing scan root {root}")
            for path in sorted(root.rglob("*.py")):
                self.assertNotIn(
                    "country_detail",
                    path.read_text(encoding="utf-8"),
                    msg=str(path),
                )
        freeze = Path("scripts/market_watch_launch/freeze.py")
        self.assertTrue(freeze.is_file())
        self.assertNotIn("country_detail", freeze.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
