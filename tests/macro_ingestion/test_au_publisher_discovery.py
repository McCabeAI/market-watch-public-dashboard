"""Publisher discovery for ANZ, NAB, and SEEK must not treat one historical URL as current."""

from __future__ import annotations

import io
import sys
import unittest
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_leading import anz, nab, seek

FIXTURES = Path(__file__).resolve().parent / "fixtures/au/leading"
OCTOBER_PRESS = anz.PRESS_RELEASE_URL
NOVEMBER_PRESS = "https://www.anz.com.au/newsroom/media/2026/november/job-ads-november/"
NOVEMBER_XLSX = (
    "https://www.anz.com.au/content/dam/anzcomau/mediacentre/images/jobads/2026/november/"
    "ANZ-Indeed%20Australian%20Job%20Ads%20data_Nov26.xlsx"
)
NAB_NOVEMBER = "https://www.nabtrade.com.au/insights/news/2026/11/nab-business-survey---november-2026"
SEEK_NOVEMBER = "https://au.seek.com/about/news/seek-employment-report-november26/"


def _november_xlsx() -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "ANZ-Indeed Australian Job Ads"
    sheet.append(["date", "trend", "sa"])
    sheet.append([None, None, None])
    sheet.append([None, None, None])
    sheet.append([date(2026, 11, 1), 1.0, 130.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestAuPublisherDiscovery(unittest.TestCase):
    def test_timeout_does_not_fall_back_to_historical_url(self) -> None:
        seen: list[str] = []

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            seen.append(url)
            return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "timeout"}

        payload = anz.collect_anz(as_of=date(2026, 11, 10), opener=opener)
        self.assertEqual(payload["points"], [])
        self.assertTrue(seen)
        self.assertTrue(all(url == anz.NEWSROOM_INDEX_URL for url in seen))
        self.assertLessEqual(len(seen), 2)
        self.assertTrue(any(g["status"] == "source_failed" for g in payload["gaps"]))
        self.assertNotIn(OCTOBER_PRESS, seen)

    def test_license_wall_is_not_a_guessed_url(self) -> None:
        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            return {
                "ok": False,
                "url": url,
                "http_status": 403,
                "body": b"Access Denied",
                "error": "HTTP 403",
            }

        payload = nab.collect_nab(as_of=date(2026, 11, 20), opener=opener)
        self.assertEqual(payload["points"], [])
        self.assertTrue(any(g["status"] == "license_gap" for g in payload["gaps"]))

    def test_anz_follows_later_dated_release(self) -> None:
        seen: list[str] = []
        press = (
            '<meta name="modified_date" content="2026-11-03"/>'
            f'<a href="{NOVEMBER_XLSX}">Download data</a>'
        )
        index = f'<a href="{NOVEMBER_PRESS}">Job ads November</a>'
        bodies = {
            anz.NEWSROOM_INDEX_URL: index.encode(),
            NOVEMBER_PRESS: press.encode(),
            NOVEMBER_XLSX: _november_xlsx(),
        }

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            seen.append(url)
            body = bodies.get(url)
            if body is None:
                return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "fixture_miss"}
            return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

        payload = anz.collect_anz(as_of=date(2026, 11, 10), opener=opener)
        self.assertEqual(len(payload["points"]), 1)
        point = payload["points"][0]
        self.assertEqual(point["period"], "2026-11")
        self.assertEqual(point["value"], 130.5)
        self.assertEqual(point["provenance"], "publisher_index")
        self.assertNotIn(OCTOBER_PRESS, seen)
        self.assertNotIn(anz.DEFAULT_XLSX_URL, seen)

    def test_empty_listing_reports_gap_and_keeps_verified_vintage(self) -> None:
        august = (FIXTURES / "seek_employment_report_august26_excerpt.html").read_bytes()
        seen: list[str] = []

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            seen.append(url)
            if url == seek.CATEGORY_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": b"<html><body>no reports</body></html>", "error": None}
            if url == seek.AUGUST_ARTICLE_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": august, "error": None}
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "fixture_miss"}

        payload = seek.collect_seek(as_of=date(2026, 10, 14), opener=opener)
        self.assertTrue(any(g["status"] == "discovery_gap" for g in payload["gaps"]))
        self.assertEqual(len(payload["points"]), 1)
        self.assertEqual(payload["points"][0]["period"], "2026-08")
        self.assertEqual(payload["points"][0]["provenance"], "controlled_release_index")
        self.assertNotIn(SEEK_NOVEMBER, seen)

    def test_seek_prefers_discovered_november_article(self) -> None:
        seen: list[str] = []
        index = f'<a href="{SEEK_NOVEMBER}">November report</a>'
        article = (
            '<meta name="article-publish-date" content="2026-11-18"/>'
            "<p>Job ads rose modestly, up 0.4% from October.</p>"
        )

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            seen.append(url)
            if url == seek.CATEGORY_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": index.encode(), "error": None}
            if url == SEEK_NOVEMBER:
                return {"ok": True, "url": url, "http_status": 200, "body": article.encode(), "error": None}
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "fixture_miss"}

        payload = seek.collect_seek(as_of=date(2026, 11, 20), opener=opener)
        self.assertEqual(payload["points"][0]["period"], "2026-11")
        self.assertAlmostEqual(payload["points"][0]["value"], 0.4)
        self.assertNotIn(seek.AUGUST_ARTICLE_URL, seen)

    def test_nab_discovered_article_does_not_reuse_september_pdf(self) -> None:
        seen: list[str] = []
        september_pdf = (FIXTURES / "nab_survey_sep2026_pages12.pdf").read_bytes()
        index = f'<a href="{NAB_NOVEMBER}">NAB Business Survey - November 2026</a>'
        article = (
            "<h1>NAB Business Survey - November 2026</h1>"
            '<div class="cmp-author-by-line__timedate--text">10 November 2026</div>'
            '<a href="https://www.nab.com.au/content/dam/example/2026m11%20NAB%20Monthly%20Business%20Survey.pdf">pdf</a>'
        )

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            seen.append(url)
            if url == nab.NEWS_INDEX_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": index.encode(), "error": None}
            if url == NAB_NOVEMBER:
                return {"ok": True, "url": url, "http_status": 200, "body": article.encode(), "error": None}
            if "2026m11" in url:
                return {"ok": True, "url": url, "http_status": 200, "body": september_pdf, "error": None}
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "fixture_miss"}

        payload = nab.collect_nab(as_of=date(2026, 11, 12), opener=opener)
        self.assertEqual(len(payload["points"]), 1)
        self.assertEqual(payload["points"][0]["period"], "2026-11")
        self.assertNotIn(nab.NEWS_URL, seen)
        self.assertNotIn(nab.DEFAULT_PDF_URL, seen)


if __name__ == "__main__":
    unittest.main()
