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

    def test_consumer_confidence_from_live_raw(self) -> None:
        raw = ROOT / "data/temperature_history/raw/jp/estat_consumer_confidence_longterm.xlsx"
        self.assertTrue(raw.is_file())
        obs = parse_consumer_confidence_xlsx(raw.read_bytes())
        periods = {o["reference_period"] for o in obs}
        self.assertIn("2026-04", periods)


if __name__ == "__main__":
    unittest.main()
