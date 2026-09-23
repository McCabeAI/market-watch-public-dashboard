"""Tests for canonical gauge bridge merge and persistence."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.country_registry import history_files
from scripts.macro_ingestion.canonical_bridge import merge_scored_points, period_after, persist_if_changed
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.temperature_level import (
    CALIBRATION_PATH,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    period_sort_key,
    raw_values_by_period,
    scoring_cutoff,
)

EVIDENCE_PATH = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_EVIDENCE_SHA = "41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b"

# Scored components with direct published source_transformation (one per country).
COUNTRY_FIXTURES: dict[str, dict[str, str]] = {
    "US": {
        "catalog_id": "US.Labor.unemployment",
        "series_id": "UNRATE",
        "transformation": "percent",
    },
    "CA": {
        "catalog_id": "CA.Labor.unemployment",
        "series_id": "LFS_unemployment_rate_v2062815",
        "transformation": "percent",
    },
    "AU": {
        "catalog_id": "AU.Labor.unemployment",
        "series_id": "A84423050A",
        "transformation": "percent",
    },
    "NZ": {
        "catalog_id": "NZ.Inflation.underlying",
        "series_id": "CPIQ.SE9NS1450",
        "transformation": "yoy_pct",
    },
    "EA": {
        "catalog_id": "EA.Inflation.underlying",
        "series_id": "PRC_HICP_MINR.M.RCH_A.TOT_X_NRG_FOOD.EA21",
        "transformation": "yoy_pct",
    },
    "JP": {
        "catalog_id": "JP.Inflation.underlying",
        "series_id": "CPI_2025BASE_LESS_FRESH_FOOD_ENERGY_YOY",
        "transformation": "yoy_pct",
    },
}


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _history_shas() -> dict[str, str]:
    names = history_files()
    return {code: _sha256_path(ROOT / "data/temperature_history" / names[code]) for code in names}


def _base_point(
    fixture: dict[str, str],
    *,
    period: str,
    value: float,
    revision_status: str = "final",
) -> dict:
    country = fixture["catalog_id"].split(".", 1)[0]
    return {
        "country": country,
        "catalog_id": fixture["catalog_id"],
        "role": "scored",
        "series_id": fixture["series_id"],
        "period": period,
        "value": value,
        "transformation": fixture["transformation"],
        "revision_status": revision_status,
        "source_url": "https://example.test/series",
        "raw_sha256": "abc" * 10 + "cd",
        "vintage": "latest_available",
        "retrieved_at": "2026-09-23T12:00:00Z",
    }


def _latest_stored_period(
    history: dict,
    *,
    history_key: str,
    transformation: str,
    series_id: str,
) -> str:
    comp = history["components"][history_key]
    rows = [
        o
        for o in comp.get("observations", [])
        if o.get("transformation") == transformation and o.get("series_id") == series_id
    ]
    return max((r["reference_period"] for r in rows), key=period_sort_key)


class TestCanonicalBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calibration = load_calibration()
        cls.repo_history_shas = _history_shas()
        cls.calibration_sha = _sha256_path(CALIBRATION_PATH)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.history_dir = self.tmp_path / "temperature_history"
        self.history_dir.mkdir()
        names = history_files()
        for code, filename in names.items():
            shutil.copy2(
                ROOT / "data/temperature_history" / filename,
                self.history_dir / filename,
            )
        self.histories = load_history(self.history_dir)
        self.scores_path = self.tmp_path / "temperature_scores.json"
        self.paths_path = self.tmp_path / "score_paths.json"
        self.calibration_path = CALIBRATION_PATH

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_forward_observation_per_country(self) -> None:
        checked_at = "2026-09-23T12:00:00Z"
        for country, fixture in COUNTRY_FIXTURES.items():
            with self.subTest(country=country):
                histories = copy.deepcopy(self.histories)
                spec = self.calibration["components"][fixture["catalog_id"]]
                history_key = spec["history_key"]
                latest = _latest_stored_period(
                    histories[country],
                    history_key=history_key,
                    transformation=fixture["transformation"],
                    series_id=fixture["series_id"],
                )
                next_period = period_after(latest)
                before_len = len(histories[country]["components"][history_key]["observations"])

                pre_cutoff = scoring_cutoff(self.calibration, histories)
                pre_state = build_score_state(
                    self.calibration, compute_state(self.calibration, histories, cutoff=pre_cutoff)
                )
                pre_comp = pre_state["countries"][country]
                dim = fixture["catalog_id"].split(".")[1]
                pre_as_of = pre_comp[dim]["component_state"][
                    fixture["catalog_id"].split(".", 2)[2]
                ]["as_of"]

                point = _base_point(fixture, period=next_period, value=3.25)
                result = merge_scored_points(
                    histories, self.calibration, [point], checked_at=checked_at
                )
                self.assertEqual(len(result["appended"]), 1, result)
                after_len = len(histories[country]["components"][history_key]["observations"])
                self.assertEqual(after_len, before_len + 1)

                values = raw_values_by_period(
                    histories[country], spec, scoring_cutoff(self.calibration, histories)
                )
                self.assertIn(next_period, values)

                persist_if_changed(
                    histories,
                    appended=result["appended"],
                    history_dir=self.history_dir,
                    scores_path=self.scores_path,
                    paths_path=self.paths_path,
                    calibration_path=self.calibration_path,
                )
                self.assertEqual(_sha256_path(self.calibration_path), self.calibration_sha)

                post_cutoff = scoring_cutoff(self.calibration, histories)
                post_state = build_score_state(
                    self.calibration, compute_state(self.calibration, histories, cutoff=post_cutoff)
                )
                comp_name = fixture["catalog_id"].split(".", 2)[2]
                post_as_of = post_state["countries"][country][dim]["component_state"][comp_name][
                    "as_of"
                ]
                self.assertEqual(post_as_of, next_period)
                self.assertNotEqual(post_as_of, pre_as_of)

        for code, digest in _history_shas().items():
            self.assertEqual(digest, self.repo_history_shas[code], msg=code)

    def test_duplicate_value_skipped(self) -> None:
        fixture = COUNTRY_FIXTURES["US"]
        histories = copy.deepcopy(self.histories)
        spec = self.calibration["components"][fixture["catalog_id"]]
        latest = _latest_stored_period(
            histories["US"],
            history_key=spec["history_key"],
            transformation=fixture["transformation"],
            series_id=fixture["series_id"],
        )
        next_period = period_after(latest)
        point = _base_point(fixture, period=next_period, value=4.0)
        first = merge_scored_points(histories, self.calibration, [point], checked_at="2026-09-23T12:00:00Z")
        self.assertEqual(len(first["appended"]), 1)
        length = len(histories["US"]["components"][spec["history_key"]]["observations"])
        second = merge_scored_points(histories, self.calibration, [point], checked_at="2026-09-23T12:01:00Z")
        self.assertEqual(second["skipped"], [{"id": fixture["catalog_id"], "reason": "duplicate_value"}])
        self.assertEqual(
            len(histories["US"]["components"][spec["history_key"]]["observations"]),
            length,
        )

    def test_malformed_and_transform_mismatch(self) -> None:
        fixture = COUNTRY_FIXTURES["US"]
        histories = copy.deepcopy(self.histories)
        spec = self.calibration["components"][fixture["catalog_id"]]
        latest = _latest_stored_period(
            histories["US"],
            history_key=spec["history_key"],
            transformation=fixture["transformation"],
            series_id=fixture["series_id"],
        )
        next_period = period_after(latest)
        before = len(histories["US"]["components"][spec["history_key"]]["observations"])

        bad_value = _base_point(fixture, period=next_period, value=0.0)
        bad_value["value"] = "nope"
        wrong_tf = _base_point(fixture, period=next_period, value=4.0)
        wrong_tf["transformation"] = "yoy_pct"

        result = merge_scored_points(
            histories,
            self.calibration,
            [bad_value, wrong_tf],
            checked_at="2026-09-23T12:00:00Z",
        )
        reasons = {row["reason"] for row in result["skipped"]}
        self.assertIn("partial_malformed", reasons)
        self.assertIn("partial_transform_mismatch", reasons)
        self.assertEqual(
            len(histories["US"]["components"][spec["history_key"]]["observations"]),
            before,
        )

    def test_revision_flash_and_final(self) -> None:
        fixture = COUNTRY_FIXTURES["US"]
        histories = copy.deepcopy(self.histories)
        spec = self.calibration["components"][fixture["catalog_id"]]
        period = "2026-08"
        comp = histories["US"]["components"][spec["history_key"]]
        for obs in comp["observations"]:
            if (
                obs.get("reference_period") == period
                and obs.get("transformation") == fixture["transformation"]
                and obs.get("series_id") == fixture["series_id"]
            ):
                obs["revision_status"] = "final"
                break
        else:
            self.fail("expected final row for revision test")

        flash = _base_point(fixture, period=period, value=3.9, revision_status="flash")
        flash_result = merge_scored_points(
            histories, self.calibration, [flash], checked_at="2026-09-23T12:00:00Z"
        )
        self.assertEqual(
            flash_result["skipped"],
            [{"id": fixture["catalog_id"], "reason": "final_not_superseded_by_flash"}],
        )

        final = _base_point(fixture, period=period, value=3.9, revision_status="final")
        final_result = merge_scored_points(
            histories, self.calibration, [final], checked_at="2026-09-23T12:01:00Z"
        )
        self.assertEqual(len(final_result["appended"]), 1)
        values = raw_values_by_period(
            histories["US"], spec, scoring_cutoff(self.calibration, histories)
        )
        self.assertAlmostEqual(values[period], 3.9, places=6)

    def test_review_evidence_sha256_unchanged(self) -> None:
        if EVIDENCE_PATH.is_file():
            self.assertEqual(_sha256_path(EVIDENCE_PATH), EXPECTED_EVIDENCE_SHA)

    def test_context_and_mapped_bridge_not_written(self) -> None:
        histories = copy.deepcopy(self.histories)
        bridge_key = "Inflation.mapped_bridge"
        before_bridge = len(histories["US"]["components"][bridge_key]["observations"])
        points = [
            {
                "country": "US",
                "catalog_id": "US.Inflation.mapped_bridge",
                "role": "registry_unweighted",
                "series_id": "bridge",
                "period": "2026-09",
                "value": 1.0,
                "transformation": "mom_sa_pct",
                "revision_status": "final",
                "source_url": "https://example.test",
                "raw_sha256": "deadbeef",
                "retrieved_at": "2026-09-23T12:00:00Z",
            },
            {
                "country": "US",
                "catalog_id": "US.Consumer.context_placeholder",
                "role": "context",
                "series_id": "UMCSENT",
                "period": "2026-09",
                "value": 50.0,
                "transformation": "index_level",
                "revision_status": "final",
                "source_url": "https://example.test",
                "raw_sha256": "cafebabe",
                "retrieved_at": "2026-09-23T12:00:00Z",
            },
        ]
        result = merge_scored_points(
            histories, self.calibration, points, checked_at="2026-09-23T12:00:00Z"
        )
        self.assertEqual(len(result["appended"]), 0)
        self.assertTrue(all(row["reason"] == "context_not_scored" for row in result["skipped"]))
        self.assertEqual(
            len(histories["US"]["components"][bridge_key]["observations"]),
            before_bridge,
        )

    def test_score_bridge_recompute_uses_merged_histories(self) -> None:
        fixture = COUNTRY_FIXTURES["US"]
        histories = copy.deepcopy(self.histories)
        spec = self.calibration["components"][fixture["catalog_id"]]
        next_period = period_after(
            _latest_stored_period(
                histories["US"],
                history_key=spec["history_key"],
                transformation=fixture["transformation"],
                series_id=fixture["series_id"],
            )
        )
        point = _base_point(fixture, period=next_period, value=3.5)
        outcome = recompute_scores_after_observation(
            persist_scores=False,
            persist_history=False,
            histories=histories,
            points=[point],
            checked_at="2026-09-23T12:00:00Z",
        )
        self.assertTrue(outcome.ok)
        assert outcome.state is not None
        comp = outcome.state["countries"]["US"]["Labor"]["component_state"]["unemployment"]
        self.assertEqual(comp["as_of"], next_period)


if __name__ == "__main__":
    unittest.main()
