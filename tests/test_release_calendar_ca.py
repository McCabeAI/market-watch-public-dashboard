"""Canada release calendar adapter tests (fixtures only, no network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.dashboard_repair.schedules import ca
from scripts.dashboard_repair.schedules.ca import ADAPTER, GAPS
from scripts.dashboard_repair.release_contract import validate_source_plan


_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "ca"

_FETCHED_AT = "2026-11-06T18:00:00Z"
_NOW = datetime(2026, 11, 6, 12, 0, 0)


def _load(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _by_family(events: list, family: str):
    return [e for e in events if e.event_family == family]


class ReleaseCalendarCaTests(unittest.TestCase):
    def test_validate_source_plan(self) -> None:
        validate_source_plan(ADAPTER.source_plan())

    def test_parse_full_fixtures_standing_clock(self) -> None:
        docs = {
            "primary_table": _load("release_dates_2026.txt"),
            "daily_clock": _load("daily_clock.html"),
            "lfs_daily": _load("lfs_daily.html"),
            "boc_rate": _load("boc_key.html"),
        }
        evs = ADAPTER.parse_documents(docs, now=_NOW, fetched_at=_FETCHED_AT)
        self.assertNotEqual(evs, [])

        lfs_nov = [e for e in evs if e.event_family == "ca_lfs" and e.local_date == date(2026, 11, 6)]
        self.assertEqual(len(lfs_nov), 1)
        e = lfs_nov[0]
        self.assertEqual(e.local_time, "08:30")
        self.assertEqual(e.timezone, "America/Toronto")
        self.assertEqual(e.status, "standing")
        self.assertEqual(e.reference_period, "2026-10")
        self.assertEqual(
            set(e.series_ids),
            {
                "CA.Labor.unemployment",
                "CA.Labor.wages",
                "CA.Labor.employment",
                "CA.Labor.participation",
            },
        )

        cpi = [e for e in evs if e.event_family == "ca_cpi" and e.local_date == date(2026, 11, 16)]
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0].local_time, "08:30")
        self.assertEqual(cpi[0].status, "standing")
        self.assertEqual(cpi[0].reference_period, "2026-10")

        retail = [e for e in evs if e.event_family == "ca_retail" and e.local_date == date(2026, 11, 20)]
        self.assertEqual(len(retail), 1)
        self.assertEqual(retail[0].local_time, "08:30")
        self.assertEqual(retail[0].status, "standing")
        self.assertEqual(retail[0].reference_period, "2026-09")

        gdp_ind = [
            e
            for e in evs
            if e.event_family == "ca_gdp_industry" and e.local_date == date(2026, 11, 30)
        ]
        gdp_exp = [
            e
            for e in evs
            if e.event_family == "ca_gdp_expenditure" and e.local_date == date(2026, 11, 30)
        ]
        self.assertEqual(len(gdp_ind), 1)
        self.assertEqual(len(gdp_exp), 1)
        self.assertEqual(gdp_ind[0].reference_period, "2026-09")
        self.assertEqual(gdp_exp[0].reference_period, "2026-Q3")

        boc = _by_family(evs, "ca_boc")
        self.assertEqual(len(boc), 1)
        self.assertEqual(boc[0].local_date, date(2026, 12, 9))
        self.assertIsNone(boc[0].local_time)
        self.assertEqual(boc[0].status, "tba")
        self.assertEqual(boc[0].series_ids, ())

        self.assertEqual(GAPS, ())

    def test_omit_clock_document_lfs_is_tba(self) -> None:
        docs = {
            "primary_table": _load("release_dates_2026.txt"),
            "lfs_daily": _load("lfs_daily.html"),
            "boc_rate": _load("boc_key.html"),
        }
        evs = ADAPTER.parse_documents(docs, now=_NOW, fetched_at=_FETCHED_AT)
        lfs_nov = [e for e in evs if e.event_family == "ca_lfs" and e.local_date == date(2026, 11, 6)]
        self.assertEqual(len(lfs_nov), 1)
        self.assertIsNone(lfs_nov[0].local_time)
        self.assertEqual(lfs_nov[0].status, "tba")

    def test_garbage_returns_empty_list(self) -> None:
        docs = {"primary_table": "@@@not valid@@@<<<", "daily_clock": ""}
        evs = ADAPTER.parse_documents(docs, now=_NOW, fetched_at=_FETCHED_AT)
        self.assertEqual(evs, [])
        self.assertEqual(GAPS, ())

    def test_cal2_html_fallback_with_clock(self) -> None:
        # Minimal cal2-shaped HTML: exercises cal2 parser when PDF text is absent
        clock_excerpt = _load("daily_clock.html")
        docs = {
            "primary_table": "",
            "daily_clock": clock_excerpt
            + """
<div class="upcoming"><div class="master">
<h2>November 16<span class="hd3">\u00a0to\u00a0</span>20, 2026</h2>
<h3 class="hd1">November&nbsp;20</h3>
<div class="rtitle">Retail trade, <span class="refper">September 2026</span></div>
</div></div>
""",
        }
        evs = ADAPTER.parse_documents(docs, now=_NOW, fetched_at=_FETCHED_AT)
        retail = [e for e in evs if e.event_family == "ca_retail" and e.local_date == date(2026, 11, 20)]
        self.assertEqual(len(retail), 1)
        self.assertEqual(retail[0].reference_period, "2026-09")
        self.assertEqual(retail[0].local_time, "08:30")
        self.assertEqual(retail[0].status, "standing")


if __name__ == "__main__":
    unittest.main()
