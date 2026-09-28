#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.market_watch_launch.acquire import run as acquire_run
from scripts.overnight.clock import isoformat
from scripts.overnight.collect import collect_inputs
from scripts.overnight.constants import EVIDENCE_FAMILIES, ROOT
from scripts.overnight.delta import compute_delta
from scripts.overnight.evidence import freeze_snapshot
from scripts.overnight.live_news import (
    acquire_current_news,
    attribute_country_codes,
    merge_live_news,
)
from scripts.overnight.store import OvernightStore

CUTOFF = datetime.fromisoformat("2026-09-27T18:00:00-04:00")

BING_RSS_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Bing News</title>
    <item>
      <title>Iran Says Won't Soften Demands After Trump Rejects Hormuz Offer - Bloomberg.com</title>
      <link>http://www.bing.com/news/apiclick.aspx?aid=1&amp;url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2firan-says-won-t-soften-demands-after-trump-rejects-hormuz-offer</link>
      <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
      <description>Iran said it will not soften demands after President Trump rejected a Hormuz offer, and crude bounced.</description>
      <Source>Bloomberg</Source>
    </item>
    <item>
      <title>Japan Has No Space for Solar Farms Apart From Old Golf Courses - Bloomberg.com</title>
      <link>http://www.bing.com/news/apiclick.aspx?aid=2&amp;url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2fjapan-golf-solar</link>
      <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
      <description>A look at land use for solar in Japan.</description>
      <Source>Bloomberg</Source>
    </item>
  </channel>
</rss>
"""

REUTERS_FED_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.reuters.com/markets/us/fed-officials-see-inflation-progress-stalling-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T14:00:00Z</news:publication_date>
      <news:title>Fed officials see inflation progress stalling</news:title>
    </news:news>
  </url>
</urlset>
"""

REUTERS_NIO_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.reuters.com/business/autos/nio-geely-battery-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T15:00:00Z</news:publication_date>
      <news:title>NIO inks battery-swapping deal with Geely</news:title>
    </news:news>
  </url>
</urlset>
"""

REUTERS_IRAN_SIMILAR = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.reuters.com/world/middle-east/iran-refuses-soften-demands-trump-hormuz-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T15:30:00Z</news:publication_date>
      <news:title>Iran refuses to soften demands as Trump rejects Hormuz plan</news:title>
    </news:news>
  </url>
</urlset>
"""

