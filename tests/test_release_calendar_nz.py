"""Unit tests for the New Zealand release calendar adapter (fixtures only, no network)."""

from __future__ import annotations

import importlib
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.dashboard_repair.release_contract import (
    validate_events,
    validate_source_plan,
)
from scripts.dashboard_repair.schedules import nz as nz_mod


def _fixture(name: str) -> str:
    return (
        Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "nz" / name
    ).read_text(encoding="utf-8")


def _reload_nz() -> object:
    return importlib.reload(nz_mod)


class NzReleaseCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self._now = datetime(2026, 11, 6, 12, 0, 0)
        self._fetched_at = "2026-11-06T12:00:00Z"

    def test_source_plan_https(self) -> None:
        mod = _reload_nz()
        validate_source_plan(mod.NzOfficialSchedule().source_plan())

    def test_fixture_parses_expected_events(self) -> None:
        mod = _reload_nz()
        sched = mod.NzOfficialSchedule()
        docs = {
            "stats_nz_calendar": _fixture("stats_nz_calendar_ics_snippet.txt"),
            "stats_nz_gdp": _fixture("stats_nz_gdp_latest_release.html"),
            "stats_nz_cpi": _fixture("stats_nz_cpi_latest.html"),
            "rbnz_ocr": _fixture("rbnz_statistics_ocr.html"),
        }
        events = mod.ADAPTER.parse_documents(
            docs, now=self._now, fetched_at=self._fetched_at
        )
        validate_events(events)

        by_f = {e.event_family: e for e in events}

        spi = by_f["nz_selected_prices"]
        self.assertEqual(spi.local_date, date(2026, 11, 17))
        self.assertIsNone(spi.local_time)
        self.assertEqual(spi.status, "tba")
        self.assertEqual(spi.series_ids, ())
        self.assertNotIn("NZ.Inflation.headline", spi.series_ids)

        bpp = by_f["nz_business_prices"]
        self.assertEqual(bpp.local_date, date(2026, 11, 18))
        self.assertEqual(
            set(bpp.series_ids),
            {
                "NZ.Inflation.ppi",
                "NZ.Inflation.import_price_index",
                "NZ.Inflation.export_price_index",
            },
        )

        rts = by_f["nz_retail"]
        self.assertEqual(rts.local_date, date(2026, 11, 23))
        self.assertEqual(set(rts.series_ids), {"NZ.Consumer.retail"})

        emp = by_f["nz_employment_indicators"]
        self.assertEqual(emp.local_date, date(2026, 11, 30))
        self.assertNotIn("NZ.Labor.unemployment", emp.series_ids)

        ocr = by_f["nz_ocr"]
        self.assertEqual(ocr.local_date, date(2026, 12, 9))
        self.assertEqual(ocr.local_time, "14:00")
        self.assertEqual(ocr.status, "verified")

        gdp = by_f["nz_gdp"]
        self.assertEqual(gdp.local_date, date(2026, 12, 17))
        self.assertIsNone(gdp.local_time)
        self.assertEqual(gdp.reference_period, "2026-Q3")

        cpi = by_f["nz_cpi"]
        self.assertEqual(cpi.local_date, date(2027, 1, 27))
        self.assertIsNone(cpi.local_time)
        self.assertEqual(cpi.reference_period, "2026-Q4")

        self.assertIn("nz_labour_market", by_f)
        self.assertEqual(by_f["nz_labour_market"].local_date, date(2027, 2, 3))

        self.assertEqual(len(mod.GAPS), 0)

    def test_garbage_returns_empty(self) -> None:
        mod = _reload_nz()
        out = mod.ADAPTER.parse_documents(
            {"stats_nz_calendar": "@@@", "stats_nz_gdp": "", "stats_nz_cpi": "", "rbnz_ocr": ""},
            now=self._now,
            fetched_at=self._fetched_at,
        )
        self.assertEqual(out, [])

    def test_cpi_gdp_only_when_sentence_present(self) -> None:
        mod = _reload_nz()
        base = {
            "stats_nz_calendar": "",
            "rbnz_ocr": "",
        }
        no_next = _fixture("stats_nz_gdp_latest_release.html").replace(
            "will be released on", "availability to be advised for"
        )
        ev = mod.ADAPTER.parse_documents(
            {**base, "stats_nz_gdp": no_next, "stats_nz_cpi": ""},
            now=self._now,
            fetched_at=self._fetched_at,
        )
        self.assertEqual([e.event_family for e in ev], [])
        self.assertTrue(any("GDP" in g for g in mod.GAPS))

    def test_ocr_tba_when_fixture_has_no_time(self) -> None:
        mod = _reload_nz()
        html = _fixture("rbnz_statistics_ocr.html").replace("2:00pm, ", "")
        ev = mod.ADAPTER.parse_documents(
            {
                "stats_nz_calendar": "",
                "stats_nz_gdp": "",
                "stats_nz_cpi": "",
                "rbnz_ocr": html,
            },
            now=self._now,
            fetched_at=self._fetched_at,
        )
        ocr = next(e for e in ev if e.event_family == "nz_ocr")
        self.assertIsNone(ocr.local_time)
        self.assertEqual(ocr.status, "tba")


if __name__ == "__main__":
    unittest.main()
