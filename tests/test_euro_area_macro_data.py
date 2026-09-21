from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.euro_area_macro_data import (  # noqa: E402
    SeriesUnavailableError,
    employment_qq_change_thousands,
    parse_ecb_csvdata,
    parse_eurostat_sdmx_json,
    parse_eurostat_statistics_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ea_macro"


class EuroAreaMacroParserTest(unittest.TestCase):
    def test_parse_hicp_headline_fixture(self) -> None:
        payload = json.loads((FIXTURES / "hicp_headline_snippet.json").read_text(encoding="utf-8"))
        rows = parse_eurostat_statistics_json(payload)
        self.assertEqual(rows, [("2025-09", 2.2), ("2025-10", 2.1), ("2025-11", 2.1), ("2025-12", 2.0)])

    def test_parse_hicp_underlying_fixture(self) -> None:
        payload = json.loads((FIXTURES / "hicp_underlying_snippet.json").read_text(encoding="utf-8"))
        rows = parse_eurostat_statistics_json(payload)
        self.assertEqual(rows[-1], ("2025-12", 2.3))

    def test_parse_unemployment_sdmx_fixture(self) -> None:
        payload = json.loads((FIXTURES / "unemployment_sdmx_snippet.json").read_text(encoding="utf-8"))
        rows = parse_eurostat_sdmx_json(payload)
        self.assertEqual(rows[0], ("2025-09", 6.3))

    def test_parse_gdp_qq_fixture(self) -> None:
        payload = json.loads((FIXTURES / "gdp_qq_snippet.json").read_text(encoding="utf-8"))
        rows = parse_eurostat_sdmx_json(payload)
        self.assertEqual(rows[1], ("2025-Q2", 0.0))

    def test_parse_ecb_wages_fixture(self) -> None:
        text = (FIXTURES / "ecb_wages_snippet.csv").read_text(encoding="utf-8")
        rows = parse_ecb_csvdata(text, series_key="INW.Q.I10.N.INWR.000000.4F0.GY.IX")
        self.assertEqual(rows[-1], ("2026-Q1", 2.56))

    def test_employment_qq_thousands_derivation(self) -> None:
        levels = [("2025-Q3", 164700.0), ("2025-Q4", 165181.0), ("2026-Q1", 165305.0)]
        changes = employment_qq_change_thousands(levels)
        self.assertEqual(changes[0], ("2025-Q4", 481.0))
        self.assertEqual(changes[1], ("2026-Q1", 124.0))

    def test_missing_series_raises(self) -> None:
        payload = json.loads((FIXTURES / "eurostat_empty.json").read_text(encoding="utf-8"))
        with self.assertRaises(SeriesUnavailableError):
            parse_eurostat_statistics_json(payload)

    def test_collect_macro_strict_raises_on_missing(self) -> None:
        from scripts.euro_area_macro_data import collect_macro

        def boom(*_args, **_kwargs):  # noqa: ANN001
            raise SeriesUnavailableError("TEST_SERIES", "network blocked")

        with patch("scripts.euro_area_macro_data.fetch_eurostat_stats", side_effect=boom):
            with self.assertRaises(SeriesUnavailableError):
                collect_macro(strict=True)


if __name__ == "__main__":
    unittest.main()
