"""Integration coverage gate: catalog, adapters, offline runner, frozen anchors."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.adapters import au, ca, ea, jp, nz, us  # noqa: F401
from scripts.macro_ingestion.contract import (
    COUNTRY_CODES,
    index_series_rows,
    load_catalog,
    validate_catalog_against_baseline,
)
from scripts.macro_ingestion.runner import run_ingestion

CALIBRATION_PATH = ROOT / "data/temperature_calibration.json"
CATALOG_PATH = ROOT / "data/macro_ingestion/catalog.json"
EVIDENCE_PATH = (
    ROOT / "data/overnight/runs/overnight-20260923/reviews/review-001/evidence_snapshot.json"
)
EXPECTED_CALIBRATION_SHA256 = (
    "f28d68f846c87a8f675398620d59c5a7bc1ab30c8771b316817251a08ba1cb5b"
)
EXPECTED_EVIDENCE_SHA256 = (
    "41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b"
)
_ZERO_WEIGHT_ROLES = frozenset({"context", "registry_unweighted", "explanatory_alias"})


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _release_dates_empty(release_rule: dict | None) -> bool:
    if not release_rule:
        return True
    return not bool(release_rule.get("dates"))


class TestMacroIngestionCoverageGate(unittest.TestCase):
    def test_frozen_anchors_and_catalog(self) -> None:
        self.assertEqual(_sha256_bytes(CALIBRATION_PATH.read_bytes()), EXPECTED_CALIBRATION_SHA256)
        if EVIDENCE_PATH.exists():
            self.assertEqual(_sha256_bytes(EVIDENCE_PATH.read_bytes()), EXPECTED_EVIDENCE_SHA256)

        catalog = load_catalog()
        on_disk = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        validate_catalog_against_baseline(on_disk)
        self.assertEqual(
            sorted(index_series_rows(on_disk["series"]).keys()),
            sorted(index_series_rows(catalog["series"]).keys()),
        )

        scored = [r for r in catalog["series"] if r.get("role") == "scored"]
        self.assertEqual(len(scored), 66)
        for row in catalog["series"]:
            if row.get("role") in _ZERO_WEIGHT_ROLES:
                self.assertEqual(float(row.get("weight", 0.0)), 0.0)

        flash = index_series_rows(catalog["series"])["EA.Activity.flash_composite_pmi"]
        dates = (flash.get("release_rule") or {}).get("dates") or []
        self.assertIn("2026-09-23T08:00:00Z", dates)
        self.assertNotEqual(flash.get("latest_period"), "2026-09")
        fixture = flash.get("known_fixture") or {}
        self.assertIsNone(fixture.get("value_in_catalog"))

    def test_offline_runner_no_quiet_window_success_on_empty_calendar(self) -> None:
        catalog = load_catalog()
        by_id = index_series_rows(catalog["series"])
        when = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as tmp:
            obs_dir = Path(tmp) / "observations"
            health_dir = Path(tmp) / "health"
            result = run_ingestion(
                mode="offline",
                countries=list(COUNTRY_CODES),
                catalog=catalog,
                now=when,
                observations_dir=obs_dir,
                health_dir=health_dir,
            )

            for row in result["rows"]:
                spec = by_id[row["series_id"]]
                if not _release_dates_empty(spec.get("release_rule")):
                    continue
                self.assertNotEqual(
                    row["status"],
                    "checked_success_no_new_release",
                    msg=f"{row['series_id']} must not claim success without a pinned calendar",
                )


if __name__ == "__main__":
    unittest.main()
