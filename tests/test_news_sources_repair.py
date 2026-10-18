#!/usr/bin/env python3
"""Workstream A regressions for news_sources (fixtures only; no network).

Fixtures prove parser behavior only. They are not historical proof the 15 Oct
CoreWeave URL was on the sitemap during its 24h window.

The cnbc_investing RSS fixture does not prove the 15 Oct CoreWeave URL was listed
on that feed during [2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z].
"""

from __future__ import annotations

import unittest
from datetime import datetime
from urllib.parse import quote

from scripts.overnight.live_news import REQUIRED_SOURCES, acquire_current_news
from scripts.overnight.news_sources import (
    CNBC_HEADLINE_ONLY,
    CNBC_INVESTING_RSS_URL,
    CNBC_SITEMAP_URL,
    REUTERS_CREDIT_QUERY,
    _boj_boe_title_kept,
    _canonical_from_bing_link,
    discovery_surfaces,
    parse_surface,
)

BOC_PRESS_URL = "https://www.bankofcanada.ca/content_type/press/feed/"
RBA_MEDIA_URL = "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"
RBNZ_NEWS_URL = "https://www.rbnz.govt.nz/feeds/news"

EMPTY_RSS_CHANNEL = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
EMPTY_SITEMAP = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
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
        self.assertIn("rbnz_news", sources)
        self.assertIn("cnbc_investing", sources)
        self.assertNotIn("cnbc", REQUIRED_SOURCES)
        self.assertNotIn("cnbc_credit", REQUIRED_SOURCES)
        self.assertNotIn("rbnz_news", REQUIRED_SOURCES)
        self.assertNotIn("cnbc_investing", REQUIRED_SOURCES)
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


class Rss10RdfOfficialParserTests(unittest.TestCase):
    def test_boc_rdf_fixture(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns="http://purl.org/rss/1.0/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://www.bankofcanada.ca/content_type/press/feed/">
    <title>Bank of Canada — Press</title>
  </channel>
  <item rdf:about="https://www.bankofcanada.ca/2026/10/policy-rate-maintained/">
    <title>Bank of Canada maintains policy rate</title>
    <link>https://www.bankofcanada.ca/2026/10/policy-rate-maintained/</link>
    <description>The Bank held the overnight policy rate steady amid cooling inflation.</description>
    <dc:date>2026-10-17T15:00:00-04:00</dc:date>
  </item>
  <item>
    <title>Older speech announcement</title>
    <link>https://www.bankofcanada.ca/2026/10/stale-press/</link>
    <description>An older item.</description>
    <dc:date>2026-10-10T12:00:00-04:00</dc:date>
  </item>
</rdf:RDF>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface=BOC_PRESS_URL,
            cutoff=CUTOFF,
            source_name="Bank of Canada",
        )
        self.assertEqual(parsed["raw_count"], 2)
        self.assertEqual(parsed["feed_parse"], "parsed")
        self.assertEqual(len(parsed["items"]), 1)
        kept = parsed["items"][0]
        self.assertEqual(kept["headline"], "Bank of Canada maintains policy rate")
        self.assertEqual(
            kept["url"],
            "https://www.bankofcanada.ca/2026/10/policy-rate-maintained/",
        )
        self.assertEqual(kept["source_name"], "Bank of Canada")
        self.assertEqual(kept["verification_status"], "official")
        self.assertTrue(any(d["reason"] == "window" for d in parsed["dropped"]))

    def test_boc_rdf_about_without_link_text(self) -> None:
        xml = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns="http://purl.org/rss/1.0/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <item rdf:about="https://www.bankofcanada.ca/2026/10/about-only/">
    <title>About attribute only</title>
    <dc:date>2026-10-17T14:00:00-04:00</dc:date>
  </item>
