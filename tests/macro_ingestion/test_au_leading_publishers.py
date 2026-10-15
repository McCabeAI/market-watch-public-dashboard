"""Offline tests for AU leading-indicator publisher ingestion (ANZ, NAB, SEEK)."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_leading import anz, nab, seek

FIXTURES = Path(__file__).resolve().parent / "fixtures/au/leading"
LIVE_SMOKE_PATH = FIXTURES / "live_smoke.json"
SIDECAR_PATH = ROOT / "data/macro_ingestion/au_leading_publisher_rows.json"

ANZ_PRESS = anz.PRESS_RELEASE_URL
ANZ_XLSX = anz.DEFAULT_XLSX_URL
NAB_NEWS = nab.NEWS_URL
NAB_PDF = nab.DEFAULT_PDF_URL
SEEK_CATEGORY = seek.CATEGORY_URL
SEEK_AUGUST = seek.AUGUST_ARTICLE_URL


def _fixture_mapping() -> dict[str, bytes]:
    return {
        anz.NEWSROOM_INDEX_URL: (FIXTURES / "anz_newsroom_index_excerpt.html").read_bytes(),
        ANZ_PRESS: (FIXTURES / "anz_press_release_sep2026_excerpt.html").read_bytes(),
        ANZ_XLSX: (FIXTURES / "anz_job_ads_data_sep26.xlsx").read_bytes(),
        nab.NEWS_INDEX_URL: (FIXTURES / "nab_news_index_excerpt.html").read_bytes(),
        NAB_NEWS: (FIXTURES / "nab_trade_sept2026_excerpt.html").read_bytes(),
        NAB_PDF: (FIXTURES / "nab_survey_sep2026_pages12.pdf").read_bytes(),
        SEEK_CATEGORY: (FIXTURES / "seek_employment_reports_category_excerpt.html").read_bytes(),
        SEEK_AUGUST: (FIXTURES / "seek_employment_report_august26_excerpt.html").read_bytes(),
    }


def _fixture_opener(url: str) -> dict:
    body = _fixture_mapping().get(url)
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


def build_au_leading_publisher_rows(as_of: date, opener) -> dict:
    parts = [
        anz.collect_anz(as_of=as_of, opener=opener),
        nab.collect_nab(as_of=as_of, opener=opener),
        seek.collect_seek(as_of=as_of, opener=opener),
    ]
    rows: list[dict] = []
    gaps: list[dict] = []
    qualitative: list[dict] = []
    attempts: list[dict] = []
    for part in parts:
        rows.extend(part.get("points") or [])
        gaps.extend(part.get("gaps") or [])
        qualitative.extend(part.get("qualitative") or [])
        attempts.extend(
            anz.attempts_to_json(part.get("attempts") or [])
            if part is parts[0]
            else (
                nab.attempts_to_json(part.get("attempts") or [])
                if part is parts[1]
                else seek.attempts_to_json(part.get("attempts") or [])
            )
        )
    return {
        "added_by": "au-labor-reliability-20261014",
        "as_of": as_of.isoformat(),
        "rows": rows,
        "gaps": gaps,
        "qualitative": qualitative,
        "attempts": attempts,
    }


class TestAuLeadingPublishers(unittest.TestCase):
    def test_anz_parses_sa_level_september(self) -> None:
        payload = anz.collect_anz(as_of=date(2026, 10, 14), opener=_fixture_opener)
        self.assertEqual(len(payload["points"]), 1)
        pt = payload["points"][0]
        self.assertEqual(pt["id"], "AU.Labor.anz_indeed_job_ads_sa")
        self.assertEqual(pt["period"], "2026-09")
        self.assertAlmostEqual(pt["value"], 125.29980391886193, places=6)
        self.assertEqual(pt["series_label"], "seasonally_adjusted")
        self.assertEqual(pt["release_date"], "2026-10-06")
        self.assertEqual(pt["weight"], 0.0)

    def test_anz_hidden_before_release(self) -> None:
        payload = anz.collect_anz(as_of=date(2026, 10, 5), opener=_fixture_opener)
        self.assertEqual(payload["points"], [])
        self.assertTrue(any(g["id"] == "AU.Labor.anz_indeed_job_ads_sa" for g in payload["gaps"]))

    def test_nab_employment_subindex_from_pdf_fixture(self) -> None:
        payload = nab.collect_nab(as_of=date(2026, 10, 14), opener=_fixture_opener)
        self.assertEqual(len(payload["points"]), 1)
        pt = payload["points"][0]
        self.assertEqual(pt["id"], "AU.Labor.nab_employment_subindex")
        self.assertEqual(pt["period"], "2026-09")
        self.assertEqual(pt["value"], -1.0)
        self.assertEqual(pt["units"], "index_points")
        self.assertEqual(pt["release_date"], "2026-10-13")

    def test_seek_august_trend_mom_only(self) -> None:
        payload = seek.collect_seek(as_of=date(2026, 10, 14), opener=_fixture_opener)
        self.assertEqual(len(payload["points"]), 1)
        pt = payload["points"][0]
        self.assertEqual(pt["id"], "AU.Labor.seek_job_ad_trend")
        self.assertEqual(pt["period"], "2026-08")
        self.assertAlmostEqual(pt["value"], 0.5)
        self.assertEqual(pt["transformation"], "trend_mom_pct")
        self.assertEqual(pt["series_label"], "trend")

    def test_seek_does_not_emit_september_at_as_of_oct14(self) -> None:
        payload = build_au_leading_publisher_rows(date(2026, 10, 14), _fixture_opener)
        periods = {(r["id"], r["period"]) for r in payload["rows"]}
        self.assertNotIn(("AU.Labor.seek_job_ad_trend", "2026-09"), periods)

    def test_sidecar_fixture_on_disk(self) -> None:
        self.assertTrue(SIDECAR_PATH.is_file(), "au_leading_publisher_rows.json missing")
        doc = json.loads(SIDECAR_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc.get("added_by"), "au-labor-reliability-20261014")
        self.assertIn("rows", doc)
        self.assertIn("gaps", doc)

    def test_live_smoke_fixture_present(self) -> None:
        self.assertTrue(LIVE_SMOKE_PATH.is_file(), "live_smoke.json missing")
        doc = json.loads(LIVE_SMOKE_PATH.read_text(encoding="utf-8"))
        self.assertIn("attempts", doc)
        for row in doc["attempts"]:
            self.assertIn("url", row)
            self.assertIn("outcome", row)


if __name__ == "__main__":
    unittest.main()
