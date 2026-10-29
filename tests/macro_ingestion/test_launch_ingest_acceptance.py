"""Launch live-ingest acceptance: preflight isolation, health merge, seeding."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]

from scripts.macro_ingestion.ledger import load_latest
from scripts.market_watch_launch import ingest as ingest_mod


class LiveIngestPreflightIsolationTests(unittest.TestCase):
    def test_preflight_blocked_country_still_runs_ingestion(self) -> None:
        when = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
        preflight = {
            "ok": False,
            "mismatches": [{"concept_id": "CA.Labor.unemployment", "country": "CA", "reason": "units_mismatch"}],
            "blocked_countries": ["CA"],
        }
        captured: dict = {}

        def fake_run_ingestion(**kwargs):
            captured.update(kwargs)
            return {
                "rows": [
                    {
                        "series_id": "US.Labor.unemployment",
                        "status": "source_failed",
                        "error": "budget_deferred",
                    }
                ],
                "checked_at": "2026-10-15T08:00:00Z",
                "cutoff_class": "post_freeze",
            }

        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            with (
                mock.patch.object(ingest_mod, "run_weighted_series_preflight", return_value=preflight),
                mock.patch.object(ingest_mod, "run_ingestion", side_effect=fake_run_ingestion),
                mock.patch.object(ingest_mod, "stage_verified_lineage", return_value={"ok": True}),
                mock.patch.object(ingest_mod, "_au_labor_evidence_for_launch", return_value={}),
                mock.patch.object(ingest_mod, "_write_au_labor_handoff", return_value=({}, "abc")),
            ):
                ingest_mod._live_ingestion(
                    launch_dir=launch_dir,
                    when=when,
                    launch_id="mwl-test",
                    root=ROOT,
                )
        self.assertEqual(captured.get("countries"), list(ingest_mod._LAUNCH_COUNTRIES))

    def test_retry_merges_health_latest_json(self) -> None:
        when = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
        calls: list[dict] = []

        def fake_run_ingestion(**kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("only_series_ids"):
                return {
                    "rows": [
                        {
                            "series_id": "US.Labor.unemployment",
                            "status": "checked_unchanged",
                            "error": None,
                        }
                    ],
                    "checked_at": "2026-10-15T08:00:00Z",
                    "cutoff_class": "post_freeze",
                }
            return {
                "rows": [
                    {
                        "series_id": "US.Labor.unemployment",
                        "status": "source_failed",
                        "error": "budget_deferred",
                    }
                ],
                "checked_at": "2026-10-15T08:00:00Z",
                "cutoff_class": "post_freeze",
            }

        preflight = {"ok": True, "mismatches": [], "blocked_countries": []}
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = Path(tmp) / "launch"
            with (
                mock.patch.object(ingest_mod, "run_weighted_series_preflight", return_value=preflight),
                mock.patch.object(ingest_mod, "run_ingestion", side_effect=fake_run_ingestion),
                mock.patch.object(ingest_mod, "stage_verified_lineage", return_value={"ok": True}),
                mock.patch.object(ingest_mod, "_au_labor_evidence_for_launch", return_value={}),
                mock.patch.object(ingest_mod, "_write_au_labor_handoff", return_value=({}, "abc")),
            ):
                ingest_mod._live_ingestion(
                    launch_dir=launch_dir,
                    when=when,
                    launch_id="mwl-test",
                    root=ROOT,
                )
            health = load_latest(launch_dir / "ingestion" / "health")
            rows = health.get("rows") or []
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "checked_unchanged")
        self.assertTrue(calls[0].get("write_health", True))
        self.assertFalse(calls[1].get("write_health", True))


if __name__ == "__main__":
    unittest.main()
