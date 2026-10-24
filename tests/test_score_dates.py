"""Score date semantics: calibration anchor vs input ingestion (not a score freeze)."""

from __future__ import annotations

import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.dashboard_repair.apply import load_scores
from scripts.dashboard_repair.brief import _print_score_class, _prints, render_brief
from scripts.dashboard_repair.score_dates import format_ingestion_day
from scripts.dashboard_repair.scoreboard import render_scoreboard
from scripts.temperature_level import (
    build_score_state,
    compute_state,
    load_calibration,
    load_history,
    period_sort_key,
    reference_period_end,
    _lineage_for_scored_period,
    _component_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def _filter_histories_by_retrieved(histories: dict, max_iso: str) -> dict:
    out: dict = {}
    for code, doc in histories.items():
        comps = {}
        for ck, comp in (doc.get("components") or {}).items():
            obs = []
            for row in comp.get("observations") or []:
                ra = row.get("retrieved_at")
                if ra is None or ra <= max_iso:
                    obs.append(row)
            comps[ck] = {**comp, "observations": obs}
        out[code] = {**doc, "components": comps}
    return out


class ScoreDatesMetadataTests(unittest.TestCase):
    def test_committed_state_metadata_and_levels(self) -> None:
        state = load_scores()
        self.assertEqual(state.get("calibration_anchor_date"), "2026-09-21")
        self.assertEqual(state.get("scoring_cutoff"), "2026-09")
        self.assertGreater(str(state.get("last_refresh_date")), "2026-09-21")
        head = json.loads(
            subprocess.check_output(
                ["git", "show", "HEAD:data/temperature_scores.json"],
                cwd=ROOT,
                text=True,
            )
        )
        for country, dims in head["countries"].items():
            for dim, spec in dims.items():
                new = state["countries"][country][dim]
                for field in ("level", "impulse", "direction", "coverage", "temperature_class"):
                    self.assertEqual(spec.get(field), new.get(field), f"{country} {dim} {field}")
                self.assertEqual(spec.get("components"), new.get("components"))

    def test_september_ingestion_cutoff_changes_ca_jp_inflation(self) -> None:
        cal = load_calibration()
        histories = load_history()
        filtered = _filter_histories_by_retrieved(histories, "2026-09-21T23:59:59Z")
        current = compute_state(cal, histories)["countries"]
        vintage = compute_state(cal, filtered)["countries"]
        self.assertAlmostEqual(current["CA"]["Inflation"]["level"], 54.34, places=2)
        self.assertAlmostEqual(current["JP"]["Inflation"]["level"], 51.5, places=2)
        self.assertAlmostEqual(vintage["CA"]["Inflation"]["level"], 54.78, places=2)
        self.assertAlmostEqual(vintage["JP"]["Inflation"]["level"], 47.75, places=2)

    def test_mixed_component_vintages_set_latest_reference_period(self) -> None:
        state = load_scores()
        dim = state["countries"]["CA"]["Activity"]
        periods = {
            cs["as_of"]
            for cs in dim["component_state"].values()
            if isinstance(cs, dict) and cs.get("as_of")
        }
        self.assertGreater(len(periods), 1)
        self.assertEqual(
            dim["latest_reference_period"],
            max(periods, key=period_sort_key),
        )

    def test_release_date_rejected_when_before_period_end(self) -> None:
        cal = load_calibration()
        histories = deepcopy(load_history())
        ca = histories["CA"]
        comp = ca["components"]["Inflation.headline"]
        for row in comp["observations"]:
            if row.get("reference_period") == "2026-09":
                row["release_date"] = "2026-09-14"
                row["retrieved_at"] = "2026-10-01T00:00:00Z"
        spec = _component_spec(cal, "CA", "Inflation", "headline")
        lineage = _lineage_for_scored_period(ca, spec, "2026-09", "2026-09")
        self.assertIsNone(lineage["release_date"])
        self.assertEqual(lineage["release_date_status"], "inherited_or_inconsistent")
        self.assertEqual(reference_period_end("2026-09").isoformat(), "2026-09-30")


class ScoreDatesPresentationTests(unittest.TestCase):
    def test_brief_print_classification_and_no_freeze_wording(self) -> None:
        scores = load_scores()
        scored_as_of = scores["countries"]["CA"]["Inflation"]["component_state"]["headline"]["as_of"]
        country_detail = {
            "attention": {
                "countries": {
                    "CA": {
                        "findings": [
                            {"observation_id": "in-score"},
                            {"observation_id": "newer"},
                            {"observation_id": "context"},
                        ]
                    }
                }
            },
            "projection": {
                "countries": {
                    "CA": {
                        "observations": [
                            {
                                "observation_id": "in-score",
                                "catalog_id": "CA.Inflation.headline",
                                "country": "CA",
                                "reference_period": scored_as_of,
                                "score_input": True,
                                "score_role": "scored",
                                "transformation": "yoy_pct",
                                "value": 3.0,
                                "units": "%",
                                "release_date": "2026-10-01",
                            },
                            {
                                "observation_id": "newer",
                                "catalog_id": "CA.Inflation.headline",
                                "country": "CA",
                                "reference_period": "2099-12",
                                "score_input": True,
                                "score_role": "scored",
                                "transformation": "yoy_pct",
                                "value": 4.0,
                                "units": "%",
                                "release_date": "2099-12-15",
                            },
                            {
                                "observation_id": "context",
                                "catalog_id": "CA.Activity.retail_sales",
                                "country": "CA",
                                "reference_period": "2026-09",
                                "score_input": False,
                                "score_role": "context",
                                "transformation": "mom_pct",
                                "value": 1.0,
                                "units": "%",
                            },
                        ]
                    }
                }
            },
        }
        obs_in = country_detail["projection"]["countries"]["CA"]["observations"][0]
        obs_new = country_detail["projection"]["countries"]["CA"]["observations"][1]
        obs_ctx = country_detail["projection"]["countries"]["CA"]["observations"][2]
        self.assertEqual(_print_score_class(obs_in, scores), "in_score")
        self.assertEqual(_print_score_class(obs_new, scores), "newer_than_score")
        self.assertEqual(_print_score_class(obs_ctx, scores), "context_only")
        rows = _prints(country_detail, scores, limit=10)
        self.assertEqual(rows[0]["score_class"], "newer_than_score")
        html = render_brief(
            scores=scores,
            tape_cards=[],
            packet=None,
            calendar=None,
            country_detail=country_detail,
        )
        lowered = html.lower()
        self.assertNotIn("after score freeze", lowered)
        self.assertNotIn("scores frozen", lowered)
        self.assertIn("In score", html)
        self.assertIn("Newer than score", html)
        self.assertIn("Context only", html)

    def test_scoreboard_and_country_header_labels(self) -> None:
        from scripts.country_detail.render import _score_header

        scores = load_scores()
        board = render_scoreboard(scores)
        header = _score_header(scores)
        ingested = format_ingestion_day(scores.get("score_inputs_last_ingested_at"))
        for blob in (board, header):
            self.assertIn("calibration anchor 21 Sep 2026", blob)
            self.assertIn(f"inputs last ingested {ingested}", blob)
            self.assertIn("reference periods through Sep 2026", blob)
            lowered = blob.lower()
            self.assertNotIn("score freeze", lowered)
            self.assertNotIn("scores frozen", lowered)
        self.assertIn('data-score-dates', header)


class ScoreDatesDeterminismTests(unittest.TestCase):
    def test_regenerated_state_matches_committed_file(self) -> None:
        import tempfile

        from scripts.temperature_level import write_state

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "temperature_scores.json"
            write_state(path)
            committed = Path(ROOT / "data/temperature_scores.json").read_text(encoding="utf-8")
            self.assertEqual(path.read_text(encoding="utf-8"), committed)


if __name__ == "__main__":
    unittest.main()
