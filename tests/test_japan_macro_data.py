from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.japan_macro_data import (  # noqa: E402
    SeriesUnavailableError,
    parse_consumer_confidence_xlsx,
    parse_cpi_yoy_csv,
    parse_esri_real_gdp_qoq_saar_csv,
    parse_esri_shouhi2_consumer_confidence_xlsx,
    parse_mhlw_cash_earnings_yoy_xls,
)

FIXTURES = Path(__file__).parent / "fixtures" / "jp_macro"


class JapanMacroParserTest(unittest.TestCase):
    def test_parse_cpi_yoy_fixture(self) -> None:
        text = (FIXTURES / "cpi_yoy_snippet.csv").read_text(encoding="cp932", errors="replace")
        headline, underlying = parse_cpi_yoy_csv(text)
        self.assertTrue(headline)
        self.assertTrue(underlying)
        periods = {o["reference_period"] for o in headline}
        self.assertIn("2026-08", periods)

    def test_parse_gdp_saar_fixture(self) -> None:
        text = (FIXTURES / "gdp_nritu_snippet.csv").read_text(encoding="cp932", errors="replace")
        rows = parse_esri_real_gdp_qoq_saar_csv(text)
        self.assertTrue(any(r["reference_period"] == "2026-Q2" for r in rows))

    def test_cpi_empty_raises_unavailable(self) -> None:
        with self.assertRaises(SeriesUnavailableError):
            parse_cpi_yoy_csv("a,b\n")

    def test_mhlw_wages_yoy_only_from_raw_xls(self) -> None:
        raw = ROOT / "data/temperature_history/raw/jp/estat_mhlw_total_cash_earnings_yoy.xls"
        self.assertTrue(raw.is_file())
        obs = parse_mhlw_cash_earnings_yoy_xls(raw.read_bytes())
        periods = [o["reference_period"] for o in obs]
        self.assertEqual(len(periods), len(set(periods)))
        for o in obs:
            self.assertGreaterEqual(o["value"], -10.0)
            self.assertLessEqual(o["value"], 20.0)
        by_period = {o["reference_period"]: o["value"] for o in obs}
        if "2026-06" in by_period:
            self.assertAlmostEqual(by_period["2026-06"], 4.0)
        self.assertNotIn(93.5, {o["value"] for o in obs})
        self.assertNotIn(198.6, {o["value"] for o in obs})

    def test_consumer_confidence_esri_shouhi2_through_august_2026(self) -> None:
        raw = ROOT / "data/temperature_history/raw/jp/esri_shouhi2_sa.xlsx"
        self.assertTrue(raw.is_file())
        obs = parse_esri_shouhi2_consumer_confidence_xlsx(raw.read_bytes())
        periods = {o["reference_period"] for o in obs}
        latest = max(periods)
        self.assertGreaterEqual(latest, "2026-08")
        by_period = {o["reference_period"]: o["value"] for o in obs}
        self.assertAlmostEqual(by_period["2026-08"], 35.5)

    def test_cci_current_methodology_era_mean_is_38_1(self) -> None:
        """Canonical LEVEL anchor from official Table 2 SA CCI, April 2013 onward."""
        import json

        raw = ROOT / "data/temperature_history/raw/jp/esri_shouhi2_sa.xlsx"
        obs = parse_esri_shouhi2_consumer_confidence_xlsx(
            raw.read_bytes(),
            restrict_to_score_window=False,
        )
        window = [o for o in obs if o["reference_period"] >= "2013-04"]
        periods = [o["reference_period"] for o in window]
        self.assertEqual(periods[0], "2013-04")
        self.assertEqual(periods[-1], "2026-08")
        self.assertEqual(len(periods), len(set(periods)))
        self.assertEqual(len(window), 161)
        mean = sum(float(o["value"]) for o in window) / len(window)
        self.assertAlmostEqual(mean, 38.10310559, places=6)
        self.assertAlmostEqual(round(mean, 1), 38.1)
        cal = json.loads((ROOT / "data" / "temperature_calibration.json").read_text())
        self.assertAlmostEqual(cal["components"]["JP.Consumer.confidence"]["anchor"], 38.1)

    def test_consumer_confidence_estat_fallback_parser(self) -> None:
        raw = ROOT / "data/temperature_history/raw/jp/estat_consumer_confidence_longterm.xlsx"
        self.assertTrue(raw.is_file())
        obs = parse_consumer_confidence_xlsx(raw.read_bytes())
        periods = {o["reference_period"] for o in obs}
        self.assertIn("2026-04", periods)


if __name__ == "__main__":
    unittest.main()
