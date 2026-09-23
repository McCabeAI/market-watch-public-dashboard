"""Public S&P Eurozone flash retrieval: articles, direct PDFs, and rejections."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_ea_pmi import ALT_PUBLIC_DISCOVERY_URLS, RAW_DIR, parse_release_artifact
from scripts.macro_ingestion.adapters import ea as ea_adapter
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion

NY = ZoneInfo("America/New_York")
LISTING = "https://www.pmi.spglobal.com/Public/Release/PressReleases"
ARTICLE = ALT_PUBLIC_DISCOVERY_URLS[0]
FLASH_GUID = "ab6649de01fd4c38a7f2c9a3e52a81bf"
FLASH_PDF_URL = f"https://www.pmi.spglobal.com/Public/Home/PressRelease/{FLASH_GUID}"
ARCHIVED_PDF = RAW_DIR / "sp_eurozone_flash_composite_2026-09.pdf"
EVIDENCE = ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
EVIDENCE_SHA = "41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b"


def _listing_row(title: str, guid: str, when: str = "September 23 2026 08:00 UTC") -> bytes:
    html = (
        "<html><body>"
        f'<span class="releaseDate">{when}</span> '
        f'<span class="releaseTitle">{title}</span> '
        f'<span class="greenListItem"><a href="https://www.pmi.spglobal.com/Public/Home/PressRelease/{guid}">'
        "View More</a></span>"
        "</body></html>"
    )
    return html.encode()


def _article(body: str) -> bytes:
    return f"<html><body><p>{body}</p></body></html>".encode()


class TestEaFlashRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        catalog = load_catalog()
        self.flash = copy.deepcopy(
            next(row for row in catalog["series"] if row["id"] == "EA.Activity.flash_composite_pmi")
        )
        self.final = copy.deepcopy(
            next(row for row in catalog["series"] if row["id"] == "EA.Activity.business_surveys")
        )
        self.when = datetime(2026, 9, 23, 4, 5, tzinfo=NY)

    def _fetch(self, spec, opener):
        return ea_adapter.fetch_series(spec, opener=opener, now=self.when)

    def test_archived_primary_pdf_is_september_flash_not_august(self) -> None:
        data = ARCHIVED_PDF.read_bytes()
        meta = parse_release_artifact(data)
        self.assertTrue(meta["is_flash"])
        self.assertEqual(meta["reference_period"], "2026-09")
        self.assertEqual(meta["composite_value"], 53.1)
        self.assertEqual(meta["release_date"], "2026-09-23")
        self.assertNotEqual(meta["composite_value"], 52.0)
        august = parse_release_artifact((RAW_DIR / "sp_eurozone_composite_2026-08.pdf").read_bytes())
        self.assertFalse(august["is_flash"])
        self.assertEqual(august["reference_period"], "2026-08")
        self.assertEqual(august["composite_value"], 52.0)

    def test_listing_403_public_article_supplies_flash(self) -> None:
        article = _article(
            "S&P Global Flash Eurozone PMI. "
            "Flash Eurozone PMI Composite Output Index: 53.1. "
            "Data were collected 10-21 September 2026. "
            "Embargoed until 1000 CEST (0800 UTC) 23 September 2026. "
            "The index rose to 53.1 in September from 52.0 in August."
        )

        def opener(url: str, *, timeout: float = 20):
            if url == ARTICLE:
                return {"ok": True, "url": url, "http_status": 200, "body": article, "error": None}
            return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}

        payload = self._fetch(self.flash, opener)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["points"]), 1)
        point = payload["points"][0]
        self.assertEqual(point["period"], "2026-09")
        self.assertEqual(point["value"], 53.1)
        self.assertEqual(point["revision_status"], "flash")
        self.assertEqual(point["source_url"], ARTICLE)
        self.assertEqual(point["release_date"], "2026-09-23")
        self.assertNotEqual(point["value"], 52.0)

    def test_listing_403_direct_pdf_discovered_from_public_html(self) -> None:
        pdf = ARCHIVED_PDF.read_bytes()
        listing = _listing_row("S&P Global Flash Eurozone PMI", FLASH_GUID)

        def opener(url: str, *, timeout: float = 20):
            if url == LISTING:
                return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}
            if url == ARTICLE:
                return {"ok": True, "url": url, "http_status": 200, "body": listing, "error": None}
            if url == FLASH_PDF_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": pdf, "error": None}
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "missing"}

        payload = self._fetch(self.flash, opener)
        self.assertTrue(payload["ok"])
        point = payload["points"][0]
        self.assertEqual(point["period"], "2026-09")
        self.assertEqual(point["value"], 53.1)
        self.assertEqual(point["revision_status"], "flash")
        self.assertEqual(point["source_url"], FLASH_PDF_URL)
        self.assertEqual(payload["raw_sha256"], hashlib.sha256(pdf).hexdigest())

    def test_both_routes_closed_stays_missing(self) -> None:
        def opener(url: str, *, timeout: float = 20):
            return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}

        payload = self._fetch(self.flash, opener)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["points"], [])
        self.assertIn("403", payload["error"])
        self.assertIn(LISTING, payload["error"])
        self.assertIsNone(payload.get("value"))

    def test_prior_month_comparator_alone_is_rejected(self) -> None:
        article = _article(
            "S&P Global Flash Eurozone PMI. "
            "The composite reading was unchanged from 52.0 in August. "
            "Data were collected 10-21 September 2026."
        )

        def opener(url: str, *, timeout: float = 20):
            if url == ARTICLE:
                return {"ok": True, "url": url, "http_status": 200, "body": article, "error": None}
            return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}

        payload = self._fetch(self.flash, opener)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["points"], [])

    def test_wrong_geography_component_and_final_are_rejected(self) -> None:
        germany = _article(
            "HCOB Flash Germany PMI. Germany Composite PMI Output Index at 49.1. "
            "Data were collected 10-21 September 2026."
        )
        manufacturing = _article(
            "S&P Global Flash Eurozone PMI. Flash Eurozone Manufacturing PMI: 52.7. "
            "Data were collected 10-21 September 2026."
        )
        final_doc = _article(
            "S&P Global Eurozone Composite PMI. "
            "Eurozone Composite PMI Output Index at 52.0. "
            "Data were collected 12-26 August 2026."
        )

        def opener_for(body: bytes):
            def opener(url: str, *, timeout: float = 20):
                if url == ARTICLE:
                    return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}
                return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}

            return opener

        for body in (germany, manufacturing, final_doc):
            payload = self._fetch(self.flash, opener_for(body))
            self.assertFalse(payload["ok"], body)
            self.assertEqual(payload["points"], [])

    def test_archived_august_final_does_not_clear_september_flash(self) -> None:
        def opener(url: str, *, timeout: float = 20):
            return {"ok": False, "url": url, "http_status": 403, "body": b"Access Denied", "error": "HTTP 403"}

        flash = self._fetch(self.flash, opener)
        self.assertEqual(flash["points"], [])
        final = self._fetch(self.final, opener)
        periods = {point["period"]: point for point in final["points"]}
        self.assertIn("2026-08", periods)
        self.assertEqual(periods["2026-08"]["value"], 52.0)
        self.assertEqual(periods["2026-08"]["revision_status"], "final")
        self.assertNotIn("2026-09", periods)

    def test_repeat_fetch_and_post_freeze_do_not_touch_review_packet(self) -> None:
        before = hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()
        pdf = ARCHIVED_PDF.read_bytes()
        listing = _listing_row("S&P Global Flash Eurozone PMI", FLASH_GUID)

        def opener(url: str, *, timeout: float = 20):
            if url == LISTING:
                return {"ok": True, "url": url, "http_status": 200, "body": listing, "error": None}
            if url == FLASH_PDF_URL:
                return {"ok": True, "url": url, "http_status": 200, "body": pdf, "error": None}
            return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "missing"}

        mini = copy.deepcopy(load_catalog())
        mini["series"] = [self.flash]
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "observations"
            health = Path(tmp) / "health"
            first = run_ingestion(
                mode="offline",
                countries=["EA"],
                catalog=mini,
                now=self.when,
                opener=opener,
                observations_dir=obs,
                health_dir=health,
                persist_canonical=False,
            )
            flash_row = first["rows"][0]
            self.assertEqual(flash_row["status"], "new_observation")
            self.assertEqual(flash_row["cutoff_class"], "post_freeze")
            second = run_ingestion(
                mode="offline",
                countries=["EA"],
                catalog=mini,
                now=self.when,
                opener=opener,
                observations_dir=obs,
                health_dir=health,
                persist_canonical=False,
            )
            self.assertEqual(second["rows"][0]["status"], "checked_unchanged")
            store = json.loads((obs / "ea.json").read_text(encoding="utf-8"))
            sept = [row for row in store["observations"] if row["period"] == "2026-09"]
            self.assertEqual(len(sept), 1)
            self.assertEqual(sept[0]["value"], 53.1)
            self.assertEqual(sept[0]["revision_status"], "flash")
            self.assertTrue(str(first["post_freeze_path"]).startswith(tmp))
        self.assertEqual(hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(), before)
        self.assertEqual(before, EVIDENCE_SHA)


if __name__ == "__main__":
    unittest.main()
