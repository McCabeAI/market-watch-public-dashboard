"""Release calendar evaluation tests."""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.calendar import release_due, schedule_parseable
from scripts.macro_ingestion.contract import load_catalog
from scripts.macro_ingestion.windows import cutoff_class

NY = ZoneInfo("America/New_York")


class TestMacroIngestionCalendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        catalog = load_catalog()
        cls.ea_flash = next(
            row for row in catalog["series"] if row["id"] == "EA.Activity.flash_composite_pmi"
        )

    def test_ea_flash_sep23_not_due_at_0359_et(self) -> None:
        when = datetime(2026, 9, 23, 3, 59, tzinfo=NY)
        self.assertFalse(release_due(self.ea_flash, when))

    def test_ea_flash_sep23_due_at_0400_et_post_freeze(self) -> None:
        when = datetime(2026, 9, 23, 4, 0, tzinfo=NY)
        self.assertTrue(release_due(self.ea_flash, when))
        self.assertEqual(cutoff_class(when), "post_freeze")

    def test_country_local_schedule_required_empty_not_parseable(self) -> None:
        rule = {"kind": "country_local_schedule_required", "timezone": "America/New_York", "dates": []}
        self.assertFalse(schedule_parseable(rule))
        spec = {
            "country": "US",
            "timezone": "America/New_York",
            "release_rule": rule,
        }
        when = datetime(2026, 9, 23, 12, 0, tzinfo=NY)
        self.assertFalse(release_due(spec, when))

    def test_us_dst_spring_boundary_local_list(self) -> None:
        """Release at 08:30 NY on the Monday after US spring-forward Sunday."""
        spec = {
            "country": "US",
            "timezone": "America/New_York",
            "release_rule": {
                "kind": "local_datetime_list",
                "timezone": "America/New_York",
                "dates": ["2026-03-09T08:30:00"],
            },
        }
        before = datetime(2026, 3, 9, 8, 29, tzinfo=NY)
        after = datetime(2026, 3, 9, 8, 30, tzinfo=NY)
        self.assertFalse(release_due(spec, before))
        self.assertTrue(release_due(spec, after))
        # EDT offset after DST start
        self.assertEqual(after.utcoffset().total_seconds(), -4 * 3600)

    def test_holiday_roll_forward(self) -> None:
        # US Independence Day 2026 observed Friday July 3 (holiday); roll to Monday July 6.
        spec = {
            "country": "US",
            "timezone": "America/New_York",
            "release_rule": {
                "kind": "local_datetime_list",
                "timezone": "America/New_York",
                "dates": ["2026-07-03T08:30:00"],
            },
        }
        friday = datetime(2026, 7, 3, 8, 30, tzinfo=NY)
        monday = datetime(2026, 7, 6, 8, 30, tzinfo=NY)
        self.assertFalse(release_due(spec, friday))
        self.assertFalse(release_due(spec, datetime(2026, 7, 5, 12, 0, tzinfo=NY)))
        self.assertTrue(release_due(spec, monday))


if __name__ == "__main__":
    unittest.main()
