# Phase 1A repair — was the 15 Oct 2026 CoreWeave CDS story discoverable?

Check time: 2026-10-17 about 22:51 UTC. User-agent: `MarketWatch-Public-News-Discovery/1.0` (the string in `scripts/overnight/news_sources.py`). No source, test, or `accepted_public_news.json` edits. This file does not claim a feed snapshot from inside the publication window.

## Verdict

**UNRESOLVED BLOCKER.** The CNBC URL cannot be emitted by the implemented parsers. No live implemented surface returned that URL or a verified `bloomberg.com` / `reuters.com` equivalent on this check. The 7-day Bing credit RSS is empty now, and the Reuters sitemap no longer lists 15 Oct. That is not a capture from the 24 hours after publication. Injected unit-test XML that scores `show` is not recall.

Missing proof, exactly:

1. A saved response of `REUTERS_SURFACE` or of the four Bing News RSS URLs from a cutoff in `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]`.
2. A `reuters.com` canonical URL for the 15 Oct CDS or “slump” wire. Syndication pages were fetched. Search did not return a `reuters.com` story URL for those headlines.
3. Bloomberg article HTML. Direct GETs of the 15 Oct Bloomberg URLs below returned HTTP 403 (“Are you a robot?”), so their search-snippet timestamps were not confirmed from the page.

## Primary article

| Field | Value |
| --- | --- |
| URL | https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html |
| HTTP | 200 |
| `<title>` | CoreWeave credit default swaps hit distress levels as investors sour on AI debt |
| `article:published_time` | `2026-10-15T16:52:16+0000` (Thu 15 Oct 2026, 12:52:16 PM EDT) |
| `article:modified_time` | `2026-10-15T21:33:24+0000` (5:33:24 PM EDT) |

Same title and clock as `docs/news_intelligence/phase1_C_replay_corpus.md` and `docs/NEWS_INTELLIGENCE_REPAIR.md`. A second CNBC page the same afternoon, https://www.cnbc.com/2026/10/15/whats-behind-the-sell-off-in-ai-neocloud-stocks-like-coreweave-and-nebius-.html, was HTTP 200, `datePublished` `2026-10-15T16:01:19+0000`. It is also `cnbc.com`.

Parser window (`_parse_bing_rss` / `_parse_reuters_sitemap`): keep `published` with `cutoff - 24h <= published <= cutoff`. A run can keep this CNBC timestamp only if its cutoff is inside `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]`.

## What the code queries

`discovery_surfaces()` in `scripts/overnight/news_sources.py`. Bing `qft` is `interval="7"` (7 days). The parser then drops anything outside 24 hours. Bing canonical hosts are only `bloomberg.com` or `reuters.com` (`_canonical_from_bing_link`). `live_news._allowed_hosts_for_surface` then keeps `reuters.com` for `reuters_credit` and `bloomberg.com` for the other Bing surfaces. Paths containing `/video`, `/newsletter`, `/podcast`, or `/audio` are dropped. `cnbc.com` never becomes a candidate.

| Source | Kind | Query or URL |
| --- | --- | --- |
| `bloomberg` | `bing_rss` | `site:bloomberg.com (Federal Reserve OR FOMC OR inflation OR CPI OR payrolls OR Treasury OR yields OR oil OR Brent OR crude OR Hormuz OR OPEC OR FX OR dollar OR tariff OR sanctions OR "central bank" OR RBA OR "Bank of Canada" OR RBNZ OR ECB OR "Bank of Japan")` |
| `reuters` | `reuters_sitemap` | `https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml` |
| `bloomberg_credit` | `bing_rss` | `site:bloomberg.com (CoreWeave OR neocloud OR "data center" OR hyperscaler) (bond OR debt OR financing OR "credit facility" OR IPO OR CDS OR "credit default")` |
| `bloomberg_equity` | `bing_rss` | `site:bloomberg.com ("S&P 500" OR Nasdaq OR "bank stocks" OR selloff) (Fed OR yields OR dollar OR Treasury)` |
| `reuters_credit` | `bing_rss` | `site:reuters.com ("private credit" OR "high-yield" OR "credit spread" OR CLO OR "funding stress")` |
| `fed_monetary` | `rss_official` | `https://www.federalreserve.gov/feeds/press_monetary.xml` |
| `boc_press` | `rss_official` | `https://www.bankofcanada.ca/content_type/press/feed/` |
| `rba_media` | `rss_official` | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` |
| `ecb_press` | `rss_official` | `https://www.ecb.europa.eu/rss/press.html` |
| `boj_whatsnew` | `rss_official` | `https://www.boj.or.jp/en/rss/whatsnew.xml` |
| `boe_news` | `rss_official` | `https://www.bankofengland.co.uk/rss/news` |

