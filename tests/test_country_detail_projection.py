from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from scripts.country_detail import policy

try:
    from scripts.country_detail.projection import build_projection
except ImportError:  # pragma: no cover
    build_projection = None

PROJECTION_SOURCE = Path("scripts/country_detail/projection.py")
TEMP_SCORES = Path("data/temperature_scores.json")
AU_HISTORY = Path("data/temperature_history/au.json")
FIXTURE_MHSI_TTY_NOT_AN_ABS_ID = "FIXTURE_MHSI_TTY_NOT_AN_ABS_ID"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CountryDetailProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        if build_projection is None:
            self.skipTest("scripts.country_detail.projection is not importable")

    def test_projection_source_has_no_trader_imports(self) -> None:
        if not PROJECTION_SOURCE.is_file():
            self.skipTest("projection.py not present yet")
        source = PROJECTION_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("scripts.trader_room", source)
        self.assertNotIn("scripts.trading", source)
        self.assertNotIn("scripts.pm", source)

    def test_builds_for_all_six_countries(self) -> None:
        projection = build_projection()
        self.assertIn("countries", projection)
        for code in policy.COUNTRY_CODES:
            country_projection = projection["countries"][code]
            self.assertIsInstance(country_projection, dict)
            self.assertIn("observations", country_projection)

    def test_build_projection_does_not_mutate_temperature_files(self) -> None:
        before_scores = file_sha256(TEMP_SCORES)
        before_au = file_sha256(AU_HISTORY)
        build_projection()
        self.assertEqual(file_sha256(TEMP_SCORES), before_scores)
        self.assertEqual(file_sha256(AU_HISTORY), before_au)

    def test_au_household_spending_identity_rules(self) -> None:
        projection = build_projection()
        observations = projection["countries"]["AU"].get("observations") or []
        monthly = [
            row
            for row in observations
            if row.get("series_id") == policy.AU_HOUSEHOLD_SPENDING_MONTHLY["series_id"]
            and row.get("transformation") == "mom_pct"
        ]
        annual = [row for row in observations if row.get("transformation") == "yoy_pct"]
        if monthly:
            self.assertTrue(monthly)
        if annual:
            for row in annual:
                self.assertNotEqual(row.get("series_id"), FIXTURE_MHSI_TTY_NOT_AN_ABS_ID)
                self.assertEqual(row.get("transformation"), "yoy_pct")
            if monthly:
                self.assertNotEqual(monthly[0].get("observation_id"), annual[0].get("observation_id"))
        else:
            placeholder = next(
                (row for row in observations if row.get("transformation") == "yoy_pct"),
                None,
            )
            if placeholder is None:
                missing_annual = [
                    row
                    for row in observations
                    if row.get("limitation") or row.get("data_state") == "missing"
                ]
                if missing_annual:
                    row = missing_annual[0]
                    self.assertEqual(row.get("data_state"), "missing")
                    self.assertIsNone(row.get("value"))

    def test_ca_alberta_oil_monthly_vs_calendar_day_rate(self) -> None:
        projection = build_projection()
        observations = projection["countries"]["CA"].get("observations") or []
        aer_rows = [
            row
            for row in observations
            if row.get("geography") == policy.GEOGRAPHY_ALBERTA
            and "AER" in str(row.get("series_id", ""))
        ]
        if not aer_rows:
            self.skipTest("no Alberta AER rows in projection yet")
        by_series: dict[str, list[dict]] = {}
        for row in aer_rows:
            by_series.setdefault(row["series_id"], []).append(row)
        for series_id, rows in by_series.items():
            transforms = {row.get("transformation") for row in rows}
            if "monthly_level" in transforms and "calendar_day_rate" in transforms:
                monthly = next(r for r in rows if r["transformation"] == "monthly_level")
                daily = next(r for r in rows if r["transformation"] == "calendar_day_rate")
                self.assertNotEqual(monthly.get("observation_id"), daily.get("observation_id"))
                self.assertFalse(daily.get("seasonal_adjustment"))
                label_blob = " ".join(
                    str(daily.get(field, ""))
                    for field in ("label", "units", "display_label", "headline_text")
                ).lower()
                self.assertNotIn("seasonally adjusted", label_blob)


if __name__ == "__main__":
    unittest.main()
