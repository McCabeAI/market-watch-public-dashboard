"""Policy meeting calendar parsers and refresh behavior."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts.policy_calendar import (
    PARSERS,
    SOURCE_URLS,
    effective_date,
    merge_bank,
    next_decisions,
    parse_boc_calendar,
    parse_boj_calendar,
    parse_ecb_calendar,
    parse_fed_calendar,
    parse_rba_calendar,
    parse_rbnz_calendar,
    refresh_calendars,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "policy_calendar"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParserFixtureTest(unittest.TestCase):
    def test_fed_uses_last_day_and_skips_notation(self) -> None:
        decisions = parse_fed_calendar(_read("fed.html"))
        by_date = {item["decision_date"]: item for item in decisions}
        self.assertEqual(by_date["2026-01-28"]["meeting_start"], "2026-01-27")
        self.assertIn("2026-09-16", by_date)
        self.assertIn("2027-01-27", by_date)
        self.assertEqual(by_date["2025-05-01"]["meeting_start"], "2025-04-30")
        self.assertNotIn("2025-08-22", by_date)

    def test_boc_keeps_interest_rate_announcement_rows(self) -> None:
        decisions = parse_boc_calendar(_read("boc.html"))
        self.assertEqual(decisions[0]["decision_date"], "2026-01-28")
        self.assertEqual(len(decisions), 8)

    def test_rba_monetary_policy_column_only(self) -> None:
        decisions = parse_rba_calendar(_read("rba.html"))
        self.assertEqual(decisions[0]["decision_date"], "2026-02-03")
        self.assertEqual(decisions[0]["meeting_start"], "2026-02-02")
        self.assertNotIn("2026-03-05", {item["decision_date"] for item in decisions})

    def test_ecb_keeps_day_two_press_conferences(self) -> None:
        decisions = parse_ecb_calendar(_read("ecb.html"))
        dates = {item["decision_date"] for item in decisions}
        self.assertIn("2026-12-17", dates)
        self.assertNotIn("2026-12-16", dates)
        self.assertNotIn("2026-11-25", dates)

    def test_boj_uses_last_mpm_day_not_minutes_column(self) -> None:
        decisions = parse_boj_calendar(_read("boj.html"))
        last = decisions[-1]
        self.assertEqual(last["decision_date"], "2026-12-18")
        self.assertEqual(last["meeting_start"], "2026-12-17")
        jan = next(item for item in decisions if item["meeting_start"] == "2026-01-22")
        self.assertEqual(jan["decision_date"], "2026-01-23")
        unpunctuated = parse_boj_calendar(
            '<h2 id="p2027">2027</h2><div class="tbl-box"><table><tr><td>June 10 (Thurs.), 11 (Fri.)</td>'
            "<td>June 21 (Mon.)</td></tr></table></div>"
        )
        self.assertEqual(unpunctuated[0]["decision_date"], "2027-06-11")
        self.assertEqual(unpunctuated[0]["meeting_start"], "2027-06-10")

    def test_rbnz_empty_without_ocr_dates(self) -> None:
        self.assertEqual(parse_rbnz_calendar(_read("rbnz_empty.html")), [])

    def test_rbnz_ocr_fixture(self) -> None:
        decisions = parse_rbnz_calendar(_read("rbnz_ocr.html"))
        self.assertEqual([item["decision_date"] for item in decisions], ["2026-01-28", "2026-04-09"])


class CalendarLogicTest(unittest.TestCase):
    def test_effective_dates(self) -> None:
        self.assertEqual(effective_date("US", "2026-09-16"), "2026-09-17")
        self.assertEqual(effective_date("CA", "2026-03-18"), "2026-03-19")
        self.assertEqual(effective_date("EA", "2026-12-17"), "2026-12-23")
        self.assertEqual(effective_date("US", "2026-09-18"), "2026-09-21")

    def test_next_five_upcoming(self) -> None:
        parsed = PARSERS["US"](_read("fed.html"))
        decisions = merge_bank(
            "US",
            parsed,
            source_url=SOURCE_URLS["US"],
            as_of=date(2026, 6, 1),
        )
        calendar = {"banks": {"US": {"decisions": decisions}}}
        upcoming = next_decisions(calendar, "US", date(2026, 6, 1), n=5)
        self.assertEqual(len(upcoming), 5)
        self.assertEqual(upcoming[0]["decision_date"], "2026-06-17")
        self.assertTrue(all(date.fromisoformat(item["decision_date"]) > date(2026, 6, 1) for item in upcoming))

    def test_failed_nz_fetch_keeps_prior_schedule_and_us_updates(self) -> None:
        previous = {
            "schema_version": 1,
            "banks": {
                "NZ": {
                    "timezone": "Pacific/Auckland",
                    "source_url": SOURCE_URLS["NZ"],
                    "status": "verified",
                    "retrieved_at": "2026-05-01T00:00:00Z",
                    "last_attempt_at": "2026-05-01T00:00:00Z",
                    "last_error": None,
                    "decisions": [
                        {
                            "decision_date": "2026-07-08",
                            "meeting_start": None,
                            "local_time": "14:00",
                            "effective_date": "2026-07-09",
                            "source_url": SOURCE_URLS["NZ"],
                            "state": "upcoming",
                        }
                    ],
                }
            },
            "revisions": [],
        }

        def fetch(url: str) -> str:
            if url == SOURCE_URLS["US"]:
                return _read("fed.html")
            if url == SOURCE_URLS["NZ"]:
                raise OSError("HTTP 403")
            if url == SOURCE_URLS["CA"]:
                return _read("boc.html")
            if url == SOURCE_URLS["AU"]:
                return _read("rba.html")
            if url == SOURCE_URLS["EA"]:
                return _read("ecb.html")
            if url == SOURCE_URLS["JP"]:
                return _read("boj.html")
            raise AssertionError(url)

        updated = refresh_calendars(fetch, previous, NOW)
        self.assertEqual(updated["banks"]["US"]["status"], "verified")
        self.assertGreater(len(updated["banks"]["US"]["decisions"]), 0)
        nz = updated["banks"]["NZ"]
        self.assertEqual(nz["status"], "verified")
        self.assertEqual(nz["decisions"][0]["decision_date"], "2026-07-08")
        self.assertIn("403", nz["last_error"] or "")


if __name__ == "__main__":
    unittest.main()
