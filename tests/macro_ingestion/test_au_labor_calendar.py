"""AU labour force release calendar (ABS schedule verified 2026-10-14)."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.calendar import latest_due_release, release_due
from scripts.macro_ingestion.contract import load_catalog

SYDNEY = ZoneInfo("Australia/Sydney")
LABOUR_IDS = (
    "AU.Labor.unemployment",
    "AU.Labor.employment",
    "AU.Labor.participation",
)
FIXTURE_SUFFIX = "abs_labour_release_schedule_20261014.txt"
WRONG_BINDING = "2026-10-16T11:30:00+11:00"


def _spec(catalog_id: str) -> dict:
    catalog = load_catalog()
    return next(s for s in catalog["series"] if s["id"] == catalog_id)


class AuLaborCalendarTests(unittest.TestCase):
    def test_september_release_not_due_before_1130_local(self) -> None:
        when = datetime(2026, 10, 15, 11, 29, tzinfo=SYDNEY)
        spec = _spec("AU.Labor.unemployment")
        due = latest_due_release(spec, when)
        self.assertIsNotNone(due)
        self.assertEqual(due["period"], "2026-08")
        self.assertNotEqual(due.get("raw"), "2026-10-15T11:30:00+11:00")

    def test_september_release_due_at_1130_local(self) -> None:
        when = datetime(2026, 10, 15, 11, 30, tzinfo=SYDNEY)
        spec = _spec("AU.Labor.unemployment")
        self.assertTrue(release_due(spec, when))
        due = latest_due_release(spec, when)
        self.assertIsNotNone(due)
        self.assertEqual(due["period"], "2026-09")
        utc = when.astimezone(timezone.utc)
        self.assertEqual(utc.replace(microsecond=0), datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc))

    def test_catalog_does_not_bind_september_to_oct_16(self) -> None:
        spec = _spec("AU.Labor.unemployment")
        rule = spec.get("release_rule") or {}
        periods = rule.get("expected_periods") or {}
        self.assertNotIn(WRONG_BINDING, periods)
        self.assertEqual(periods.get("2026-10-15T11:30:00+11:00"), "2026-09")

    def test_october_release_november_19_aedt(self) -> None:
        when = datetime(2026, 11, 19, 11, 30, tzinfo=SYDNEY)
        spec = _spec("AU.Labor.unemployment")
        due = latest_due_release(spec, when)
        self.assertIsNotNone(due)
        self.assertEqual(due["period"], "2026-10")
        utc = when.astimezone(timezone.utc)
        self.assertEqual(utc.replace(microsecond=0), datetime(2026, 11, 19, 0, 30, tzinfo=timezone.utc))

    def test_participation_includes_october_15_release(self) -> None:
        spec = _spec("AU.Labor.participation")
        rule = spec.get("release_rule") or {}
        dates = rule.get("dates") or []
        self.assertIn("2026-10-15T11:30:00+11:00", dates)
        self.assertTrue(str(rule.get("schedule_source") or "").endswith(FIXTURE_SUFFIX))
        self.assertEqual(rule.get("calendar_coverage_ends"), "2027-03-25T11:30:00+11:00")

    def test_all_labour_series_share_labour_fixture(self) -> None:
        for catalog_id in LABOUR_IDS:
            rule = _spec(catalog_id).get("release_rule") or {}
            self.assertTrue(str(rule.get("schedule_source") or "").endswith(FIXTURE_SUFFIX))
            self.assertNotIn(WRONG_BINDING, rule.get("dates") or [])


if __name__ == "__main__":
    unittest.main()
