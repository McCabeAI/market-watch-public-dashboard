from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_au_pmi import (  # noqa: E402
    choose_observations,
    is_flash_release,
    parse_headline_composite,
    parse_restated_priors,
)

FIXTURES = Path(__file__).parent / "fixtures" / "au_pmi"


class HarvestAuPmiTest(unittest.TestCase):
    def test_parse_april_2026_final_composite_from_fixture(self) -> None:
        text = (FIXTURES / "april_2026_final_excerpt.txt").read_text(encoding="utf-8")
        self.assertFalse(is_flash_release(text))
        self.assertEqual(parse_headline_composite(text, "2026-04"), 50.4)

    def test_july_2026_flash_labeled_preliminary_in_choose_observations(self) -> None:
        text = (FIXTURES / "july_2026_flash_excerpt.txt").read_text(encoding="utf-8")
        self.assertTrue(is_flash_release(text))
        headline = parse_headline_composite(text, "2026-07")
        self.assertEqual(headline, 52.6)
        priors = parse_restated_priors(text, headline_period="2026-07")
        self.assertEqual(priors.get("2026-06"), 50.4)
        chosen = choose_observations(
            [
                {
                    "source_url": "https://example.test/july-flash",
                    "release_date": "2026-07-24",
                    "reference_period": "2026-07",
                    "composite_value": headline,
                    "is_flash": True,
                    "restated_priors": priors,
                }
            ],
            retrieved_at="2026-09-21T12:00:00Z",
        )
        self.assertEqual(chosen["2026-07"]["revision_status"], "preliminary")
        self.assertEqual(chosen["2026-06"]["revision_status"], "revised")

    def test_october_2025_final_restates_september_prior(self) -> None:
        text = (FIXTURES / "october_2025_final_excerpt.txt").read_text(encoding="utf-8")
        priors = parse_restated_priors(text, headline_period="2025-10")
        self.assertEqual(priors.get("2025-09"), 52.4)
        self.assertEqual(parse_headline_composite(text, "2025-10"), 52.1)

    def test_final_beats_flash_for_same_month(self) -> None:
        chosen = choose_observations(
            [
                {
                    "source_url": "https://example.test/april-flash",
                    "release_date": "2026-04-23",
                    "reference_period": "2026-04",
                    "composite_value": 50.1,
                    "is_flash": True,
                    "restated_priors": {},
                },
                {
                    "source_url": "https://example.test/april-final",
                    "release_date": "2026-05-05",
                    "reference_period": "2026-04",
                    "composite_value": 50.4,
                    "is_flash": False,
                    "restated_priors": {},
                },
            ],
            retrieved_at="2026-09-21T12:00:00Z",
        )
        self.assertEqual(chosen["2026-04"]["value"], 50.4)
        self.assertEqual(chosen["2026-04"]["revision_status"], "final")

    def test_parse_real_april_and_august_final_pdfs(self) -> None:
        from pypdf import PdfReader

        raw = ROOT / "data" / "temperature_history" / "raw" / "au"
        april = "\n".join(
            (page.extract_text() or "")
            for page in PdfReader(str(raw / "sp_australia_composite_2026-04.pdf")).pages
        )
        august = "\n".join(
            (page.extract_text() or "")
            for page in PdfReader(str(raw / "sp_australia_composite_2026-08.pdf")).pages
        )
        self.assertEqual(parse_headline_composite(april, "2026-04"), 50.4)
        self.assertEqual(parse_headline_composite(august, "2026-08"), 52.7)
        priors = parse_restated_priors(august, headline_period="2026-08")
        self.assertEqual(priors.get("2026-07"), 53.2)


if __name__ == "__main__":
    unittest.main()
