# Phase 1A — lawful public source coverage

Checked 2026-10-17 against `scripts/overnight/live_news.py`. Direct GETs used `MarketWatch-Public-News-Discovery/1.0`. No article HTML was retrieved. A URL below is **verified live** only when that GET returned a feed or sitemap body. Paths that were not linked from an official index are marked as probes.

## Verified defects

Discovery is two surfaces only (`acquire_current_news`, lines 499–519):

| Defect | Where |
| --- | --- |
| Bloomberg is one Bing News RSS macro query, 7-day `qft=interval="7"`, `site:bloomberg.com` | `BLOOMBERG_QUERY` 17–21, `BLOOMBERG_SURFACE` 22–24 |
| Reuters is the public news sitemap, not an RSS wire | `REUTERS_SURFACE` line 25 |
| Positive token gate. A headline with no listed token is dropped. Reuters never sees a story snippet: the summary is the constant headline-only string, so the gate is the title alone | `MARKET_TOKENS` 29–67; `REUTERS_HEADLINE_ONLY` line 91; `_text_matches_market_gate` 227–231; Reuters call 378–379 |
| Each parser keeps the 8 newest matches inside 24 hours | `_parse_bing_rss` line 353 `out[:8]`; `_parse_reuters_sitemap` line 402 `out[:8]` |
| Merged baseline plus live items are cut to 16 before review. Live-only non-Bloomberg rows are dropped first | `_cap_items` 680–718, called at 758 |
| `central_bank_research` is always empty from this path. `OFFICIAL_SOURCES` includes Bank of England, but nothing fetches an official feed, and country attribution has no GB/UK | lines 75–85, 93–135, 777 |
| Salience tier-3 repeats the same macro/energy list and does not score credit, equity stress, gas, or BoE | line 585 |

`MARKET_TOKENS` / `BLOOMBERG_QUERY` versus the missed classes:

| Class | In `BLOOMBERG_QUERY` (17–21) | In `MARKET_TOKENS` (29–67) |
| --- | --- | --- |
| Fed, CPI, payrolls, Treasury, yields, oil, Brent, Hormuz, OPEC, FX, dollar, tariff, sanctions, RBA, BoC, RBNZ, ECB, BoJ | yes | yes (plus `ppi`, `unemployment`, `wti`, `lng`, `pipeline`, `boc`, `boj`, `rate cut` / `rate hike`, `recession`, `gdp`) |
| Bank of England / BoE / gilt | no | no |
| Credit, private credit, CLO, high-yield, funding, repo, bank lending | no | no |
| AI capex, CoreWeave-class debt or equity, data-center financing, IPO | no | no |
| Index, megacap, or bank-equity stress | no | no (`fx` / `dollar` / `yield` pass only if those words are also present) |
| Gas beyond the token `lng`, copper, freight, shipping | no (`lng` is not in the query) | `lng` and `pipeline` only. `ENERGY_TOKENS` (line 71) is oil / crude / brent / hormuz / opec, so an LNG-only title is category `macro` |

The noise list (`podcast`, `golf`, `celebrity`, lines 69 and 252–254) is not what drops credit or equity stories. Omission from `MARKET_TOKENS` is.

## Recommended discovery surfaces

Checked 2026-10-17. “Lawful constraint” means metadata only: title, link, date, publisher summary if the feed includes one. Do not GET the article URL.