</rdf:RDF>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface=BOC_PRESS_URL,
            cutoff=CUTOFF,
            source_name="Bank of Canada",
        )
        self.assertEqual(parsed["raw_count"], 1)
        self.assertEqual(
            parsed["items"][0]["url"],
            "https://www.bankofcanada.ca/2026/10/about-only/",
        )

    def test_rba_rdf_fixture(self) -> None:
        xml = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns="http://purl.org/rss/1.0/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://www.rba.gov.au/rss/rss-cb-media-releases.xml">
    <title>RBA media releases</title>
  </channel>
  <item>
    <title>Monetary policy decision</title>
    <link>https://www.rba.gov.au/media-releases/2026/mr-26-99.html</link>
    <description>At its meeting the Board decided to leave the cash rate unchanged.</description>
    <dc:date>2026-10-17T12:00:00+11:00</dc:date>
  </item>
</rdf:RDF>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface=RBA_MEDIA_URL,
            cutoff=CUTOFF,
            source_name="Reserve Bank of Australia",
        )
        self.assertEqual(parsed["feed_parse"], "parsed")
        self.assertEqual(len(parsed["items"]), 1)
        kept = parsed["items"][0]
        self.assertEqual(kept["headline"], "Monetary policy decision")
        self.assertEqual(kept["url"], "https://www.rba.gov.au/media-releases/2026/mr-26-99.html")
        self.assertEqual(kept["source_name"], "Reserve Bank of Australia")
        self.assertEqual(kept["verification_status"], "official")

    def test_rbnz_rss20_fixture(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Reserve Bank of New Zealand News Releases</title>
    <item>
      <title>Official Cash Rate unchanged</title>
      <link>https://www.rbnz.govt.nz/news-and-events/news/2026/oct/ocr-unchanged</link>
      <pubDate>Fri, 17 Oct 2026 17:00:00 -0400</pubDate>
      <description>The Monetary Policy Committee held the OCR at 3.25 percent.</description>
    </item>
  </channel>
</rss>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface=RBNZ_NEWS_URL,
            cutoff=CUTOFF,
            source_name="Reserve Bank of New Zealand",
        )
        self.assertEqual(parsed["feed_parse"], "parsed")
        self.assertEqual(len(parsed["items"]), 1)
        kept = parsed["items"][0]
        self.assertEqual(kept["headline"], "Official Cash Rate unchanged")
        self.assertEqual(kept["source_name"], "Reserve Bank of New Zealand")
        self.assertEqual(kept["verification_status"], "official")
        self.assertIn("rbnz.govt.nz", kept["url"])

    def test_empty_rss_channel_feed_parse(self) -> None:
        parsed = parse_surface(
            "rss_official",
            EMPTY_RSS_CHANNEL,
            surface=BOC_PRESS_URL,
            cutoff=CUTOFF,
            source_name="Bank of Canada",
        )
        self.assertEqual(parsed["raw_count"], 0)
        self.assertEqual(parsed["feed_parse"], "empty")

    def test_rdf_unparsed_item_no_title_or_link(self) -> None:
        xml = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns="http://purl.org/rss/1.0/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <item>
    <description>Orphan body</description>
    <dc:date>2026-10-17T12:00:00-04:00</dc:date>
  </item>
</rdf:RDF>"""
        parsed = parse_surface(
            "rss_official",
            xml.encode("utf-8"),
            surface=BOC_PRESS_URL,
            cutoff=CUTOFF,
            source_name="Bank of Canada",
        )
        self.assertEqual(parsed["raw_count"], 0)
        self.assertEqual(parsed["feed_parse"], "unparsed")


class CnbcInvestingRssParserTests(unittest.TestCase):
    def test_cnbc_investing_rss_fixture(self) -> None:
        headline = (
            "CoreWeave credit default swaps hit distress levels as investors sour on AI debt"
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Investing</title>
    <item>
      <title>{headline}</title>
      <link>{COREWEAVE_CNBC_URL}</link>
      <pubDate>Fri, 17 Oct 2026 14:00:00 -0400</pubDate>
      <description>Long article prose that must not be stored.</description>
    </item>
    <item>
      <title>Off-host story</title>
      <link>https://www.example.com/not-cnbc.html</link>
      <pubDate>Fri, 17 Oct 2026 14:00:00 -0400</pubDate>
      <description>Should not count toward raw_count.</description>
    </item>
  </channel>
</rss>"""
        parsed = parse_surface(
            "cnbc_rss",
            xml.encode("utf-8"),
            surface=CNBC_INVESTING_RSS_URL,
            cutoff=CUTOFF,
            source_name="CNBC",
        )
        self.assertEqual(parsed["raw_count"], 1)
        self.assertEqual(parsed["feed_parse"], "parsed")
        kept = parsed["items"][0]
        self.assertEqual(kept["headline"], headline)
        self.assertEqual(kept["url"], COREWEAVE_CNBC_URL)
        self.assertEqual(kept["summary"], CNBC_HEADLINE_ONLY)
        self.assertEqual(kept["source_name"], "CNBC")
        self.assertEqual(kept["verification_status"], "single_source")


