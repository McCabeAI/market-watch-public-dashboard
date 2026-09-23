"""Runner integration tests with injected adapters."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import clear_adapter_overrides, register_adapter_override
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.runner import run_ingestion

CALIBRATION_PATH = ROOT / "data/temperature_calibration.json"
EVIDENCE_PATH = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_EVIDENCE_SHA = (
    "41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestMacroIngestionRunner(unittest.TestCase):
    def setUp(self) -> None:
        clear_adapter_overrides()
        self.catalog = load_catalog()
        self.tmp = tempfile.TemporaryDirectory()
        self.obs_dir = Path(self.tmp.name) / "observations"
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self) -> None:
        clear_adapter_overrides()
        self.tmp.cleanup()

    def _mini_catalog(self, spec: dict) -> dict:
        cat = copy.deepcopy(self.catalog)
        cat["series"] = [spec]
        return cat

    def test_idempotent_rerun(self) -> None:
        raw = "abc123hash"

        def fetch_series(spec, *, opener, now, timeout=20):
            return {
                "ok": True,
                "raw_sha256": raw,
                "vintage": "latest_available",
                "points": [
                    {
                        "period": "2026-08",
                        "value": 4.1,
                        "transformation": spec.get("transform"),
                        "revision_status": "final",
                    }
                ],
            }

        register_adapter_override("US", fetch_series)
        spec = next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment")
        spec = copy.deepcopy(spec)
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        cat = self._mini_catalog(spec)
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
        status = second["rows"][0]["status"]
        self.assertEqual(status, "checked_success_no_new_release")
        store = json.loads((self.obs_dir / "us.json").read_text())
        self.assertEqual(len(store["observations"]), 1)

    def test_revision_applied(self) -> None:
        calls = {"n": 0}

        def fetch_series(spec, *, opener, now, timeout=20):
            calls["n"] += 1
            value = 4.1 if calls["n"] == 1 else 4.3
            return {
                "ok": True,
                "raw_sha256": f"hash{calls['n']}",
                "points": [{"period": "2026-08", "value": value, "revision_status": "final"}],
            }

        register_adapter_override("US", fetch_series)
        spec = copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment"))
        spec["release_rule"] = {
            "kind": "explicit_timestamp",
            "timezone": "America/New_York",
            "dates": ["2026-12-01T08:30:00-05:00"],
        }
        cat = self._mini_catalog(spec)
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
        self.assertEqual(second["rows"][0]["status"], "revision_applied")

    def test_missing_adapter_incomplete_country(self) -> None:
        template = copy.deepcopy(
            next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment")
        )
        template["id"] = "ZZ.Labor.unemployment"
        template["country"] = "ZZ"
        template["series_id"] = "ZZ_UNRATE"
        cat = self._mini_catalog(template)
        result = run_ingestion(
            mode="offline",
            countries=["ZZ"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        zz_rows = [r for r in result["rows"] if r["series_id"].startswith("ZZ.")]
        self.assertTrue(zz_rows)
        self.assertTrue(all(r["status"] == "incomplete_country" for r in zz_rows))

    def test_calendar_unparsed(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {"ok": True, "raw_sha256": "x", "points": []}

        register_adapter_override("US", fetch_series)
        spec = copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment"))
        cat = self._mini_catalog(spec)
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "calendar_unparsed")

    def test_license_gap(self) -> None:
        def fetch_series(spec, *, opener, now, timeout=20):
            return {"ok": False, "status": "license_gap", "error": "challenge_page", "challenge_page": True}

        register_adapter_override("US", fetch_series)
        spec = copy.deepcopy(next(r for r in self.catalog["series"] if r["id"] == "US.Labor.unemployment"))
        cat = self._mini_catalog(spec)
        result = run_ingestion(
            mode="offline",
            countries=["US"],
            catalog=cat,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(result["rows"][0]["status"], "license_gap")

    def test_calibration_and_evidence_unchanged(self) -> None:
        before = CALIBRATION_PATH.read_bytes()
        result = run_ingestion(
            mode="offline",
            countries=["JP"],
            catalog=self.catalog,
            now=datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            observations_dir=self.obs_dir,
            health_dir=self.health_dir,
        )
        self.assertEqual(CALIBRATION_PATH.read_bytes(), before)
        if EVIDENCE_PATH.exists():
            self.assertEqual(_sha(EVIDENCE_PATH), EXPECTED_EVIDENCE_SHA)
        jp_rows = [r for r in result["rows"] if r["series_id"].startswith("JP.")]
        self.assertTrue(jp_rows)


if __name__ == "__main__":
    unittest.main()
