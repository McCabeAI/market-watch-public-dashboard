"""Australia macro ingestion adapter tests."""

from __future__ import annotations

import copy
import io
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
from scripts.macro_ingestion.vintage import append_observation, load_store, save_store
from scripts.market_watch_launch.ingest import _enrich_row
from scripts.market_watch_launch.quality_gate import _country_release_due_blocking

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "au"
LIVE_REPORT_PATH = FIXTURES / "live_smoke_report.json"
CPI_SPENDING_LIVE_REPORT_PATH = FIXTURES / "cpi_spending_live_smoke_report.json"

DUE_AFTER_AUG_CPI = datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)


def _build_abs_workbook(series_id: str, observations: list[tuple[datetime, float]]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data1"
    for _ in range(9):
        ws.append([None])
    header = [None, series_id]
    ws.append(header)
    for dt, val in observations:
        ws.append([dt, val])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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

    def _spec(self, series_id: str) -> dict:
        return copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == series_id))

    def test_due_cpi_and_spending_resolve_aug_workbook(self) -> None:
        cases = [
            ("AU.Inflation.headline", "A130393721F", "640101.xlsx", 3.5, 4.0),
            ("AU.Inflation.underlying", "A130400382R", "640106.xlsx", 3.6, 3.6),
            ("AU.Consumer.spending", "A130200586W", "5682001.xlsx", 1.1, 0.0),
        ]
        july = datetime(2026, 7, 1)
        august = datetime(2026, 8, 1)
        for catalog_id, abs_series_id, workbook_name, july_val, aug_val in cases:
            spec = self._spec(catalog_id)
            body = _build_abs_workbook(
                abs_series_id,
                [(july, july_val), (august, aug_val)],
            )
            seen: list[str] = []

            def opener(url: str, *, timeout: float = 20) -> dict:
                seen.append(url)
                return {
                    "ok": True,
                    "url": url,
                    "http_status": 200,
                    "body": body,
                    "error": None,
                }

            payload = fetch_series(spec, opener=opener, now=DUE_AFTER_AUG_CPI)
            self.assertTrue(payload.get("ok"), (catalog_id, payload))
            self.assertTrue(any(f"/aug-2026/{workbook_name}" in url for url in seen), seen)
            self.assertEqual(payload["points"][0]["period"], "2026-08")
            self.assertAlmostEqual(payload["points"][0]["value"], aug_val)

    def test_stale_july_workbook_on_aug_url_fails_closed(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        july_only = _build_abs_workbook(
            "A130393721F",
            [(datetime(2026, 7, 1), 3.5)],
        )
        aug_url_marker = "/aug-2026/640101.xlsx"

        def opener(url: str, *, timeout: float = 20) -> dict:
            if aug_url_marker in url:
                return {
                    "ok": True,
                    "url": url,
                    "http_status": 200,
                    "body": july_only,
                    "error": None,
                }
            raise AssertionError(f"unexpected url {url}")

        payload = fetch_series(spec, opener=opener, now=DUE_AFTER_AUG_CPI)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("status"), "source_failed")
        self.assertTrue(str(payload.get("error") or "").startswith("release_due_stale_workbook"))
        self.assertEqual(payload.get("points"), [])

    def test_stale_workbook_preserves_seeded_july_observation(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        store = load_store("AU", self.obs_dir)
        append_observation(
            store,
            series_id="A130393721F",
            period="2026-07",
            transformation="yoy_pct",
            value=3.5,
            raw_sha256="seed",
            retrieved_at="2026-09-21T14:49:33Z",
        )
        save_store(store, self.obs_dir)
        before = json.loads((self.obs_dir / "au.json").read_text())

        july_only = _build_abs_workbook("A130393721F", [(datetime(2026, 7, 1), 3.5)])

        def opener(url: str, *, timeout: float = 20) -> dict:
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": july_only,
                "error": None,
            }

        result = run_ingestion(
            mode="offline",
            countries=["AU"],
            catalog=self._mini_catalog(spec),
            now=DUE_AFTER_AUG_CPI,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        after = json.loads((self.obs_dir / "au.json").read_text())
        self.assertEqual(after, before)
        self.assertEqual(len(after["observations"]), 1)
        self.assertEqual(after["observations"][0]["period"], "2026-07")
        self.assertEqual(after["observations"][0]["retrieved_at"], "2026-09-21T14:49:33Z")

    def test_release_due_unresolved_skips_opener(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        spec["registry_urls"] = []
        spec["endpoint"] = (
            "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
            "consumer-price-index-australia/640101.xlsx"
        )

        def opener(url: str, *, timeout: float = 20) -> dict:
            raise AssertionError("opener must not run when release_due_unresolved")

        payload = fetch_series(spec, opener=opener, now=DUE_AFTER_AUG_CPI)
        self.assertFalse(payload.get("ok"))
        self.assertTrue(str(payload.get("error") or "").startswith("release_due_unresolved"))

    def test_aug_404_does_not_fallback_to_july_url(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        seen: list[str] = []

        def opener(url: str, *, timeout: float = 20) -> dict:
            seen.append(url)
            if "/aug-2026/" in url:
                return {
                    "ok": False,
                    "url": url,
                    "http_status": 404,
                    "body": b"",
                    "error": "HTTP 404",
                }
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": _build_abs_workbook("A130393721F", [(datetime(2026, 7, 1), 3.5)]),
                "error": None,
            }

        payload = fetch_series(spec, opener=opener, now=DUE_AFTER_AUG_CPI)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("status"), "source_failed")
        self.assertTrue(all("/jul-2026/" not in url for url in seen))
        self.assertEqual(len(seen), 1)

    def test_headline_not_due_uses_static_july_workbook(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        july_body = _build_abs_workbook("A130393721F", [(datetime(2026, 7, 1), 3.5)])
        for now in (
            datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc),
        ):
            seen: list[str] = []

            def opener(url: str, *, timeout: float = 20) -> dict:
                seen.append(url)
                return {
                    "ok": True,
                    "url": url,
                    "http_status": 200,
                    "body": july_body,
                    "error": None,
                }

            payload = fetch_series(spec, opener=opener, now=now)
            self.assertTrue(payload.get("ok"), now)
            self.assertTrue(any("/jul-2026/640101.xlsx" in url for url in seen))
            self.assertEqual(payload["points"][0]["period"], "2026-07")
            err = str(payload.get("error") or "")
            self.assertFalse(err.startswith("release_due_unresolved"))
            self.assertFalse(err.startswith("release_due_stale_workbook"))

    def test_source_failed_release_due_blocks_au_quality_gate(self) -> None:
        spec = self._spec("AU.Inflation.headline")
        raw = {
            "series_id": spec["id"],
            "status": "source_failed",
            "error": "release_due_stale_workbook:expected=2026-08:observed=2026-07",
        }
        row = _enrich_row(
            raw,
            spec,
            when=DUE_AFTER_AUG_CPI,
            observations_dir=None,
            observation_period="2026-07",
        )
        blocked = _country_release_due_blocking([row], "AU")
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["status"], "source_failed")

    def test_cpi_spending_live_smoke_report_offline(self) -> None:
        if not CPI_SPENDING_LIVE_REPORT_PATH.is_file():
            self.skipTest("cpi_spending_live_smoke_report.json not present (live smoke not run)")
        report = json.loads(CPI_SPENDING_LIVE_REPORT_PATH.read_text(encoding="utf-8"))
        for probe in report.get("probes") or []:
            period = probe.get("period")
            error = probe.get("error")
            if probe.get("ok"):
                self.assertIn("/aug-2026/", str(probe.get("url") or ""))
                self.assertEqual(period, "2026-08")
            else:
                self.assertTrue(period == "2026-08" or bool(error))

    def test_live_smoke_report(self) -> None:
        if os.environ.get("MACRO_INGESTION_LIVE_SMOKE") != "1":
            if LIVE_REPORT_PATH.is_file():
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

        cpi_probes = [
            {
                "name": "cpi_headline",
                "url": (
                    "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
                    "consumer-price-index-australia/aug-2026/640101.xlsx"
                ),
                "series_id": "A130393721F",
            },
            {
                "name": "cpi_underlying",
                "url": (
                    "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/"
                    "consumer-price-index-australia/aug-2026/640106.xlsx"
                ),
                "series_id": "A130400382R",
            },
            {
                "name": "household_spending",
                "url": (
                    "https://www.abs.gov.au/statistics/economy/finance/"
                    "monthly-household-spending-indicator/aug-2026/5682001.xlsx"
                ),
                "series_id": "A130200586W",
            },
        ]
        cpi_report: dict[str, object] = {
            "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "probes": [],
        }
        for probe in cpi_probes:
            entry: dict[str, object] = {
                "name": probe["name"],
                "url": probe["url"],
                "series_id": probe["series_id"],
            }
            resp = live_opener(probe["url"], timeout=20)
            body = resp.get("body") or b""
            entry["http_status"] = resp.get("http_status")
            entry["error"] = resp.get("error")
            period = None
            value = None
            if resp.get("ok") and body[:2] == b"PK":
                try:
                    parsed = parse_abs_time_series_workbook(body, probe["series_id"], cadence="monthly")
                    period, value = parsed[-1]
                    entry["ok"] = True
                except ValueError as exc:
                    entry["ok"] = False
                    entry["error"] = str(exc)
            else:
                entry["ok"] = False
            entry["period"] = period
            entry["value"] = value
            cpi_report["probes"].append(entry)

        CPI_SPENDING_LIVE_REPORT_PATH.write_text(
            json.dumps(cpi_report, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assertTrue(CPI_SPENDING_LIVE_REPORT_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
