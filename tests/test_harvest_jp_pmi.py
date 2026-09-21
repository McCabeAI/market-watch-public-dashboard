from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.harvest_jp_pmi import (  # noqa: E402
    choose_observations,
    discover_japan_listing,
    infer_reference_period,
    is_flash_release,
    is_services_final_release,
    parse_flash_composite,
    parse_headline_composite,
    parse_services_final_composite,
    press_release_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "jp_macro"


class HarvestJpPmiTest(unittest.TestCase):
    def test_parse_march_2026_flash_fixture(self) -> None:
        text = (FIXTURES / "sp_japan_flash_composite_2026-03.txt").read_text(encoding="utf-8")
        self.assertTrue(is_flash_release(text))
        self.assertEqual(infer_reference_period(text, is_flash=True), "2026-03")
        self.assertEqual(parse_flash_composite(text), 52.5)

    def test_parse_august_2026_services_final_fixture(self) -> None:
        text = (FIXTURES / "sp_japan_composite_2026-08.txt").read_text(encoding="utf-8")
        self.assertTrue(is_services_final_release(text))
        ref, val, priors = parse_services_final_composite(text)
        self.assertEqual(ref, "2026-08")
        self.assertEqual(val, 53.5)
        self.assertEqual(priors.get("2026-07"), 52.7)

    def test_final_beats_flash_for_same_month(self) -> None:
        flash_text = (
            "Comment March 2026\n"
            "Flash Japan Composite PMI Output Index: 52.4 (February: 53.0)\n"
        )
        final_text = (
            "Comment March 2026\n"
            "Composite Output Index rose from 52.4 in February to 52.6 in March, signalling growth.\n"
        )
        chosen = choose_observations(
            [
                {
                    "source_url": "https://example.test/flash",
                    "release_date": "2026-03-24",
                    "reference_period": "2026-03",
                    "composite_value": parse_headline_composite(
                        flash_text, "2026-03", is_flash=True, is_services_final=False
                    ),
                    "is_flash": True,
                    "is_services_final": False,
                    "restated_priors": {},
                },
                {
                    "source_url": "https://example.test/final",
                    "release_date": "2026-04-03",
                    "reference_period": "2026-03",
                    "composite_value": parse_headline_composite(
                        final_text, "2026-03", is_flash=False, is_services_final=True
                    ),
                    "is_flash": False,
                    "is_services_final": True,
                    "restated_priors": {},
                },
            ],
            retrieved_at="2026-09-21T12:00:00Z",
        )
        self.assertEqual(chosen["2026-03"]["value"], 52.6)
        self.assertEqual(chosen["2026-03"]["revision_status"], "final")

    def test_discover_japan_services_listing(self) -> None:
        html = """
        <span class="releaseDate">September 03 2026</span>
        <span class="releaseTitle">S&amp;P Global Japan Manufacturing PMI</span>
        <span class="greenListItem"><a href="/Public/Home/PressRelease/aaa11111111111111111111111111111"></a></span>
        <span class="releaseDate">September 03 2026</span>
        <span class="releaseTitle">S&amp;P Global Japan Services PMI</span>
        <span class="greenListItem"><a href="/Public/Home/PressRelease/bbb22222222222222222222222222222"></a></span>
        """
        rows = discover_japan_listing(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["guid"], "bbb22222222222222222222222222222")
        self.assertEqual(rows[0]["source_url"], press_release_url(rows[0]["guid"]))


if __name__ == "__main__":
    unittest.main()
