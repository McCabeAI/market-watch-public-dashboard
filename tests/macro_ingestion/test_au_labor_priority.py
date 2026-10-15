"""AU official labor must run before catalog-order countries exhaust the run budget."""

from __future__ import annotations

import copy
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion
from scripts.macro_ingestion.source_health_summary import build_source_health_summary


class TestAuLaborPriority(unittest.TestCase):
    def setUp(self) -> None:
        clear_adapter_overrides()
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self) -> None:
        clear_adapter_overrides()
        self.tmp.cleanup()

    def _mini_catalog(self, specs: list[dict]) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = specs
        return cat

    def _au_labor_spec(self, series_id: str) -> dict:
        return copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == series_id))

    def _due_au_release_rule(self) -> dict:
        return {
            "kind": "explicit_timestamp",
            "timezone": "Australia/Sydney",
            "dates": ["2026-10-16T11:30:00+11:00"],
            "expected_periods": {"2026-10-16T11:30:00+11:00": "2026-09"},
        }

    def test_us_timeout_does_not_defer_due_au_official_labor(self) -> None:
        clock = {"t": 0.0}
        calls: dict[str, int] = defaultdict(int)

        def monotonic() -> float:
            return clock["t"]

        def us_fetch(spec, *, opener, now, timeout=20):
            calls[spec["id"]] += 1
            clock["t"] += 60.0
            raise TimeoutError("timed out")

        def au_fetch(spec, *, opener, now, timeout=20):
            calls[spec["id"]] += 1
            clock["t"] += 0.1
            return {
                "ok": True,
                "raw_sha256": spec["id"],
                "points": [{"period": "2026-09", "value": 4.2, "revision_status": "final"}],
            }

        us_spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment")
        )
        us_spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-09-05T08:30:00-04:00"],
            "expected_periods": {"2026-09-05T08:30:00-04:00": "2026-08"},
        }
        au_unemp = self._au_labor_spec("AU.Labor.unemployment")
        au_unemp["release_rule"] = self._due_au_release_rule()
        au_emp = self._au_labor_spec("AU.Labor.employment")
        au_emp["release_rule"] = self._due_au_release_rule()
        au_context = self._au_labor_spec("AU.Labor.wages")
        au_context["id"] = "AU.Labor.jsa_claims"
        au_context["series_id"] = "AU_LABOR_JSA"
        au_context["role"] = "context"
        au_context["weight"] = 0.0
        au_context["release_rule"] = self._due_au_release_rule()

        register_adapter_override("US", us_fetch)
        register_adapter_override("AU", au_fetch)
        cat = self._mini_catalog([us_spec, au_unemp, au_emp, au_context])
        due_now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["US", "AU"],
            catalog=cat,
            now=due_now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            run_budget_seconds=50.0,
            country_budget_seconds=500.0,
            attempts=1,
            monotonic=monotonic,
        )
        by_id = {row["series_id"]: row for row in result["rows"]}
        self.assertIn("AU.Labor.unemployment", calls)
        self.assertIn("AU.Labor.employment", calls)
        self.assertNotEqual(by_id["AU.Labor.unemployment"].get("error"), "budget_deferred")
        self.assertNotEqual(by_id["AU.Labor.employment"].get("error"), "budget_deferred")
        self.assertEqual(by_id["US.Labor.unemployment"].get("error"), "timed out")
        if by_id.get("AU.Labor.jsa_claims"):
            self.assertEqual(by_id["AU.Labor.jsa_claims"].get("error"), "budget_deferred")

    def test_404_not_yet_due_before_release(self) -> None:
        spec = self._au_labor_spec("AU.Labor.unemployment")
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "Australia/Sydney",
            "dates": ["2026-10-15T11:30:00+11:00"],
            "expected_periods": {"2026-10-15T11:30:00+11:00": "2026-09"},
        }

        def fetch(spec, *, opener, now, timeout=20):
            return opener("https://example.test/abs", timeout=timeout)

        def opener(url: str, *, timeout: float = 20, **kwargs):
            return {"ok": False, "http_status": 404, "body": b"", "error": "HTTP 404"}

        register_adapter_override("AU", fetch)
        now = datetime(2026, 10, 15, 0, 29, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["AU"],
            catalog=self._mini_catalog([spec]),
            now=now,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            attempts=3,
        )
        row = result["rows"][0]
        self.assertEqual(row["status"], "checked_unchanged")
        self.assertIsNone(row.get("error"))
        self.assertEqual(row.get("publication_state"), "not_yet_due")

    def test_404_due_missing_at_release(self) -> None:
        spec = self._au_labor_spec("AU.Labor.unemployment")
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "Australia/Sydney",
            "dates": ["2026-10-15T11:30:00+11:00"],
            "expected_periods": {"2026-10-15T11:30:00+11:00": "2026-09"},
        }
        fetch_calls = {"n": 0}

        def fetch(spec, *, opener, now, timeout=20):
            fetch_calls["n"] += 1
            return opener("https://example.test/abs", timeout=timeout)

        def opener(url: str, *, timeout: float = 20, **kwargs):
            if fetch_calls["n"] > 1:
                return {
                    "ok": True,
                    "raw_sha256": "fake",
                    "points": [{"period": "2026-09", "value": 4.2, "revision_status": "final"}],
                }
            return {"ok": False, "http_status": 404, "body": b"", "error": "HTTP 404"}

        register_adapter_override("AU", fetch)
        now = datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["AU"],
            catalog=self._mini_catalog([spec]),
            now=now,
            opener=opener,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            attempts=3,
        )
        row = result["rows"][0]
        self.assertEqual(row["status"], "due_missing")
        self.assertEqual(row.get("error"), "HTTP 404")
        self.assertEqual(row.get("publication_state"), "due_missing")
        self.assertEqual(fetch_calls["n"], 1)

    def test_source_health_summary_core_and_leading(self) -> None:
        rows = [
            {
                "series_id": "US.Labor.payrolls",
                "status": "due_missing",
                "error": "HTTP 404",
                "publication_state": "due_missing",
            },
            {
                "series_id": "AU.Labor.jsa_claims",
                "status": "source_failed",
                "error": "timeout",
                "attempt_history": [{"status": "source_failed", "error": "timeout"}],
            },
            {
                "series_id": "AU.Labor.anz_jobs",
                "status": "source_failed",
                "error": "timeout",
            },
            {
                "series_id": "AU.Labor.unemployment",
                "status": "checked_unchanged",
                "error": None,
                "publication_state": "not_yet_due",
            },
        ]
        summary = build_source_health_summary(rows)
        self.assertEqual(len(summary["missing_due_core_labor"]), 1)
        self.assertEqual(summary["missing_due_core_labor"][0]["series_id"], "US.Labor.payrolls")
        alerted = {item["series_id"] for item in summary["leading_source_alert"]}
        self.assertIn("AU.Labor.jsa_claims", alerted)
        self.assertNotIn("AU.Labor.anz_jobs", alerted)


if __name__ == "__main__":
    unittest.main()
