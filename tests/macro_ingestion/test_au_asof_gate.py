"""Fail-closed point-in-time gate for AU leading observations."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.au_leading.asof import (
    BEFORE,
    ELIGIBLE,
    MISSING,
    NAIVE,
    TIME_UNKNOWN,
    filter_observations_by_asof,
    observation_eligible,
    release_gate,
)
from scripts.macro_ingestion.au_leading import jsa_reos

SYDNEY = ZoneInfo("Australia/Sydney")
NEW_YORK = ZoneInfo("America/New_York")


class TestAuAsOfGate(unittest.TestCase):
    def test_missing_release_instant_is_not_eligible(self) -> None:
        as_of = datetime(2026, 10, 15, 11, 30, tzinfo=SYDNEY)
        self.assertFalse(observation_eligible(None, as_of))
        self.assertFalse(observation_eligible("", as_of))
        self.assertEqual(release_gate(None, as_of), MISSING)
        kept = filter_observations_by_asof(
            [{"id": "AU.Labor.jsa_reos_recruiting_share", "period": "2026-08", "value": 1.0}],
            as_of,
        )
        self.assertEqual(kept, [])

    def test_sydney_1130_instant_boundary(self) -> None:
        release = "2026-10-15T11:30:00+11:00"
        before = datetime(2026, 10, 15, 11, 29, tzinfo=SYDNEY)
        at = datetime(2026, 10, 15, 11, 30, tzinfo=SYDNEY)
        self.assertEqual(release_gate(release, before), BEFORE)
        self.assertFalse(observation_eligible(release, before))
        self.assertEqual(release_gate(release, at), ELIGIBLE)
        self.assertTrue(observation_eligible(release, at))
        self.assertEqual(
            at.astimezone(timezone.utc).replace(microsecond=0),
            datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc),
        )

    def test_date_only_same_day_is_quarantined(self) -> None:
        release = date(2026, 10, 15)
        same_morning = datetime(2026, 10, 15, 11, 30, tzinfo=SYDNEY)
        next_day = datetime(2026, 10, 16, 0, 1, tzinfo=SYDNEY)
        self.assertEqual(release_gate(release, same_morning), TIME_UNKNOWN)
        self.assertFalse(observation_eligible("2026-10-15", same_morning))
        self.assertTrue(observation_eligible(release, next_day))

    def test_us_dst_boundary_uses_exact_instant(self) -> None:
        # 2026-11-01 01:30 America/New_York is still EDT (UTC-4); the fallback is at 02:00.
        release = datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK)
        before = datetime(2026, 11, 1, 1, 29, tzinfo=NEW_YORK)
        at = datetime(2026, 11, 1, 1, 30, tzinfo=NEW_YORK)
        self.assertEqual(release.utcoffset().total_seconds(), -4 * 3600)
        self.assertFalse(observation_eligible(release, before))
        self.assertTrue(observation_eligible(release, at))
        # Same UTC calendar date must not make 01:29 eligible.
        self.assertEqual(before.astimezone(timezone.utc).date(), release.astimezone(timezone.utc).date())

    def test_historical_as_of_and_delayed_publication_keep_reference_period(self) -> None:
        point = {
            "id": "AU.Labor.jsa_ivi_national_sa",
            "period": "2026-08",
            "value": 212400.806,
            "release_date": "2026-10-21",
            "vintage": "release:2026-10-21",
        }
        early = filter_observations_by_asof([point], datetime(2026, 9, 1, tzinfo=timezone.utc))
        delayed = filter_observations_by_asof([point], datetime(2026, 10, 14, tzinfo=timezone.utc))
        visible = filter_observations_by_asof([point], datetime(2026, 10, 22, tzinfo=timezone.utc))
        self.assertEqual(early, [])
        self.assertEqual(delayed, [])
        self.assertEqual(visible[0]["period"], "2026-08")
        self.assertEqual(visible[0]["vintage"], "release:2026-10-21")

    def test_naive_release_is_quarantined(self) -> None:
        naive = datetime(2026, 10, 15, 11, 30)
        as_of = datetime(2026, 10, 16, tzinfo=SYDNEY)
        self.assertEqual(release_gate(naive, as_of), NAIVE)
        self.assertFalse(observation_eligible(naive, as_of))

    def test_reos_does_not_substitute_today_for_missing_provenance(self) -> None:
        source = Path(jsa_reos.__file__).read_text(encoding="utf-8")
        self.assertNotIn("date.today", source)

        def opener(url: str, timeout: float = 8) -> dict:
            _ = timeout
            if url.endswith("data_file.xlsx"):
                return {"ok": True, "url": url, "http_status": 200, "body": b"PK\x03\x04not-a-workbook", "error": None}
            html = (
                '<a href="https://www.jobsandskills.gov.au/sites/default/files/2026-09/'
                'recruitment_insights_report_-_august_2026_data_file.xlsx">data</a>'
            )
            return {"ok": True, "url": url, "http_status": 200, "body": html.encode(), "error": None}

        payload = jsa_reos.fetch_reos(
            as_of=datetime(2026, 10, 15, tzinfo=timezone.utc),
            opener=opener,
        )
        self.assertEqual(payload["points"], [])
        self.assertTrue(any("quarantined" in g["reason"] or "not a valid XLSX" in g["reason"] for g in payload["gaps"]))


if __name__ == "__main__":
    unittest.main()