REUTERS_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
</urlset>
"""

DIPLOMACY_BASELINE = {
    "headline": "US and Iran signal diplomatic progress on Hormuz reopening",
    "url": "https://www.reuters.com/world/us-iran-diplomatic-progress-hormuz-2026-09-26/",
    "summary": "Officials described productive talks on easing Hormuz tensions.",
    "published_at": "2026-09-26T12:00:00-04:00",
    "source_name": "Reuters",
    "verification_status": "corroborated",
    "primary_category": "geopolitics",
    "country_codes": ["US"],
}


def _news_fetcher(bing_body: str, reuters_body: str):
    def fetcher(url: str) -> bytes:
        if "bing.com" in url:
            return bing_body.encode("utf-8")
        if "reuters.com" in url:
            return reuters_body.encode("utf-8")
        raise RuntimeError(f"unexpected url {url}")

    return fetcher


class LiveNewsAcquisitionTests(unittest.TestCase):
    def test_bloomberg_video_and_newsletter_urls_are_not_results(self) -> None:
        rss = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Oil Rises as Iran Says It Won't Soften Strait of Hormuz Demands - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2foil-hormuz</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Crude bounced after Iran refused to soften Hormuz demands.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Iran Refuses to Soften Demands as Trump Rejects Hormuz Plan - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2fnewsletters%2f2026-09-27%2firan-newsletter</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>A newsletter restates the Hormuz demands.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Nomura Strategist Says the US Can Absorb More Rate Hikes - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2fvideos%2f2026-09-28%2frate-hikes-video</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>A strategist discusses rate hikes.</description>
    <Source>Bloomberg</Source>
  </item>
</channel></rss>"""
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_news_fetcher(rss, REUTERS_EMPTY),
        )
        urls = [c["url"] for c in acquisition["candidates"]]
        self.assertEqual(urls, ["https://www.bloomberg.com/news/articles/2026-09-27/oil-hormuz"])
        receipt = next(r for r in acquisition["receipts"] if r["source"] == "bloomberg")
        self.assertEqual(receipt["candidate_count"], 3)
        self.assertEqual(receipt["result_count"], 1)

    def test_offline_collect_does_not_fetch(self) -> None:
        calls = 0

        def boom(_url: str) -> bytes:
            nonlocal calls
            calls += 1
            raise RuntimeError("should not fetch")

        with tempfile.TemporaryDirectory() as temp:
            snapshot = collect_inputs(
                OvernightStore(root=ROOT, state_root=Path(temp)),
                when=CUTOFF,
                run_id="overnight-20260927-offline",
                offline=True,
                news_fetcher=boom,
            )
        self.assertTrue(snapshot["offline"])
        self.assertEqual(calls, 0)
        offline_acquire = acquire_current_news(when=CUTOFF, offline=True, fetcher=boom)
        self.assertEqual(offline_acquire["mode"], "offline")
        self.assertEqual(offline_acquire["candidates"], [])
        for receipt in offline_acquire["receipts"]:
            self.assertEqual(receipt["status"], "skipped")

    def test_hormuz_bloomberg_outranks_stale_diplomacy(self) -> None:
        fetcher = _news_fetcher(BING_RSS_FIXTURE, REUTERS_FED_SITEMAP)
        acquisition = acquire_current_news(when=CUTOFF, offline=False, fetcher=fetcher)
        self.assertTrue(any(c["source_name"] == "Bloomberg" for c in acquisition["candidates"]))
        merged = merge_live_news(
            baseline=[DIPLOMACY_BASELINE],
            live_candidates=acquisition["candidates"],
            when=CUTOFF,
        )
        bloomberg_items = [
            i
            for i in merged["items"]
            if "iran-says-won-t-soften" in (i.get("url") or "").lower()
        ]
        self.assertTrue(bloomberg_items)
        bbg = bloomberg_items[0]
        self.assertEqual(bbg["verification_status"], "single_source")
        self.assertTrue(any(e["source_name"] == "Bloomberg" for e in bbg.get("source_edges") or []))
        diplomacy = next(
            (i for i in merged["items"] if "diplomatic progress" in (i.get("headline") or "").lower()),
            None,
        )
        self.assertIsNotNone(diplomacy)
        self.assertEqual(diplomacy["verification_status"], "corroborated")
        self.assertGreater(
            bbg["market_salience"]["score"],
            diplomacy["market_salience"]["score"],
        )
        self.assertIn(bbg["id"], merged["research_supplement"]["top_market_driver_candidates"])

        with tempfile.TemporaryDirectory() as temp:
            store = OvernightStore(root=ROOT, state_root=Path(temp))
            run_id = "overnight-20260927-live"
            snapshot = collect_inputs(
                store,
                when=CUTOFF,
                run_id=run_id,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=fetcher,
            )
            urls = [i.get("url") or "" for i in snapshot["families"]["news"]["items"]]
            self.assertTrue(
                any("iran-says-won-t-soften" in u for u in urls),
                msg=f"expected Bloomberg URL in {urls}",
            )
            compute_delta(
                store,
                run_id=run_id,
                stage="pre_trader_delta",
                when=CUTOFF,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=fetcher,
            )
            freeze_snapshot(store, run_id=run_id, when=CUTOFF, reuse_open=False)
            frozen = store.read_artifact(run_id, "evidence_snapshot.json")
            frozen_news = frozen["families"]["news"]
            frozen_urls = [i.get("url") or "" for i in frozen_news["items"]]
            self.assertTrue(any("iran-says-won-t-soften" in u for u in frozen_urls))
            supplement = frozen_news["research_supplement"]
            self.assertIn(
                next(i["id"] for i in frozen_news["items"] if "iran-says-won-t-soften" in (i.get("url") or "")),
                supplement["top_market_driver_candidates"],
            )
            self.assertEqual(supplement["presentation_caps"]["last_24_hours"], 6)
            self.assertEqual(supplement["presentation_caps"]["top_market_drivers"], 3)

    def test_bloomberg_only_qualifying_item_is_single_source(self) -> None:
        fetcher = _news_fetcher(BING_RSS_FIXTURE, REUTERS_NIO_ONLY)
        acquisition = acquire_current_news(when=CUTOFF, offline=False, fetcher=fetcher)
        self.assertTrue(any(c["source_name"] == "Bloomberg" for c in acquisition["candidates"]))
        bloomberg = [c for c in acquisition["candidates"] if c["source_name"] == "Bloomberg"]
        self.assertEqual(len(bloomberg), 1)
        self.assertEqual(bloomberg[0]["verification_status"], "single_source")
        merged = merge_live_news(baseline=[], live_candidates=acquisition["candidates"], when=CUTOFF)
        self.assertEqual(len(merged["items"]), 1)
        self.assertEqual(merged["items"][0]["verification_status"], "single_source")

    def test_bloomberg_failure_is_explicit_and_partial(self) -> None:
        def fetcher(url: str) -> bytes:
            if "bing.com" in url:
                raise RuntimeError("bloomberg surface down")
            return REUTERS_FED_SITEMAP.encode("utf-8")

        acquisition = acquire_current_news(when=CUTOFF, offline=False, fetcher=fetcher)
        self.assertTrue(acquisition["partial"])
        bloomberg_receipt = next(r for r in acquisition["receipts"] if r["source"] == "bloomberg")
        self.assertEqual(bloomberg_receipt["status"], "failed")
        self.assertIn("bloomberg surface down", bloomberg_receipt["failure"] or "")
        self.assertEqual(bloomberg_receipt["result_count"], 0)
        self.assertFalse(any(c["source_name"] == "Bloomberg" for c in acquisition["candidates"]))

        with tempfile.TemporaryDirectory() as temp:
            snapshot = collect_inputs(
                OvernightStore(root=ROOT, state_root=Path(temp)),
                when=CUTOFF,
                run_id="overnight-20260927-partial",
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=fetcher,
            )
        acq = snapshot["families"]["news"]["acquisition"]
        self.assertTrue(acq["partial"])
        failed = next(r for r in acq["receipts"] if r["source"] == "bloomberg")
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(
            any(
                i.get("source_name") == "Bloomberg"
                for i in snapshot["families"]["news"]["items"]
            )
        )

    def test_same_event_keeps_bloomberg_edge(self) -> None:
        fetcher = _news_fetcher(BING_RSS_FIXTURE, REUTERS_IRAN_SIMILAR)
        acquisition = acquire_current_news(when=CUTOFF, offline=False, fetcher=fetcher)
        merged = merge_live_news(baseline=[], live_candidates=acquisition["candidates"], when=CUTOFF)
        self.assertEqual(len(merged["items"]), 1)
        item = merged["items"][0]
        self.assertEqual(item["verification_status"], "corroborated")
        families = {e["source_name"] for e in item["source_edges"]}
        self.assertIn("Bloomberg", families)
        self.assertIn("Reuters", families)
        self.assertTrue(any("bloomberg.com" in (e.get("url") or "") for e in item["source_edges"]))

    def test_stage02_live_receipt_records_bloomberg_check(self) -> None:
        checked = isoformat(CUTOFF)
        fake_families = {
            name: {"status": "fresh", "as_of": checked, "digest": f"d-{name}"}
            for name in EVIDENCE_FAMILIES
        }
        fake_families["market_state"]["data"] = {
            "status": "ok",
            "generated_at": checked,
            "rates": {"US": {"status": "ok"}, "CA": {"status": "ok"}, "AU": {"status": "ok"}},
            "fx": {"status": "ok"},
        }
        fake_families["news"]["acquisition"] = {
            "mode": "live",
            "partial": True,
            "cutoff": checked,
            "receipts": [
                {
                    "source": "bloomberg",
                    "checked_at": checked,
                    "status": "failed",
                    "candidate_count": 0,
                    "result_count": 0,
                    "failure": "bloomberg surface down",
                    "surface": "https://www.bing.com/news/search",
                },
                {
                    "source": "reuters",
                    "checked_at": checked,
                    "status": "ok",
                    "candidate_count": 2,
                    "result_count": 1,
                    "failure": None,
                    "surface": "https://www.reuters.com/arc/outboundfeeds/news-sitemap/",
                },
            ],
        }
        fake_snapshot = {"families": fake_families}

        with tempfile.TemporaryDirectory() as temp:
            ctx = {
                "root": str(ROOT),
                "overnight_store_root": temp,
                "when": CUTOFF,
                "launch_dir": temp,
            }
            launch = {
                "overnight_run_id": "overnight-20260927-stage02",
                "session_date": "2026-09-27",
                "request": {"mode": "live"},
            }
            with patch("scripts.market_watch_launch.acquire.collect_inputs", return_value=fake_snapshot):
                receipt = acquire_run(launch, ctx)
            self.assertEqual(receipt["status"], "succeeded")
            bloomberg = next(
                r
                for r in receipt["details"]["news_acquisition"]["receipts"]
                if r["source"] == "bloomberg"
            )
            self.assertEqual(bloomberg["status"], "failed")
            self.assertEqual(bloomberg["checked_at"], checked)
            self.assertIn("candidate_count", bloomberg)
            self.assertIn("result_count", bloomberg)
            self.assertIn("failure", bloomberg)

            def boom(_url: str) -> bytes:
                raise RuntimeError("network")

            fixture_launch = {
                "overnight_run_id": "overnight-20260927-fixture",
                "session_date": "2026-09-27",
                "request": {"mode": "fixture"},
            }
            with patch("scripts.overnight.live_news._default_fetcher", boom):
                fixture_receipt = acquire_run(fixture_launch, ctx)
            self.assertEqual(fixture_receipt["status"], "succeeded")
            self.assertNotIn("news_acquisition", fixture_receipt.get("details") or {})

    def test_stage02_live_mode_acquires_before_freeze(self) -> None:
        fetcher = _news_fetcher(BING_RSS_FIXTURE, REUTERS_FED_SITEMAP)
        calls: list[str] = []

        def wrapped(url: str) -> bytes:
            calls.append(url)
            return fetcher(url)

        with tempfile.TemporaryDirectory() as temp:
            ctx = {
                "root": str(ROOT),
                "overnight_store_root": temp,
                "when": CUTOFF,
                "launch_dir": temp,
            }
            launch = {
                "overnight_run_id": "overnight-20260927-stage02-live",
                "session_date": "2026-09-27",
                "request": {
                    "mode": "live",
                    "market_state_path": "data/overnight/fixtures/market_state.json",
                },
            }
            with patch("scripts.overnight.live_news._default_fetcher", wrapped):
                receipt = acquire_run(launch, ctx)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertTrue(any("bing.com" in url for url in calls))
            self.assertTrue(any("reuters.com" in url for url in calls))
            bloomberg = next(
                r for r in receipt["details"]["news_acquisition"]["receipts"] if r["source"] == "bloomberg"
            )
            self.assertEqual(bloomberg["status"], "ok")
            self.assertGreaterEqual(bloomberg["candidate_count"], 1)
            self.assertGreaterEqual(bloomberg["result_count"], 1)
            self.assertIsNone(bloomberg["failure"])
            store = OvernightStore(root=ROOT, state_root=Path(temp))
            collected = store.read_artifact("overnight-20260927-stage02-live", "collect.json")
            urls = [i.get("url") or "" for i in collected["families"]["news"]["items"]]
            self.assertTrue(any("iran-says-won-t-soften" in u for u in urls))

    def test_delta_retains_bloomberg_when_recheck_fails(self) -> None:
        good = _news_fetcher(BING_RSS_FIXTURE, REUTERS_FED_SITEMAP)

        def fail(_url: str) -> bytes:
            raise RuntimeError("bloomberg surface down")

        with tempfile.TemporaryDirectory() as temp:
            store = OvernightStore(root=ROOT, state_root=Path(temp))
            run_id = "overnight-20260927-delta-retain"
            collect_inputs(
                store,
                when=CUTOFF,
                run_id=run_id,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=good,
            )
            delta = compute_delta(
                store,
                run_id=run_id,
                stage="pre_trader_delta",
                when=CUTOFF,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=fail,
            )
        urls = [i.get("url") or "" for i in delta["families"]["news"]["items"]]
        self.assertTrue(any("iran-says-won-t-soften" in u for u in urls))
        retry = delta["families"]["news"]["acquisition"]["delta_retry"]
        failed = next(r for r in retry["receipts"] if r["source"] == "bloomberg")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("bloomberg surface down", failed["failure"] or "")

    def test_final_delta_does_not_browse_and_keeps_frozen_bloomberg(self) -> None:
        good = _news_fetcher(BING_RSS_FIXTURE, REUTERS_FED_SITEMAP)
        calls: list[str] = []

        def fail(url: str) -> bytes:
            calls.append(url)
            raise RuntimeError("post-freeze browse")

        with tempfile.TemporaryDirectory() as temp:
            store = OvernightStore(root=ROOT, state_root=Path(temp))
            run_id = "overnight-20260927-final-delta"
            collect_inputs(
                store,
                when=CUTOFF,
                run_id=run_id,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=good,
            )
            compute_delta(
                store,
                run_id=run_id,
                stage="pre_trader_delta",
                when=CUTOFF,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=good,
            )
            freeze_snapshot(store, run_id=run_id, when=CUTOFF, reuse_open=False)
            delta = compute_delta(
                store,
                run_id=run_id,
                stage="final_delta",
                when=CUTOFF,
                offline=False,
                market_state_path=ROOT / "data" / "overnight" / "fixtures" / "market_state.json",
                news_fetcher=fail,
            )
        self.assertEqual(calls, [])
        urls = [i.get("url") or "" for i in delta["families"]["news"]["items"]]
        self.assertTrue(any("iran-says-won-t-soften" in u for u in urls))


