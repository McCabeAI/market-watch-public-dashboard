"""Australia macro ingestion adapter tests."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters.au import fetch_series, parse_abs_time_series_workbook
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import live_opener, run_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "au"
LIVE_REPORT_PATH = FIXTURES / "live_smoke_report.json"


class TestAustraliaAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mini_catalog(self, spec: dict) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [copy.deepcopy(spec)]
        return cat

    def test_fixture_workbook_parse(self) -> None:
        body = (FIXTURES / "labour_unemployment_fixture.xlsx").read_bytes()
        series = parse_abs_time_series_workbook(body, "A84423050A", cadence="monthly")
        self.assertEqual(series[-1], ("2026-08", 4.1))

    def test_fixture_ingestion_new_observation(self) -> None:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "AU.Labor.unemployment")
        )
        spec["endpoint"] = "fixture://labour_unemployment_fixture.xlsx"
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "Australia/Sydney",
            "dates": ["2026-12-01T11:30:00+11:00"],
        }
        fixture_bytes = (FIXTURES / "labour_unemployment_fixture.xlsx").read_bytes()

        def opener(url: str, *, timeout: float = 20) -> dict:
            if "labour_unemployment_fixture" in url:
                return {
                    "ok": True,
                    "url": url,
                    "http_status": 200,
                    "body": fixture_bytes,
                    "error": None,
                }
            return {"ok": False, "url": url, "http_status": None, "body": b"", "error": "unexpected_url"}

        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["AU"],
            catalog=self._mini_catalog(spec),
            now=now,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "new_observation")
        store = json.loads((self.obs_dir / "au.json").read_text())
        self.assertEqual(store["observations"][-1]["period"], "2026-08")
        self.assertAlmostEqual(store["observations"][-1]["value"], 4.1)

    def test_due_labour_release_resolves_current_workbook(self) -> None:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "AU.Labor.unemployment")
        )
        fixture_bytes = (FIXTURES / "labour_unemployment_fixture.xlsx").read_bytes()
        seen: list[str] = []

        def opener(url: str, *, timeout: float = 20) -> dict:
            seen.append(url)
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": fixture_bytes,
                "error": None,
            }

        payload = fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(payload.get("ok"))
        self.assertTrue(any("/aug-2026/62020001.xlsx" in url for url in seen), seen)
        self.assertEqual(payload["points"][0]["period"], "2026-08")
        self.assertAlmostEqual(payload["points"][0]["value"], 4.1)

    def test_ceased_retail_does_not_gain_2026_point(self) -> None:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "AU.Consumer.retail")
        )
        spec["endpoint"] = "fixture://retail_ceased_fixture.xlsx"
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "Australia/Sydney",
            "dates": ["2027-01-01T11:30:00+11:00"],
        }
        fixture_bytes = (FIXTURES / "retail_ceased_fixture.xlsx").read_bytes()

        def opener(url: str, *, timeout: float = 20) -> dict:
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": fixture_bytes,
                "error": None,
            }

        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        run_ingestion(
            mode="offline",
            countries=["AU"],
            catalog=self._mini_catalog(spec),
            now=now,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        store = json.loads((self.obs_dir / "au.json").read_text())
        periods = [row["period"] for row in store["observations"]]
        self.assertIn("2025-06", periods)
        self.assertFalse(any(p.startswith("2026-") for p in periods))

    def test_explanatory_alias_not_applicable_without_network(self) -> None:
        spec = next(r for r in self.catalog["series"] if r["id"] == "AU.Inflation.cpi_core_trimmed_already_scored_note")

        def opener(url: str, *, timeout: float = 20) -> dict:
            raise AssertionError("opener must not be called for explanatory_alias")

        payload = fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        self.assertEqual(payload.get("status"), "not_applicable")

    def test_challenge_html_is_license_gap(self) -> None:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "AU.Activity.business_surveys")
        )
        challenge = (FIXTURES / "pmi_challenge.html").read_bytes()

        def opener(url: str, *, timeout: float = 20) -> dict:
            return {
                "ok": True,
                "url": url,
                "http_status": 403,
                "body": challenge,
                "error": None,
            }

        payload = fetch_series(
            spec,
            opener=opener,
            now=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
        self.assertTrue(payload.get("challenge_page"))
        self.assertEqual(payload.get("status"), "license_gap")

    def test_live_smoke_report(self) -> None:
        if os.environ.get("MACRO_INGESTION_LIVE_SMOKE") != "1":
            report = json.loads(LIVE_REPORT_PATH.read_text(encoding="utf-8"))
            self.assertIn("probes", report)
            self.assertTrue(report["probes"])
            return
        probes = [
            {
                "name": "abs_labour_topic",
                "url": "https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia",
            },
            {
                "name": "abs_ppi_topic",
                "url": "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/producer-price-indexes-australia",
            },
            {
                "name": "sp_global_pmi_listing",
                "url": "https://www.pmi.spglobal.com/Public/Release/PressReleases",
            },
        ]
        report: dict[str, object] = {
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "probes": [],
        }
        for probe in probes:
            entry: dict[str, object] = {"name": probe["name"], "url": probe["url"]}
            resp = live_opener(probe["url"], timeout=20)
            body = resp.get("body") or b""
            entry["ok"] = bool(resp.get("ok"))
            entry["http_status"] = resp.get("http_status")
            entry["error"] = resp.get("error")
            entry["bytes"] = len(body)
            entry["challenge_page"] = b"cf-chl" in body.lower() or b"access denied" in body.lower()
            if probe["name"] == "sp_global_pmi_listing":
                entry["release_title_present"] = b"releaseTitle" in body
            if probe["name"] == "abs_ppi_topic":
                entry["xlsx_link_in_html"] = b".xlsx" in body
            report["probes"].append(entry)

        LIVE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(LIVE_REPORT_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
