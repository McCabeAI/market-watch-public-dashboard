from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_ca_pmi import (  # noqa: E402
    discover_canada_services_listing,
    parse_composite_output_index,
    parse_embargo_release_date,
    parse_headline_reference_period,
    pdf_to_text,
    press_release_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ca_pmi"


class HarvestCaPmiTest(unittest.TestCase):
    def test_parse_composite_june_2026_fixture(self) -> None:
        text = (FIXTURES / "june_2026_composite.txt").read_text(encoding="utf-8")
        self.assertEqual(parse_headline_reference_period(text), "2026-06")
        self.assertEqual(parse_embargo_release_date(text), "2026-07-06")
        self.assertEqual(parse_composite_output_index(text), 47.9)

    def test_parse_composite_july_2026_fixture(self) -> None:
        text = (FIXTURES / "july_2026_composite.txt").read_text(encoding="utf-8")
        self.assertEqual(parse_headline_reference_period(text), "2026-07")
        self.assertEqual(parse_embargo_release_date(text), "2026-08-06")
        self.assertEqual(parse_composite_output_index(text), 49.7)

    def test_parse_composite_august_2026_fixture(self) -> None:
        text = (FIXTURES / "august_2026_composite.txt").read_text(encoding="utf-8")
        self.assertEqual(parse_headline_reference_period(text), "2026-08")
        self.assertEqual(parse_embargo_release_date(text), "2026-09-03")
        self.assertEqual(parse_composite_output_index(text), 47.8)

    def test_discover_canada_services_from_listing_fixture(self) -> None:
        html = (FIXTURES / "listing_snippet.html").read_text(encoding="utf-8")
        rows = discover_canada_services_listing(html)
        guids = {r["guid"] for r in rows}
        self.assertIn("8b925a72bf154a35becc7364eb6e7e58", guids)
        self.assertIn("b28d51a7ae54422e9e991e6ea2b06643", guids)
        self.assertTrue(all(r["source_url"] == press_release_url(r["guid"]) for r in rows))

    def test_parse_headline_from_data_collected_without_hash_header(self) -> None:
        text = (
            "Embargoed until 0930 EDT 6 July 2026 / 1330 UTC 6 July 2026\n"
            "Data were collected 11-25 June 2026.\n"
            "June 2026\n"
            "The S&P Global Canada Composite PMI recorded 47.9 in June.\n"
        )
        self.assertEqual(parse_headline_reference_period(text), "2026-06")
        self.assertEqual(parse_composite_output_index(text), 47.9)

    def test_parse_real_june_july_august_pdfs(self) -> None:
        raw = ROOT / "data" / "temperature_history" / "raw" / "ca"
        expected = {
            "2026-06": 47.9,
            "2026-07": 49.7,
            "2026-08": 47.8,
        }
        for period, value in expected.items():
            data = (raw / f"sp_canada_composite_{period}.pdf").read_bytes()
            self.assertEqual(data[:4], b"%PDF")
            text = pdf_to_text(data)
            self.assertEqual(parse_headline_reference_period(text), period)
            self.assertEqual(parse_composite_output_index(text), value)

    def test_local_cache_recovers_august_when_live_fetch_returns_202(self) -> None:
        from scripts.harvest_ca_pmi import fetch_release_bytes, local_cached_pdf

        guid = "8b925a72bf154a35becc7364eb6e7e58"
        cached = local_cached_pdf(guid)
        self.assertIsNotNone(cached)
        self.assertEqual(cached[:4], b"%PDF")
        attempted: list[dict] = []

        def boom(_url, **kwargs):  # noqa: ANN001, ARG001
            raise RuntimeError("HTTP 202 from PressRelease")

        with patch(
            "scripts.harvest_ca_pmi._curl_cffi_get",
            return_value=(202, b"<html/>", "challenge"),
        ):
            data = fetch_release_bytes(
                press_release_url(guid),
                guid=guid,
                fetcher=boom,
                attempted=attempted,
            )
        self.assertIsNotNone(data)
        self.assertEqual(data[:4], b"%PDF")
        self.assertEqual(parse_composite_output_index(pdf_to_text(data)), 47.8)
        self.assertTrue(any("local_cache" in str(row.get("notes")) for row in attempted))


if __name__ == "__main__":
    unittest.main()