class CountryAttributionTests(unittest.TestCase):
    def test_direct_attribution_six_economies(self) -> None:
        cases = [
            ("Fed holds rates", "", ["US"]),
            ("FOMC sees inflation progress", "", ["US"]),
            ("Treasury yields rise", "", ["US"]),
            ("US payrolls beat forecasts", "", ["US"]),
            ("USD slips", "", ["US"]),
            ("U.S. inflation cools", "", ["US"]),
            ("U.S. dollar slides", "", ["US"]),
            ("u.s. payrolls beat", "", ["US"]),
            ("U.S.A. jobs", "", ["US"]),
            ("Bank of Canada holds the policy rate", "", ["CA"]),
            ("BoC watches CAD", "", ["CA"]),
            ("Canada inflation", "", ["CA"]),
            ("RBA holds the policy rate", "", ["AU"]),
            ("Australia AUD", "", ["AU"]),
            ("RBNZ holds the policy rate", "", ["NZ"]),
            ("New Zealand NZD", "", ["NZ"]),
            ("ECB holds the policy rate", "", ["EA"]),
            ("euro area inflation", "", ["EA"]),
            ("eurozone EUR", "", ["EA"]),
            ("Bank of Japan holds the policy rate", "", ["JP"]),
            ("BoJ and the yen", "", ["JP"]),
            ("Japan JPY", "", ["JP"]),
        ]
        for headline, snippet, expected in cases:
            self.assertEqual(attribute_country_codes(headline, snippet), expected, msg=headline)

    def test_direct_attribution_multi_country_and_dedup(self) -> None:
        self.assertEqual(
            attribute_country_codes(
                "RBNZ and the Fed weigh rate hikes while the Bank of Japan watches",
                "",
            ),
            ["US", "NZ", "JP"],
        )
        self.assertEqual(
            attribute_country_codes("ECB and Bank of Canada", ""),
            ["CA", "EA"],
        )
        self.assertEqual(
            attribute_country_codes("Fed and the Federal Reserve and USD", ""),
            ["US"],
        )

    def test_direct_attribution_global_and_negatives(self) -> None:
        self.assertEqual(
            attribute_country_codes("Brent crude jumps as OPEC weighs Hormuz risk", ""),
            [],
        )
        self.assertEqual(
            attribute_country_codes(
                "Iran says it will not soften demands after Trump rejects a Hormuz offer",
                "",
            ),
            [],
        )
        self.assertEqual(
            attribute_country_codes("Oil traders tell us Brent is rising", ""),
            [],
        )
        self.assertEqual(
            attribute_country_codes("Crude was fed by OPEC supply cuts", ""),
            [],
        )
        self.assertEqual(attribute_country_codes("The dollar falls as gold rises", ""), [])
        self.assertEqual(attribute_country_codes("Australian dollar slides", ""), ["AU"])
        self.assertEqual(attribute_country_codes("Australian Treasury yields rise", ""), ["AU"])
        self.assertEqual(attribute_country_codes("UK Treasury bond sale", ""), [])

    def test_direct_attribution_snippet_and_join_boundary(self) -> None:
        self.assertEqual(
            attribute_country_codes("Policy preview", "The Bank of Canada is in focus"),
            ["CA"],
        )
        self.assertEqual(attribute_country_codes("Brent", "jumps"), [])
        self.assertEqual(attribute_country_codes("euro", "zone growth"), ["EA"])

    def test_bloomberg_rss_country_codes_on_candidates(self) -> None:
        rss = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Fed Sees Inflation Cooling After CPI Surprise - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2ffed-inflation-cpi</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Fed officials said inflation progress may stall after the latest CPI print.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Bank of Canada Holds Policy Rate Steady - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2fboc-policy-rate</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Officials left the policy rate unchanged as inflation cooled.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Central Banks in Focus - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2frba-snippet-only</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>RBA holds the policy rate steady as inflation remains sticky.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Fed and ECB Both Signal Rate Hikes - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2ffed-ecb-hikes</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Central bank officials flagged further policy rate increases.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Brent Crude Jumps as OPEC Weighs Hormuz Risk - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2fbrent-hormuz</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Oil traders tracked Brent as Hormuz tensions lifted crude prices.</description>
    <Source>Bloomberg</Source>
  </item>
  <item>
    <title>Iran Says Won't Soften Demands After Trump Rejects Hormuz Offer - Bloomberg.com</title>
    <link>http://www.bing.com/news/apiclick.aspx?aid=1&amp;url=https%3a%2f%2fwww.bloomberg.com%2fnews%2farticles%2f2026-09-27%2firan-says-won-t-soften-demands-after-trump-rejects-hormuz-offer</link>
    <pubDate>Sun, 27 Sep 2026 16:06:17 GMT</pubDate>
    <description>Iran said it will not soften demands after President Trump rejected a Hormuz offer, and crude bounced.</description>
    <Source>Bloomberg</Source>
  </item>