| Source | URL | Covers | Status | Lawful constraint |
| --- | --- | --- | --- | --- |
| Fed monetary press | `https://www.federalreserve.gov/feeds/press_monetary.xml` | FOMC statements and other monetary releases. Already the policy parser feed in `scripts/policy_state.py` line 35, which keeps only “issues FOMC statement” items (line 248) | **verified live** HTTP 200 `text/xml` RSS 2.0. A separate WebFetch of the same URL returned HTTP 500; the direct GET did not | Official RSS. News may link the item. Do not re-parse the funds-rate range; `policy_state.py` owns that |
| Fed all press / speeches | `https://www.federalreserve.gov/feeds/press_all.xml`, `https://www.federalreserve.gov/feeds/speeches.xml` | Both linked from `https://www.federalreserve.gov/feeds/feeds.htm` (HTTP 200) | **verified live** HTTP 200 `text/xml` RSS 2.0 | Prefer monetary + speeches over `press_all` so enforcement and bank orders do not fill the 16-item cap |
| Fed H.8 DDP | `https://www.federalreserve.gov/feeds/h8.xml` | Weekly commercial-bank assets and liabilities **announcement**, linked from the feeds index. The HTML release is `https://www.federalreserve.gov/releases/h8/current/default.htm` (linked, not fetched as a table) | **verified live** HTTP 200 `text/xml`, RDF | Announcement metadata only. Not a private-credit tape. Do not ingest the H.8 grid in the news path |
| Fed SLOOS DDP | `https://www.federalreserve.gov/feeds/sloos.xml` | Senior loan officer survey **release announcements** | **verified live** HTTP 200 `text/xml`; title is the DDP SLOOS feed | Same: link the release. The survey numbers are not a news body |
| BoC press | `https://www.bankofcanada.ca/content_type/press/feed/` | Policy and other press. Listed on `https://www.bankofcanada.ca/rss-feeds/` (HTTP 200) | **verified live** HTTP 200 `application/rss+xml` | Official RSS. FSR feed `…/content_type/fsr/feed/` also HTTP 200; use it for the financial-system review, not every content type on that index |
| RBA media / FSR | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml`, `https://www.rba.gov.au/rss/rss-cb-fsr.xml` | Decisions and the Financial Stability Review. Both hrefs are on `https://www.rba.gov.au/rss/index.html` (HTTP 200) | **verified live** HTTP 200 `text/xml` | Speeches feed exists on the same index (`rss-cb-speeches.xml`, also HTTP 200). Skip exchange-rate and webcast feeds |
| ECB press | `https://www.ecb.europa.eu/rss/press.html` | Press, speeches, interviews. Linked from `https://www.ecb.europa.eu/home/html/rss.en.html` (HTTP 200) | **verified live** HTTP 200 `application/rss+xml` | `…/rss/statpress.html` is also HTTP 200 and overlaps the ECB SDMX data family. Do not add it as a second macro store |
| BoJ what’s new | `https://www.boj.or.jp/en/rss/whatsnew.xml` | Linked from `https://www.boj.or.jp/en/tips.htm` (HTTP 200) | **verified live** HTTP 200 `application/xml` RSS 2.0 | High volume (statistics plus speeches). Title-filter to monetary policy. `…/en/rss/statistics.xml` (HTTP 200) duplicates BoJ stats already ingested |
| BoE news | `https://www.bankofengland.co.uk/rss/news` | Linked from `https://www.bankofengland.co.uk/rss` (HTTP 200) | **verified live** HTTP 200 `text/xml` RSS 2.0 | G10 transmission via gilts and GBP. `…/rss/speeches` also HTTP 200. Skip statistics and prudential-regulation firehoses |
| RBNZ news | `https://www.rbnz.govt.nz/news-and-events/news` | OCR and media releases, per the bank’s “how we release information” page | **failed** HTTP 403 HTML (“Website unavailable”) from this environment. No RSS href was found in search or on a fetched RBNZ page | Do not scrape the news HTML. Same host already 403s on the B2 workbook (`docs/MARKET_STATE_FEED_V1.md`). Until a feed is verified, RBNZ stays a wire term (`RBNZ` is already in the Bing query and the token list) |
| BLS CPI / payrolls | `https://www.bls.gov/feed/cpi.rss`, `https://www.bls.gov/feed/empsit.rss` | Release headlines. Linked from `https://www.bls.gov/feed/` (HTTP 200). PPI feed `…/ppi.rss` also HTTP 200 | **verified live** HTTP 200 Atom | Link-out only. Prints already enter through BLS API and FRED. Do not add `bls_latest.rss` (also HTTP 200): it is a latest-numbers firehose |
| BEA | `https://www.bea.gov/rss` → `https://apps.bea.gov/rss/rss.xml` | BEA releases | **verified live** HTTP 200 `text/xml` RSS 2.0 after redirect. Not copied from a separate index page in this pass | Link-out. GDP, PCE, income, and spending are already FRED/BEA data families |
| EIA | `https://www.eia.gov/rss/press_rss.xml`, `https://www.eia.gov/rss/todayinenergy.xml` | Listed on `https://www.eia.gov/tools/rssfeeds/` (HTTP 200) | **verified live** HTTP 200 `text/xml` | Press feed for oil/product headlines. `todayinenergy` is commentary-volume; do not add it wholesale. No natural-gas-specific feed was listed on that index |
| SEC EDGAR latest 8-K | `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&start=0&count=10&output=atom` | Pattern is the documented latest-filings Atom on `https://www.sec.gov/about/rss-feeds` (the page’s example is `type=10-k`; this check set `type=8-K`) | **verified live** HTTP 200 `application/atom+xml` | Metadata only. Declared user-agent. SEC fair-access cap is 10 requests/second. Filter to a short issuer list. Do not download filing bodies. An unfiltered 8-K feed is volume-max |
| Existing wires | Bing URL in `BLOOMBERG_SURFACE`; `REUTERS_SURFACE` | Current macro query; Reuters sitemap | **verified live** Bing HTTP 200 `application/xml` (RSS, items present in the first 8 KB). Reuters sitemap HTTP 200 `application/xml` | Keep. Expand the **query string** for credit / AI financing / equity stress. Do not raise the per-source cap of 8 to compensate |
| Bing credit probe | `site:reuters.com ("private credit" OR "high-yield" OR "credit spread" OR CLO OR "funding stress")` with the same `format=rss` and 7-day `qft` | Would be the wire complement to H.8 / SLOOS / FSR | **verified live** HTTP 200 RSS, **zero items** in that window | Empty is a valid receipt, not a dead host. One narrow query, not a keyword explosion |
| Bing AI-financing probe | `site:bloomberg.com (CoreWeave OR neocloud OR "data center" OR hyperscaler) (bond OR debt OR financing OR "credit facility" OR IPO)` | Issuer and instrument words absent from `BLOOMBERG_QUERY` | **verified live** HTTP 200 RSS, **zero items** in that window | Same. This does **not** prove any historical CoreWeave headline was in the feed. US-registrant raises are the SEC 8-K Atom’s job; the Bing query is the wire job |
| Bing equity-stress probe | `site:reuters.com ("S&P 500" OR Nasdaq OR "bank stocks" OR selloff) (Fed OR yields OR dollar)` | Equity stress that also names a rates or dollar channel | **verified live** HTTP 200 RSS, 4 `<item>` tags in the fetched body | Require the transmission word in the query so a plain index recap does not enter |

