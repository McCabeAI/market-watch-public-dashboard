#!/usr/bin/env python3
"""Workstream A regressions for news_sources (fixtures only; no network).

Fixtures prove parser behavior only. They are not historical proof the 15 Oct
CoreWeave URL was on the sitemap during its 24h window.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from urllib.parse import quote

from scripts.overnight.live_news import REQUIRED_SOURCES
from scripts.overnight.news_sources import (
    CNBC_HEADLINE_ONLY,
    CNBC_SITEMAP_URL,
    REUTERS_CREDIT_QUERY,
    _boj_boe_title_kept,
    _canonical_from_bing_link,
    discovery_surfaces,
    parse_surface,
)

CUTOFF = datetime.fromisoformat("2026-10-17T18:00:00-04:00")

COREWEAVE_CNBC_URL = (
    "https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-"
    "as-investors-sour-on-ai-debt.html"
)


class CnbcSitemapParserTests(unittest.TestCase):
    def test_cnbc_sitemap_fixture(self) -> None:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:n="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>{COREWEAVE_CNBC_URL}</loc>
    <n:news>
      <n:publication><n:name>CNBC</n:name></n:publication>
      <n:publication_date>2026-10-17T14:00:00-04:00</n:publication_date>
      <n:title>CoreWeave credit default swaps hit distress levels</n:title>
    </n:news>
  </url>
  <url>
    <loc>https://www.cnbc.com/2026/10/17/wrong-publisher.html</loc>
    <n:news>
      <n:publication><n:name>Reuters</n:name></n:publication>
      <n:publication_date>2026-10-17T13:00:00-04:00</n:publication_date>
      <n:title>Wrong publisher row</n:title>
    </n:news>
  </url>
  <url>
    <loc>https://www.cnbc.com/2026/10/10/stale-story.html</loc>
    <n:news>
      <n:publication><n:name>CNBC</n:name></n:publication>
      <n:publication_date>2026-10-10T12:00:00-04:00</n:publication_date>
      <n:title>Stale CNBC row</n:title>
    </n:news>
  </url>
</urlset>"""
        parsed = parse_surface(
            "cnbc_sitemap",
            xml.encode("utf-8"),
            surface=CNBC_SITEMAP_URL,
            cutoff=CUTOFF,
            source_name="CNBC",
        )
        self.assertEqual(len(parsed["items"]), 1)
        kept = parsed["items"][0]
        self.assertEqual(kept["headline"], "CoreWeave credit default swaps hit distress levels")
        self.assertEqual(kept["summary"], CNBC_HEADLINE_ONLY)
        self.assertEqual(kept["source_name"], "CNBC")
        self.assertEqual(kept["url"], COREWEAVE_CNBC_URL)
        reasons = {d["reason"] for d in parsed["dropped"]}
        self.assertIn("publication_name", reasons)
        self.assertIn("window", reasons)


class BingCanonicalAndHostFilterTests(unittest.TestCase):
    def test_canonical_from_bing_link_hosts(self) -> None:
        cnbc_bing = (
            "https://www.bing.com/news/apiclick.aspx?url="
            + quote(COREWEAVE_CNBC_URL, safe="")
            + "&ref=newssearch"
        )
        self.assertEqual(_canonical_from_bing_link(cnbc_bing), COREWEAVE_CNBC_URL)
        bloomberg = (
            "https://www.bing.com/news/apiclick.aspx?url="
            + quote("https://www.bloomberg.com/news/articles/2026-10-17/example", safe="")
        )
        self.assertEqual(
            _canonical_from_bing_link(bloomberg),
            "https://www.bloomberg.com/news/articles/2026-10-17/example",
        )
        random_host = (
            "https://www.bing.com/news/apiclick.aspx?url="
            + quote("https://www.example.com/story", safe="")
        )
        self.assertIsNone(_canonical_from_bing_link(random_host))

    def test_bing_rss_allowed_hosts_cnbc_only(self) -> None:
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
          <item>
            <title>CoreWeave CDS on CNBC</title>
            <link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.cnbc.com%2F2026%2F10%2F17%2Fcredit-story.html</link>
            <pubDate>Fri, 17 Oct 2026 16:00:00 GMT</pubDate>
            <description>CNBC credit headline.</description>
          </item>
          <item>
            <title>Bloomberg credit story</title>
            <link>https://www.bing.com/news/apiclick.aspx?url=https%3A%2F%2Fwww.bloomberg.com%2Fnews%2Farticles%2F2026-10-17%2Fcredit.html</link>
            <pubDate>Fri, 17 Oct 2026 16:00:00 GMT</pubDate>
            <description>Bloomberg item.</description>
          </item>
        </channel></rss>"""
        parsed = parse_surface(
            "bing_rss",
            xml.encode("utf-8"),
            surface="https://www.bing.com/news/search?q=test&format=rss",
            cutoff=CUTOFF,
            source_name="CNBC",
            allowed_hosts=("cnbc.com",),
        )
        urls = [i["url"] for i in parsed["items"]]
        self.assertEqual(urls, ["https://www.cnbc.com/2026/10/17/credit-story.html"])
        self.assertEqual(parsed["raw_count"], 1)


class DiscoverySurfacesTests(unittest.TestCase):
    def test_cnbc_surfaces_and_reuters_credit_query(self) -> None:
        surfaces = discovery_surfaces()
        sources = {e["source"] for e in surfaces}
        self.assertIn("cnbc", sources)
        self.assertIn("cnbc_credit", sources)
        self.assertNotIn("cnbc", REQUIRED_SOURCES)
        self.assertNotIn("cnbc_credit", REQUIRED_SOURCES)
        reuters_credit = next(e for e in surfaces if e["source"] == "reuters_credit")
        surface_url = reuters_credit["surface"]
        self.assertIn("CoreWeave", surface_url)
        self.assertTrue(
            "credit%20default" in surface_url or "credit default" in REUTERS_CREDIT_QUERY
        )


class BojBoeTitleFilterTests(unittest.TestCase):
    def test_boj_boe_title_kept_phrases(self) -> None:
        self.assertTrue(_boj_boe_title_kept("Bank rate maintained at 3.75%"))
        self.assertTrue(
            _boj_boe_title_kept(
                "(Reference) Change in the Guideline for Money Market Operations (September 2026 MPM)"
            )
        )
        self.assertTrue(
            _boj_boe_title_kept(
                "Amendment to Principal Terms and Conditions of Complementary Deposit Facility"
            )
        )
        self.assertTrue(_boj_boe_title_kept("Foreign exchange intervention operations"))
        self.assertTrue(_boj_boe_title_kept("Official Cash Rate unchanged"))
        self.assertTrue(_boj_boe_title_kept("Financial Stability Report"))
        self.assertFalse(_boj_boe_title_kept("Services Producer Price Index for August"))
        self.assertTrue(_boj_boe_title_kept("Monetary Policy Meeting statement"))


if __name__ == "__main__":
    unittest.main()
