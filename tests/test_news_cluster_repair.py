#!/usr/bin/env python3
"""Cluster repair regressions: facet-aware same-event matching. No network."""

from __future__ import annotations

import unittest
from datetime import datetime

from scripts.overnight.news_cluster import cluster_and_rank, merge_live_news

CUTOFF = datetime.fromisoformat("2026-09-27T18:00:00-04:00")

# Same-facet headlines that share 4 tokens can still merge below Jaccard 0.55.
# That residual is intentional for the CDS pair and is not claimed to separate
# every distinct incident.


def _news_item(
    *,
    headline: str,
    summary: str = "",
    url: str,
    published_at: str,
    source_name: str,
    verification_status: str = "single_source",
    primary_category: str = "macro",
    country_codes: list[str] | None = None,
) -> dict:
    return {
        "headline": headline,
        "summary": summary,
        "url": url,
        "published_at": published_at,
        "source_name": source_name,
        "verification_status": verification_status,
        "primary_category": primary_category,
        "country_codes": country_codes or ["US"],
    }


class NewsClusterRepairTests(unittest.TestCase):
    def test_hormuz_supply_does_not_merge_with_diplomacy(self) -> None:
        supply = _news_item(
            headline="Trump rejects Iran Hormuz oil tanker supply demands",
            url="https://www.reuters.com/world/trump-rejects-hormuz-supply",
            published_at="2026-09-27T16:00:00-04:00",
            source_name="Reuters",
        )
        diplomacy = _news_item(
            headline="Trump diplomatic Iran Hormuz oil tanker supply reopening",
            url="https://www.reuters.com/world/trump-diplomatic-hormuz-reopening",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Reuters",
        )
        out = cluster_and_rank([], [supply, diplomacy], CUTOFF)
        self.assertEqual(len(out["items"]), 2)
        ids = {i["id"] for i in out["items"]}
        self.assertEqual(len(ids), 2)

    def test_coreweave_cds_wires_merge(self) -> None:
        a = _news_item(
            headline=(
                "CoreWeave credit default swaps hit distress levels as investors sour on AI debt"
            ),
            url="https://www.bloomberg.com/news/articles/2026-09-27/coreweave-cds-distress",
            published_at="2026-09-27T16:00:00-04:00",
            source_name="Bloomberg",
        )
        b = _news_item(
            headline="CoreWeave CDS hit distress as investors sour on AI debt",
            url="https://www.reuters.com/business/coreweave-cds-distress-2026-09-27/",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Reuters",
        )
        out = merge_live_news(baseline=[], live_candidates=[a, b], when=CUTOFF)
        self.assertEqual(len(out["items"]), 1)
        urls = {e["url"] for e in out["items"][0]["source_edges"]}
        self.assertIn(a["url"], urls)
        self.assertIn(b["url"], urls)

    def test_coreweave_cds_does_not_merge_unrelated_ai(self) -> None:
        coreweave = _news_item(
            headline="CoreWeave investors sour on AI debt as credit distress hits record levels",
            url="https://www.bloomberg.com/news/articles/2026-09-27/coreweave-ai-debt",
            published_at="2026-09-27T16:00:00-04:00",
            source_name="Bloomberg",
        )
        nvidia = _news_item(
            headline="Nvidia investors sour on AI debt as chip distress hits record levels",
            url="https://www.reuters.com/business/nvidia-ai-debt-2026-09-27/",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Reuters",
        )
        out = cluster_and_rank([], [coreweave, nvidia], CUTOFF)
        self.assertEqual(len(out["items"]), 2)
        for item in out["items"]:
            self.assertNotEqual(item.get("verification_status"), "corroborated")

    def test_india_trade_gap_does_not_merge_oil_shock(self) -> None:
        trade = _news_item(
            headline="India September trade gap widens on higher oil import bill",
            summary="India's trade gap expanded on the import bill.",
            url="https://www.bloomberg.com/news/articles/2026-09-27/india-trade-gap",
            published_at="2026-09-27T17:00:00-04:00",
            source_name="Bloomberg",
        )
        oil = _news_item(
            headline="India September oil gap widens on higher Hormuz",
            summary="Crude supply halted in the Strait of Hormuz.",
            url="https://www.reuters.com/world/india-hormuz-oil-2026-09-27/",
            published_at="2026-09-27T14:00:00-04:00",
            source_name="Reuters",
        )
        oil_reuters_url = oil["url"]

        def assert_split(
            result: dict,
            *,
            expected_oil_url: str,
            expected_oil_headline: str,
        ) -> None:
            shown = result["items"]
            self.assertEqual(len(shown), 1)
            self.assertEqual(shown[0]["headline"], expected_oil_headline)
            self.assertEqual(shown[0]["url"], expected_oil_url)
            trade_row = next(
                r for r in result["diagnostics_rows"] if r["headline"] == trade["headline"]
            )
            self.assertEqual(trade_row["stage"], "relevance_rejection")
            self.assertEqual(trade_row["reason"], "incidental_link_only")
            oil_row = next(
                r for r in result["diagnostics_rows"] if "Hormuz" in (r["headline"] or "")
            )
            self.assertEqual(oil_row["stage"], "shown")
            edge_urls = {e.get("url") for e in shown[0].get("source_edges") or []}
            self.assertNotIn(trade["url"], edge_urls)

        oil_bbg = dict(oil)
        oil_bbg["source_name"] = "Bloomberg"
        oil_bbg["published_at"] = "2026-09-27T17:30:00-04:00"
        oil_bbg["url"] = "https://www.bloomberg.com/news/articles/2026-09-27/india-hormuz-oil"

        trade_newer = dict(trade)
        trade_newer["published_at"] = "2026-09-27T17:30:00-04:00"
        assert_split(
            cluster_and_rank([], [trade_newer, oil], CUTOFF),
            expected_oil_url=oil_reuters_url,
            expected_oil_headline=oil["headline"],
        )

        trade_wire = dict(trade)
        trade_wire["source_name"] = "Reuters"
        trade_wire["published_at"] = "2026-09-27T14:00:00-04:00"
        trade_wire["url"] = "https://www.reuters.com/world/india-trade-gap-2026-09-27/"
        assert_split(
            cluster_and_rank([], [trade_wire, oil_bbg], CUTOFF),
            expected_oil_url=oil_bbg["url"],
            expected_oil_headline=oil_bbg["headline"],
        )

    def test_india_export_halt_does_not_merge_into_trade_gap(self) -> None:
        trade = _news_item(
            headline="India September trade gap widens on higher oil import bill",
            summary="India's trade gap expanded on the import bill.",
            url="https://www.bloomberg.com/news/articles/2026-09-27/india-trade-gap-only",
            published_at="2026-09-27T17:00:00-04:00",
            source_name="Bloomberg",
        )
        shock = _news_item(
            headline="India oil-export halt widens the trade deficit",
            summary="Crude exports halted and Brent jumped.",
            url="https://www.reuters.com/world/india-export-halt-2026-09-27/",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Reuters",
        )
        out = cluster_and_rank([], [trade, shock], CUTOFF)
        shown = {item["headline"] for item in out["items"]}
        self.assertIn(shock["headline"], shown)
        self.assertNotIn(trade["headline"], shown)
        edges = {edge.get("url") for item in out["items"] for edge in item.get("source_edges") or []}
        self.assertNotIn(trade["url"], edges)

    def test_vietnam_gdp_does_not_merge_g10_oil(self) -> None:
        gdp = _news_item(
            headline="Vietnam GDP growth target of at least 10 percent this year",
            summary="Parliament GDP target.",
            url="https://www.bloomberg.com/news/articles/2026-09-27/vietnam-gdp",
            published_at="2026-09-27T16:00:00-04:00",
            source_name="Bloomberg",
        )
        oil = _news_item(
            headline="Vietnam oil growth target of at least 10 percent this year",
            summary="Crude exports halted and Brent rose.",
            url="https://www.reuters.com/world/vietnam-oil-growth-2026-09-27/",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Reuters",
        )
        out = cluster_and_rank([], [gdp, oil], CUTOFF)
        headlines = {i["headline"] for i in out["items"]}
        self.assertIn(oil["headline"], headlines)
        reasons = {r["reason"] for r in out["diagnostics_rows"]}
        self.assertIn("oil_supply_shock", reasons)
        self.assertIn("local_non_g10_macro", reasons)
        gdp_diag = next(
            r for r in out["diagnostics_rows"] if r["headline"] == gdp["headline"]
        )
        self.assertEqual(gdp_diag["stage"], "relevance_rejection")
        self.assertEqual(gdp_diag["reason"], "local_non_g10_macro")
        oil_item = next(i for i in out["items"] if "oil growth" in i["headline"])
        edge_headlines = {e.get("headline") for e in oil_item.get("source_edges") or []}
        self.assertNotIn(gdp["headline"], edge_headlines)

    def test_ormuz_alias_merges_with_hormuz_wire(self) -> None:
        hormuz = _news_item(
            headline="Strait of Hormuz tanker mines",
            url="https://www.reuters.com/world/hormuz-mines",
            published_at="2026-09-27T16:00:00-04:00",
            source_name="Reuters",
        )
        ormuz = _news_item(
            headline="Strait of Ormuz tanker mines",
            url="https://www.bloomberg.com/news/articles/2026-09-27/ormuz-mines",
            published_at="2026-09-27T15:00:00-04:00",
            source_name="Bloomberg",
        )
        out = merge_live_news(baseline=[], live_candidates=[hormuz, ormuz], when=CUTOFF)
        self.assertEqual(len(out["items"]), 1)

    def test_same_event_refusal_wires_still_merge(self) -> None:
        bloomberg = _news_item(
            headline="Iran Says Won't Soften Demands After Trump Rejects Hormuz Offer",
            summary=(
                "Iran said it will not soften demands after President Trump rejected "
                "a Hormuz offer, and crude bounced."
            ),
            url=(
                "https://www.bloomberg.com/news/articles/2026-09-27/"
                "iran-says-won-t-soften-demands-after-trump-rejects-hormuz-offer"
            ),
            published_at="2026-09-27T16:06:17-04:00",
            source_name="Bloomberg",
        )
        reuters = _news_item(
            headline="Iran refuses to soften demands as Trump rejects Hormuz plan",
            url="https://www.reuters.com/world/middle-east/iran-refuses-soften-demands-trump-hormuz-2026-09-27/",
            published_at="2026-09-27T15:30:00-04:00",
            source_name="Reuters",
        )
        out = merge_live_news(baseline=[], live_candidates=[bloomberg, reuters], when=CUTOFF)
        self.assertEqual(len(out["items"]), 1)
        families = {e["source_name"] for e in out["items"][0]["source_edges"]}
        self.assertIn("Bloomberg", families)
        self.assertIn("Reuters", families)


if __name__ == "__main__":
    unittest.main()