## Asset classes currently missed

- **G10 official decisions.** Fed, BoC, RBA, ECB, BoJ, and BoE all have a verified public RSS. None is a news-discovery surface. BoE is also absent from the Bing query, the token gate, and country codes, so a gilt or Bank Rate story that does not say “central bank” or “dollar” is dropped. RBNZ’s official news URL failed (403) and no substitute RSS was verified.
- **Credit and funding stress.** No token and no query term for private credit, CLO, high-yield, spreads, repo, or bank lending. Official substitutes that do resolve are Fed H.8 and SLOOS announcement XML plus BoC FSR and RBA FSR RSS. The catalog’s only credit row is `US.Credit.mortgage_30y` (Freddie Mac via FRED, context, weight 0, `docs/MACRO_INGESTION_COVERAGE_MATRIX.md`). That is not private credit.
- **AI capex financing.** CoreWeave-class debt and equity raises are invisible unless the headline also hits CPI, oil, the Fed, or another current token. The 8-K Atom is the lawful US-filing surface; the Bing query above is the lawful wire surface. Both worked as endpoints on this check; neither is wired.
- **Equity and bank-equity stress.** Index, megacap, and bank-stock moves that transmit into G10 FX and rates are dropped when the title lacks a `MARKET_TOKENS` word. Transmission stories still need a rates, dollar, or Fed word (the equity probe query does that).
- **Energy and geopolitics, partial.** Oil, Brent, crude, Hormuz, OPEC, tariff, and sanctions are in both the query and the token list. Gaps: gas (the token `lng` is not in the Bing query), copper, and shipping. No verified public RSS for OPEC, copper, or freight was found. A guessed OPEC path `https://www.opec.org/opec_web/en/press_room/rss.htm` returned **HTTP 403** and is not a recommended URL.

## Already a data family — link the release, do not ingest it again

News may point at these. It must not store a second print:

