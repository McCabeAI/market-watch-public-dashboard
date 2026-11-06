"""Tests for EA official schedule adapter (no network)."""

from __future__ import annotations

import re
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.dashboard_repair.release_contract import validate_source_plan
from scripts.dashboard_repair.schedules.ea import ADAPTER, GAPS

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "release_calendar" / "ea"


def _load(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _has_hh_mm_clock(text: str) -> bool:
    return bool(re.search(r"\b\d{2}:\d{2}\b", text))


class EaReleaseCalendarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetched_at = "2026-11-06T18:00:00Z"
        self.now = datetime(2026, 11, 6, 12, 0, 0)

    def test_source_plan_https_validate(self) -> None:
        plan = ADAPTER.source_plan()
        validate_source_plan(plan)
        for doc in plan:
            self.assertTrue(doc.url.startswith("https://"))

    def test_gaps_includes_pmi(self) -> None:
        self.assertIn("EA PMI dates are not on a directly fetchable primary calendar", GAPS)

    def test_hicp_nov_18_oct_reference(self) -> None:
        docs = {
            "ecb_hicp": _load("ecb_hicp_excerpt.html"),
            "eurostat_qna": _load("eurostat_qna_excerpt.txt"),
            "ecb_gc": _load("ecb_gc_excerpt.html"),
        }
        hicp_html = docs["ecb_hicp"]
        events = ADAPTER.parse_documents(docs, now=self.now, fetched_at=self.fetched_at)
        nov18 = [e for e in events if e.local_date == date(2026, 11, 18)]
        self.assertEqual(len(nov18), 1)
        ev = nov18[0]
        self.assertEqual(ev.event_family, "ea_hicp")
        self.assertEqual(ev.reference_period, "2026-10")
        self.assertEqual(
            ev.series_ids,
            ("EA.Inflation.headline", "EA.Inflation.underlying"),
        )
        if _has_named_euro_zone(hicp_html):
            self.assertEqual(ev.status, "verified")
            self.assertEqual(ev.local_time, "12:00")
        else:
            self.assertEqual(ev.status, "tba")
            self.assertIsNone(ev.local_time)
            self.assertIn("12:00", ev.provenance)

    def test_gdp_flash_provisional(self) -> None:
        docs = {
            "ecb_hicp": _load("ecb_hicp_excerpt.html"),
            "eurostat_qna": _load("eurostat_qna_excerpt.txt"),
            "ecb_gc": _load("ecb_gc_excerpt.html"),
        }
        events = ADAPTER.parse_documents(docs, now=self.now, fetched_at=self.fetched_at)
        flash = [e for e in events if e.event_family == "ea_gdp_flash"]
        self.assertEqual(len(flash), 1)
        ev = flash[0]
        self.assertEqual(ev.local_date, date(2026, 11, 13))
        self.assertEqual(ev.date_confidence, "provisional")
        self.assertEqual(ev.status, "tba")
        self.assertIsNone(ev.local_time)
        self.assertEqual(
            ev.series_ids,
            ("EA.Activity.gdp_domestic_demand", "EA.Activity.gdp_components"),
        )

    def test_ecb_mp_dec_2026(self) -> None:
        docs = {
            "ecb_hicp": _load("ecb_hicp_excerpt.html"),
            "eurostat_qna": _load("eurostat_qna_excerpt.txt"),
            "ecb_gc": _load("ecb_gc_excerpt.html"),
        }
        gc_html = docs["ecb_gc"]
        events = ADAPTER.parse_documents(docs, now=self.now, fetched_at=self.fetched_at)
        dec17 = [e for e in events if e.event_family == "ea_ecb_mp" and e.local_date == date(2026, 12, 17)]
        self.assertEqual(len(dec17), 1)
        ev = dec17[0]
        if _has_hh_mm_clock(gc_html):
            self.assertEqual(ev.status, "verified")
            self.assertIsNotNone(ev.local_time)
        else:
            self.assertEqual(ev.status, "tba")
            self.assertIsNone(ev.local_time)

    def test_garbage_returns_empty(self) -> None:
        docs = {
            "ecb_hicp": "not valid {{{",
            "eurostat_qna": "",
            "ecb_gc": "",
        }
        events = ADAPTER.parse_documents(docs, now=self.now, fetched_at=self.fetched_at)
        self.assertEqual(events, [])

    def test_omit_one_document(self) -> None:
        docs_hicp_only = {
            "ecb_hicp": _load("ecb_hicp_excerpt.html"),
        }
        ev_h = ADAPTER.parse_documents(docs_hicp_only, now=self.now, fetched_at=self.fetched_at)
        self.assertTrue(any(e.event_family in ("ea_hicp", "ea_hicp_flash") for e in ev_h))

        docs_qna_only = {
            "eurostat_qna": _load("eurostat_qna_excerpt.txt"),
        }
        ev_q = ADAPTER.parse_documents(docs_qna_only, now=self.now, fetched_at=self.fetched_at)
        self.assertTrue(ev_q)


def _has_named_euro_zone(html: str) -> bool:
    return bool(
        re.search(
            r"\b(?:CET|CEST|Central European Time|Frankfurt time)\b",
            html,
            re.IGNORECASE,
        )
    )


if __name__ == "__main__":
    unittest.main()
