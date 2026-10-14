"""Offline tests for Jobs and Skills Australia IVI and REOS adapters."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_leading.asof import filter_observations_by_asof
from scripts.macro_ingestion.au_leading import jsa_ivi, jsa_reos

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "au" / "jsa"
LIVE_SMOKE_PATH = FIXTURES / "live_smoke.json"
SIDECAR_PATH = ROOT / "data/macro_ingestion/au_jsa_rows.json"

IVI_LANDING = jsa_ivi.IVI_LANDING_URL
IVI_XLSX_AUGUST = (
    "https://www.jobsandskills.gov.au/sites/default/files/2026-09/"
    "internet_vacancies_anzsco_skill_level_states_and_territories_-_august_2026.xlsx"
)
REOS_LANDING = jsa_reos.REOS_LANDING_URL
REOS_XLSX_AUGUST = (
    "https://www.jobsandskills.gov.au/sites/default/files/2026-09/"
    "recruitment_insights_report_-_august_2026_data_file.xlsx"
)


def _fixture_opener(url: str) -> dict:
    mapping = {
        IVI_LANDING: FIXTURES / "ivi_landing_august2026_excerpt.html",
        IVI_XLSX_AUGUST: FIXTURES / "internet_vacancies_skill_level_states_august_2026.xlsx",
        REOS_LANDING: FIXTURES / "reos_landing_august2026_excerpt.html",
        REOS_XLSX_AUGUST: FIXTURES / "reos_august_2026_data_file.xlsx",
    }
    path = mapping.get(url)
    if path is None or not path.is_file():
        return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "fixture_miss"}
    body = path.read_bytes()
    return {
        "ok": True,
        "url": url,
        "http_status": 200,
        "content_type": "application/octet-stream",
        "body": body,
        "error": None,
    }


class TestAuJsa(unittest.TestCase):
    def test_live_smoke_records_not_retrieved_when_publisher_unreachable(self) -> None:
        self.assertTrue(LIVE_SMOKE_PATH.is_file())
        doc = json.loads(LIVE_SMOKE_PATH.read_text(encoding="utf-8"))
        self.assertFalse(doc.get("publisher_live_retrieved"))
        for row in doc["attempts"]:
            self.assertEqual(row.get("outcome"), "not_retrieved")
            self.assertIn("url", row)
            self.assertIn("http_status", row)

    def test_ivi_workbook_parses_august_sa_level_and_mom(self) -> None:
        body = (FIXTURES / "internet_vacancies_skill_level_states_august_2026.xlsx").read_bytes()
        points = jsa_ivi.parse_ivi_skill_states_workbook(
            body,
            source_url=IVI_XLSX_AUGUST,
            release_date=date(2026, 9, 23),
            raw_sha256="26d4dad65384308011fe9f0bf9c08fccbbefe75d05e2d2e758a2be4db919ea36",
            target_period="2026-08",
        )
        levels = [p for p in points if p["transformation"] == "sa_level"]
        moms = [p for p in points if p["transformation"] == "mom_change_from_published_levels"]
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0]["period"], "2026-08")
        self.assertAlmostEqual(levels[0]["value"], 212400.806, places=3)
        self.assertEqual(levels[0]["series_id"], "AUSTRALIAN_TOTAL")
        self.assertEqual(len(moms), 1)
        self.assertAlmostEqual(moms[0]["value"], 0.2639154327497673, places=6)

    def test_fetch_ivi_fixture_end_to_end(self) -> None:
        payload = jsa_ivi.fetch_ivi(
            as_of=datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc),
            opener=_fixture_opener,
        )
        self.assertEqual(payload["status"], "ok")
        periods = {p["period"] for p in payload["points"] if p["transformation"] == "sa_level"}
        self.assertIn("2026-08", periods)
        self.assertNotIn("2026-09", periods)

    def test_asof_drops_september_when_release_after_cutoff(self) -> None:
        doc = json.loads(
            (FIXTURES / "asof_august_september_observations.json").read_text(encoding="utf-8")
        )
        obs = doc["observations"]
        kept = filter_observations_by_asof(obs, datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc))
        periods = {o["period"] for o in kept}
        self.assertEqual(periods, {"2026-08"})

    def test_fetch_reos_reports_workbook_gap_without_xlsx_fixture(self) -> None:
        payload = jsa_reos.fetch_reos(
            as_of=datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc),
            opener=_fixture_opener,
        )
        self.assertEqual(payload["status"], "source_failed")
        self.assertEqual(payload["points"], [])
        gap_ids = {g["id"] for g in payload["gaps"]}
        self.assertIn("AU.Labor.jsa_reos_recruiting_share", gap_ids)
        self.assertIn("AU.Labor.jsa_reos_recruitment_difficulty", gap_ids)
        self.assertIn("AU.Labor.jsa_reos_hiring_intent", gap_ids)

    def test_sidecar_on_disk(self) -> None:
        self.assertTrue(SIDECAR_PATH.is_file())
        doc = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc.get("added_by"), "au-labor-reliability-20261014")
        self.assertEqual(doc.get("score_weight_policy"), "weight_must_remain_zero")
        self.assertIn("rows", doc)
        self.assertIn("gaps", doc)
        for row in doc["rows"]:
            self.assertEqual(row.get("weight"), 0)
            self.assertEqual(row.get("role"), "context")
            self.assertEqual(row.get("country"), "AU")


if __name__ == "__main__":
    unittest.main()