class FeedHealthReceiptTests(unittest.TestCase):
    def _stub_fetcher(self, overrides: dict[str, bytes]):
        def fetcher(url: str) -> bytes:
            if url in overrides:
                return overrides[url]
            if "news-sitemap" in url or "sitemap_news" in url:
                return EMPTY_SITEMAP
            return EMPTY_RSS_CHANNEL

        return fetcher

    def test_empty_boc_feed_receipt_empty_feed_health(self) -> None:
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=self._stub_fetcher({BOC_PRESS_URL: EMPTY_RSS_CHANNEL}),
        )
        receipt = next(r for r in acquisition["receipts"] if r["source"] == "boc_press")
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["feed_health"], "empty_feed")
        self.assertEqual(receipt["candidate_count"], 0)

    def test_unparsed_rdf_receipt_zero_item_parse(self) -> None:
        bad = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <item><description>no title</description><dc:date>2026-10-17T12:00:00-04:00</dc:date></item>
</rdf:RDF>"""
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=self._stub_fetcher({BOC_PRESS_URL: bad}),
        )
        receipt = next(r for r in acquisition["receipts"] if r["source"] == "boc_press")
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["failure"], "unparsed_feed_items")
        self.assertEqual(receipt["feed_health"], "zero_item_parse")
        self.assertFalse(any(c.get("source_name") == "Bank of Canada" for c in acquisition["candidates"]))

    def test_in_window_irrelevant_official_item_is_no_relevant(self) -> None:
        xml = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Staff cafeteria menu for October</title>
    <link>https://www.bankofcanada.ca/2026/10/cafeteria-menu/</link>
    <pubDate>Fri, 17 Oct 2026 16:00:00 -0400</pubDate>
    <description>Lunch service hours.</description>
  </item>
</channel></rss>"""
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=self._stub_fetcher({BOC_PRESS_URL: xml}),
        )
        receipt = next(r for r in acquisition["receipts"] if r["source"] == "boc_press")
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["candidate_count"], 1)
        self.assertEqual(receipt["result_count"], 0)
        self.assertEqual(receipt["feed_health"], "no_relevant_candidates")

    def test_http_403_is_fetch_failed_not_empty_feed(self) -> None:
        def fetcher(url: str) -> bytes:
            if url == RBNZ_NEWS_URL:
                raise RuntimeError("HTTP Error 403: Forbidden")
            if "news-sitemap" in url or "sitemap_news" in url:
                return EMPTY_SITEMAP
            return EMPTY_RSS_CHANNEL

        acquisition = acquire_current_news(when=CUTOFF, offline=False, fetcher=fetcher)
        blocked = next(r for r in acquisition["receipts"] if r["source"] == "rbnz_news")
        empty = next(r for r in acquisition["receipts"] if r["source"] == "boc_press")
        self.assertEqual(blocked["status"], "failed")
        self.assertEqual(blocked["feed_health"], "fetch_failed")
        self.assertIn("403", blocked["failure"] or "")
        self.assertEqual(empty["status"], "ok")
        self.assertEqual(empty["feed_health"], "empty_feed")
        self.assertIsNone(empty["failure"])


if __name__ == "__main__":
    unittest.main()
