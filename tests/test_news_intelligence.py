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
        self.assertEqual(bloomberg["feed_health"], "candidates")
        for key in (
            "source",
            "checked_at",
            "status",
            "candidate_count",
            "result_count",
            "failure",
            "surface",
            "feed_health",
        ):
            self.assertIn(key, bloomberg)
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


class PoliticalTransmissionTests(unittest.TestCase):
    """General political and geopolitical transmission. No party boost and no date special case."""

    ELECTION = "US national election result changes control of Congress"
    ELECTION_YIELDS = (
        "US national election results change control of Congress; Treasury yields fall"
    )
    ELECTION_DOLLAR_STOCKS = (
        "US national election results change control of Congress; "
        "dollar rises and stocks fall"
    )
    FED = "Fed officials see inflation progress stalling as Treasury yields rise"

    def test_election_outcome_does_not_need_treasury_language(self) -> None:
        self.assertNotIn("treasury", self.ELECTION.lower())
        scored = score_transmission(self.ELECTION, "")
        self.assertEqual(scored["disposition"], "show")
        self.assertEqual(scored["reason_code"], "political_risk_transmission")
        self.assertGreaterEqual(scored["score"], 12)
        self.assertEqual(scored["claim"], "possible")
        self.assertEqual(scored["affected_assets"], ["USD", "UST"])
        self.assertTrue(recall_candidate(self.ELECTION, ""))
        evidenced = score_transmission(
            self.ELECTION,
            "The dollar moved after the result.",
        )
        self.assertEqual(evidenced["claim"], "evidenced")
        self.assertGreaterEqual(evidenced["score"], scored["score"])

    def test_party_labels_score_the_same(self) -> None:
        republicans = score_transmission(
            "Republicans win control of Congress in the US national election",
            "",
        )
        democrats = score_transmission(
            "Democrats win control of Congress in the US national election",
            "",
        )
        self.assertEqual(republicans["score"], democrats["score"])
        self.assertEqual(republicans["disposition"], democrats["disposition"])
        self.assertEqual(republicans["channel"], democrats["channel"])
        self.assertEqual(republicans["reason_code"], democrats["reason_code"])
        self.assertEqual(republicans["affected_assets"], democrats["affected_assets"])

    def test_neutral_routine_and_non_us_events(self) -> None:
        neutral = score_transmission(
            "US national election count continues with congressional control unchanged",
            "",
        )
        shock = score_transmission(self.ELECTION, "")
        self.assertEqual(neutral["disposition"], "assess")
        self.assertEqual(neutral["reason_code"], "political_risk_transmission")
        self.assertLess(neutral["score"], shock["score"])

        routine = "City council election result is declared after a long count"
        routine_score = score_transmission(routine, "")
        self.assertIn(routine_score["disposition"], {"hold-for-review", "suppress"})
        self.assertFalse(recall_candidate(routine, ""))
        self.assertFalse(recall_candidate("Senator endorsement draws a campaign rally crowd", ""))
        scheduled = score_transmission("Britain's general election is set for next year", "")
        self.assertNotEqual(scheduled["disposition"], "show")
        snap_calendar = score_transmission("UK snap election is set for December", "")
        self.assertNotEqual(snap_calendar["disposition"], "show")
        self.assertFalse(recall_candidate("Congressional midterms are next week", ""))
        mixed = score_transmission(
            "Republicans win control of Congress while Senate margin unchanged",
            "",
        )
        self.assertEqual(mixed["disposition"], "show")
        self.assertGreaterEqual(mixed["score"], shock["score"])

        japan = score_transmission("Japan snap election result changes control of parliament", "")
        self.assertEqual(japan["disposition"], "show")
        self.assertEqual(japan["reason_code"], "political_risk_transmission")
        self.assertIn("JPY", japan["affected_assets"])
        france = score_transmission("French government collapses after a no-confidence vote", "")
        self.assertEqual(france["disposition"], "show")
        self.assertIn("EUR", france["affected_assets"])
        brazil = score_transmission("Brazil mayoral election result is declared", "")
        self.assertNotEqual(brazil["disposition"], "show")
        linked = score_transmission("Brazil election result sends the dollar higher", "")
        self.assertEqual(linked["disposition"], "show")
        self.assertEqual(linked["claim"], "evidenced")
        missile = score_transmission("Russia missile strike hits a shipping lane", "")
        self.assertEqual(missile["disposition"], "show")
        self.assertEqual(missile["reason_code"], "geopolitics_haven_or_oil")
        self.assertEqual(missile["claim"], "possible")

        self.assertEqual(score_transmission(COREWEAVE_HEADLINE, "")["reason_code"], "ai_capex_credit")
        self.assertEqual(score_transmission("Fed holds the policy rate", "")["reason_code"], "g10_policy_path")
        cpi = score_transmission("CPI rises more than expected", "")
        self.assertEqual(cpi["reason_code"], "usd_rates_repricing")
        self.assertIn(cpi["disposition"], {"show", "assess"})
        self.assertEqual(score_transmission(CHINA_HEADLINE, CHINA_SUMMARY)["reason_code"], "china_commodity_spillover")
        self.assertEqual(score_transmission(VIETNAM_HEADLINE, "Parliament growth target.")["disposition"], "suppress")

    def test_fresh_election_leads_stale_boe_and_oil_but_not_a_fresh_fed_or_hormuz(self) -> None:
        from datetime import datetime

        from scripts.overnight.live_news import merge_live_news

        when = datetime.fromisoformat("2026-11-04T08:00:00-05:00")
        election = {
            "headline": self.ELECTION,
            "summary": "Headline-only public metadata; article body was not retrieved.",
            "url": "https://www.cnbc.com/2026/11/04/us-election-congress-control.html",
            "published_at": "2026-11-04T06:10:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "geopolitics",
            "country_codes": ["US"],
        }
        fed = {
            "headline": self.FED,
            "summary": "Officials said inflation progress may stall.",
            "url": "https://www.cnbc.com/2026/11/04/fed-inflation-yields.html",
            "published_at": "2026-11-04T05:30:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "monetary_policy",
            "country_codes": ["US"],
        }
        fresh_hormuz = {
            "headline": "Iran says it will not soften demands after Trump rejects a Hormuz offer",
            "summary": "Crude bounced.",
            "url": "https://www.reuters.com/world/hormuz-fresh-2026-11-04/",
            "published_at": "2026-11-04T07:00:00-05:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_oil = {
            "headline": "Oil rebounds as Hormuz tensions keep crude bid",
            "summary": "Brent rose.",
            "url": "https://www.reuters.com/world/hormuz-stale-2026-10-28/",
            "published_at": "2026-10-28T06:00:00-04:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_boe = {
            "headline": "Bank rate maintained at 3.75%",
            "summary": "The Bank of England left policy unchanged.",
            "url": "https://www.bankofengland.co.uk/news/2026/october/bank-rate-maintained",
            "published_at": "2026-10-28T07:00:00-04:00",
            "source_name": "Bank of England",
            "verification_status": "official",
            "primary_category": "monetary_policy",
            "country_codes": [],
        }
        merged = merge_live_news(
            baseline=[stale_oil, stale_boe],
            live_candidates=[election, fed],
            when=when,
        )
        headlines = [row["headline"] for row in merged["items"]]
        self.assertLess(headlines.index(self.FED), headlines.index(self.ELECTION))
        self.assertLess(headlines.index(self.ELECTION), headlines.index(stale_oil["headline"]))
        self.assertLess(headlines.index(self.ELECTION), headlines.index(stale_boe["headline"]))
        by_headline = {row["headline"]: row for row in merged["items"]}
        self.assertEqual(by_headline[self.ELECTION]["currency"], "current")
        self.assertEqual(by_headline[self.ELECTION]["transmission"]["claim"], "possible")
        self.assertEqual(
            by_headline[self.ELECTION]["summary"],
            "Headline-only public metadata; article body was not retrieved.",
        )
        self.assertEqual(by_headline[stale_oil["headline"]]["currency"], "archival")
        self.assertEqual(by_headline[stale_boe["headline"]]["currency"], "archival")
        drivers = merged["research_supplement"]["top_market_driver_candidates"]
        election_id = by_headline[self.ELECTION]["id"]
        stale_oil_id = by_headline[stale_oil["headline"]]["id"]
        self.assertIn(election_id, drivers)
        self.assertEqual(drivers[0], by_headline[self.FED]["id"])
        if stale_oil_id in drivers:
            self.assertLess(drivers.index(election_id), drivers.index(stale_oil_id))

        with_shock = merge_live_news(
            baseline=[stale_oil],
            live_candidates=[election, fresh_hormuz],
            when=when,
        )
        shock_order = [row["headline"] for row in with_shock["items"]]
        self.assertLess(shock_order.index(fresh_hormuz["headline"]), shock_order.index(self.ELECTION))

    def test_recorded_moves_and_political_precedence(self) -> None:
        from datetime import datetime

        from scripts.overnight.live_news import merge_live_news

        yields_fall = score_transmission(self.ELECTION_YIELDS, "")
        self.assertEqual(yields_fall["reason_code"], "political_risk_transmission")
        self.assertEqual(yields_fall["disposition"], "show")
        self.assertGreaterEqual(yields_fall["score"], 12)
        self.assertEqual(yields_fall["claim"], "evidenced")
        self.assertEqual(yields_fall["channel"], "geopolitics_haven")
        self.assertIn("usd_rates", yields_fall["channels"])
        self.assertIn("USD", yields_fall["affected_assets"])
        self.assertIn("UST", yields_fall["affected_assets"])

        dollar_stocks = score_transmission(self.ELECTION_DOLLAR_STOCKS, "")
        self.assertEqual(dollar_stocks["reason_code"], "political_risk_transmission")
        self.assertEqual(dollar_stocks["disposition"], "show")
        self.assertEqual(dollar_stocks["claim"], "evidenced")
        self.assertIn("USD", dollar_stocks["affected_assets"])
        self.assertIn("SPX", dollar_stocks["affected_assets"])

        approaches = score_transmission(
            "US election approaches; Treasury yields rise on Fed signal",
            "",
        )
        self.assertNotEqual(approaches["reason_code"], "political_risk_transmission")
        self.assertIn(
            approaches["reason_code"],
            {"usd_rates_repricing", "g10_policy_path"},
        )

        debate = score_transmission("Congress debates Treasury borrowing", "")
        self.assertNotEqual(debate["reason_code"], "political_risk_transmission")

        keyword_only = score_transmission(
            self.ELECTION,
            "Treasury yields and the dollar were mentioned",
        )
        self.assertEqual(keyword_only["claim"], "possible")

        secretary_says = score_transmission(
            self.ELECTION,
            "Treasury secretary says yields will fall",
        )
        self.assertEqual(secretary_says["claim"], "possible")

        auction = score_transmission(
            self.ELECTION,
            "scheduled Treasury auction",
        )
        self.assertEqual(auction["claim"], "possible")

        rep = score_transmission(
            "US national election results change control of Congress for Republicans; Treasury yields fall",
            "",
        )
        dem = score_transmission(
            "US national election results change control of Congress for Democrats; Treasury yields fall",
            "",
        )
        self.assertEqual(rep["score"], dem["score"])
        self.assertEqual(rep["disposition"], dem["disposition"])
        self.assertEqual(rep["reason_code"], dem["reason_code"])
        self.assertEqual(rep["channel"], dem["channel"])

        france = score_transmission(
            "French government collapses after a no-confidence vote as yields fall",
            "",
        )
        self.assertEqual(france["reason_code"], "political_risk_transmission")
        self.assertEqual(france["disposition"], "show")
        self.assertEqual(france["claim"], "evidenced")

        fed_election = score_transmission(
            "Fed surprises with an emergency rate cut as the US national election result "
            "changes control of Congress",
            "",
        )
        self.assertEqual(fed_election["reason_code"], "g10_policy_path")
        self.assertNotEqual(fed_election["reason_code"], "political_risk_transmission")

        when = datetime.fromisoformat("2026-11-04T08:00:00-05:00")
        election_row = {
            "headline": self.ELECTION_YIELDS,
            "summary": "Headline-only public metadata; article body was not retrieved.",
            "url": "https://www.cnbc.com/2026/11/04/us-election-yields.html",
            "published_at": "2026-11-04T06:10:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "geopolitics",
            "country_codes": ["US"],
        }
        fed_row = {
            "headline": self.FED,
            "summary": "Officials said inflation progress may stall.",
            "url": "https://www.cnbc.com/2026/11/04/fed-inflation-yields.html",
            "published_at": "2026-11-04T05:30:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "monetary_policy",
            "country_codes": ["US"],
        }
        fresh_hormuz = {
            "headline": "Iran says it will not soften demands after Trump rejects a Hormuz offer",
            "summary": "Crude bounced.",
            "url": "https://www.reuters.com/world/hormuz-fresh-2026-11-04/",
            "published_at": "2026-11-04T07:00:00-05:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_oil = {
            "headline": "Oil rebounds as Hormuz tensions keep crude bid",
            "summary": "Brent rose.",
            "url": "https://www.reuters.com/world/hormuz-stale-2026-10-28/",
            "published_at": "2026-10-28T06:00:00-04:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_boe = {
            "headline": "Bank rate maintained at 3.75%",
            "summary": "The Bank of England left policy unchanged.",
            "url": "https://www.bankofengland.co.uk/news/2026/october/bank-rate-maintained",
            "published_at": "2026-10-28T07:00:00-04:00",
            "source_name": "Bank of England",
            "verification_status": "official",
            "primary_category": "monetary_policy",
            "country_codes": [],
        }
        merged = merge_live_news(
            baseline=[stale_oil, stale_boe],
            live_candidates=[election_row, fed_row, fresh_hormuz],
            when=when,
        )
        order = [row["headline"] for row in merged["items"]]
        self.assertLess(order.index(self.FED), order.index(self.ELECTION_YIELDS))
        self.assertLess(order.index(fresh_hormuz["headline"]), order.index(self.ELECTION_YIELDS))
        self.assertLess(order.index(self.ELECTION_YIELDS), order.index(stale_oil["headline"]))
        self.assertLess(order.index(self.ELECTION_YIELDS), order.index(stale_boe["headline"]))
        election = next(row for row in merged["items"] if row["headline"] == self.ELECTION_YIELDS)
        self.assertEqual(election["currency"], "current")
        self.assertEqual(election["transmission"]["claim"], "evidenced")
        self.assertEqual(election["transmission"]["reason_code"], "political_risk_transmission")
        self.assertEqual(election["transmission"]["channel"], "geopolitics_haven")

    def test_political_modality_matrix(self) -> None:
        from datetime import datetime

        from scripts.overnight.live_news import merge_live_news
        from scripts.overnight.news_relevance import presentation_rank_tuple

        def pol(headline: str, summary: str = "") -> dict[str, object]:
            scored = score_transmission(headline, summary)
            return scored

        def assert_show(row: dict[str, object], *, claim: str, score_min: int = 12) -> None:
            self.assertEqual(row["disposition"], "show")
            self.assertEqual(row["reason_code"], "political_risk_transmission")
            self.assertGreaterEqual(int(row["score"]), score_min)
            self.assertEqual(row["claim"], claim)

        def assert_not_political_show(headline: str, summary: str = "") -> None:
            scored = score_transmission(headline, summary)
            if scored["reason_code"] == "political_risk_transmission":
                self.assertNotEqual(scored["disposition"], "show")
            else:
                self.assertNotEqual(scored["reason_code"], "political_risk_transmission")

        realized = [
            "Democrats win control of Congress",
            "Republicans win control of Congress",
            "US national election results change control of Congress",
            "AP calls the House for Democrats",
            "Reuters calls the Senate for Republicans",
            "AP projects the House for Democrats",
            "French government collapses after a no-confidence vote",
            "French government collapses after a no-confidence vote as yields fall",
            "Democrats win control of Congress; analysts expected a closer race",
            "Democrats win control of Congress; analysts expect yields to fall",
            "Democrats win control of Congress; analysts expected Republicans to win",
            "Democrats could win control, but Republicans secured control of Congress",
            self.ELECTION_YIELDS,
            self.ELECTION_DOLLAR_STOCKS,
        ]
        for headline in realized:
            row = pol(headline)
            claim = "evidenced" if _market_evidence_headline(headline) else "possible"
            assert_show(row, claim=claim)

        for party in ("Democrats", "Republicans"):
            assert_show(pol(f"{party} win control of Congress"), claim="possible")

        pending = score_transmission("US national election results still pending", "")
        self.assertEqual(pending["disposition"], "assess")
        self.assertEqual(pending["reason_code"], "political_risk_transmission")
        self.assertEqual(pending["score"], 8)

        for assess_headline in (
            "Control of Congress remains unchanged",
            "Control of the House remains unchanged",
            "US national election count continues with congressional control unchanged",
        ):
            row = score_transmission(assess_headline, "")
            self.assertEqual(row["disposition"], "assess")
            self.assertEqual(row["reason_code"], "political_risk_transmission")
            self.assertEqual(row["score"], 8)
            self.assertEqual(row["claim"], "possible")

        forecasts = [
            "Democrats could win control of Congress",
            "Republicans could win control of Congress",
            "US national election results may change control of Congress",
            "Control of Congress is expected to change",
            "Congressional control might change",
            "Democrats did not win control of Congress",
            "Democrats didn't win control of Congress",
            "Senate majority might flip",
            "party expected to take the House",
            "candidate says they will win the election",
            "poll forecasts Congress will flip",
            "would win control of Congress in a tight race",
            "likely to win the Senate",
            "may flip the House",
            "could change control of Congress",
            "expected to flip the House",
            "polls project a flip in Congress",
            "polls project Democrats could win the House",
            "a poll projects Democrats could win the House",
            "If Democrats win control of Congress, markets will watch",
        ]
        for headline in forecasts:
            assert_not_political_show(headline)

        assert_not_political_show("I have no confidence Congress will act")

        mixed_rates = score_transmission(
            "Democrats could win control of Congress as Treasury yields fell",
            "",
        )
        self.assertNotEqual(mixed_rates["reason_code"], "political_risk_transmission")
        self.assertIn(mixed_rates["reason_code"], {"usd_rates_repricing", "g10_policy_path"})

        rates_after_election = score_transmission("Treasury yields fell after the election", "")
        self.assertNotEqual(rates_after_election["reason_code"], "political_risk_transmission")
        self.assertEqual(rates_after_election["reason_code"], "usd_rates_repricing")
        self.assertTrue(_market_evidence_headline("Treasury yields fell after the election"))

        brazil = score_transmission("Brazil election result sends the dollar higher", "")
        self.assertEqual(brazil["disposition"], "show")
        self.assertEqual(brazil["reason_code"], "political_risk_transmission")
        self.assertEqual(brazil["claim"], "evidenced")

        realized_election_yields = score_transmission(
            "Democrats win control of Congress as Treasury yields fell after the election",
            "",
        )
        self.assertEqual(realized_election_yields["disposition"], "show")
        self.assertEqual(realized_election_yields["reason_code"], "political_risk_transmission")
        self.assertEqual(realized_election_yields["score"], 13)
        self.assertEqual(realized_election_yields["claim"], "evidenced")
        self.assertIn("usd_rates", realized_election_yields["channels"])

        prospective_only = score_transmission(
            "US national election results change control of Congress; "
            "Treasury yields are expected to fall",
            "",
        )
        assert_show(prospective_only, claim="possible")
        self.assertNotIn("usd_rates", prospective_only["channels"])

        for neg in (
            "Treasury yields are expected to fall",
            "Treasury yields are expected to fall after election",
            "stocks could rally",
            "the dollar may weaken",
            "strategists predict bonds will rise",
            "yields did not fall",
        ):
            self.assertFalse(_market_evidence_headline(neg))

        for pos in (
            "Treasury yields fell",
            "stocks tumble",
            "dollar strengthens",
            "Treasury yields fell, and analysts think they will fall further",
        ):
            self.assertTrue(_market_evidence_headline(pos))

        secretary = score_transmission(
            self.ELECTION,
            "Treasury secretary says yields will fall",
        )
        self.assertEqual(secretary["claim"], "possible")

        rep = pol(
            "US national election results change control of Congress for Republicans; "
            "Treasury yields fall"
        )
        dem = pol(
            "US national election results change control of Congress for Democrats; "
            "Treasury yields fall"
        )
        self.assertEqual(rep["score"], dem["score"])
        self.assertEqual(rep["disposition"], dem["disposition"])
        self.assertEqual(rep["reason_code"], dem["reason_code"])
        self.assertEqual(rep["channel"], dem["channel"])

        when = datetime.fromisoformat("2026-11-04T08:00:00-05:00")
        election_row = {
            "headline": self.ELECTION_YIELDS,
            "summary": "",
            "url": "https://example.test/election-yields",
            "published_at": "2026-11-04T06:10:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "geopolitics",
            "country_codes": ["US"],
        }
        forecast_row = {
            "headline": "Democrats could win control of Congress",
            "summary": "",
            "url": "https://example.test/election-forecast",
            "published_at": "2026-11-04T06:05:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "geopolitics",
            "country_codes": ["US"],
        }
        fed_row = {
            "headline": self.FED,
            "summary": "",
            "url": "https://example.test/fed",
            "published_at": "2026-11-04T05:30:00-05:00",
            "source_name": "CNBC",
            "verification_status": "single_source",
            "primary_category": "monetary_policy",
            "country_codes": ["US"],
        }
        fresh_hormuz = {
            "headline": "Iran says it will not soften demands after Trump rejects a Hormuz offer",
            "summary": "Crude bounced.",
            "url": "https://example.test/hormuz-fresh",
            "published_at": "2026-11-04T07:00:00-05:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_oil = {
            "headline": "Oil rebounds as Hormuz tensions keep crude bid",
            "summary": "",
            "url": "https://example.test/hormuz-stale",
            "published_at": "2026-10-28T06:00:00-04:00",
            "source_name": "Reuters",
            "verification_status": "single_source",
            "primary_category": "energy",
            "country_codes": [],
        }
        stale_boe = {
            "headline": "Bank rate maintained at 3.75%",
            "summary": "",
            "url": "https://example.test/boe",
            "published_at": "2026-10-28T07:00:00-04:00",
            "source_name": "Bank of England",
            "verification_status": "official",
            "primary_category": "monetary_policy",
            "country_codes": [],
        }
        merged = merge_live_news(
            baseline=[stale_oil, stale_boe],
            live_candidates=[election_row, forecast_row, fed_row, fresh_hormuz],
            when=when,
        )
        order = [row["headline"] for row in merged["items"]]
        self.assertLess(order.index(self.FED), order.index(self.ELECTION_YIELDS))
        self.assertLess(order.index(fresh_hormuz["headline"]), order.index(self.ELECTION_YIELDS))
        self.assertLess(order.index(self.ELECTION_YIELDS), order.index(stale_oil["headline"]))
        self.assertLess(order.index(self.ELECTION_YIELDS), order.index(stale_boe["headline"]))
        forecast_scored = score_transmission(forecast_row["headline"], forecast_row["summary"])
        self.assertNotEqual(forecast_scored.get("reason_code"), "political_risk_transmission")
        self.assertNotEqual(forecast_scored.get("disposition"), "show")
        by_headline = {row["headline"]: row for row in merged["items"]}
        election_rank = presentation_rank_tuple(
            int(by_headline[self.ELECTION_YIELDS]["transmission"]["score"]),
            by_headline[self.ELECTION_YIELDS]["published_at"],
            when,
        )
        forecast_rank = presentation_rank_tuple(
            int(forecast_scored["score"]),
            forecast_row["published_at"],
            when,
        )
        self.assertGreater(election_rank, forecast_rank)


def _market_evidence_headline(headline: str) -> bool:
    from scripts.overnight.news_relevance import _market_evidence

    return _market_evidence(headline)


if __name__ == "__main__":
    unittest.main()
