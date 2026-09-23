"""Sep 23 2026 EA flash composite PMI calendar and miss fixture."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import ea as ea_adapter
from scripts.macro_ingestion.calendar import release_due
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.vintage import append_observation, load_store, save_store
from scripts.macro_ingestion.windows import cutoff_class

NY = ZoneInfo("America/New_York")


class TestEaFlashSep23(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog()
        self.flash_spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "EA.Activity.flash_composite_pmi")
        )
        self.scored_spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "EA.Activity.business_surveys")
        )

    def test_release_not_due_before_0400_et(self) -> None:
        when = datetime(2026, 9, 23, 3, 59, 0, tzinfo=NY)
        self.assertFalse(release_due(self.flash_spec, when))

    def test_release_due_at_0400_et_post_freeze(self) -> None:
        when = datetime(2026, 9, 23, 4, 0, 0, tzinfo=NY)
        self.assertTrue(release_due(self.flash_spec, when))
        self.assertEqual(cutoff_class(when), "post_freeze")

    def test_html_listing_does_not_append_september_flash(self) -> None:
        html = b"<!DOCTYPE html><html><body>Access Denied challenge</body></html>"

        def opener(url: str, *, timeout: float = 20):
            return {
                "ok": True,
                "url": url,
                "http_status": 403,
                "body": html,
                "error": None,
            }

        when = datetime(2026, 9, 23, 4, 0, 0, tzinfo=NY)
        payload = ea_adapter.fetch_series(self.flash_spec, opener=opener, now=when)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload.get("points"))

        mini = copy.deepcopy(self.catalog)
        mini["series"] = [self.flash_spec, self.scored_spec]

        with tempfile.TemporaryDirectory() as tmp:
            obs_dir = Path(tmp) / "observations"
            health_dir = Path(tmp) / "health"
            store = load_store("EA", obs_dir)
            append_observation(
                store,
                series_id=str(self.scored_spec["series_id"]),
                period="2026-08",
                transformation=str(self.scored_spec["transform"]),
                value=52.0,
                raw_sha256="aug-final-sha",
                retrieved_at="2026-09-03T12:00:00Z",
                revision_status="final",
            )
            save_store(store, obs_dir)

            result = run_ingestion(
                mode="offline",
                countries=["EA"],
                catalog=mini,
                now=when,
                opener=opener,
                observations_dir=obs_dir,
                health_dir=health_dir,
            )
            flash_row = next(r for r in result["rows"] if r["series_id"] == self.flash_spec["id"])
            self.assertIn(flash_row["status"], {"due_missing", "source_failed"})

            store_after = load_store("EA", obs_dir)
            periods = [o["period"] for o in store_after["observations"]]
            self.assertNotIn("2026-09", periods)
            aug = [
                o
                for o in store_after["observations"]
                if o["series_id"] == self.scored_spec["series_id"] and o["period"] == "2026-08"
            ]
            self.assertEqual(len(aug), 1)
            self.assertEqual(float(aug[0]["value"]), 52.0)


if __name__ == "__main__":
    unittest.main()
