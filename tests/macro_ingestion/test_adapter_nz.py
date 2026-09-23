"""Tests for the New Zealand macro ingestion adapter."""

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

from scripts.macro_ingestion.adapters import nz as nz_adapter
from scripts.macro_ingestion.contract import index_series_rows, load_catalog
from scripts.macro_ingestion.runner import live_opener, run_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures/nz"


def _fixture_opener_factory() -> dict[str, bytes]:
    mapping = {
        "https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/": (
            FIXTURES / "cpi_release_page.html"
        ).read_bytes(),
        "https://www.stats.govt.nz/assets/Uploads/test/consumers-price-index-june-2026-quarter-infoshare-data.csv": (
            FIXTURES / "cpi_infoshare_tiny.csv"
        ).read_bytes(),
        "https://www.stats.govt.nz/assets/Uploads/Labour-market-statistics/Labour-market-statistics-June-2026-quarter/Download-data/household-labour-force-survey-june-2026-quarter.xlsx": (
            FIXTURES / "hlfs_table1_tiny.xlsx"
        ).read_bytes(),
        "https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/": (
            FIXTURES / "cpi_release_page.html"
        ).read_bytes(),
        "https://businessnz.org.nz/psi/": (FIXTURES / "businessnz_psi_challenge.html").read_bytes(),
        "https://www.bnz.co.nz/institutional-banking/research/publications": (
            FIXTURES / "bnz_publications_snippet.html"
        ).read_bytes(),
        "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf": (
            FIXTURES / "bnz_psi_august_2026.pdf"
        ).read_bytes(),
        "https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/": (
            FIXTURES / "anz_consumer_confidence_no_index.html"
        ).read_bytes(),
    }
    return mapping


