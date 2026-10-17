# Repair phase 1B — Bing / Reuters source coverage

Diagnosis only, 2026-10-17. Current engine is `discovery_surfaces()` plus `acquire_current_news`. `docs/news_intelligence/phase1_A_source_coverage.md` still describes the old per-source cap of 8 and the merged cap of 16. Those caps are gone. This note uses the code on this branch.

No article HTML was stored. HTTP checks used `MarketWatch-Public-News-Discovery/1.0` and kept only status, content type, item counts, and channel or publication names.

## 1. Queries, windows, caps, failure semantics

Four Bing News RSS GETs and one Reuters sitemap. There is no Bing News API and no key. `acquire_current_news` fetches every row from `discovery_surfaces()` (`scripts/overnight/live_news.py` 252, 281–289). `BLOOMBERG_SURFACE` (`live_news.py` 23–25) is the same macro URL and is not what the loop fetches.

| Receipt `source` | Query or URL | Kind | Hosts kept |
| --- | --- | --- | --- |
| `bloomberg` | `site:bloomberg.com (Federal Reserve OR FOMC OR inflation OR CPI OR payrolls OR Treasury OR yields OR oil OR Brent OR crude OR Hormuz OR OPEC OR FX OR dollar OR tariff OR sanctions OR "central bank" OR RBA OR "Bank of Canada" OR RBNZ OR ECB OR "Bank of Japan")` | `bing_rss` | `bloomberg.com` |
| `bloomberg_credit` | `site:bloomberg.com (CoreWeave OR neocloud OR "data center" OR hyperscaler) (bond OR debt OR financing OR "credit facility" OR IPO OR CDS OR "credit default")` | `bing_rss` | `bloomberg.com` |
| `bloomberg_equity` | `site:bloomberg.com ("S&P 500" OR Nasdaq OR "bank stocks" OR selloff) (Fed OR yields OR dollar OR Treasury)` | `bing_rss` | `bloomberg.com` |
| `reuters_credit` | `site:reuters.com ("private credit" OR "high-yield" OR "credit spread" OR CLO OR "funding stress")` | `bing_rss` | `reuters.com` |
| `reuters` | `https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml` | `reuters_sitemap` | sitemap `loc`, publication name must be `Reuters` |

Query strings: `scripts/overnight/news_sources.py` 19–39. Bing URL shape: `https://www.bing.com/news/search?q={quote(query)}&format=rss&qft=interval%3d%227%22` (`news_sources.py` 43, 55–57). `qft` is Bing’s 7-day news interval. The parser then applies its own 24-hour window, so the extra days are fetched and dropped.

Window, every parser: `window_start = cutoff - 24h`. A row is dropped when `published` is missing, `published > cutoff`, or `published < window_start` (`news_sources.py` 278, 306–313, 338, 365–373, 464, 552–558). Both endpoints are inclusive. Reason is `window` or `unparsed_date`. Those drops are `relevance_rejection` on the acquire result (`live_news.py` 299–306). The receipt stays `ok`.

Other mechanical drops before recall:

- Bing link with no `url=` parameter, or a host other than `bloomberg.com` / `reuters.com`, is skipped with `continue` and is not in `raw_count` (`news_sources.py` 186–198, 293–299).
- A canonical Reuters URL inside a Bloomberg Bing feed, or the reverse, is also skipped: `_allowed_hosts_for_surface` is `reuters.com` only for `reuters_credit` and `bloomberg.com` for the other three (`live_news.py` 196–200).
- Path contains `/video`, `/newsletter`, `/podcast`, or `/audio` → `path_drop` (`news_sources.py` 254–261, 300–303).
- Reuters `news:name` other than `Reuters` → `publication_name` (`news_sources.py` 375–378). Summary is always the constant `REUTERS_HEADLINE_ONLY` (`news_sources.py` 41, 360).

Caps, in order:

1. **Newest 60 per surface**, after stage-1 recall, sorted by `published_at` descending. Rows past 60 are `discovery_failure` / `safety_ceiling`. The receipt is still `ok` and `result_count` is 60 (`live_news.py` 215–238). Test: 61 in-window Fed items → `result_count` 60 and one ceiling drop (`tests/test_news_intelligence.py` 222–240). The 2026-10-17 shadow did not bind it (`discovery_failure` 0).
2. **Score cap 24** after clustering, `show` and `assess` only, rank is salience then `published_at` (`scripts/overnight/news_cluster.py` 27, 246–248). That is `presentation_suppression`, not the safety ceiling.
3. Recorded HTML caps 6 and 3 are not applied in acquire (`news_cluster.py` 277). The refresh script still applies them later (`docs/NEWS_INTELLIGENCE_REPAIR.md`).

`candidate_count` is parser `raw_count` (after the silent host skip, before recall and the ceiling). `result_count` is survivors after recall and the ceiling (`live_news.py` 310–316).

Failure is per surface, not per run:

