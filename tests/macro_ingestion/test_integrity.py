"""Ingestion integrity: dedup, provenance, due/stale, budget, post-freeze."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import POST_FREEZE_DIR, run_ingestion
from scripts.macro_ingestion.vintage import append_observation
from scripts.macro_ingestion.windows import TRUSTED_PACKET_STATEMENT, write_post_freeze_delta

NY = ZoneInfo("America/New_York")
REPO_POST_FREEZE = ROOT / "data/macro_ingestion/post_freeze"


class TestIngestionIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        clear_adapter_overrides()
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self) -> None:
        clear_adapter_overrides()
        self.tmp.cleanup()
        self.assertFalse(REPO_POST_FREEZE.exists(), "repo post_freeze must not be created by tests")

    def _mini_catalog(self, specs: list[dict]) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = specs
        return cat

    def _us_unemployment_spec(self) -> dict:
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment")
        )
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        return spec

    def test_dedup_close_value_different_hash(self) -> None:
        store = {"country": "US", "observations": []}
        when = "2026-09-21T12:00:00Z"
        append_observation(
            store,
            series_id="UNRATE",
            period="2026-08",
            transformation="",
            value=4.1,
            raw_sha256="hash_a",
            retrieved_at=when,
        )
        result = append_observation(
            store,
            series_id="UNRATE",
            period="2026-08",
            transformation="",
            value=4.1,
            raw_sha256="hash_b",
            retrieved_at="2026-09-22T12:00:00Z",
        )
        self.assertTrue(result.duplicate)
        self.assertEqual(len(store["observations"]), 1)
        row = store["observations"][0]
        self.assertEqual(row["retrieved_at"], when)
        self.assertIn("hash_b", row.get("raw_sha256_aliases", []))

    def test_runner_dedup_same_period_new_hash(self) -> None:
        calls = {"n": 0}

        def fetch_series(spec, *, opener, now, timeout=20):
            calls["n"] += 1
            return {
                "ok": True,
                "raw_sha256": f"hash{calls['n']}",
                "points": [{"period": "2026-08", "value": 4.1, "revision_status": "final"}],
            }

        register_adapter_override("US", fetch_series)
        cat = self._mini_catalog([self._us_unemployment_spec()])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        first = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(first["rows"][0]["status"], "new_observation")
        second = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "checked_unchanged")
        store = json.loads((self.obs_dir / "us.json").read_text())
        self.assertEqual(len(store["observations"]), 1)

    def test_provenance_fields_on_append(self) -> None:
        store = {"country": "US", "observations": []}
        append_observation(
            store,
            series_id="UNRATE",
            period="2026-08",
            transformation="",
            value=4.1,
            raw_sha256="h1",
            retrieved_at="2026-09-21T12:00:00Z",
            release_date="2026-09-05",
            vintage="v2026",
        )
        row = store["observations"][0]
        self.assertEqual(row["release_date"], "2026-09-05")
        self.assertEqual(row["vintage"], "v2026")
        self.assertEqual(row["earliest_release_vintage"], "2026-09-05")
        self.assertEqual(row["latest_release_vintage"], "2026-09-05")
        self.assertIsNone(row.get("calibration_as_of"))

        append_observation(
            store,
            series_id="UNRATE",
            period="2026-08",
            transformation="",
            value=4.3,
            raw_sha256="h2",
            retrieved_at="2026-09-22T12:00:00Z",
            release_date="2026-09-10",
        )
        self.assertEqual(len(store["observations"]), 2)
        revised = store["observations"][-1]
        self.assertEqual(revised["earliest_release_vintage"], "2026-09-05")
        self.assertEqual(revised["latest_release_vintage"], "2026-09-10")

    def test_due_missing_when_release_due_old_period_only(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "x",
                "points": [{"period": "2026-08", "value": 4.1, "revision_status": "final"}],
            }

        register_adapter_override("US", fetch_series)
        spec = self._us_unemployment_spec()
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-09-01T08:30:00-04:00"],
            "expected_periods": {"2026-09-01T08:30:00-04:00": "2026-09"},
        }
        cat = self._mini_catalog([spec])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        second = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "due_missing")

    def test_repeat_fetch_then_later_release_missing(self) -> None:
        """New period, unchanged rerun, then a later bound release that is absent."""
        payload = {
            "ok": True,
            "raw_sha256": "p",
            "points": [{"period": "2026-08", "value": 4.2, "revision_status": "final"}],
        }

        def fetch_series(spec, *, opener, now, timeout=20):
            return payload

        register_adapter_override("US", fetch_series)
        spec = self._us_unemployment_spec()
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": [
                "2026-09-04T08:30:00-04:00",
                "2026-10-02T08:30:00-04:00",
            ],
            "expected_periods": {
                "2026-09-04T08:30:00-04:00": "2026-08",
                "2026-10-02T08:30:00-04:00": "2026-09",
            },
        }
        cat = self._mini_catalog([spec])
        first_now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
        first = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=first_now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(first["rows"][0]["status"], "new_observation")
        second = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=first_now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "checked_unchanged")
        third = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(third["rows"][0]["status"], "due_missing")

    def test_unbound_due_date_stays_unparsed(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "x",
                "points": [{"period": "2026-08", "value": 4.1, "revision_status": "final"}],
            }

        register_adapter_override("US", fetch_series)
        spec = self._us_unemployment_spec()
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-09-01T08:30:00-04:00"],
        }
        cat = self._mini_catalog([spec])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        second = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "calendar_unparsed")

    def test_pinned_fixture_period_stays_missing(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "aug",
                "points": [{"period": "2026-08", "value": 51.1, "revision_status": "final"}],
            }

        register_adapter_override("EA", fetch_series)
        spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "EA.Activity.flash_composite_pmi")
        )
        cat = self._mini_catalog([spec])
        now = datetime(2026, 9, 23, 8, 5, tzinfo=timezone.utc)
        run_ingestion(
            mode="offline",
            countries=["EA"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        second = run_ingestion(
            mode="offline",
            countries=["EA"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(second["rows"][0]["status"], "due_missing")
        store = json.loads((self.obs_dir / "ea.json").read_text())
        self.assertFalse(any(row.get("period") == "2026-09" for row in store["observations"]))

    def test_run_budget_deferred(self) -> None:
        clock = {"t": 0.0}

        def monotonic() -> float:
            return clock["t"]

        def slow_us(spec, *, opener, now, timeout=20):
            clock["t"] += 10.0
            return {
                "ok": True,
                "raw_sha256": "a",
                "points": [{"period": "2026-08", "value": 4.1}],
            }

        spec_a = self._us_unemployment_spec()
        spec_b = copy.deepcopy(spec_a)
        spec_b["id"] = "US.Labor.other"
        spec_b["series_id"] = "US_OTHER"
        cat = self._mini_catalog([spec_a, spec_b])

        register_adapter_override("US", slow_us)
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
            run_budget_seconds=5.0,
            monotonic=monotonic,
        )
        deferred = [r for r in result["rows"] if r.get("error") == "budget_deferred"]
        self.assertTrue(deferred)
        self.assertTrue(all(r["status"] == "source_failed" for r in deferred))

    def test_malformed_point_does_not_block_next_country(self) -> None:
        def bad_us(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "x",
                "points": [{"value": 4.1}],
            }

        def good_ca(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "y",
                "points": [{"period": "2026-08", "value": 5.0, "revision_status": "final"}],
            }

        register_adapter_override("US", bad_us)
        register_adapter_override("CA", good_ca)
        us_spec = self._us_unemployment_spec()
        ca_spec = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "CA.Labor.unemployment")
        )
        ca_spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/Toronto",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        cat = self._mini_catalog([us_spec, ca_spec])
        now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        result = run_ingestion(
            mode="offline",
            countries=["US", "CA"],
            catalog=cat,
            now=now,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        us_row = next(r for r in result["rows"] if r["series_id"] == us_spec["id"])
        ca_row = next(r for r in result["rows"] if r["series_id"] == ca_spec["id"])
        self.assertEqual(us_row["status"], "source_failed")
        self.assertEqual(us_row["error"], "malformed_point")
        self.assertEqual(ca_row["status"], "new_observation")

    def test_post_freeze_via_runner_and_writer(self) -> None:
        self.assertIsInstance(POST_FREEZE_DIR, Path)

        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "pf",
                "points": [{"period": "2026-09", "value": 50.1, "revision_status": "flash"}],
            }

        register_adapter_override("US", fetch_series)
        spec = self._us_unemployment_spec()
        cat = self._mini_catalog([spec])
        when = datetime(2026, 9, 23, 4, 0, tzinfo=NY)
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=when,
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertIsNotNone(result["post_freeze_path"])
        pf_path = Path(result["post_freeze_path"])
        self.assertTrue(str(pf_path).startswith(str(self.tmp.name)))
        self.assertNotIn("evidence_snapshot", str(pf_path))
        doc = json.loads(pf_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["cutoff_class"], "post_freeze")
        self.assertEqual(doc["freeze_cutoff"], "01:50 America/New_York")
        self.assertEqual(doc["trusted_packet_statement"], TRUSTED_PACKET_STATEMENT)

        with tempfile.TemporaryDirectory() as alt_tmp:
            alt_base = Path(alt_tmp)
            written = write_post_freeze_delta(
                when=when,
                changed_series=[{"id": spec["id"], "period": "2026-09", "value": 50.1}],
                base_dir=alt_base,
            )
            self.assertTrue(written.exists())
            self.assertNotIn("evidence_snapshot", str(written))
            alt_doc = json.loads(written.read_text(encoding="utf-8"))
            self.assertEqual(alt_doc["cutoff_class"], "post_freeze")
            self.assertEqual(alt_doc["freeze_cutoff"], "01:50 America/New_York")
            self.assertIn("trusted", alt_doc["trusted_packet_statement"].lower())

    def test_non_finite_value_malformed(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": "x",
                "points": [{"period": "2026-08", "value": math.nan}],
            }

        register_adapter_override("US", fetch_series)
        cat = self._mini_catalog([self._us_unemployment_spec()])
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "source_failed")
        self.assertEqual(result["rows"][0]["error"], "malformed_point")


if __name__ == "__main__":
    unittest.main()
