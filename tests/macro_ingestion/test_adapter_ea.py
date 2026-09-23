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


if __name__ == "__main__":
    unittest.main()