- An exception on one URL sets that receipt to `failed`, `result_count` 0, `failure` = `str(exc)`. The loop continues (`live_news.py` 322–333). HTTP errors from `urlopen` take this path. Timeout is 20s (`live_news.py` 161–172).
- `partial` is true only when one of `bloomberg` and `reuters` is `failed` and the other is `ok` (`live_news.py` 27, 345–348). Credit, equity, and official failures do not set it. Both required sources failed → `partial` false. Offline → every receipt `skipped`, `partial` false, no fetch (`live_news.py` 254–272).
- A zero-item RSS or a sitemap that parses is `ok`. Empty is not `failed`.

Shadow `docs/news_intelligence/shadow_20261017.json` (cutoff `2026-10-17T18:35:55-04:00`, `partial` false): `bloomberg` 8→2, `reuters` 50→2, and `bloomberg_credit`, `bloomberg_equity`, `reuters_credit` all `ok` / `candidate_count` 0 / `result_count` 0 / `failure` null. Fed 15, ECB 15, BoJ 51, and BoE 50 were `ok` with `result_count` 0 (window or BoJ/BoE title filter). BoC and RBA were `ok` with `candidate_count` 0.

This pass, same four Bing URLs and the Reuters sitemap, all HTTP 200 `application/xml`. Item counts in the fetched body: macro 8 (decoded hosts `www.bloomberg.com`), credit 0, equity 0, `reuters_credit` 0, sitemap 50 `url` tags, every `news:name` `Reuters`. That is the empty-as-`ok` mode, live, not only in the shadow file.

## 2. Why those three stories stay invisible

**CNBC.** No CNBC surface exists. `discovery_surfaces()` is Bloomberg Bing, Reuters sitemap, two more Bloomberg Bing queries, one Reuters Bing query, and six official RSS feeds (`news_sources.py` 61–140). A CNBC URL cannot become a candidate: `_canonical_from_bing_link` returns `None` unless the host ends with `bloomberg.com` or `reuters.com` (`news_sources.py` 196–198), and that `None` is a silent `continue` (`news_sources.py` 294–295). The Oct 15 CoreWeave CDS story is a CNBC page (`docs/NEWS_INTELLIGENCE_REPAIR.md`, `docs/news_intelligence/phase1_C_replay_corpus.md`). The shadow did not show it. Scoring can mark that headline `show` if some other path hands the row in (`tests/test_news_intelligence.py` 93–98, overlay fixture uses a CNBC URL at line 155). Live discovery never does. The 24-hour window is a second miss for that story: published Thu Oct 15 2026 12:52 PM EDT, shadow cutoff Oct 17 18:35 ET. The live CNBC news sitemap’s oldest `n:publication_date` on this check was `2026-10-15T18:55:01-04:00`, so that 12:52 PM story was not in the sitemap body either.

**Reuters body only.** The sitemap parser never reads a description. `summary` is the fixed headline-only string (`news_sources.py` 360–383). `recall_candidate` and `score_transmission` see headline plus summary only (`scripts/overnight/news_relevance.py` 653–654, 667–669). A transmission word that exists only in the article fails stage-1 recall when the title has no positive class, and it cannot change the score when the title does. China stimulus is `show` in tests only because the crude-demand sentence is passed in as the summary (`tests/test_news_intelligence.py` 30, 141–144). On the live sitemap that sentence is not present. Repair doc states the same limit (`docs/NEWS_INTELLIGENCE_REPAIR.md`).

**Bloomberg markets firehose.** Not a discovery surface. A story that is only on `https://www.bloomberg.com/feeds/markets/news.rss` is invisible unless one of the three `site:bloomberg.com` Bing queries also returns it inside 24 hours and it survives host, path, and recall. Phase 1A already refused this firehose as volume-max. This pass: `https://feeds.bloomberg.com/markets/news.rss` redirected there and returned HTTP 200 `text/xml`, 20 `<item>` tags. It is a real RSS feed. It is still the unfiltered markets feed, so it should not be added as a fifth Bloomberg surface.

## 3. Are the Bing endpoints actually called?

Yes. Default fetcher is `urllib.request.urlopen` on the surface URL with the discovery user-agent (`live_news.py` 161–172, 275–289). Smoke uses `fetcher=None`, so it takes that path (`scripts/live_news_discovery_smoke.py` 25). The stage-02 live test patches `_default_fetcher` and asserts a `bing.com` URL and a `reuters.com` URL were requested (`tests/test_live_news_acquisition.py` 382–409).

What is called is only `www.bing.com/news/search?...&format=rss`. No other Bing host appears in `scripts/`.

Known empty-success mode: parse success with zero `<item>` tags yields `status=ok`, `result_count` 0, `failure` null (`live_news.py` 310–319; empty channel short-circuit at `news_sources.py` 284–285). Shadow and this pass both show that for `bloomberg_credit`, `bloomberg_equity`, and `reuters_credit`. An empty body is not evidence the query is dead, and it is not evidence a historical headline was absent from Bing outside this response.

