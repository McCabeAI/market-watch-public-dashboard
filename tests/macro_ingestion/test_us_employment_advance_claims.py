"""ETA 538 advance claims are distinct from ETA 539 revised history."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.macro_ingestion.us_employment.advance_claims import (
    expected_advance_week_ending,
    fetch_advance_claims_series,
    parse_advance_release_text,
)
from scripts.macro_ingestion.us_employment.cache import clear_employment_caches


def _oct1() -> bytes:
    return (
        "TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL "
        "8:30 A.M. (Eastern) Thursday, October 1, 2026 "
        "In the week ending September 26, the advance figure for seasonally adjusted initial claims was 197,000, "
        "a decrease of 1,000 from the previous week's revised level. "
        "The 4-week moving average was 200,000, a decrease of 2,500 from the previous week's revised average. "
        "The advance seasonally adjusted insured unemployment rate was 1.1 percent for the week ending September 19, "
        "unchanged from the previous week's unrevised rate. "
        "The advance number for seasonally adjusted insured unemployment during the week ending September 19 was 1,701,000. "
        "2. Most recent week used covered employment of 153,732,307 as denominator."
    ).encode()


def _sep17() -> bytes:
    return (
        "TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL "
        "8:30 A.M. (Eastern) Thursday, September 17, 2026 "
        "In the week ending September 12, the advance figure for seasonally adjusted initial claims was 196,000. "
        "The 4-week moving average was 203,250. "
        "The advance seasonally adjusted insured unemployment rate was 1.1 percent for the week ending September 5. "
        "The advance number for seasonally adjusted insured unemployment during the week ending September 5 was 1,730,000."
    ).encode()


def _sep3() -> bytes:
    return (
        "TRANSMISSION OF MATERIALS IN THIS RELEASE IS EMBARGOED UNTIL "
        "8:30 A.M. (Eastern) Thursday, September 3, 2026 "
        "In the week ending August 29, the advance figure for seasonally adjusted initial claims was 206,000. "
        "The 4-week moving average was 207,250. "
        "The advance seasonally adjusted insured unemployment rate was 1.2 percent for the week ending August 22. "
        "The advance number for seasonally adjusted insured unemployment during the week ending August 22 was 1,779,000."
    ).encode()


class TestAdvanceClaims(unittest.TestCase):
    def setUp(self) -> None:
        clear_employment_caches()

    def tearDown(self) -> None:
        clear_employment_caches()

    def test_expected_week_respects_thursday_embargo(self) -> None:
        self.assertEqual(
            expected_advance_week_ending(datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)).isoformat(),
            "2026-09-26",
        )
        self.assertEqual(
            expected_advance_week_ending(datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)).isoformat(),
            "2026-09-19",
        )
        self.assertEqual(
            expected_advance_week_ending(datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)).isoformat(),
            "2026-09-26",
        )

    def test_parser_keeps_only_the_advance_week(self) -> None:
        parsed = parse_advance_release_text(_oct1().decode(), source_url="https://example.test/100126.pdf", source_sha256="abc")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["release_date"], "2026-10-01")
        self.assertEqual(parsed["initial_claims_sa"], {"week_ending": "2026-09-26", "value": 197000.0})
        self.assertEqual(parsed["initial_claims_sa_4w"]["value"], 200000.0)
        self.assertEqual(parsed["continued_claims_sa"], {"week_ending": "2026-09-19", "value": 1701000.0})
        self.assertEqual(parsed["iur_sa"]["value"], 1.1)
        self.assertEqual(parsed["covered_employment"], 153732307.0)

    def test_cps_reference_week_keeps_the_pre_payroll_advance_vintage(self) -> None:
        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, content_type: str | None = None) -> dict:
            _ = timeout, data, content_type
            if url.rstrip("/").endswith("/press/2026"):
                body = b'<a href="091726.pdf"></a><a href="100126.pdf"></a>'
            elif url.endswith("100126.pdf"):
                body = _oct1()
            elif url.endswith("091726.pdf"):
                body = _sep17()
            elif url.endswith("/ui/data.pdf"):
                return {"ok": False, "url": url, "http_status": 403, "body": b"", "error": "HTTP 403"}
            else:
                return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "missing"}
            return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

        result = fetch_advance_claims_series(
            {"id": "US.Labor.initial_claims", "transform": "level"},
            opener=opener,
            timeout=5,
            now=datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(result["ok"], result.get("error"))
        by_period = {point["period"]: point for point in result["points"]}
        self.assertEqual(by_period["2026-09-26"]["value"], 197000)
        self.assertEqual(by_period["2026-09-26"]["revision_status"], "advance")
        reference = by_period["2026-09-12"]
        self.assertEqual(reference["value"], 196000)
        self.assertEqual(reference["vintage"], "2026-09-17")
        self.assertTrue(reference["derivation"]["cps_reference_week"])
        self.assertTrue(reference["derivation"]["available_before_payroll"])
        self.assertEqual(reference["derivation"]["payroll_release_bound"], "2026-10-02")
        self.assertEqual(reference["derivation"]["report"], "ETA 538")
        self.assertTrue(reference["derivation"]["not_eta_539"])
        self.assertTrue(all(point["revision_status"] == "advance" for point in result["points"]))

    def test_stale_official_advance_is_due_missing_without_revised_substitute(self) -> None:
        def opener(url: str, *, timeout: float = 20, data: bytes | None = None, content_type: str | None = None) -> dict:
            _ = timeout, data, content_type
            if url.rstrip("/").endswith("/press/2026"):
                body = b'<a href="090326.pdf">090326.pdf</a>'
            elif url.endswith("090326.pdf"):
                body = _sep3()
            elif url.endswith("/ui/data.pdf"):
                return {"ok": False, "url": url, "http_status": 403, "body": b"", "error": "HTTP 403"}
            else:
                return {"ok": False, "url": url, "http_status": 404, "body": b"", "error": "missing"}
            return {"ok": True, "url": url, "http_status": 200, "body": body, "error": None}

        result = fetch_advance_claims_series(
            {"id": "US.Labor.initial_claims", "transform": "level"},
            opener=opener,
            timeout=5,
            now=datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "due_missing")
        self.assertIn("expected_week_ending=2026-09-26", result["error"])
        self.assertIn("latest_official_week_ending=2026-08-29", result["error"])
        self.assertIn("source=eta_538", result["error"])
        self.assertNotIn("points", result)


if __name__ == "__main__":
    unittest.main()
