#!/usr/bin/env python3
"""Publication trail: research pool vs final webpage display slots."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.apply_overnight_news_refresh import explain_display_slots
from scripts.overnight.accepted_news import overlay_drop_rows
from scripts.overnight.news_diagnostics import build_report, SCHEMA_VERSION
from scripts.overnight.news_relevance import score_transmission

NY = ZoneInfo("America/New_York")
CUTOFF = datetime(2026, 10, 17, 18, 0, tzinfo=NY)
VIETNAM_HEADLINE = "Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%"
OIL_HEADLINE = "Oil rebounds in early 22 September trade on U.S.–Iran headlines and supply risks"


def _macro_news_row(headline: str, hours_before_cutoff: float, *, slug: str) -> dict:
    published = CUTOFF - timedelta(hours=hours_before_cutoff)
    return {
        "headline": headline,
        "summary": f"Summary for {slug}.",
        "url": f"https://www.reuters.com/markets/{slug}",
        "published_at": published.isoformat(),
        "source_name": "Reuters",
        "primary_category": "macro",
        "country_codes": ["US"],
    }


def _rows_for_headline(rows: list[dict], headline: str) -> list[dict]:
    return [row for row in rows if row.get("headline") == headline]


class DisplaySlotExplainerTests(unittest.TestCase):
    def test_eight_in_window_rows_split_last24_and_digest(self) -> None:
        news = [
            _macro_news_row(f"Macro marker {i:02d}", float(i + 1), slug=f"macro-{i:02d}")
            for i in range(8)
        ]
        dataset = {
            "agent_research_cutoff": CUTOFF.isoformat(),
            "agent_research": {"news": news, "central_bank_research": []},
        }
        rows = explain_display_slots(dataset, cutoff=CUTOFF)

        newest = "Macro marker 00"
        oldest_in_window = "Macro marker 07"

        newest_rows = _rows_for_headline(rows, newest)
        self.assertTrue(
            any(
                r["outcome"] == "published"
                and r["slot"] == "last_24_hours"
                and r["reason"] == "in_slot"
                and r["cap"] == 6
                for r in newest_rows
            )
        )
        self.assertTrue(
            any(
                r["outcome"] == "published"
                and r["slot"] == "digest_stories"
                and r["reason"] == "in_slot"
                and r["cap"] == 12
                for r in newest_rows
            )
        )

        dropped = _rows_for_headline(rows, oldest_in_window)
        self.assertTrue(
            any(
                r["outcome"] == "display_slot_drop"
                and r["slot"] == "last_24_hours"
                and r["reason"] == "beyond_6"
                and r["cap"] == 6
                for r in dropped
            )
        )
        self.assertTrue(
            any(
                r["outcome"] == "published"
                and r["slot"] == "digest_stories"
                and r["reason"] == "in_slot"
                for r in dropped
            )
        )

        self.assertGreaterEqual(len(newest_rows), 2)
        slots = {r["slot"] for r in newest_rows if r["outcome"] == "published"}
        self.assertIn("last_24_hours", slots)
        self.assertIn("digest_stories", slots)

    def test_explain_display_slots_does_not_require_file_write(self) -> None:
        dataset = {
            "agent_research_cutoff": CUTOFF.isoformat(),
            "agent_research": {
                "news": [_macro_news_row("Only story", 1.0, slug="only")],
                "central_bank_research": [],
            },
        }
        rows = explain_display_slots(dataset, cutoff=CUTOFF)
        self.assertTrue(rows)


class BuildReportPublicationRowsTests(unittest.TestCase):
    def test_shown_is_research_top_24_not_published(self) -> None:
        report = build_report(
            {"cutoff": CUTOFF.isoformat(), "partial": False, "receipts": [], "story_drops": []},
            {
                "items": [{"headline": "Shown only", "url": "https://example.test/a"}],
                "diagnostics_rows": [
                    {
                        "headline": "Shown only",
                        "url": "https://example.test/a",
                        "source": "Reuters",
                        "published_at": CUTOFF.isoformat(),
                        "stage": "shown",
                        "reason": "g10_policy_path",
                    }
                ],
            },
        )
        pub = report["publication_rows"]
        self.assertEqual(len(pub), 1)
        self.assertEqual(pub[0]["outcome"], "research_top_24")
        self.assertEqual(pub[0]["cap"], 24)
        self.assertNotEqual(pub[0]["outcome"], "published")
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)

    def test_presentation_suppression_absent_from_publication_rows(self) -> None:
        report = build_report(
            {"cutoff": CUTOFF.isoformat(), "partial": False, "receipts": [], "story_drops": []},
            {
                "items": [],
                "diagnostics_rows": [
                    {
                        "headline": "Ranked out",
                        "url": "https://example.test/b",
                        "source": "Reuters",
                        "published_at": CUTOFF.isoformat(),
                        "stage": "presentation_suppression",
                        "reason": "g10_policy_path",
                    }
                ],
            },
        )
        stages = {row["headline"]: row["stage"] for row in report["stories"]}
        self.assertEqual(stages["Ranked out"], "presentation_suppression")
        self.assertEqual(report["publication_rows"], [])


class SharedIdentityTests(unittest.TestCase):
    def test_dated_twin_outside_window_is_not_published_with_undated_copy(self) -> None:
        fresh = _macro_news_row("Fresh marker", 1.0, slug="fresh")
        dated = {
            "headline": "Shared headline",
            "summary": "Dated body that is outside the 7-day window.",
            "url": "https://www.reuters.com/markets/shared",
            "published_at": (CUTOFF - timedelta(days=10)).isoformat(),
            "source_name": "Reuters",
            "primary_category": "macro",
        }
        undated = {
            "headline": "Shared headline",
            "summary": "Undated body.",
            "url": "https://www.reuters.com/markets/shared",
            "source_name": "Reuters",
            "primary_category": "macro",
        }
        dataset = {
            "agent_research_cutoff": CUTOFF.isoformat(),
            "agent_research": {"news": [fresh, dated, undated], "central_bank_research": []},
        }
        rows = explain_display_slots(dataset, cutoff=CUTOFF)
        shared = [row for row in rows if row["headline"] == "Shared headline"]
        dated_rows = [row for row in shared if row.get("published_at")]
        self.assertTrue(dated_rows)
        self.assertTrue(all(row["outcome"] != "published" for row in dated_rows))
        self.assertTrue(
            any(row["outcome"] == "display_slot_drop" and row["reason"] == "outside_7d" for row in dated_rows)
        )
        undated_rows = [row for row in shared if not row.get("published_at")]
        self.assertTrue(
            any(
                row["outcome"] == "published" and row["slot"] == "digest_stories"
                for row in undated_rows
            )
        )


class OverlayDropRowsTests(unittest.TestCase):
    def test_vietnam_overlay_drop_and_oil_not_dropped(self) -> None:
        vietnam = {
            "headline": VIETNAM_HEADLINE,
            "summary": "Parliament growth target.",
            "url": "https://www.bloomberg.com/news/vietnam-gdp",
            "source_name": "Bloomberg",
        }
        oil = {
            "headline": OIL_HEADLINE,
            "summary": "Crude prices rose on supply risks.",
            "url": "https://www.reuters.com/markets/oil-rebound",
            "source_name": "Reuters",
        }
        oil_scored = score_transmission(oil["headline"], oil["summary"])
        self.assertIn(oil_scored["disposition"], {"show", "assess"})

        drops = overlay_drop_rows([vietnam, oil])
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["outcome"], "overlay_drop")
        self.assertEqual(drops[0]["reason"], "local_non_g10_macro")
        self.assertEqual(drops[0]["headline"], VIETNAM_HEADLINE)


if __name__ == "__main__":
    unittest.main()
