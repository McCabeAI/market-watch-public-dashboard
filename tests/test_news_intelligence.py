#!/usr/bin/env python3
"""Focused news-intelligence regressions. Injected fetchers only; no network."""

from __future__ import annotations

import unittest
from datetime import datetime

from scripts.overnight.accepted_news import overlay_accepted_research
from scripts.overnight.live_news import acquire_current_news, merge_live_news
from scripts.overnight.news_diagnostics import build_report
from scripts.overnight.news_relevance import public_news_rows, recall_candidate, score_transmission
from scripts.overnight.news_sources import parse_surface

CUTOFF = datetime.fromisoformat("2026-09-27T18:00:00-04:00")

COREWEAVE_HEADLINE = (
    "CoreWeave credit default swaps hit distress levels as investors sour on AI debt"
)
VIETNAM_HEADLINE = "Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%"
INDIA_HEADLINE = "India Trade Deficit Widened in September on Higher Import Bill"
INDIA_SUMMARY = (
    "India's trade gap expanded in September as festive demand and surging oil prices "
    "pushed up imports, adding to risks from the drawn-out conflict in the Middle East."
)
CHICAGO_HEADLINE = "Chicago Fed national activity index slips to -0.04 in August"
CHINA_HEADLINE = (
    "China Q3 growth set to pick up on stimulus, keeping 2026 goal within reach: Reuters poll"
)
CHINA_SUMMARY = "The poll cited stimulus and a rebound in crude demand."
INDONESIA_HEADLINE = (
    "Indonesia's president ready to accept foreign assistance to combat fires, foreign minister says"
)
INDONESIA_SUMMARY = "Officials also mentioned palm oil plantations near the fire zone."
OIL_HEADLINE = "Oil rebounds in early 22 September trade on U.S.–Iran headlines and supply risks"


def _bing_item(title: str, slug: str, description: str | None = None) -> str:
    blurb = description if description is not None else title
    return f"""<item>
      <title>{title} - Bloomberg.com</title>
      <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2f{slug}</link>
      <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
      <description>{blurb}</description>
      <Source>Bloomberg</Source>
    </item>"""


def _rss(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        f"{items}</channel></rss>"
    ).encode("utf-8")


REUTERS_EMPTY = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"></urlset>"""


def _reuters_item(title: str, slug: str) -> bytes:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.reuters.com/business/{slug}</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T14:00:00Z</news:publication_date>
      <news:title>{title}</news:title>
    </news:news>
  </url>
