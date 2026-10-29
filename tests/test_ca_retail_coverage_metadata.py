"""CA Consumer retail coverage must follow the observations actually stored."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "temperature_history" / "ca.json"


def _month_index(period: str) -> int:
    year, month = period.split("-")
    return int(year) * 12 + int(month)


def _months_inclusive(start: str, end: str) -> int:
    return _month_index(end) - _month_index(start) + 1


class CaRetailCoverageMetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = json.loads(HISTORY.read_text(encoding="utf-8"))
        cls.retail = payload["components"]["Consumer.retail"]

    def test_july_and_august_are_observed_and_september_stays_a_gap(self) -> None:
        rows = {row["reference_period"]: row for row in self.retail["observations"]}
        self.assertIn("2026-07", rows)
        self.assertIn("2026-08", rows)
        self.assertNotIn("2026-09", rows)
        self.assertAlmostEqual(rows["2026-07"]["value"], -0.8148385765720634)
        self.assertAlmostEqual(rows["2026-08"]["value"], 1.1980293951844967)
        self.assertEqual(rows["2026-08"]["release_date"], "2026-10-23")
        self.assertNotIn("release_date", rows["2026-07"])

        gap_periods = [gap["expected_period"] for gap in self.retail["gaps"]]
        self.assertNotIn("2026-07", gap_periods)
        self.assertNotIn("2026-08", gap_periods)
        self.assertEqual(gap_periods, ["2026-09"])
        september = self.retail["gaps"][0]
        self.assertEqual(september["reason"], "not yet released")
        self.assertEqual(september["as_of"], "2026-09-21")
        self.assertEqual(
            september["attempted_sources"],
            ["https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601"],
        )

    def test_coverage_is_the_recorded_window_through_august(self) -> None:
        periods = [row["reference_period"] for row in self.retail["observations"]]
        latest = max(periods)
        start = min(periods)
        lookback = {
            row["reference_period"]
            for row in self.retail["observations"]
            if row.get("calibration_lookback")
        }
        expected = _months_inclusive(start, latest)
        observed = expected - len(lookback)
        coverage = self.retail["coverage"]
        august = next(row for row in self.retail["observations"] if row["reference_period"] == latest)

        self.assertEqual(latest, "2026-08")
        self.assertEqual(coverage["latest_reference_period"], latest)
        self.assertEqual(coverage["latest_release_date"], august["release_date"])
        self.assertEqual(coverage["expected_periods_in_window"], expected)
        self.assertEqual(coverage["observed_periods_in_window"], observed)
        self.assertEqual(coverage["gap_count"], len(self.retail["gaps"]))
        self.assertEqual(coverage["status"], "ok")
        self.assertEqual(expected, 12)
        self.assertEqual(observed, 11)
        self.assertEqual(coverage["gap_count"], 1)


if __name__ == "__main__":
    unittest.main()
