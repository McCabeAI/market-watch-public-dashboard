"""AU labour evidence packet and catalog integration (C6)."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_labor_evidence import (
    P1_GAP_IDS,
    build_au_labor_evidence_packet,
    gather_au_labor_collector_results,
)
from scripts.macro_ingestion.contract import index_series_rows, load_catalog

FIXTURES = Path(__file__).resolve().parent / "fixtures/au"
LEADING_FIXTURES = FIXTURES / "leading"
JSA_FIXTURES = FIXTURES / "jsa"
CALIBRATION_PATH = ROOT / "data/temperature_calibration.json"
OVERNIGHT_EVIDENCE = (
    ROOT
    / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)

from scripts.macro_ingestion.au_leading import anz, jsa_ivi, nab, seek

ANZ_PRESS = anz.PRESS_RELEASE_URL
ANZ_XLSX = anz.DEFAULT_XLSX_URL
NAB_NEWS = nab.NEWS_URL
NAB_PDF = nab.DEFAULT_PDF_URL
SEEK_CATEGORY = seek.CATEGORY_URL
SEEK_AUGUST = seek.AUGUST_ARTICLE_URL
IVI_LANDING = jsa_ivi.IVI_LANDING_URL
IVI_XLSX_AUGUST = (
    "https://www.jobsandskills.gov.au/sites/default/files/2026-09/"
    "internet_vacancies_anzsco_skill_level_states_and_territories_-_august_2026.xlsx"
)


def _fixture_opener(url: str) -> dict:
    mapping = {
        ANZ_PRESS: (LEADING_FIXTURES / "anz_press_release_sep2026_excerpt.html").read_bytes(),
        ANZ_XLSX: (LEADING_FIXTURES / "anz_job_ads_data_sep26.xlsx").read_bytes(),
        NAB_NEWS: (LEADING_FIXTURES / "nab_trade_sept2026_excerpt.html").read_bytes(),
        NAB_PDF: (LEADING_FIXTURES / "nab_survey_sep2026_pages12.pdf").read_bytes(),
        SEEK_CATEGORY: (LEADING_FIXTURES / "seek_employment_reports_category_excerpt.html").read_bytes(),
        SEEK_AUGUST: (LEADING_FIXTURES / "seek_employment_report_august26_excerpt.html").read_bytes(),
        IVI_LANDING: (JSA_FIXTURES / "ivi_landing_august2026_excerpt.html").read_bytes(),
        IVI_XLSX_AUGUST: (
            JSA_FIXTURES / "internet_vacancies_skill_level_states_august_2026.xlsx"
        ).read_bytes(),
    }
    body = mapping.get(url)
    if body is None:
        return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "fixture_miss"}
    return {
        "ok": True,
        "url": url,
        "http_status": 200,
        "content_type": "application/octet-stream",
        "body": body,
        "error": None,
    }


class TestAuLaborEvidence(unittest.TestCase):
    def test_catalog_load_and_labor_rows(self) -> None:
        catalog = load_catalog()
        by_id = index_series_rows(catalog["series"])
        scored = [r for r in catalog["series"] if r.get("role") == "scored"]
        self.assertEqual(len(scored), 66)

        for rid in (
            "AU.Labor.jsa_ivi_national_sa",
            "AU.Labor.anz_indeed_job_ads_sa",
            "AU.Labor.nab_employment_subindex",
            "AU.Labor.seek_job_ad_trend",
            "AU.Labor.jsa_reos_recruiting_share",
            "AU.Labor.full_time",
        ):
            self.assertIn(rid, by_id)
            self.assertEqual(float(by_id[rid].get("weight", 0.0)), 0.0)

        unemployment = by_id["AU.Labor.unemployment"]
        self.assertEqual(unemployment.get("transform"), "percent")
        rule = unemployment.get("release_rule") or {}
        self.assertEqual(rule.get("expected_periods", {}).get("2026-10-15T11:30:00+11:00"), "2026-09")
        self.assertIn("2026-10-15T11:30:00+11:00", rule.get("dates") or [])

    def test_evidence_as_of_oct15_from_fixtures(self) -> None:
        as_of = datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)
        points, gaps = gather_au_labor_collector_results(as_of, _fixture_opener)
        packet = build_au_labor_evidence_packet(as_of, points=points, gaps=gaps)
        periods = {(o["id"], o["period"]) for o in packet["observations"]}
        self.assertIn(("AU.Labor.anz_indeed_job_ads_sa", "2026-09"), periods)
        self.assertIn(("AU.Labor.nab_employment_subindex", "2026-09"), periods)
        self.assertIn(("AU.Labor.seek_job_ad_trend", "2026-08"), periods)
        self.assertIn(("AU.Labor.jsa_ivi_national_sa", "2026-08"), periods)
        self.assertNotIn(("AU.Labor.jsa_ivi_national_sa", "2026-09"), periods)
        self.assertNotIn(("AU.Labor.seek_job_ad_trend", "2026-09"), periods)

        planted = copy.deepcopy(points)
        planted.append(
            {
                "id": "AU.Labor.jsa_ivi_national_sa",
                "publisher": "jsa_ivi",
                "period": "2026-09",
                "value": 999.0,
                "units": "vacancies",
                "transformation": "sa_level",
                "release_date": "2026-10-21",
                "raw_sha256": "deadbeef",
            }
        )
        planted.append(
            {
                "id": "AU.Labor.seek_job_ad_trend",
                "publisher": "seek_employment_report",
                "period": "2026-09",
                "value": 1.0,
                "units": "percent",
                "transformation": "trend_mom_pct",
                "release_date": "2026-10-21",
                "raw_sha256": "deadbeef",
            }
        )
        planted.append(
            {
                "id": "AU.Labor.jsa_ivi_national_sa",
                "publisher": "jsa_ivi",
                "period": "2026-09",
                "value": 1.0,
                "units": "vacancies",
                "transformation": "sa_level",
                "release_date": "2026-09-23",
                "raw_sha256": "deadbeef",
            }
        )
        blocked = build_au_labor_evidence_packet(as_of, points=planted, gaps=gaps)
        blocked_periods = {(o["id"], o["period"]) for o in blocked["observations"]}
        self.assertNotIn(("AU.Labor.jsa_ivi_national_sa", "2026-09"), blocked_periods)
        self.assertNotIn(("AU.Labor.seek_job_ad_trend", "2026-09"), blocked_periods)

    def test_reos_gaps_mark_partial(self) -> None:
        as_of = datetime(2026, 10, 15, tzinfo=timezone.utc)
        gaps = [{"id": gid, "status": "source_failed", "reason": "missing workbook"} for gid in P1_GAP_IDS]
        packet = build_au_labor_evidence_packet(as_of, points=[], gaps=gaps)
        self.assertTrue(packet["partial"])
        gap_ids = {g["id"] for g in packet["gaps"]}
        self.assertTrue(P1_GAP_IDS.issubset(gap_ids))

    def test_packet_hash_stable(self) -> None:
        as_of = datetime(2026, 10, 15, tzinfo=timezone.utc)
        points, gaps = gather_au_labor_collector_results(as_of, _fixture_opener)
        first = build_au_labor_evidence_packet(as_of, points=points, gaps=gaps)
        second = build_au_labor_evidence_packet(as_of, points=points, gaps=gaps)
        self.assertEqual(first["packet_sha256"], second["packet_sha256"])

    def test_build_does_not_touch_frozen_anchors(self) -> None:
        import tempfile

        cal_before = CALIBRATION_PATH.read_bytes()
        overnight_before = OVERNIGHT_EVIDENCE.read_bytes() if OVERNIGHT_EVIDENCE.is_file() else None
        with tempfile.TemporaryDirectory() as tmp:
            as_of = datetime(2026, 10, 15, tzinfo=timezone.utc)
            points, gaps = gather_au_labor_collector_results(as_of, _fixture_opener)
            packet = build_au_labor_evidence_packet(as_of, points=points, gaps=gaps)
            out = Path(tmp) / "au_labor_evidence.json"
            out.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(out.is_file())
        self.assertEqual(CALIBRATION_PATH.read_bytes(), cal_before)
        if overnight_before is not None:
            self.assertEqual(OVERNIGHT_EVIDENCE.read_bytes(), overnight_before)


if __name__ == "__main__":
    unittest.main()
