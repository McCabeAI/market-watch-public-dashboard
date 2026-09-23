"""US adapter tests (offline) plus optional live smoke report artifact."""

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

from scripts.macro_ingestion.adapters.us import fetch_series
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import live_opener, run_ingestion

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "us"
UNRATE_FIXTURE = FIXTURES / "unrate_offline.csv"
LIVE_SMOKE_PATH = FIXTURES / "live_smoke_report.json"

LIVE_SMOKE_TARGETS = (
    ("PCEPILFE", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPILFE"),
    ("CPIAUCSL", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"),
    ("WPSFD49207", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WPSFD49207"),
    ("IR", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IR"),
    ("IQ", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IQ"),
    (
        "ISM_MANUFACTURING",
        "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/",
    ),
)


def _write_live_smoke_report() -> None:
    catalog = load_catalog()
    rows: list[dict] = []
    for label, url in LIVE_SMOKE_TARGETS:
        entry: dict = {"label": label, "url": url}
        try:
            response = live_opener(url, timeout=20)
            entry["http_status"] = response.get("http_status")
            entry["ok"] = response.get("ok")
            entry["error"] = response.get("error")
            body = response.get("body") or b""
            entry["challenge_page"] = b"access denied" in body[:8000].lower() or b"cf-challenge" in body[:8000].lower()
            if response.get("ok") and body:
                spec = next((r for r in catalog["series"] if r.get("series_id") == label), None)
                if spec is None and label == "ISM_MANUFACTURING":
                    spec = next(r for r in catalog["series"] if r["id"] == "US.Activity.manufacturing_surveys")
                if spec:
                    payload = fetch_series(spec, opener=lambda u, timeout=20: response, now=datetime.now(timezone.utc))
                    points = payload.get("points") or []
                    entry["point_count"] = len(points)
                    entry["latest_period"] = points[-1]["period"] if points else None
                else:
                    from scripts.macro_source_refresh import parse_fred_csv

                    parsed = parse_fred_csv(body.decode("utf-8", errors="replace"))
                    entry["point_count"] = len(parsed)
                    entry["latest_period"] = parsed[-1][0] if parsed else None
            else:
                entry["point_count"] = 0
                entry["latest_period"] = None
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = str(exc)
            entry["point_count"] = 0
            entry["latest_period"] = None
        rows.append(entry)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    LIVE_SMOKE_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows}, indent=2) + "\n")


class TestUSAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Live probes are recorded in the committed fixture. Refresh only when
        # a human sets MACRO_INGESTION_LIVE_SMOKE=1 so unit runs stay offline.
        if os.environ.get("MACRO_INGESTION_LIVE_SMOKE") == "1":
            _write_live_smoke_report()

    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"
        self.fixture_bytes = UNRATE_FIXTURE.read_bytes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _mini_catalog(self, spec: dict) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [copy.deepcopy(spec)]
        return cat

    def _fake_opener(self, url: str, *, timeout: float = 20) -> dict:
        if "UNRATE" in url:
            return {
                "ok": True,
                "url": url,
                "http_status": 200,
                "body": self.fixture_bytes,
                "error": None,
            }
        return {
            "ok": False,
            "url": url,
            "http_status": None,
            "body": b"",
            "error": "offline_unmapped_url",
        }

    def test_unrate_fixture_new_observation_and_idempotent_rerun(self) -> None:
        spec = copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment"))
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        cat = self._mini_catalog(spec)
        now = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
        first = run_ingestion(
            countries=["US"],
            mode="offline",
            opener=self._fake_opener,
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(first["rows"][0]["status"], "new_observation")
        store = json.loads((self.obs_dir / "us.json").read_text())
        self.assertEqual(len(store["observations"]), 1)
        self.assertEqual(store["observations"][0]["period"], "2026-09")
        second = run_ingestion(
            countries=["US"],
            mode="offline",
            opener=self._fake_opener,
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "checked_success_no_new_release")
        store_after = json.loads((self.obs_dir / "us.json").read_text())
        self.assertEqual(len(store_after["observations"]), 1)

    def test_conference_board_license_gap(self) -> None:
        spec = next(r for r in self.catalog["series"] if r["id"] == "US.Consumer.confidence_conference_board")
        payload = fetch_series(
            spec,
            opener=self._fake_opener,
            now=datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("status"), "license_gap")

    def test_live_smoke_report_present_without_invented_september_print(self) -> None:
        self.assertTrue(LIVE_SMOKE_PATH.is_file(), "live_smoke_report.json should exist")
        report = json.loads(LIVE_SMOKE_PATH.read_text())
        blob = json.dumps(report)
        self.assertNotIn('"period": "2026-09"', blob)
        self.assertNotIn("September 2026 PMI", blob)
        for row in report.get("rows", []):
            if row.get("label") == "ISM_MANUFACTURING" and row.get("latest_period") == "2026-09":
                self.fail("ISM live smoke must not record an unparsed September PMI print")


if __name__ == "__main__":
    unittest.main()
