"""Unit tests for the EA macro ingestion adapter."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import ea as ea_adapter
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ea"
HICP_FIXTURE = FIXTURES / "eurostat_hicp_headline_2026-08.json"
HICP_DE_FIXTURE = FIXTURES / "eurostat_hicp_de.json"
ZEW_TABELLE_TEXT = FIXTURES / "zew_tabelle_sample.txt"


class TestEaAdapter(unittest.TestCase):
    def test_fetch_hicp_from_fixture(self) -> None:
        body = HICP_FIXTURE.read_bytes()
        spec = next(r for r in load_catalog()["series"] if r["id"] == "EA.Inflation.headline")

        def opener(url: str, *, timeout: float = 20):
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": body,
                "error": None,
            }

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["points"][-1]["period"], "2026-08")
        self.assertEqual(payload["points"][-1]["value"], 3.2)

    def test_import_price_not_applicable(self) -> None:
        spec = next(
            r for r in load_catalog()["series"] if r["id"] == "EA.Inflation.import_price_index"
        )

        def opener(url: str, *, timeout: float = 20):
            raise AssertionError("network disabled")

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("status"), "not_applicable")

    def test_offline_ingestion_new_observation(self) -> None:
        catalog = load_catalog()
        spec = copy.deepcopy(next(r for r in catalog["series"] if r["id"] == "EA.Inflation.headline"))
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "UTC",
            "dates": ["2026-12-01T08:00:00Z"],
        }
        catalog = copy.deepcopy(catalog)
        catalog["series"] = [spec]
        body = HICP_FIXTURE.read_bytes()

        def opener(url: str, *, timeout: float = 20):
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": body,
                "error": None,
            }

        with tempfile.TemporaryDirectory() as tmp:
            obs_dir = Path(tmp) / "observations"
            health_dir = Path(tmp) / "health"
            result = run_ingestion(
                mode="offline",
                countries=["EA"],
                catalog=catalog,
                now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
                opener=opener,
                observations_dir=obs_dir,
                health_dir=health_dir,
            )
            self.assertEqual(result["rows"][0]["status"], "new_observation")
            store = json.loads((obs_dir / "ea.json").read_text())
            self.assertTrue(any(o["period"] == "2026-08" for o in store["observations"]))

    def test_country_hicp_de_fixture_uses_geo_de(self) -> None:
        body = HICP_DE_FIXTURE.read_bytes()
        spec = next(r for r in load_catalog()["series"] if r["id"] == "EA.Inflation.hicp_de")
        captured: list[str] = []

        def opener(url: str, *, timeout: float = 20):
            captured.append(url)
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": body,
                "error": None,
            }

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["points"][-1]["period"], "2026-08")
        self.assertEqual(payload["points"][-1]["value"], 2.9)
        self.assertTrue(captured)
        self.assertIn("geo=DE", captured[0])
        self.assertNotIn("geo=EA21", captured[0])

    def test_headline_hicp_series_unchanged(self) -> None:
        headline = next(r for r in load_catalog()["series"] if r["id"] == "EA.Inflation.headline")
        self.assertIn("EA21", str(headline["series_id"]))
        self.assertEqual(headline["weight"], 0.4)

    def test_context_catalog_rows_remain_zero_weight(self) -> None:
        catalog = load_catalog()
        self.assertEqual(catalog["scored_weight_row_count"], 66)
        for row in catalog["series"]:
            if row["id"].startswith("EA.Inflation.hicp_") and row["id"] != "EA.Inflation.hicp_flash":
                self.assertEqual(row["weight"], 0.0)
            if row["id"].startswith("EA.Activity.zew_"):
                self.assertEqual(row["weight"], 0.0)

    def test_zew_tabelle_text_parser(self) -> None:
        text = ZEW_TABELLE_TEXT.read_text(encoding="utf-8")
        balances = ea_adapter.parse_zew_tabelle_text(text)
        self.assertEqual(balances["ZEW_DE_CURRENT_SITUATION"], -47.1)
        self.assertEqual(balances["ZEW_DE_EXPECTATIONS"], 34.7)
        self.assertEqual(balances["ZEW_EA_EXPECTATIONS"], 25.8)

    def test_zew_discovers_indicator_article_past_other_press_notes(self) -> None:
        spec = next(
            r for r in load_catalog()["series"] if r["id"] == "EA.Activity.zew_expectations_de"
        )
        listing = str(spec["endpoint"])
        fillers = "".join(
            f'<a href="/en/press/latest-press-releases/filler-{i}">note {i}</a>'
            for i in range(10)
        )
        listing_html = (
            "<html><body>"
            + fillers
            + "<p>ZEW Indicator of Economic Sentiment // 15.09.2026</p>"
            + '<a href="/en/press/latest-press-releases/late-release">Economic Expectations</a>'
            + "</body></html>"
        ).encode()
        article_html = (
            b'<html><body><a href="http://download.zew.de/e_09_2026_Tabelle.pdf">table</a></body></html>'
        )
        calls: list[str] = []

        def opener(url: str, *, timeout: float = 20):
            calls.append(url)
            if url == listing:
                body = listing_html
            elif url.endswith("/late-release"):
                body = article_html
            else:
                body = b"%PDF-1.4\nnot-a-real-pdf"
            return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertIn("http://download.zew.de/e_09_2026_Tabelle.pdf", calls)
        self.assertTrue(any(url.endswith("/late-release") for url in calls))
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("status"), "source_failed")
        self.assertIn("not parsed", str(payload.get("error")))

    def test_zew_listing_without_tabelle_is_source_failed(self) -> None:
        spec = next(
            r for r in load_catalog()["series"] if r["id"] == "EA.Activity.zew_expectations_de"
        )
        listing = str(spec["endpoint"])

        def opener(url: str, *, timeout: float = 20):
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": b"<html><body><p>No table PDF here.</p></body></html>",
                "error": None,
            }

        payload = ea_adapter.fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("status"), "source_failed")
        self.assertEqual(payload.get("points"), [])
        self.assertIn(listing, str(payload.get("error")))
        self.assertIn("Official ZEW Tabelle was not retrieved or not parsed", str(payload.get("error")))


if __name__ == "__main__":
    unittest.main()
