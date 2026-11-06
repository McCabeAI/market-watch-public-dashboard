"""Tests for Japan release calendar adapter (fixtures only, no network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.dashboard_repair.release_contract import validate_source_plan
from scripts.dashboard_repair.schedules import jp as jp_sched
from scripts.dashboard_repair.schedules.jp import ADAPTER, JpOfficialSchedule

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "jp"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class ReleaseCalendarJapanTests(unittest.TestCase):
    def test_source_plan_https(self) -> None:
        plan = ADAPTER.source_plan()
        validate_source_plan(plan)
        for doc in plan:
            self.assertTrue(doc.url.startswith("https://"), msg=doc.url)

    def test_parse_fixtures_regression(self) -> None:
        documents = {
            "cao_gdp": _load("cao_gdp.html"),
            "estat": _load("estat_schedule_excerpt.txt"),
            "boj_mpm": _load("boj_mpm.html"),
            "boj_calendar": _load("boj_calendar_nov2026.html"),
        }
        events = ADAPTER.parse_documents(
            documents,
            now=datetime(2026, 11, 6, 12, 0, 0),
            fetched_at="2026-11-06T12:00:00Z",
        )
        by_family: dict[str, list] = {}
        for ev in events:
            by_family.setdefault(ev.event_family, []).append(ev)

        self.assertTrue(
            any(
                "Services Producer Price Index" in g and "Skipped" in g
                for g in jp_sched.GAPS
            ),
            msg=f"expected SPPI skip in GAPS, got {jp_sched.GAPS!r}",
        )

        gdp_first = [
            ev
            for ev in by_family.get("jp_gdp", [])
            if ev.title == "Quarterly GDP first preliminary"
            and ev.local_date == date(2026, 11, 16)
        ]
        self.assertEqual(len(gdp_first), 1, "expected one GDP first preliminary event")
        g0 = gdp_first[0]
        self.assertEqual(g0.local_time, "08:50")
        self.assertEqual(g0.timezone, "Asia/Tokyo")
        self.assertEqual(g0.status, "verified")
        self.assertEqual(g0.reference_period, "2026-Q3")
        self.assertEqual(
            g0.series_ids,
            ("JP.Activity.gdp_domestic_demand", "JP.Activity.domestic_demand"),
        )

        gdp_second = [
            ev
            for ev in by_family.get("jp_gdp", [])
            if ev.title == "Quarterly GDP second preliminary"
            and ev.local_date == date(2026, 12, 8)
        ]
        self.assertEqual(len(gdp_second), 1)
        self.assertEqual(gdp_second[0].local_time, "08:50")
        self.assertNotEqual(gdp_first[0].event_id(), gdp_second[0].event_id())

        cpi = [
            ev
            for ev in by_family.get("jp_cpi", [])
            if ev.local_date == date(2026, 11, 20)
        ]
        self.assertEqual(len(cpi), 1)
        self.assertEqual(cpi[0].local_time, "08:30")
        self.assertEqual(cpi[0].reference_period, "2026-10")

        mpm = [ev for ev in by_family.get("jp_boj_mpm", []) if ev.local_date.year == 2026]
        self.assertTrue(
            any(
                ev.local_date == date(2026, 12, 18)
                and ev.status == "tba"
                and ev.local_time is None
                and ev.reference_period == "2026-12-17/2026-12-18"
                for ev in mpm
            )
        )

        cgpi = [
            ev
            for ev in by_family.get("jp_cgpi", [])
            if ev.local_date == date(2026, 11, 12)
        ]
        self.assertEqual(len(cgpi), 1)
        self.assertEqual(cgpi[0].local_time, "08:50")
        self.assertEqual(cgpi[0].status, "verified")
        self.assertEqual(cgpi[0].reference_period, "2026-10")

    def test_approximate_mid_november_emits_nothing_for_that_row(self) -> None:
        tiny = "公表内容 2026-11月中旬 総務省 消費者物価指数 全国(2026年10月分)"
        events = ADAPTER.parse_documents(
            {"estat": tiny},
            now=datetime(2026, 11, 6, 12, 0, 0),
            fetched_at="2026-11-06T12:00:00Z",
        )
        self.assertEqual(events, [])

    def test_garbage_returns_empty(self) -> None:
        out = ADAPTER.parse_documents(
            {"cao_gdp": "not html {{{", "estat": "", "boj_mpm": "", "boj_calendar": ""},
            now=datetime(2026, 11, 6, 12, 0, 0),
            fetched_at="2026-11-06T12:00:00Z",
        )
        self.assertEqual(out, [])

    def test_estat_unparsed_keywords_yield_gap(self) -> None:
        sched = JpOfficialSchedule()
        body = (
            "公表内容 2026-11月下旬 厚生労働省 消費者物価指数 全国(2026年10月分) "
            "（日内公表時間は未定）"
        )
        events = sched.parse_documents(
            {"estat": body},
            now=datetime(2026, 11, 6, 12, 0, 0),
            fetched_at="2026-11-06T12:00:00Z",
        )
        self.assertEqual(events, [])
        self.assertIn(
            "Statistics Bureau CPI/labour schedule was not in the fetched HTML",
            jp_sched.GAPS,
        )


if __name__ == "__main__":
    unittest.main()
