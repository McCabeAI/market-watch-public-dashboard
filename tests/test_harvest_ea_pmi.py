from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_ea_pmi import (  # noqa: E402
    choose_observations,
    discover_eurozone_composite_listing,
    infer_reference_period,
    is_flash_release,
    parse_headline_composite,
    press_release_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ea_macro"


class HarvestEaPmiTest(unittest.TestCase):
    def test_parse_august_2026_final_fixture(self) -> None:
        text = (FIXTURES / "pmi_august_2026_final.txt").read_text(encoding="utf-8")
        self.assertFalse(is_flash_release(text))
        self.assertEqual(infer_reference_period(text, is_flash=False), "2026-08")
        self.assertEqual(parse_headline_composite(text, "2026-08"), 52.0)

    def test_final_beats_flash_for_july(self) -> None:
        flash = (FIXTURES / "pmi_july_2026_flash.txt").read_text(encoding="utf-8")
        final = (FIXTURES / "pmi_july_2026_final.txt").read_text(encoding="utf-8")
        self.assertTrue(is_flash_release(flash))
        chosen = choose_observations(
            [
                {
                    "source_url": "https://example.test/july-flash",
                    "release_date": "2026-07-24",
                    "reference_period": "2026-07",
                    "composite_value": parse_headline_composite(flash, "2026-07"),
                    "is_flash": True,
                    "restated_priors": {},
                },
                {
                    "source_url": "https://example.test/july-final",
                    "release_date": "2026-09-03",
                    "reference_period": "2026-07",
                    "composite_value": parse_headline_composite(final, "2026-07"),
                    "is_flash": False,
                    "restated_priors": {},
                },
            ],
            retrieved_at="2026-09-21T12:00:00Z",
        )
        self.assertEqual(chosen["2026-07"]["value"], 52.0)
        self.assertEqual(chosen["2026-07"]["revision_status"], "final")

    def test_discover_exact_english_composite_title(self) -> None:
        html = """
        <span class="releaseDate">September 03 2026</span>
        <span class="releaseTitle">S&amp;P Global Eurozone Composite PMI (Français)</span>
        <span class="greenListItem"><a href="/Public/Home/PressRelease/aaa11111111111111111111111111111"></a></span>
        <span class="releaseDate">September 03 2026</span>
        <span class="releaseTitle">S&amp;P Global Eurozone Composite PMI</span>
        <span class="greenListItem"><a href="/Public/Home/PressRelease/bbb22222222222222222222222222222"></a></span>
        """
        rows = discover_eurozone_composite_listing(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["guid"], "bbb22222222222222222222222222222")
        self.assertEqual(rows[0]["source_url"], press_release_url(rows[0]["guid"]))

    def test_parse_real_august_2026_pdf_cache(self) -> None:
        from pypdf import PdfReader

        from scripts.harvest_ea_pmi import pdf_to_text

        pdf = ROOT / "data/temperature_history/raw/ea/sp_eurozone_composite_2026-08.pdf"
        self.assertTrue(pdf.is_file())
        text = pdf_to_text(pdf.read_bytes())
        self.assertEqual(infer_reference_period(text, is_flash=False), "2026-08")
        self.assertEqual(parse_headline_composite(text, "2026-08"), 52.0)


if __name__ == "__main__":
    unittest.main()
