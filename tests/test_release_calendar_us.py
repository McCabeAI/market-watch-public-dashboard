"""Unit tests for ``UsOfficialSchedule`` (no network)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.dashboard_repair.release_contract import (
    validate_events,
    validate_source_plan,
)
from scripts.dashboard_repair.schedules.us import ADAPTER, GAPS


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "us"


def _load_documents() -> dict[str, str]:
    docs: dict[str, str] = {}
    if not FIXTURE_DIR.is_dir():
        return docs
    for path in sorted(FIXTURE_DIR.iterdir()):
        if path.is_file():
            docs[path.stem] = path.read_text(encoding="utf-8", errors="replace")
    return docs


class TestUsReleaseCalendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
        cls.fetched_at = "2026-11-06T18:00:00Z"
        cls.documents = _load_documents()

    def test_validate_source_plan(self) -> None:
        plan = ADAPTER.source_plan()
        validate_source_plan(plan)
        for doc in plan:
            self.assertTrue(doc.url.startswith("https://"), doc.url)

    def test_parse_fixtures_validate_events(self) -> None:
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        validate_events(events)

    def test_employment_situation_october_2026(self) -> None:
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        em = [e for e in events if e.event_family == "us_empsit" and e.reference_period == "2026-10"]
        self.assertEqual(len(em), 1)
        e = em[0]
        self.assertEqual(str(e.local_date), "2026-11-06")
        self.assertEqual(e.local_time, "08:30")
        self.assertEqual(e.timezone, "America/New_York")
        self.assertEqual(e.status, "verified")
        self.assertEqual(
            set(e.series_ids),
            {
                "US.Labor.payrolls",
                "US.Labor.unemployment",
                "US.Labor.wages",
                "US.Labor.participation",
            },
        )

    def test_cpi_october_2026(self) -> None:
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        cpi = [e for e in events if e.event_family == "us_cpi" and e.reference_period == "2026-10"]
        self.assertEqual(len(cpi), 1)
        e = cpi[0]
        self.assertEqual(str(e.local_date), "2026-11-10")
        self.assertEqual(e.local_time, "08:30")
        self.assertEqual(e.status, "verified")
        self.assertEqual(set(e.series_ids), {"US.Inflation.cpi_headline", "US.Inflation.cpi_core"})

    def test_bea_nov_25_gdp_and_pce_distinct(self) -> None:
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        d = {e.event_family: e for e in events if str(e.local_date) == "2026-11-25"}
        self.assertIn("us_gdp", d)
        self.assertIn("us_pce", d)
        self.assertNotEqual(d["us_gdp"].title, d["us_pce"].title)

    def test_fomc_dec_2026_tba_clock(self) -> None:
        # Fixture matches https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm:
        # December 2026 row shows meeting dates 8-9* but no statement release clock on that row.
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        fomc = [e for e in events if e.event_family == "us_fomc"]
        self.assertEqual(len(fomc), 1)
        e = fomc[0]
        self.assertEqual(str(e.local_date), "2026-12-09")
        self.assertIsNone(e.local_time)
        self.assertEqual(e.status, "tba")

    def test_ism_december_2026_standing(self) -> None:
        events = ADAPTER.parse_documents(
            self.documents,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        mfg = [
            e
            for e in events
            if e.event_family == "us_ism_manufacturing"
            and e.reference_period == "December 2026"
        ]
        svc = [
            e
            for e in events
            if e.event_family == "us_ism_services" and e.reference_period == "December 2026"
        ]
        self.assertEqual(len(mfg), 1)
        self.assertEqual(len(svc), 1)
        self.assertEqual(str(mfg[0].local_date), "2026-12-01")
        self.assertEqual(str(svc[0].local_date), "2026-12-03")
        self.assertEqual(mfg[0].local_time, "10:00")
        self.assertEqual(svc[0].local_time, "10:00")
        self.assertEqual(mfg[0].status, "standing")
        self.assertEqual(svc[0].status, "standing")

    def test_garbage_documents_never_raise(self) -> None:
        garbage = {k: "<<<not a table>>>" for k in self.documents}
        events = ADAPTER.parse_documents(
            garbage,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        self.assertEqual(events, [])

    def test_jolts_single_event_all_series(self) -> None:
        docs = dict(self.documents)
        docs["bls_jolts"] = (
            "# https://www.bls.gov/schedule/news_release/jolts.htm\n"
            "| Reference Month | Release Date | Release Time |\n"
            "| --- | --- | --- |\n"
            "| November 2026 | Jan. 06, 2027 | 10:00 AM |\n"
        )
        events = ADAPTER.parse_documents(
            docs,
            now=self.now,
            fetched_at=self.fetched_at,
        )
        j = [e for e in events if e.event_family == "us_jolts"]
        self.assertEqual(len(j), 1)
        self.assertEqual(len(j[0].series_ids), 8)

    def test_gaps_tuple_non_empty(self) -> None:
        self.assertIsInstance(GAPS, tuple)
        self.assertTrue(all(isinstance(s, str) and s for s in GAPS))


if __name__ == "__main__":
    unittest.main()
