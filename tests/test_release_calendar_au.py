"""Australia release calendar adapter (fixture-backed, no network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.dashboard_repair.release_contract import SourceDocument, validate_source_plan
from scripts.dashboard_repair.schedules import au as au_mod
from scripts.dashboard_repair.schedules.au import ADAPTER, AuOfficialSchedule

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "au"


def _read(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


class AustraliaReleaseCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.maxDiff = None

    def test_source_plan_https(self) -> None:
        plan = ADAPTER.source_plan()
        validate_source_plan(plan)
        by_key = {d.key: d for d in plan}
        self.assertEqual(by_key["abs_wpi"].url[:8], "https://")
        self.assertTrue(by_key["abs_month"].url.startswith("https://"))
        self.assertTrue(by_key["rba_int_rate"].url.startswith("https://"))
        self.assertIsInstance(plan, tuple)
        self.assertTrue(all(isinstance(d, SourceDocument) for d in plan))

    def test_fixture_end_to_end(self) -> None:
        documents = {
            "abs_wpi": _read("abs_wpi.html"),
            "abs_month": _read("abs_month.html"),
            "rba_int_rate": _read("rba_int_rate.html"),
        }
        # Before the next listed media release so "3 November 2026" is still in the future in Sydney.
        now = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        fetched = "2026-11-01T12:00:00Z"
        sched = AuOfficialSchedule()
        events = sched.parse_documents(documents, now=now, fetched_at=fetched)

        wpi_rows = [e for e in events if e.event_family == "au_wpi"]
        wpi = next(e for e in wpi_rows if e.reference_period == "2026-Q3")
        self.assertEqual(wpi.local_date, date(2026, 11, 18))
        self.assertEqual(wpi.local_time, "11:30")
        self.assertEqual(wpi.timezone, "Australia/Sydney")
        self.assertEqual(wpi.status, "verified")
        self.assertEqual(wpi.reference_period, "2026-Q3")
        self.assertEqual(set(wpi.series_ids), {"AU.Labor.wages"})
        self.assertGreaterEqual(len(wpi_rows), 5)

        by_fam = {e.event_family: e for e in events}
        lf = by_fam["au_labour_force"]
        self.assertEqual(lf.local_date, date(2026, 11, 19))
        self.assertEqual(lf.local_time, "11:30")
        self.assertEqual(lf.reference_period, "2026-10")
        self.assertEqual(
            set(lf.series_ids),
            {"AU.Labor.unemployment", "AU.Labor.employment", "AU.Labor.participation"},
        )
        self.assertEqual(lf.status, "verified")

        cpi_ev = by_fam["au_cpi"]
        self.assertEqual(cpi_ev.local_date, date(2026, 11, 25))
        self.assertEqual(cpi_ev.local_time, "11:30")
        self.assertEqual(cpi_ev.reference_period, "2026-10")
        self.assertEqual(
            set(cpi_ev.series_ids),
            {"AU.Inflation.headline", "AU.Inflation.underlying"},
        )
        self.assertEqual(
            len([e for e in events if e.event_family == "au_cpi"]),
            1,
        )

        self.assertIn("au_household_spending", by_fam)

        rba_ev = by_fam.get("au_rba")
        self.assertIsNotNone(rba_ev)
        assert rba_ev is not None
        self.assertEqual(rba_ev.local_date, date(2026, 11, 3))
        self.assertIsNone(rba_ev.local_time)
        self.assertEqual(rba_ev.status, "tba")

        gaps = sched.gaps
        self.assertTrue(
            any("retail trade" in g.lower() and "household spending" in g.lower() for g in gaps),
            gaps,
        )

    def test_fixture_date_without_clock_is_tba(self) -> None:
        documents = {
            "abs_wpi": "",
            "abs_month": _read("abs_month_clock_tba.html")
            + "\n<!-- fixture clock-tba tail marker: CLOCK_TBA_FIXTURE_EXTRA -->",
            "rba_int_rate": "",
        }
        now = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
        events = ADAPTER.parse_documents(
            documents, now=now, fetched_at="2026-11-06T12:00:00Z"
        )
        tba_lf = [
            e
            for e in events
            if e.event_family == "au_labour_force"
            and e.local_date == date(2026, 11, 19)
            and e.local_time is None
        ]
        self.assertEqual(len(tba_lf), 1)
        self.assertEqual(tba_lf[0].status, "tba")

    def test_garbage_returns_empty(self) -> None:
        documents = {
            "abs_wpi": _read("garbage.txt"),
            "abs_month": _read("garbage.txt"),
            "rba_int_rate": _read("garbage.txt"),
        }
        out = ADAPTER.parse_documents(
            documents,
            now=datetime(2026, 11, 6, tzinfo=timezone.utc),
            fetched_at="2026-11-06T12:00:00Z",
        )
        self.assertEqual(out, [])

    def test_module_gaps_tuple(self) -> None:
        self.assertIsInstance(au_mod.GAPS, tuple)

    def test_event_ids_are_deduplicated(self) -> None:
        cal_html = _read("abs_month.html")
        documents = {
            "abs_wpi": _read("abs_wpi.html"),
            "abs_month": cal_html,
            "rba_int_rate": "",
        }
        events = ADAPTER.parse_documents(
            documents,
            now=datetime(2026, 11, 6, tzinfo=timezone.utc),
            fetched_at="2026-11-06T12:00:00Z",
        )
        wpi_sep_2026 = [
            e
            for e in events
            if e.event_family == "au_wpi"
            and e.reference_period == "2026-Q3"
            and e.local_date == date(2026, 11, 18)
        ]
        self.assertEqual(len(wpi_sep_2026), 1)


if __name__ == "__main__":
    unittest.main()
