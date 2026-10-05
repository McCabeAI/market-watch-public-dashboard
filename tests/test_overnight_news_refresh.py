#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.apply_overnight_news_refresh import apply_overnight_news_refresh, main
from scripts.overnight.constants import ROOT


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


OCT5_DATASET = ROOT / "data/overnight/runs/overnight-20261005/assembled_dataset.json"


def _oct5_dataset() -> dict:
    return json.loads(OCT5_DATASET.read_text(encoding="utf-8"))


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

    def test_oct5_urlless_news_is_not_discarded(self) -> None:
        dataset = _oct5_dataset()
        news = dataset["agent_research"]["news"]
        central = dataset["agent_research"]["central_bank_research"]
        self.assertGreaterEqual(len(news), 12)
        self.assertTrue(all(not str(item.get("url") or "").strip() for item in news))
        self.assertTrue(all(item.get("title") and not item.get("headline") for item in central))

        out = apply_overnight_news_refresh(BASE_HTML, dataset)

        self.assertIn("Last refreshed 5 Oct 2026 · 06:08 ET", out)
        self.assertIn("Global Oil Supply Buffer", out)
        self.assertIn("Euro-Zone Inflation Tops Estimates", out)
        self.assertIn("scarily thin", out.lower())
        # 2026-09-28T05:56 is just outside the 7-day window ending 2026-10-05T06:08.
        self.assertNotIn("Man Group Says", out)
        self.assertNotIn("href=", out)
        self.assertNotIn("<a ", out)
        self.assertIn('<div class="last24-item">', out)
        self.assertIn('<div class="driver-card">', out)
        self.assertNotIn('class="story-source"', out)
        # Undated title-only central-bank notes stay out of the current windows.
        self.assertNotIn("SOMA Manager Perli", out)
        self.assertNotIn("discount window modernization", out)
        last24, _, rest = out.partition('<div class="stitle">Top Market Drivers</div>')
        self.assertIn("Global Oil Supply Buffer", last24)
        self.assertNotIn("Euro-Zone Inflation", last24)
        self.assertIn("Euro-Zone Inflation", rest)
        self.assertEqual(out.count('class="driver-card"'), 3)
        self.assertGreaterEqual(out.count('class="story"'), 1)
        self.assertLessEqual(out.count('class="story"'), 12)

    def test_oct5_title_central_bank_is_accepted_and_urls_stay_clickable(self) -> None:
        dataset = _oct5_dataset()
        research = deepcopy(dataset["agent_research"])
        research["news"] = list(research["news"]) + [
            {
                "headline": "Linked desk wire confirms the clickable path",
                "published_at": "2026-10-04T12:00:00-04:00",
                "summary": "URL-bearing items stay clickable.",
                "url": "https://example.com/oct5-linked",
                "source_name": "Example Wire",
                "country_codes": ["US"],
                "primary_category": "rates",
            }
        ]
        research["central_bank_research"] = list(research["central_bank_research"]) + [
            {
                "title": "Fed reserve-conditions note inside the rolling window",
                "summary": "Recent central-bank remarks stay in the digest when they carry a timestamp.",
                "published_at": "2026-10-03T09:30:00-04:00",
                "institution": "Federal Reserve",
                "source_name": "Federal Reserve",
                "country_codes": ["US"],
            }
        ]
        dataset = dict(dataset)
        dataset["agent_research"] = research

        out = apply_overnight_news_refresh(BASE_HTML, dataset)

        self.assertIn("Fed reserve-conditions note inside the rolling window", out)
        self.assertIn(
            '<a class="last24-item" href="https://example.com/oct5-linked" target="_blank" rel="noopener">',
            out,
        )
        self.assertIn(
            '<a class="story-source" href="https://example.com/oct5-linked" rel="noopener" target="_blank">Open source ↗</a>',
            out,
        )
        self.assertIn('<div class="last24-item">', out)
        self.assertNotIn('href=""', out)
        self.assertNotIn("SOMA Manager Perli", out)
        last24, _, _rest = out.partition('<div class="stitle">Top Market Drivers</div>')
        self.assertIn("Linked desk wire confirms the clickable path", last24)
        self.assertNotIn("Fed reserve-conditions note", last24)

    def test_stale_items_still_fail_the_rolling_window(self) -> None:
        dataset = _dataset()
        dataset["agent_research"]["news"] = [
            {
                "headline": "Old oil story",
                "summary": "Too old for the rolling window.",
                "published_at": "2026-09-01T04:00:00-04:00",
            }
        ]
        dataset["agent_research"]["central_bank_research"] = [
            {
                "title": "Old central bank note",
                "summary": "Stale remarks.",
                "published_at": "2026-09-01T04:00:00-04:00",
            }
        ]
        with self.assertRaises(ValueError) as caught:
            apply_overnight_news_refresh(BASE_HTML, dataset)
        self.assertIn("rolling 7-day window", str(caught.exception))

    def test_cli_refreshes_canonical_oct5_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "index.html"
            html.write_text(BASE_HTML, encoding="utf-8")
            rc = main([str(html), "--dataset", str(OCT5_DATASET), "--root", str(ROOT)])
            self.assertEqual(rc, 0)
            text = html.read_text(encoding="utf-8")
        self.assertIn("Global Oil Supply Buffer", text)
        self.assertNotIn("href=", text)
        self.assertNotIn("Man Group Says", text)


if __name__ == "__main__":
    unittest.main()
