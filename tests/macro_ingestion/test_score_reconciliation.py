"""Score reconciliation and same-cycle recompute tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.macro_ingestion.canonical_bridge import merge_scored_points
from scripts.macro_ingestion.score_bridge import recompute_scores_after_observation
from scripts.macro_ingestion.score_reconciliation import reconcile_weighted_components
from scripts.market_watch_launch.lineage import stage_verified_lineage
from scripts.temperature_level import (
    CALIBRATION_PATH,
    HISTORY_DIR,
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    load_state,
    period_sort_key,
    scoring_cutoff,
)
from tests.macro_cutoff import DEFAULT_MACRO_CUTOFF, cutoff_history_dir

ROOT = Path(__file__).resolve().parents[2]
CHECKED_AT = "2026-11-04T15:00:00Z"


class ScoreReconciliationCommittedTests(unittest.TestCase):
    def test_committed_reconciliation_rows(self) -> None:
        cal = load_calibration()
        histories = load_history()
        state = load_state()
        rows = reconcile_weighted_components(cal, histories, state)
        self.assertEqual(len(rows), 66)
        for row in rows:
            self.assertTrue(str(row.get("gap_reason") or "").strip())
        self.assertEqual(
            sum(1 for row in rows if row["gap_reason"] == "newer_source_not_scored"),
            0,
        )
        by_id = {row["catalog_id"]: row for row in rows}
        self.assertEqual(by_id["AU.Consumer.retail"]["gap_reason"], "retired_unobserved")
        ca_gdp = by_id["CA.Activity.gdp_domestic_demand"]
        self.assertEqual(ca_gdp["gap_reason"], "frequency_split_context")
        self.assertEqual(ca_gdp["scored_period"], "2026-Q2")
        self.assertEqual(ca_gdp["history_period"], "2026-Q2")
        self.assertEqual(
            by_id["NZ.Consumer.confidence"]["gap_reason"],
            "ambiguous_confidence_period",
        )


class ScoreReconciliationSameCycleTests(unittest.TestCase):
    def test_unemployment_forward_print_updates_dimension_as_of(self) -> None:
        cal = load_calibration()
        with tempfile.TemporaryDirectory() as tmp:
            hist_dir = cutoff_history_dir(Path(tmp), DEFAULT_MACRO_CUTOFF)
            histories = load_history(hist_dir)
            before = build_score_state(cal, compute_state(cal, histories))
            before_unemp = before["countries"]["US"]["Labor"]["component_state"]["unemployment"]
            before_dim_level = before["countries"]["US"]["Labor"]["level"]
            self.assertEqual(before_unemp["as_of"], "2026-09")

            point = {
                "country": "US",
                "catalog_id": "US.Labor.unemployment",
                "role": "scored",
                "series_id": "UNRATE",
                "period": "2026-10",
                "transformation": "percent",
                "value": 4.3,
                "period_binding": "verified",
                "revision_status": "final",
            }
            outcome = recompute_scores_after_observation(
                persist_history=False,
                persist_scores=False,
                calibration_path=ROOT / "data/temperature_calibration.json",
                history_dir=hist_dir,
                histories=histories,
                points=[point],
                checked_at=CHECKED_AT,
            )
            self.assertTrue(outcome.ok, msg=outcome.merge)
            state = outcome.state or {}
            unemp = state["countries"]["US"]["Labor"]["component_state"]["unemployment"]
            self.assertEqual(unemp["as_of"], "2026-10")
            labor_as_of = state["countries"]["US"]["Labor"]["as_of"]
            self.assertEqual(
                period_sort_key(str(labor_as_of)),
                period_sort_key("2026-10"),
            )
            self.assertNotEqual(state["countries"]["US"]["Labor"]["level"], before_dim_level)

    def test_nz_confidence_unverified_skipped_verified_appends(self) -> None:
        cal = load_calibration()
        histories = copy.deepcopy(load_history())
        before = (
            build_score_state(cal, compute_state(cal, histories))
            ["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"]
        )
        self.assertEqual(before, "2026-08")

        unverified = {
            "country": "NZ",
            "catalog_id": "NZ.Consumer.confidence",
            "role": "scored",
            "series_id": "NZ.Consumer.confidence",
            "period": "2026-10",
            "transformation": "index_level",
            "value": 100.1,
            "revision_status": "final",
        }
        merge = merge_scored_points(histories, cal, [unverified], checked_at=CHECKED_AT)
        reasons = {item["reason"] for item in merge["skipped"]}
        self.assertIn("ambiguous_confidence_period", reasons)
        self.assertEqual(len(merge["appended"]), 0)
        after_skip = build_score_state(cal, compute_state(cal, histories))
        self.assertEqual(
            after_skip["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"],
            before,
        )

        verified = {**unverified, "period_binding": "verified", "period": "2026-09", "value": 99.0}
        merge2 = merge_scored_points(histories, cal, [verified], checked_at=CHECKED_AT)
        self.assertEqual(len(merge2["appended"]), 1)
        after = build_score_state(cal, compute_state(cal, histories))
        self.assertEqual(
            after["countries"]["NZ"]["Consumer"]["component_state"]["confidence"]["as_of"],
            "2026-09",
        )


class StageVerifiedLineageReconciliationTests(unittest.TestCase):
    def test_non_blocking_gaps_from_committed_store(self) -> None:
        cal = load_calibration()
        histories = load_history()
        state = load_state()
        rows = reconcile_weighted_components(cal, histories, state)
        by_id = {row["catalog_id"]: row for row in rows}
        self.assertEqual(by_id["AU.Consumer.retail"]["gap_reason"], "retired_unobserved")
        self.assertEqual(by_id["CA.Activity.gdp_domestic_demand"]["gap_reason"], "frequency_split_context")

    def test_dropped_store_print_fails_through_stage_verified_lineage(self) -> None:
        cal = load_calibration(CALIBRATION_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            hist_dir = cutoff_history_dir(work, DEFAULT_MACRO_CUTOFF)
            obs_root = work / "observations"
            obs_root.mkdir()
            us_store = {
                "country": "US",
                "observations": [
                    {
                        "series_id": "UNRATE",
                        "period": "2026-10",
                        "transformation": "percent",
                        "value": 9.87,
                        "revision_status": "final",
                        "period_binding": "verified",
                        "source_url": "https://fred.stlouisfed.org/series/UNRATE",
                        "retrieved_at": CHECKED_AT,
                    }
                ],
            }
            (obs_root / "us.json").write_text(json.dumps(us_store, indent=2) + "\n", encoding="utf-8")
            for country in ("ca", "au", "nz", "ea", "jp"):
                (obs_root / f"{country}.json").write_text(
                    json.dumps({"country": country.upper(), "observations": []}, indent=2) + "\n",
                    encoding="utf-8",
                )
            launch_dir = work / "launch_drop"
            launch_dir.mkdir()
            dropped = stage_verified_lineage(
                launch_dir=launch_dir,
                checked_at=CHECKED_AT,
                canonical_history_dir=hist_dir,
                calibration_path=CALIBRATION_PATH,
                points=[],
                observations_dir=obs_root,
            )
            self.assertFalse(dropped["ok"])
            matched = [
                row
                for row in dropped.get("rejections") or []
                if row.get("id") == "US.Labor.unemployment"
            ]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["period"], "2026-10")
            self.assertEqual(matched[0]["reason"], "newer_source_not_scored")

            launch_ok = work / "launch_ok"
            launch_ok.mkdir()
            point = {
                "country": "US",
                "catalog_id": "US.Labor.unemployment",
                "role": "scored",
                "series_id": "UNRATE",
                "period": "2026-10",
                "transformation": "percent",
                "value": 9.87,
                "period_binding": "verified",
                "revision_status": "final",
                "source_url": "https://fred.stlouisfed.org/series/UNRATE",
            }
            ok = stage_verified_lineage(
                launch_dir=launch_ok,
                checked_at=CHECKED_AT,
                canonical_history_dir=hist_dir,
                calibration_path=CALIBRATION_PATH,
                observations_dir=obs_root,
                points=[point],
            )
            self.assertTrue(ok["ok"], msg=ok.get("rejections") or ok.get("error"))
            self.assertGreater(ok["appended_count"], 0)
            scores = json.loads((launch_ok / "lineage/temperature_scores.json").read_text(encoding="utf-8"))
            labor = scores["countries"]["US"]["Labor"]
            unemp_as_of = labor["component_state"]["unemployment"]["as_of"]
            self.assertEqual(unemp_as_of, "2026-10")
            self.assertEqual(
                period_sort_key(str(labor["as_of"])),
                period_sort_key(unemp_as_of),
            )


if __name__ == "__main__":
    unittest.main()
