# Phase 4 historical replay

Replay time: 2026-10-17T23:15:50Z. User-agent: `MarketWatch-Public-News-Discovery/1.0`. No article HTML was stored. `data/overnight/accepted_public_news.json` was not read or written. Injected unit-test XML is not used as recall proof in this note.

## CoreWeave 15 Oct URL

| Field | Value |
| --- | --- |
| URL | `https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html` |
| Page `article:published_time` (phase 1A, HTTP 200) | `2026-10-15T16:52:16Z` |
| 24h discovery window | `[2026-10-15T16:52:16Z, 2026-10-16T16:52:16Z]` |
| Wayback CDX for `cnbc.com/sitemap_news.xml`, 20261015–20261017 | `[]` |
| Wayback CDX for the article URL | HTML captures `20261015165635` (inside the window), `20261016014202` (inside), `20261016180248` (after the window). These are the article page, not a discovery feed. |

Live `https://www.cnbc.com/sitemap_news.xml` at this replay: HTTP 200, `text/xml`, 46,235 bytes, 84 news URLs. The target URL is **absent**. Oldest `publication_date` in that body: `2026-10-15T19:49:14-04:00` (`2026-10-15T23:49:14Z`), about seven hours after the article was published. Newest: `2026-10-17T18:55:05-04:00`.

`parse_surface(kind=cnbc_sitemap)` on that same body:

| Cutoff | raw | kept | target kept |
| --- | --- | --- | --- |
| `2026-10-17T23:15:50Z` | 84 | 13 | no |
| `2026-10-16T12:00:00Z` (inside the article's 24h window) | 84 | 21 | no |

The second row parses today's sitemap as if the clock were 16 Oct. It does not reconstruct the sitemap as it was on 16 Oct. The target is not in the bytes.

Bing News RSS, same `format=rss` and 7-day `qft`, HTTP 200:

| Query | Items | Target or a CoreWeave CDS title |
| --- | --- | --- |
| `cnbc_credit` | 1 (an AI-stocks / inflation item, not the CDS URL) | no |
| `reuters_credit` (extended) | 5 (first title is a Pope Leo hospital item) | no |
| `bloomberg_credit` | 0 | no |

**Gate 1: UNRESOLVED BLOCKER.** No saved sitemap or Bing body from the 24h window contains the URL. The article page existed. The new CNBC surface is wired and parsed this live sitemap. That is not historical recall of this URL.

The current sitemap does list later CNBC CoreWeave items, all outside that window. Example: "Why did CoreWeave stock get crushed this week? Look to this corner of the debt market for clues", `publication_date` `2026-10-16T16:33:55-04:00` (`2026-10-16T20:33:55Z`), which is after `2026-10-16T16:52:16Z`. It was not in the 13 rows the parser kept at 23:15Z because it is older than 24 hours. It is a different URL.

## Scoring on the real headline strings

`score_transmission` / `recall_candidate` at this replay, not a feed result:

| Case | Disposition | Reason | Recall |
| --- | --- | --- | --- |
| CDS distress headline, empty summary | show | `ai_capex_credit` | true |
| AI-scare headline | hold-for-review | `ambiguous_transmission` | false |
| "CoreWeave opens a London office" | hold-for-review | `ambiguous_transmission` | false |
| India trade-gap fixture | suppress | `incidental_link_only` | true (summary contains `oil`; overlay still drops suppress) |
| India crude-export halt plus trade-deficit wording | assess | `oil_supply_shock` | true |
| India crude halt plus Hormuz plus trade gap | show | `oil_supply_shock` | true |
| Vietnam GDP plus parliament summary | suppress | `local_non_g10_macro` | false |
| Vietnam GDP plus crude-export halt | assess | `oil_supply_shock` | true |
| Indonesia fires plus palm-oil exports | suppress | `local_non_g10_macro` | true |
| Indonesia refinery fire halts crude exports | assess | `oil_supply_shock` | true |
| "Bank rate maintained at 3.75%" | assess | `g10_policy_path`, GBP | true |
| "Official Cash Rate unchanged" | assess | `g10_policy_path`, NZD | true |
| Money-market-operations guideline | assess | `g10_policy_path`, JPY | true |
| "Monetary Policy Committee dates for 2027" | hold-for-review | `ambiguous_transmission` | false |
| "Services Producer Price Index for August" | hold-for-review | `ambiguous_transmission` | false |

## What the live CNBC sitemap kept tonight

13 headlines inside 24 hours. None is the 15 Oct CDS URL. The parser does not relevance-filter; stage-1 recall still drops lifestyle rows. Two kept titles are market-relevant on their face: the Russia-sanctions waiver and the AI-stocks / inflation item. That shows the surface returns current CNBC metadata. It does not show the 15 Oct CDS story was on the sitemap during its window.