## 4. Public fallbacks already in this repo

Wired by the news engine today (`news_sources.py` 99–139), same 24-hour window, metadata only:

| Source id | URL in code |
| --- | --- |
| `fed_monetary` | `https://www.federalreserve.gov/feeds/press_monetary.xml` |
| `boc_press` | `https://www.bankofcanada.ca/content_type/press/feed/` |
| `rba_media` | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` |
| `ecb_press` | `https://www.ecb.europa.eu/rss/press.html` |
| `boj_whatsnew` | `https://www.boj.or.jp/en/rss/whatsnew.xml` (title filter) |
| `boe_news` | `https://www.bankofengland.co.uk/rss/news` (title filter) |

The same Fed URL is the policy-rate feed in `scripts/policy_state.py` line 35. That parser keeps FOMC statement pages for a numeric family. It does not discover CNBC or wire stories.

No other RSS, sitemap, or CNBC feed URL is referenced under `scripts/`. `data/` launch artifacts repeat the Bing macro URL and `REUTERS_SURFACE` only. CNBC URLs under `data/pm/` are article links inside old packets, not feeds.

Phase 1A verified additional official feeds (Fed speeches, H.8, SLOOS, BoC FSR, RBA FSR, BLS, BEA, EIA, SEC 8-K Atom) and recorded RBNZ news as HTTP 403. Those URLs are in `docs/news_intelligence/phase1_A_source_coverage.md`. They are not in `scripts/` except the Fed monetary feed above. This pass did not re-fetch that list. Fed monetary was re-checked: HTTP 200 `text/xml`, RSS.

## 5. Minimal repair, and what was HTTP-checked

No new credential, ACP edit, workflow edit, or CI change is required for any of the following. None of them is implemented here.

**Smallest change: document the limit.** State in the repair note that discovery cannot see CNBC, cannot see Reuters body text, treats Bing `result_count` 0 as success, and does not read the Bloomberg markets firehose. The Oct 15 CNBC CoreWeave story is outside the 24-hour window on an Oct 17 evening cutoff even if a CNBC surface is added later.

**CNBC news sitemap, verified, not in the repo.** `https://www.cnbc.com/robots.txt` HTTP 200 lists `https://www.cnbc.com/sitemap_news.xml`. That URL is HTTP 200 `text/xml`, a Google news sitemap (`xmlns:n` news namespace), 85 `n:title` / `n:publication_date` rows, every `n:name` is `CNBC`, dates from `2026-10-15T18:55:01-04:00` through `2026-10-17T15:35:18-04:00`. It is a feed, not a 403 or a paywall. It is not a drop-in for `_parse_reuters_sitemap`: that parser requires `news:name` `Reuters` and writes `source_name` Reuters (`news_sources.py` 375–385). A repair would add one non-required surface and a publisher check for `CNBC`. Do not add it to `REQUIRED_SOURCES`, or `partial` changes meaning. `https://www.cnbc.com/sitemap.xml` is HTTP 404. `https://www.cnbc.com/sitemapAll.xml` is HTTP 200 and a sitemap index (13 child sitemaps). That index is historical volume. Do not add it.

**CNBC section RSS, verified as probes, not linked from this repo or from `robots.txt`.** Each returned HTTP 200 `application/xml` and an `<rss` channel:

| URL | Channel title |
| --- | --- |
| `https://www.cnbc.com/id/100003114/device/rss/rss.html` | US Top News and Analysis |
| `https://www.cnbc.com/id/10000664/device/rss/rss.html` | Finance |
| `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664` | Finance (same section, other host) |
| `https://www.cnbc.com/id/15839135/device/rss/rss.html` | Earnings |
| `https://www.cnbc.com/id/19854910/device/rss/rss.html` | Tech |

These are section firehoses. Prefer the news sitemap, or the Finance RSS alone, over adding Top News, Earnings, and Tech together. The homepage HTML did not expose a `rel=alternate` RSS href in this check.

**An extra Bing query does nothing until the host gate moves.** A probe `site:cnbc.com (CoreWeave OR CDS OR "credit default" OR Fed OR inflation OR oil)` with the same `format=rss` and 7-day `qft` returned HTTP 200 `application/xml` and `<item>` tags in the first 2.5 KB. Current `_canonical_from_bing_link` would drop every CNBC link before `raw_count`, so the receipt would be `ok` / 0. A useful query also has to extend the canonical host tuple and `_allowed_hosts_for_surface`. Keep it off `REQUIRED_SOURCES`.

**Do not add** the Bloomberg markets firehose (HTTP 200, 20 items, unfiltered). Do not fetch article HTML for CNBC or Reuters to fill the body gap.

Not re-checked this pass: the phase 1A official list other than Fed monetary, RBNZ, FT, WSJ, OPEC, OFAC, and Treasury. Their earlier status codes stay in phase 1A.