class TestAdapterNz(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
        self.mapping = _fixture_opener_factory()

    def _opener(self, url: str, *, timeout: float = 20) -> dict:
        body = self.mapping.get(url)
        if body is None:
            return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "fixture_miss"}
        return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

    def test_catalog_keeps_scored_consumer_confidence(self) -> None:
        catalog = load_catalog()
        row = index_series_rows(catalog["series"])["NZ.Consumer.confidence"]
        self.assertEqual(row["role"], "scored")
        self.assertEqual(row["weight"], 0.25)

    def test_cpi_headline_parses_fixture(self) -> None:
        spec = {
            "id": "NZ.Inflation.headline",
            "series_id": "CPIQ.SE9A",
            "transform": "yoy_pct",
            "endpoint": "https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/",
            "retrieval_method": "information_release_xlsx_tables_3.02_3.03",
        }
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["points"]), 1)
        self.assertEqual(payload["points"][0]["period"], "2026-Q2")
        self.assertEqual(payload["points"][0]["value"], 4.1)

    def test_run_ingestion_new_observation_cpi(self) -> None:
        catalog = load_catalog()
        spec = copy.deepcopy(index_series_rows(catalog["series"])["NZ.Inflation.headline"])
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "Pacific/Auckland",
            "dates": ["2026-12-01T10:45:00"],
        }
        cat = copy.deepcopy(catalog)
        cat["series"] = [spec]
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "observations"
            health = Path(tmp) / "health"
            result = run_ingestion(
                mode="offline",
                countries=["NZ"],
                catalog=cat,
                now=self.now,
                opener=self._opener,
                observations_dir=obs,
                health_dir=health,
            )
            self.assertEqual(result["rows"][0]["status"], "new_observation")

    def test_unemployment_hlfs_fixture(self) -> None:
        page = {
            "PageDate": "2026-08-05 10:45:00",
            "PageBlocks": [
                {
                    "Title": "download",
                    "BlockDocuments": [
                        {
                            "DocumentLink": "/assets/Uploads/Labour-market-statistics/household-labour-force-survey-june-2026-quarter.xlsx",
                            "Name": "household-labour-force-survey-june-2026-quarter.xlsx",
                        }
                    ],
                }
            ],
        }
        import html as html_lib

        payload_json = html_lib.escape(json.dumps(page), quote=True)
        html_doc = (
            f'<!DOCTYPE html><html><body><div id="pageViewData" data-value="{payload_json}"></div></body></html>'
        )
        self.mapping[
            "https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/"
        ] = html_doc.encode()
        self.mapping[
            "https://www.stats.govt.nz/assets/Uploads/Labour-market-statistics/household-labour-force-survey-june-2026-quarter.xlsx"
        ] = (FIXTURES / "hlfs_table1_tiny.xlsx").read_bytes()
        spec = {
            "id": "NZ.Labor.unemployment",
            "series_id": "HLFQ.S1F3S",
            "transform": "percent",
            "endpoint": "https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/",
            "retrieval_method": "information_release_zip_hlfs_csv",
        }
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["points"][0]["value"], 5.6)

    def test_pci_from_bnz_pdf_fixture(self) -> None:
        spec = {
            "id": "NZ.Activity.business_surveys",
            "series_id": "BUSINESSNZ_PCI_GDP_WEIGHTED",
            "transform": "diffusion_index",
            "retrieval_method": "harvest_nz_pci_publications_psi_pdf",
        }
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["points"][0]["period"], "2026-08")
        self.assertGreater(payload["points"][0]["value"], 50.0)

    def test_businessnz_challenge_is_license_gap(self) -> None:
        spec = {
            "id": "NZ.Activity.business_surveys",
            "series_id": "BUSINESSNZ_PCI_GDP_WEIGHTED",
            "transform": "diffusion_index",
            "retrieval_method": "harvest_nz_pci_publications_psi_pdf",
        }
        self.mapping.pop("https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf", None)
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload.get("challenge_page"))
        self.assertEqual(payload.get("status"), "license_gap")

    def test_anz_confidence_unparseable_source_failed(self) -> None:
        spec = {
            "id": "NZ.Consumer.confidence",
            "role": "scored",
            "endpoint": "https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/",
            "retrieval_method": "official_web_page_text",
            "transform": "index_level",
        }
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertEqual(payload.get("status"), "source_failed")

    def test_explanatory_alias_skipped(self) -> None:
        spec = {
            "id": "NZ.Consumer.confidence",
            "role": "explanatory_alias",
            "endpoint": "https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/",
            "retrieval_method": "official_web_page_text",
        }
        payload = nz_adapter.fetch_series(spec, opener=self._opener, now=self.now)
        self.assertEqual(payload.get("status"), "not_applicable")


class TestNzLiveSmoke(unittest.TestCase):
    def test_write_live_smoke_report(self) -> None:
        probes = [
            {
                "label": "stats_nz_cpi_release",
                "url": "https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/",
            },
            {
                "label": "stats_nz_overseas_trade_index",
                "url": "https://www.stats.govt.nz/information-releases/overseas-trade-indexes-prices/",
            },
            {
                "label": "bnz_psi_pdf",
                "url": "https://www.bnz.co.nz/assets/markets/research/BNZ-BusinessNZ-PSI-Release_August-2026_web.pdf",
            },
            {
                "label": "bnz_publications_index",
                "url": "https://www.bnz.co.nz/institutional-banking/research/publications",
            },
        ]
        report: dict[str, object] = {"country": "NZ", "checked_at": datetime.now(timezone.utc).isoformat(), "probes": []}
        for probe in probes:
            resp = live_opener(probe["url"], timeout=20)
            entry = {
                "label": probe["label"],
                "url": probe["url"],
                "ok": resp.get("ok"),
                "http_status": resp.get("http_status"),
                "error": resp.get("error"),
                "body_prefix": (resp.get("body") or b"")[:16].hex(),
                "is_pdf": (resp.get("body") or b"")[:4] == b"%PDF",
                "challenge_page": nz_adapter.is_challenge_page(resp.get("body") or b""),
            }
            if probe["label"] == "stats_nz_cpi_release" and resp.get("ok"):
                page = nz_adapter._parse_page_view_data(nz_adapter._decode_html(resp.get("body") or b""))
                entry["has_page_view_data"] = page is not None
            report["probes"].append(entry)
        out = FIXTURES / "live_smoke_report.json"
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