</channel></rss>"""
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_news_fetcher(rss, REUTERS_EMPTY),
        )
        bloomberg = {c["url"]: c for c in acquisition["candidates"] if c["source_name"] == "Bloomberg"}
        self.assertEqual(
            bloomberg["https://www.bloomberg.com/news/articles/2026-09-27/fed-inflation-cpi"]["country_codes"],
            ["US"],
        )
        self.assertEqual(
            bloomberg["https://www.bloomberg.com/news/articles/2026-09-27/boc-policy-rate"]["country_codes"],
            ["CA"],
        )
        self.assertEqual(
            bloomberg["https://www.bloomberg.com/news/articles/2026-09-27/rba-snippet-only"]["country_codes"],
            ["AU"],
        )
        self.assertEqual(
            bloomberg["https://www.bloomberg.com/news/articles/2026-09-27/fed-ecb-hikes"]["country_codes"],
            ["US", "EA"],
        )
        self.assertEqual(
            bloomberg["https://www.bloomberg.com/news/articles/2026-09-27/brent-hormuz"]["country_codes"],
            [],
        )
        iran = next(
            c
            for c in acquisition["candidates"]
            if "iran-says-won-t-soften" in (c.get("url") or "")
        )
        self.assertEqual(iran["country_codes"], [])

    def test_reuters_sitemap_country_codes_on_candidates(self) -> None:
        reuters = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.reuters.com/markets/us/fed-officials-see-inflation-progress-stalling-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T14:00:00Z</news:publication_date>
      <news:title>Fed officials see inflation progress stalling</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://www.reuters.com/markets/asia/rba-boj-policy-rates-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T14:30:00Z</news:publication_date>
      <news:title>RBA and Bank of Japan hold policy rates</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://www.reuters.com/markets/nz/rbnz-policy-rate-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T14:45:00Z</news:publication_date>
      <news:title>RBNZ holds the policy rate</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://www.reuters.com/markets/europe/ecb-eurozone-inflation-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T15:00:00Z</news:publication_date>
      <news:title>ECB sees eurozone inflation stalling</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://www.reuters.com/markets/us/brent-crude-jumps-opec-hormuz-2026-09-27/</loc>
    <news:news>
      <news:publication><news:name>Reuters</news:name></news:publication>
      <news:publication_date>2026-09-27T15:15:00Z</news:publication_date>
      <news:title>Brent crude jumps as OPEC weighs Hormuz risk</news:title>
    </news:news>
  </url>
</urlset>"""
        empty_bing = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Bing</title></channel></rss>"""
        acquisition = acquire_current_news(
            when=CUTOFF,
            offline=False,
            fetcher=_news_fetcher(empty_bing, reuters),
        )
        reuters_items = {c["headline"]: c for c in acquisition["candidates"] if c["source_name"] == "Reuters"}
        self.assertEqual(
            reuters_items["Fed officials see inflation progress stalling"]["country_codes"],
            ["US"],
        )
        self.assertEqual(
            reuters_items["RBA and Bank of Japan hold policy rates"]["country_codes"],
            ["AU", "JP"],
        )
        self.assertEqual(
            reuters_items["RBNZ holds the policy rate"]["country_codes"],
            ["NZ"],
        )
        self.assertEqual(
            reuters_items["ECB sees eurozone inflation stalling"]["country_codes"],
            ["EA"],
        )
        global_item = reuters_items["Brent crude jumps as OPEC weighs Hormuz risk"]
        self.assertEqual(global_item["country_codes"], [])
        self.assertIn("/markets/us/", global_item["url"])


if __name__ == "__main__":
    unittest.main()
