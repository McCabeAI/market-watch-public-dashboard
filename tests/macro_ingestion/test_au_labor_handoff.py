"""Frozen Market Watch inputs cite as-of eligible AU leading observations."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_labor_evidence import (
    build_au_labor_evidence_packet,
    gather_au_labor_collector_results,
)
from scripts.macro_ingestion.au_labor_handoff import (
    attach_leading_to_families,
    leading_matrix_rows,
    merge_research_supplement,
    research_supplement_from_packet,
)
from scripts.market_watch_launch.provider_stub import _research_supplement
from scripts.overnight.research_publishability import validate_research_supplement_publishability
from tests.macro_ingestion.test_au_labor_evidence import _fixture_opener

OVERNIGHT_EVIDENCE = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
EXPECTED = {
    "AU.Labor.anz_indeed_job_ads_sa": ("2026-09", 125.29980391886193),
    "AU.Labor.nab_employment_subindex": ("2026-09", -1.0),
    "AU.Labor.seek_job_ad_trend": ("2026-08", 0.5),
    "AU.Labor.jsa_ivi_national_sa": ("2026-08", 212400.806),
}


def _packet() -> dict:
    as_of = datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)
    points, gaps = gather_au_labor_collector_results(as_of, _fixture_opener)
    return build_au_labor_evidence_packet(as_of, points=points, gaps=gaps)


class TestAuLaborHandoff(unittest.TestCase):
    def test_matrix_and_research_cite_eligible_values(self) -> None:
        packet = _packet()
        by_id = {}
        for obs in packet["observations"]:
            if obs["id"] == "AU.Labor.jsa_ivi_national_sa" and obs.get("transformation") != "sa_level":
                continue
            by_id[obs["id"]] = obs
        for series_id, (period, value) in EXPECTED.items():
            obs = by_id[series_id]
            self.assertEqual(obs["period"], period)
            self.assertAlmostEqual(float(obs["value"]), value, places=3)
            self.assertEqual(obs["weight"], 0.0)
            self.assertTrue(obs.get("vintage"))
            self.assertTrue(obs.get("source_url"))
            self.assertIn("publisher", obs["provenance"])
            self.assertEqual(obs["provenance"]["raw_sha256"], obs["raw_sha256"])

        matrix = {}
        for row in leading_matrix_rows(packet):
            if row["status"] != "context_verified":
                continue
            if row["series_id"] == "AU.Labor.jsa_ivi_national_sa" and abs(float(row["value"]) - 212400.806) > 1:
                continue
            matrix[row["series_id"]] = row
        for series_id, (period, value) in EXPECTED.items():
            row = matrix[series_id]
            self.assertEqual(row["period"], period)
            self.assertAlmostEqual(float(row["value"]), value, places=3)
            self.assertEqual(row["vintage"], by_id[series_id]["vintage"])
            self.assertEqual(row["source"], by_id[series_id]["source_url"])
            self.assertEqual(row["weight"], 0.0)

        supplement = research_supplement_from_packet(packet)
        validate_research_supplement_publishability(supplement)
        cited = " ".join(item["summary"] for item in supplement["news"])
        for series_id, (period, value) in EXPECTED.items():
            self.assertIn(series_id, cited)
            self.assertIn(period, cited)
            self.assertIn(str(by_id[series_id]["vintage"]), cited)
        source_ids = {item["id"] for item in supplement["sources"]}
        self.assertTrue(set(EXPECTED).issubset(source_ids))

    def test_frozen_packet_handoff_does_not_mutate_prior_snapshot(self) -> None:
        before = OVERNIGHT_EVIDENCE.read_bytes()
        prior = json.loads(before)
        original = copy.deepcopy(prior)
        packet = _packet()
        families = attach_leading_to_families({"macro_hard": {"temperature_scores": {"AU": 1}}}, packet)
        self.assertEqual(families["macro_hard"]["temperature_scores"], {"AU": 1})
        block = families["macro_hard"]["au_labor_leading"]
        self.assertEqual(
            {obs["id"] for obs in block["observations"]},
            set(EXPECTED),
        )
        frozen = {
            "families": families,
            "packet_sha256": "unchanged-prior",
        }
        stub = {
            "summary": "Stub provider: no live model research after trusted freeze.",
            "news": [],
            "central_bank_research": [],
            "sources": [],
        }
        merged = merge_research_supplement(stub, block)
        cited = " ".join(item["summary"] for item in merged["news"])
        self.assertIn("AU.Labor.anz_indeed_job_ads_sa", cited)
        cited = _research_supplement(frozen)
        self.assertGreaterEqual(len(cited["sources"]), 4)
        self.assertEqual(prior, original)
        self.assertEqual(OVERNIGHT_EVIDENCE.read_bytes(), before)
        again = _packet()
        self.assertEqual(packet["packet_sha256"], again["packet_sha256"])

    def test_absent_leading_block_leaves_stub_supplement_unchanged(self) -> None:
        supplement = _research_supplement({"families": {"macro_hard": {"status": "fresh"}}})
        self.assertEqual(supplement["news"], [])
        self.assertEqual(supplement["sources"], [])
        self.assertIn("Stub provider", supplement["summary"])


if __name__ == "__main__":
    unittest.main()