`reuters_credit` does not name CoreWeave, CDS, or “credit default”. Official feeds are central-bank press, not CNBC or a wire. `scripts/policy_state.py` repeats the Fed monetary URL only.

## This check of those surfaces

All eleven returned HTTP 200.

| Surface | Items | CoreWeave |
| --- | --- | --- |
| `bloomberg` | 8 `<item>`s (Vietnam GDP, Russia sanctions, US interest costs, weekend audio, and others) | none |
| `bloomberg_credit` | 0 `<item>`s. Channel title is the query | none |
| `bloomberg_equity` | 0 `<item>`s | none |
| `reuters_credit` | 0 `<item>`s | none |
| `reuters` sitemap | 50 `<loc>`s. Dates: 48 on 2026-10-17, one on 2026-10-16 (`2026-10-16T17:10:18.229Z`, White House press secretary), one `2026-01-01T10:21:38.717Z` (“OFRMO Summary”) | none |
| Six official RSS feeds | Fed, ECB, BoJ, BoE, BoC, RBA items as of this fetch | none |

The 7-day `qft` still covers 15 Oct. An empty credit channel today means Bing News is not listing a matching `bloomberg.com` row for that query in the current 7-day set. It does not prove the channel was empty between 12:52 PM EDT on 15 Oct and 12:52 PM EDT on 16 Oct.

Diagnostic Bing News RSS calls, same `format=rss` and 7-day `qft`, not implemented queries: `site:bloomberg.com CoreWeave` HTTP 200, 0 items; `site:bloomberg.com CoreWeave (CDS OR "credit default" OR distress)` HTTP 200, 0 items; `site:cnbc.com "CoreWeave credit default swaps hit distress levels"` HTTP 200, 0 items. `site:reuters.com CoreWeave` HTTP 200 returned 5 unrelated `/video/` rows (Pope Leo, sea snakes, Delhi, Albania, a California wildfire), none a CoreWeave wire.

## Shadow run

`docs/news_intelligence/shadow_20261017.json`. `cutoff` `2026-10-17T18:35:55.615951-04:00` (`2026-10-17T22:35:55Z`), about 29 hours 43 minutes after the CNBC window closed. `partial` false. `bloomberg_credit`, `bloomberg_equity`, and `reuters_credit` are `ok` with `candidate_count` 0 and `result_count` 0. Watched rows have no CoreWeave headline. Shown rows are US interest costs, Russia energy sanctions, the Portuguese Ormuz headline, and Zelenskiy on sanctions. That file records a later night, not the 15–16 Oct window.

## Fixture versus live

`tests/test_news_intelligence.py` states “Injected fetchers only; no network.” `COREWEAVE_HEADLINE` is the CNBC title string. `test_coreweave_shows_without_macro_tokens` calls `score_transmission` / `recall_candidate` on that string and expects `show` / `ai_capex_credit`. `test_reuters_sitemap_keeps_coreweave_headline` feeds fake bytes: a Bing `<item>` whose link is `https://www.bloomberg.com/news/articles/2026-09-27/coreweave-cds` with `pubDate` `Sun, 27 Sep 2026 16:06:17 GMT`, and a sitemap `<loc>` `https://www.reuters.com/business/coreweave-cds-2026-09-27` with `news:publication_date` `2026-09-27T14:00:00Z`. Those URLs are not pages fetched in this check. A `show` on that fixture is parser and scorer behavior under a stub fetcher.

## Other public pages (not implemented surfaces)

Syndication of Reuters-datelined copy. No `reuters.com` HTML URL was verified.