</urlset>"""
    return xml.encode("utf-8")


def _fetcher(bing: bytes, reuters: bytes):
    empty = _rss("")

    def fetcher(url: str) -> bytes:
        if "bing.com" in url and "site%3Areuters.com" in url.lower():
            return empty
        if "bing.com" in url:
            return bing
        if "reuters.com" in url and "news-sitemap" in url:
            return reuters
        return empty

    return fetcher


class RelevanceTests(unittest.TestCase):
    def test_coreweave_shows_without_macro_tokens(self) -> None:
        scored = score_transmission(COREWEAVE_HEADLINE, "")
        self.assertEqual(scored["disposition"], "show")
        self.assertEqual(scored["reason_code"], "ai_capex_credit")
        self.assertGreaterEqual(scored["score"], 10)
        self.assertTrue(recall_candidate(COREWEAVE_HEADLINE, ""))
        scare = "Analysis:Why CoreWeave is in the crosshairs of the AI scare"
        self.assertFalse(recall_candidate(scare, ""))
        self.assertNotEqual(
            score_transmission(scare, "")["reason_code"], "ai_capex_credit"
        )
        self.assertEqual(
            score_transmission(scare, "")["reason_code"], "ambiguous_transmission"
        )
        ormuz = score_transmission(
            "Guarda Revolucionária do Irã afirma que dois petroleiros atingiram minas no Estreito de Ormuz",
            "",
        )
        self.assertEqual(ormuz["disposition"], "show")
        self.assertEqual(ormuz["reason_code"], "oil_supply_shock")

    def test_vietnam_and_india_suppress(self) -> None:
        vietnam = score_transmission(VIETNAM_HEADLINE, "Parliament growth target.")
        self.assertEqual(vietnam["disposition"], "suppress")
        self.assertEqual(vietnam["reason_code"], "local_non_g10_macro")
        india = score_transmission(INDIA_HEADLINE, INDIA_SUMMARY)
        self.assertEqual(india["disposition"], "suppress")
        self.assertEqual(india["reason_code"], "incidental_link_only")
        self.assertFalse(recall_candidate(VIETNAM_HEADLINE, "Parliament growth target."))

    def test_domestic_subject_suppress_with_oil_supply_escape(self) -> None:
        india = score_transmission(INDIA_HEADLINE, INDIA_SUMMARY)
        self.assertEqual(india["disposition"], "suppress")
        self.assertEqual(india["reason_code"], "incidental_link_only")
        oil_export = score_transmission(
            "India oil-export halt widens the trade deficit",
            "Crude exports halted and Brent jumped.",
        )
        self.assertNotEqual(oil_export["disposition"], "suppress")
        self.assertNotEqual(oil_export["reason_code"], "incidental_link_only")
        self.assertEqual(oil_export["reason_code"], "oil_supply_shock")
        self.assertIn(oil_export["disposition"], {"assess", "show"})
        hormuz_india = score_transmission(
            "India halts crude exports after Hormuz closure widened the trade gap",
            "",
        )
        self.assertEqual(hormuz_india["disposition"], "show")
        self.assertEqual(hormuz_india["reason_code"], "oil_supply_shock")
        self.assertNotEqual(hormuz_india["reason_code"], "incidental_link_only")
        vietnam = score_transmission(VIETNAM_HEADLINE, "Parliament growth target.")
        self.assertEqual(vietnam["disposition"], "suppress")
        self.assertFalse(recall_candidate(VIETNAM_HEADLINE, "Parliament growth target."))
        vietnam_oil = score_transmission(
            "Vietnam GDP slump cuts crude exports",
            "Exports halted and Brent rose.",
        )
        self.assertNotEqual(vietnam_oil["disposition"], "suppress")
        self.assertEqual(vietnam_oil["reason_code"], "oil_supply_shock")
        indo = score_transmission(INDONESIA_HEADLINE, INDONESIA_SUMMARY)
        self.assertEqual(indo["disposition"], "suppress")
        self.assertEqual(indo["reason_code"], "local_non_g10_macro")
        palm = score_transmission(
            "Indonesia fires spread as palm oil exports are halted",
            "",
        )
        self.assertEqual(palm["disposition"], "suppress")
        self.assertEqual(palm["reason_code"], "local_non_g10_macro")
        hyphen = score_transmission(
            "Indonesia fires spread as palm-oil exports are halted",
            "",
        )
        self.assertEqual(hyphen["disposition"], "suppress")
        self.assertEqual(hyphen["reason_code"], "local_non_g10_macro")
        crude_palm = score_transmission(
            "Indonesia fires halt crude palm oil exports",
            "",
        )
        self.assertEqual(crude_palm["disposition"], "suppress")
        self.assertEqual(crude_palm["reason_code"], "local_non_g10_macro")
        palm_only = score_transmission("Indonesia palm oil exports are halted", "")
        self.assertNotEqual(palm_only["reason_code"], "oil_supply_shock")
        self.assertIn(palm_only["disposition"], {"suppress", "hold-for-review"})
        indian = score_transmission(
            "Indian trade deficit widened on the import bill",
            "Surging oil prices pushed up the import bill.",
        )
        self.assertEqual(indian["disposition"], "suppress")
        self.assertEqual(indian["reason_code"], "incidental_link_only")
        indo_crude = score_transmission(
            "Indonesia refinery fire halts crude exports",
            "Brent rose.",
        )
        self.assertNotEqual(indo_crude["disposition"], "suppress")
        self.assertEqual(indo_crude["reason_code"], "oil_supply_shock")

    def test_official_policy_scores_and_recall(self) -> None:
        bank_rate = score_transmission("Bank rate maintained at 3.75%", "")
        self.assertIn(bank_rate["disposition"], {"assess", "show"})
        self.assertEqual(bank_rate["reason_code"], "g10_policy_path")
        self.assertIn("GBP", bank_rate["affected_assets"])
        self.assertTrue(recall_candidate("Bank rate maintained at 3.75%", ""))
        self.assertFalse(recall_candidate("Monetary Policy Committee dates for 2027", ""))
        self.assertFalse(
            recall_candidate("Services Producer Price Index for August", "")
        )
        ocr = score_transmission("Official Cash Rate unchanged", "")
        self.assertIn("NZD", ocr["affected_assets"])
        self.assertNotIn(ocr["disposition"], {"hold-for-review", "suppress"})

    def test_chicago_fed_is_retained(self) -> None:
        scored = score_transmission(CHICAGO_HEADLINE, "The Chicago Fed CFNAI for August 2026 was -0.04.")
        self.assertIn(scored["disposition"], {"show", "assess"})
        self.assertEqual(scored["reason_code"], "us_activity_index")

    def test_sanctions_and_fiscal_debt_are_not_keyword_misses(self) -> None:
        energy = score_transmission(
            "Trump Halts New Russia Energy Sanctions to Ease Diesel Costs",
            "",
        )
        self.assertEqual(energy["disposition"], "show")
        self.assertEqual(energy["reason_code"], "geopolitics_haven_or_oil")
        plain = score_transmission("Zelenskyy Slams Russia Sanctions", "")
        self.assertEqual(plain["disposition"], "assess")
        self.assertNotEqual(plain["disposition"], "suppress")
        debt = score_transmission(
            "US Interest Costs Hit Record $1 Trillion, Risking Debt Snowball",
            "",
        )
        self.assertEqual(debt["disposition"], "assess")
        self.assertEqual(debt["reason_code"], "usd_rates_repricing")
        self.assertFalse(recall_candidate("Liverpool labour to a win over Brentford", ""))

    def test_china_shows_and_indonesia_suppresses(self) -> None:
        china = score_transmission(CHINA_HEADLINE, CHINA_SUMMARY)
        self.assertEqual(china["disposition"], "show")
        self.assertEqual(china["reason_code"], "china_commodity_spillover")
        indo = score_transmission(INDONESIA_HEADLINE, INDONESIA_SUMMARY)
        self.assertEqual(indo["disposition"], "suppress")
        self.assertEqual(indo["reason_code"], "local_non_g10_macro")

    def test_overlay_keeps_oil_and_chicago_in_order(self) -> None:
        oil = {
            "headline": OIL_HEADLINE,
            "summary": "Brent and WTI rebounded in early Tuesday trade.",
            "published_at": "2026-09-22T04:22:00-04:00",
            "source_name": "CNBC",
            "url": "https://www.cnbc.com/2026/09/22/oil-iran-us-bessent-un-crude.html",
        }
        chicago = {
            "headline": CHICAGO_HEADLINE,
            "summary": "The Chicago Fed CFNAI for August 2026 was -0.04.",
            "published_at": "2026-09-21T08:30:00-04:00",
            "source_name": "Federal Reserve Bank of Chicago",
        }
        vietnam = {"headline": VIETNAM_HEADLINE, "summary": "Parliament growth target."}
        india = {"headline": INDIA_HEADLINE, "summary": INDIA_SUMMARY}
        original_vietnam = dict(vietnam)
        families = {
            "news": {"status": "stale", "as_of": "2026-09-18T04:00:00", "items": [{"headline": "old"}]},
        }
        packet = {
            "evidence_cutoff": "2026-09-22T06:52:19-04:00",
            "research_supplement": {
                "summary": "Energy and activity.",
                "news": [oil, chicago, vietnam, india],
                "central_bank_research": [{"title": "ECB account", "summary": "Policy rate discussed."}],
            },
        }
        out = overlay_accepted_research(families, packet, when=CUTOFF)
        headlines = [row["headline"] for row in out["news"]["items"]]
        self.assertEqual(headlines[0], OIL_HEADLINE)
        self.assertIn(CHICAGO_HEADLINE, headlines)
        self.assertNotIn(VIETNAM_HEADLINE, headlines)
        self.assertNotIn(INDIA_HEADLINE, headlines)
        self.assertEqual(vietnam, original_vietnam)
        self.assertEqual(out["central_bank_research"]["items"][0]["title"], "ECB account")
        self.assertEqual(families["news"]["items"][0]["headline"], "old")


class DiscoveryTests(unittest.TestCase):
    def test_bloomberg_audio_path_is_not_a_candidate(self) -> None:
        bing = _rss(
            _bing_item(
                "Bloomberg This Weekend: Trump Halts Russia Sanctions",
                "bloomberg-this-weekend-trump-halts-russia-sanctions-podcast",
            ).replace("%2farticles%2f", "%2faudio%2f")
        )
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_fetcher(bing, REUTERS_EMPTY),
        )
        self.assertFalse(any("Weekend" in (c.get("headline") or "") for c in acquisition["candidates"]))
        self.assertTrue(any(row["reason"] == "path_drop" for row in acquisition["story_drops"]))

    def test_reuters_sitemap_keeps_coreweave_headline(self) -> None:
        bing = _rss(_bing_item(COREWEAVE_HEADLINE, "coreweave-cds"))
        reuters = _reuters_item(COREWEAVE_HEADLINE, "coreweave-cds-2026-09-27")
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_fetcher(bing, reuters),
        )
        headlines = [c["headline"] for c in acquisition["candidates"]]
        self.assertIn(COREWEAVE_HEADLINE, headlines)
        merged = merge_live_news(baseline=[], live_candidates=acquisition["candidates"], when=CUTOFF)
        shown = [i for i in merged["items"] if COREWEAVE_HEADLINE in (i.get("headline") or "")]
        self.assertTrue(shown)
        self.assertEqual(shown[0]["transmission"]["disposition"], "show")
        self.assertEqual(shown[0]["transmission"]["reason_code"], "ai_capex_credit")
        self.assertEqual(merged["research_supplement"]["presentation_caps"]["last_24_hours"], 6)
        self.assertEqual(merged["research_supplement"]["presentation_caps"]["top_market_drivers"], 3)

    def test_safety_ceiling_is_discovery_not_presentation(self) -> None:
        items = "".join(
            _bing_item(f"Fed decision marker{i:02d}", f"fed-decision-{i:02d}") for i in range(61)
        )
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_fetcher(_rss(items), REUTERS_EMPTY),
        )
        bloomberg = next(r for r in acquisition["receipts"] if r["source"] == "bloomberg")
        self.assertEqual(bloomberg["result_count"], 60)
        self.assertEqual(len(bloomberg), 7)
        ceilings = [
            row
            for row in acquisition["story_drops"]
            if row["reason"] == "safety_ceiling" and row["source"] == "bloomberg"
        ]
        self.assertTrue(ceilings)
        self.assertEqual(ceilings[0]["stage"], "discovery_failure")
        report = build_report(acquisition, None)
        self.assertGreater(report["counts"]["discovery_failure"], 0)
        self.assertEqual(report["counts"]["presentation_suppression"], 0)

    def test_boj_statistics_title_is_relevance_rejection(self) -> None:
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>Monetary Policy Meeting statement</title>
            <link>https://www.boj.or.jp/en/mopo/mpmdeci/index.htm</link>
            <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
            <description>Policy rate unchanged.</description>
          </item>
          <item>
            <title>Services Producer Price Index for August</title>
            <link>https://www.boj.or.jp/en/statistics/sppi.htm</link>
            <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
            <description>A statistics release.</description>
          </item>
        </channel></rss>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface="https://www.boj.or.jp/en/rss/whatsnew.xml",
            cutoff=CUTOFF,
            source_name="Bank of Japan",
        )
        self.assertEqual([i["headline"] for i in parsed["items"]], ["Monetary Policy Meeting statement"])
        self.assertEqual(parsed["dropped"][0]["reason"], "official_title_filter")
        gilt = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>Asset Purchase Facility: Gilt Sales – Market Notice</title>
            <link>https://www.bankofengland.co.uk/markets/gilt-sales</link>
            <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
            <description>Gilt sale schedule.</description>
          </item>
        </channel></rss>"""
        kept = parse_surface(
            "rss_official",
            gilt.encode("utf-8"),
            surface="https://www.bankofengland.co.uk/rss/news",
            cutoff=CUTOFF,
            source_name="Bank of England",
        )
        self.assertEqual(len(kept["items"]), 1)
        self.assertEqual(kept["items"][0]["verification_status"], "official")

    def test_post_assessment_cap_is_presentation_suppression(self) -> None:
        baseline = []
        for i in range(30):
            baseline.append(
                {
                    "headline": f"Fed decision marker{i:02d}",
                    "summary": "Policy rate unchanged.",
                    "url": f"https://www.reuters.com/markets/fed-decision-{i:02d}",
                    "published_at": f"2026-09-27T{i % 10:02d}:00:00-04:00",
                    "source_name": "Reuters",
                    "verification_status": "single_source",
                    "primary_category": "monetary_policy",
                    "country_codes": ["US"],
                }
            )
        merged = merge_live_news(baseline=baseline, live_candidates=[], when=CUTOFF)
        self.assertEqual(len(merged["items"]), 24)
        suppressed = [r for r in merged["diagnostics_rows"] if r["stage"] == "presentation_suppression"]
        self.assertEqual(len(suppressed), 6)
        shown = [r for r in merged["diagnostics_rows"] if r["stage"] == "shown"]
        self.assertEqual(len(shown), 24)
        self.assertTrue(all(i["transmission"]["disposition"] in {"show", "assess"} for i in merged["items"]))

    def test_india_oil_color_is_not_shown(self) -> None:
        merged = merge_live_news(
            baseline=[
                {
                    "headline": INDIA_HEADLINE,
                    "summary": INDIA_SUMMARY,
                    "url": "https://news.example.test/india-trade",
                    "published_at": "2026-09-27T12:00:00-04:00",
                    "source_name": "Bloomberg",
                    "verification_status": "single_source",
                    "primary_category": "macro",
                    "country_codes": [],
                }
            ],
            live_candidates=[],
            when=CUTOFF,
        )
        self.assertEqual(merged["items"], [])
        self.assertEqual(merged["diagnostics_rows"][0]["stage"], "relevance_rejection")
        self.assertEqual(merged["diagnostics_rows"][0]["reason"], "incidental_link_only")

    def test_public_rows_do_not_mutate_inputs(self) -> None:
        row = {"headline": VIETNAM_HEADLINE, "summary": "GDP target."}
        kept = public_news_rows([row])
        self.assertEqual(kept, [])
        self.assertNotIn("transmission", row)


