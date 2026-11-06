"""Unit tests for ``release_contract`` (no network)."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from scripts.dashboard_repair.release_contract import (
    COUNTRIES,
    EconomicReleaseEvent,
    SourceDocument,
    events_to_slots,
    event_to_slot,
    instant_in_et,
    instant_in_zone,
    validate_event,
    validate_events,
    validate_source_plan,
)


def _ev(
    *,
    event_family: str = "test_family",
    country: str = "US",
    title: str = "Test Release",
    publisher: str = "Test Pub",
    local_date: date = date(2026, 11, 6),
    local_time: str | None = "08:30",
    timezone: str = "America/New_York",
    reference_period: str = "Oct 2026",
    source_url: str = "https://example.com/page",
    fetched_at: str = "2026-11-06T18:00:00Z",
    status: str = "verified",
    series_ids: tuple[str, ...] = ("s1",),
    provenance: str = "Printed on official calendar table row 3.",
    date_confidence: str = "confirmed",
) -> EconomicReleaseEvent:
    return EconomicReleaseEvent(
        event_family=event_family,
        country=country,
        title=title,
        publisher=publisher,
        local_date=local_date,
        local_time=local_time,
        timezone=timezone,
        reference_period=reference_period,
        source_url=source_url,
        fetched_at=fetched_at,
        status=status,
        series_ids=series_ids,
        provenance=provenance,
        date_confidence=date_confidence,
    )


class ReleaseCalendarContractTests(unittest.TestCase):
    def test_verified_without_local_time_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_event(_ev(local_time=None, status="verified"))
        self.assertIn("verified", str(ctx.exception))
        self.assertIn("local_time", str(ctx.exception))

    def test_tba_with_local_time_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_event(_ev(status="tba", local_time="09:00"))
        self.assertIn("tba", str(ctx.exception))

    def test_standing_with_hh_mm_passes(self) -> None:
        validate_event(_ev(status="standing", local_time="14:00"))

    def test_bad_timezone_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_event(_ev(timezone="Not/AZone"))
        self.assertIn("IANA", str(ctx.exception))

    def test_http_source_url_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_event(_ev(source_url="http://example.com/x"))
        self.assertIn("https://", str(ctx.exception))

    def test_duplicate_event_id_raises_in_validate_events(self) -> None:
        a = _ev(event_family="x", reference_period="p")
        b = _ev(event_family="x", reference_period="p", title="Other title")
        with self.assertRaises(ValueError) as ctx:
            validate_events([a, b])
        self.assertIn("duplicate event_id", str(ctx.exception))

    def test_event_to_slot_verified_toronto(self) -> None:
        ev = _ev(
            country="CA",
            timezone="America/Toronto",
            local_date=date(2026, 11, 6),
            local_time="08:30",
            status="verified",
        )
        slot = event_to_slot(ev)
        self.assertEqual(slot["stamp"], "2026-11-06T08:30:00")
        self.assertEqual(slot["clock"], "verified")
        self.assertEqual(slot["timezone"], "America/Toronto")

    def test_event_to_slot_tba(self) -> None:
        ev = _ev(status="tba", local_time=None)
        slot = event_to_slot(ev)
        self.assertEqual(slot["stamp"], "")
        self.assertEqual(slot["clock"], "tba")
        self.assertEqual(slot["local_date"], "2026-11-06")
        self.assertEqual(slot["printed_clock"], "")

    def test_dst_sydney_to_et(self) -> None:
        ev = _ev(
            country="AU",
            timezone="Australia/Sydney",
            local_date=date(2026, 11, 18),
            local_time="11:30",
            status="verified",
        )
        et = instant_in_et(ev)
        assert et is not None
        self.assertEqual(et.strftime("%Y-%m-%d %H:%M"), "2026-11-17 19:30")
        self.assertEqual(et.date().isoformat(), "2026-11-17")

    def test_dst_ny_utcoffset_oct_vs_nov(self) -> None:
        ev_oct = _ev(local_date=date(2026, 10, 15), local_time="08:30")
        ev_nov = _ev(local_date=date(2026, 11, 6), local_time="08:30")
        z_oct = instant_in_zone(ev_oct)
        z_nov = instant_in_zone(ev_nov)
        assert z_oct is not None and z_nov is not None
        # October: EDT (UTC-4); November: EST (UTC-5)
        self.assertEqual(z_oct.utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(z_nov.utcoffset().total_seconds(), -5 * 3600)

    def test_provisional_date_confidence_allowed(self) -> None:
        validate_event(_ev(date_confidence="provisional"))

    def test_unknown_date_confidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            validate_event(_ev(date_confidence="maybe"))

    def test_validate_source_plan_rejects_non_https(self) -> None:
        plan = (
            SourceDocument(key="k", url="http://bad.example/", description="d"),
        )
        with self.assertRaises(ValueError) as ctx:
            validate_source_plan(plan)
        self.assertIn("https://", str(ctx.exception))

    def test_events_to_slots_validates_and_maps(self) -> None:
        ev = _ev()
        slots = events_to_slots([ev])
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]["event_family"], "test_family")


if __name__ == "__main__":
    unittest.main()