| URL | HTTP | Visible time | Note |
| --- | --- | --- | --- |
| https://www.channelnewsasia.com/business/coreweaves-slump-puts-spotlight-debt-behind-ai-boom-6462286 | 301 then 200 | `datePublished` `2026-10-15T19:22:05+08:00` (`2026-10-15T11:22:05Z`, 7:22 AM EDT) | Title on the 200: “CoreWeave's slump spotlights growing burden of debt behind AI boom”. Phase 1C’s “07:22PM” matches the +08 clock, not EDT |
| https://finance.yahoo.com/technology/ai/articles/coreweaves-slump-puts-spotlight-debt-131324427.html | 200 | `datePublished` `2026-10-15T13:13:24Z` | Title “CoreWeave's slump puts spotlight on debt behind AI boom”. Search snippet dateline: Oct 15 (Reuters). Page body not copied here |
| https://www.channelnewsasia.com/business/analysiswhy-coreweave-in-crosshairs-ai-scare-6467006 | 200 | `datePublished` `2026-10-17T01:50:41+08:00` (`2026-10-16T17:50:41Z`, 1:50 PM EDT) | “Analysis:Why CoreWeave is in the crosshairs of the AI scare”. 58 minutes after the CNBC 24h window ended |

Search snippets only (GET failed here): Investing.com CDS page https://www.investing.com/news/stock-market-news/ai-credit-default-swap-spreads-widen-sharply-4950549 reported `Published: 2026-10-15T05:26:13Z` (“AI credit worries send default insurance to record high”); this curl got HTTP 403. US News https://money.usnews.com/investing/news/articles/2026-10-15/ai-credit-default-swap-spreads-widen-sharply timed out; the search result says “Oct. 15, 2026, at 1:18 a.m.” and “By Reuters”. Investing.com and US News timestamps for the 16 Oct “crosshairs” analysis (`2026-10-16T17:50:41Z` and `2026-10-16T17:49:00Z` in search) match the CNA clock above; those two GETs were 403 and timeout. None of these hosts are discovery surfaces.

Bloomberg URLs from web search, all HTTP 403 on direct GET, so page timestamps are **not** verified:

- https://www.bloomberg.com/jp/news/articles/2026-10-15/TMYCL1KK3NZ700 — search snippet `Published: 2026-10-15T15:18:05Z`, Japanese headline on credit risk / default probability.
- https://www.bloomberg.com/news/articles/2026-10-15/nvidia-ceo-huang-says-coreweave-improving-no-backstop-needed — search snippet `Published: 2026-10-15T15:27:52Z`, title “Nvidia CEO Downplays CoreWeave Concerns, Bolstering Stock”. That title has CoreWeave and does not contain `bond`, `debt`, `financing`, `credit facility`, `IPO`, `CDS`, or `credit default`.
- https://www.bloomberg.com/news/audio/2026-10-15/stock-movers-coreweave-jb-hunt-alcoa-podcast — `/audio` and `podcast`; path drop if it were returned.
- https://www.bloomberg.com/news/videos/2026-10-15/don-t-see-canary-in-coal-mine-for-ai-khoda-video — `/video`; path drop if it were returned.

None of those four URLs appeared in the live Bing RSS bodies above.

## Fallback already in the repo

No implemented feed is CNBC. The only RSS list the acquire path fetches is the table above.

`docs/news_intelligence/phase1_A_source_coverage.md` records `https://www.bloomberg.com/feeds/markets/news.rss` as a live public feed that was **not** added (“Keep the narrow Bing `site:bloomberg.com` query”). This check: HTTP 200, `text/xml`, 20 items. One title, “CoreWeave Woes Risk Shutting Down AI Junk Market: Credit Weekly”, `pubDate` `Sat, 17 Oct 2026 14:27:13 GMT`, link `https://www.bloomberg.com/news/articles/2026-10-17/coreweave-woes-risk-shutting-down-ai-junk-market-credit-weekly`. That timestamp is 17 Oct, after the CNBC 24h window. The current 20-item body does not show a 15 Oct CoreWeave row. The feed is not queried by `discovery_surfaces()`. FT and WSJ RSS URLs in that same doc are also not wired; they were not fetched for this note.