- **US macro:** FRED `fredgraph.csv` and BLS (`scripts/macro_ingestion/adapters/us.py`, `scripts/macro_ingestion/us_employment/`, `scripts/core_pce_release/bls.py`). CPI, PPI, payrolls, PCE, GDP, retail, income, spending.
- **Canada:** StatCan WDS (`scripts/macro_source_refresh.py`). Alberta oil and gas production is the AER ST3 context family (`CA.Energy.*` in the coverage matrix), not a wire.
- **Australia:** ABS pages plus RBA statistical CSVs (`scripts/market_state.py`, `scripts/policy_path_data.py`).
- **New Zealand:** RBNZ B2 rates workbook, often HTTP 403 (`docs/MARKET_STATE_FEED_V1.md`).
- **Euro area:** ECB Data Portal SDMX (`docs/EA_MACRO_SOURCE_CONTRACT.md`, `docs/EA_RATES_SOURCE_CONTRACT.md`).
- **Japan:** BoJ Tankan zip, CGPI, and call-money tables (`docs/JP_MACRO_SOURCE_CONTRACT.md`, `docs/JP_RATES_SOURCE_CONTRACT.md`).
- **US policy rate:** `scripts/policy_state.py` already reads the Fed monetary RSS. Other G10 policy targets are explicit gaps in that file (lines 83–132), not a reason to scrape decision HTML inside news.

## What not to add

- **Paywalled article bodies.** FT markets RSS `https://www.ft.com/markets?format=rss` and WSJ markets RSS `https://feeds.content.dowjones.io/public/rss/RSSMarketsMain` both returned HTTP 200 XML on this check. They are publisher headline feeds. Fetching the linked article HTML is a paywall bypass. Do not add either section feed: they are volume-max.
- **Bloomberg markets firehose.** `https://feeds.bloomberg.com/markets/news.rss` redirected to `https://www.bloomberg.com/feeds/markets/news.rss` and returned HTTP 200 RSS. That is the unfiltered markets feed. Keep the narrow Bing `site:bloomberg.com` query.
- **Credentialed or licensed terminals and curves:** Bloomberg Terminal, Reuters API, ICE BofA spreads, LME, Baltic Exchange, CME. Not tested and out of scope.
- **HTML listing scrapes.** OFAC `https://ofac.treasury.gov/recent-actions` was HTTP 200 HTML with no RSS href. Treasury `https://home.treasury.gov/news/press-releases` was HTTP 200 HTML with no RSS href. A guessed `https://home.treasury.gov/news/press-releases.rss` returned **HTTP 404**. Sanctions already match the token `sanction` and the Bing word `sanctions`.
- **Volume-max official feeds:** Fed `press_all` used as the only Fed source, BoJ what’s-new without a title filter, BLS `bls_latest.rss`, EIA Today in Energy, unfiltered SEC latest filings.
- **A larger cap to hide a wide query.** Raising 8 or 16 does not fix missing tokens.

## Phase 3A implementation constraints

- Keep `Fetcher` injectable (`live_news.py` lines 15, 173–184, 468). Tests must pass bytes in. Live GETs stay behind the default fetcher.
- One surface, one receipt, same fields as `_receipt` (lines 405–424): `source`, `checked_at`, `status`, `candidate_count`, `result_count`, `failure`, `surface`. A zero-item RSS is `ok`, not `failed`. HTTP errors and parse errors stay `failed` with the exception string and no invented items.
- No secrets, no API keys, no credential files. SEC and Bing are anonymous public URLs. Send the existing discovery user-agent (lines 167–170).
- Do not download article HTML. Official and wire items carry title, canonical URL, published time, and the feed’s own description if present.
- Leave `policy_state.py` and the macro adapters as the numeric families. A news item may store the official URL; it may not write a rate, a CPI index, or an H.8 cell.
- New official rows should set `source_name` to a value already in `OFFICIAL_SOURCES` when the publisher is one of those seven names, so `_verification_from_edges` (lines 570–574) can mark `official`. Adding BoE items also requires a GB country code; that code does not exist today.
- `merge_live_news` hardcodes `central_bank_research` to `[]` (line 777). Official decision items either stay in `news` with category `monetary_policy`, or a later change fills that list from the same receipt path. Do not create a second fetcher.
- Keep the per-source cap of 8 and the merged cap of 16. A new surface spends that budget; it does not expand it.
