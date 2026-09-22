#!/usr/bin/env python3
from __future__ import annotations

import unittest

from scripts.apply_overnight_news_refresh import apply_overnight_news_refresh


BASE_HTML = """
<div class="last24"><div>OLD LAST24</div></div>
<div class="stitle">Top Market Drivers</div><div>OLD ROLLUP</div>
<div class="x-signal"><div>X</div></div>
"""


def _dataset() -> dict:
    return {
        "type": "OVERNIGHT_MORNING_DATASET",
        "overnight_run_id": "overnight-20260922",
        "as_of": "2026-09-22T07:34:20-04:00",
        "agent_research_cutoff": "2026-09-22T06:52:19-04:00",
        "agent_research": {
            "summary": "Energy rebounded while fresh U.S. activity data remained mixed.",
            "news": [
                {
                    "country_codes": ["US", "CA"],
                    "headline": "Oil rebounds in early trade",
                    "primary_category": "energy",
                    "published_at": "2026-09-22T04:22:00-04:00",
                    "source_name": "Example Wire",
                    "summary": "Brent and WTI rebounded as supply risks stayed in focus.",
                    "url": "https://example.com/oil",
                },
                {
                    "country_codes": ["US"],
                    "headline": "Activity index softens",
                    "primary_category": "activity",
                    "published_at": "2026-09-21T08:30:00-04:00",
                    "source_name": "Official Source",
                    "summary": "The activity index eased in August.",
                    "url": "https://example.com/activity",
                },
            ],
            "central_bank_research": [
                {
                    "country_codes": ["JP"],
                    "headline": "BoJ decision remains in the seven-day window",
                    "institution": "BoJ",
                    "published_at": "2026-09-18T00:00:00+09:00",
                    "source_name": "Bank of Japan",
                    "summary": "The Bank of Japan raised its policy rate.",
                    "url": "https://example.com/boj",
                }
            ],
        },
    }


class OvernightNewsRefreshTests(unittest.TestCase):
    def test_replaces_static_sep18_news_with_accepted_packet(self) -> None:
        out = apply_overnight_news_refresh(BASE_HTML, _dataset())
        self.assertIn("Last refreshed 22 Sep 2026 · 06:52 ET", out)
        self.assertIn("Oil rebounds in early trade", out)
        self.assertIn("Activity index softens", out)
        self.assertIn("BoJ decision remains in the seven-day window", out)
        self.assertNotIn("OLD LAST24", out)
        self.assertNotIn("OLD ROLLUP", out)
        self.assertEqual(out.count('class="driver-card"'), 3)
        self.assertEqual(out.count('class="story"'), 3)

    def test_requires_accepted_research_items(self) -> None:
        dataset = _dataset()
        dataset["agent_research"] = {"news": [], "central_bank_research": [], "summary": ""}
        with self.assertRaises(ValueError):
            apply_overnight_news_refresh(BASE_HTML, dataset)


if __name__ == "__main__":
    unittest.main()