class DiagnosticsReportTests(unittest.TestCase):
    def test_stages_stay_distinct(self) -> None:
        report = build_report(
            {
                "cutoff": "2026-09-27T18:00:00-04:00",
                "partial": True,
                "receipts": [
                    {
                        "source": "bloomberg",
                        "status": "failed",
                        "failure": "bloomberg surface down",
                        "surface": "https://www.bing.com/news/search",
                        "candidate_count": 0,
                        "result_count": 0,
                        "checked_at": "2026-09-27T18:00:00-04:00",
                    }
                ],
                "story_drops": [
                    {
                        "headline": "Services Producer Price Index",
                        "url": "https://www.boj.or.jp/en/statistics/sppi.htm",
                        "source": "boj_whatsnew",
                        "published_at": None,
                        "stage": "relevance_rejection",
                        "reason": "official_title_filter",
                    }
                ],
            },
            {
                "items": [{"headline": "kept", "url": "https://example.test/a", "source_name": "Reuters"}],
                "diagnostics_rows": [
                    {
                        "headline": "kept",
                        "url": "https://example.test/a",
                        "source": "Reuters",
                        "published_at": "2026-09-27T12:00:00-04:00",
                        "stage": "shown",
                        "reason": "g10_policy_path",
                    },
                    {
                        "headline": "ranked out",
                        "url": "https://example.test/b",
                        "source": "Reuters",
                        "published_at": "2026-09-27T11:00:00-04:00",
                        "stage": "presentation_suppression",
                        "reason": "g10_policy_path",
                    },
                    {
                        "headline": VIETNAM_HEADLINE,
                        "url": "https://example.test/c",
                        "source": "Bloomberg",
                        "published_at": "2026-09-27T10:00:00-04:00",
                        "stage": "relevance_rejection",
                        "reason": "local_non_g10_macro",
                    },
                ],
            },
        )
        stages = {row["headline"]: row["stage"] for row in report["stories"]}
        self.assertEqual(stages[None], "discovery_failure")
        self.assertEqual(stages["Services Producer Price Index"], "relevance_rejection")
        self.assertEqual(stages[VIETNAM_HEADLINE], "relevance_rejection")
        self.assertEqual(stages["ranked out"], "presentation_suppression")
        self.assertEqual(stages["kept"], "shown")
        self.assertEqual(report["counts"]["discovery_failure"], 1)
        self.assertEqual(report["counts"]["presentation_suppression"], 1)
        self.assertEqual(report["type"], "NEWS_INTELLIGENCE_SHADOW_REPORT")


if __name__ == "__main__":
    unittest.main()
