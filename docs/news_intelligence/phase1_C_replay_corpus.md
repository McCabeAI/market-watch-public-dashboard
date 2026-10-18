# Phase 1C replay corpus — CoreWeave miss vs accepted non-G10 prints

Research date: 2026-10-17. Window requested: 2026-10-10 through 2026-10-17. Code and packet reads are from this repo only. Headlines below are used as fixture facts only when a fetched page, or a snippet that names headline + date + publisher, supports them.

There is no `data/overnight/runs/overnight-20261017/` directory. The 2026-10-17 public set is `data/overnight/accepted_public_news.json` (`as_of` `2026-10-17T08:58:03.216823-04:00`, `overnight_run_id` `overnight-20261016`). The same headlines are in `data/overnight/runs/overnight-20261016/collect.json` merge items.

## Verified CoreWeave event

**Verified (fetched CNBC page).** Headline: “CoreWeave credit default swaps hit distress levels as investors sour on AI debt.” Publisher: CNBC (Michelle Fox). Printed time: Published Thu, Oct 15 2026 12:52 PM EDT, updated Thu, Oct 15 2026 5:33 PM EDT. URL: https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html

The page says CoreWeave’s 9.75% bonds due 2031 yielded 15.78%, five-year CDS spreads went above 1,140 basis points, and the firm has more than $51 billion of debt and obligations for AI infrastructure. That is the credit/AI-capex event nearest 2026-10-17. It is one day before the cutoff, not on 2026-10-17 itself.

`investors.coreweave.com` / `coreweave.com` news for this week was not found. `reuters.com` HTML for the wires below returned no canonical URL in `site:reuters.com` search; fetches of other `reuters.com` story URLs from this run returned 401. Primary Reuters HTML is therefore **not verified**. The wires are verified only as syndications.

### Alternates (not the fixture primary)

| Status | What | Date | Where |
| --- | --- | --- | --- |
| Syndication verified, `reuters.com` URL not verified | “CoreWeave's slump puts spotlight on debt behind AI boom” (CNA title on fetch: “CoreWeave's slump spotlights growing burden of debt behind AI boom”). Dateline Oct 15. CNA stamp “15 Oct 2026 07:22PM”. | 2026-10-15 | https://www.channelnewsasia.com/business/coreweaves-slump-puts-spotlight-debt-behind-ai-boom-6462286 |
| Syndication verified, `reuters.com` URL not verified | “Analysis:Why CoreWeave is in the crosshairs of the AI scare.” Dateline LONDON/BENGALURU, Oct 16. TradingView points at `reuters.com,2026:newsml_L4N461208` but that page was not fetched. | 2026-10-16 | https://www.channelnewsasia.com/business/analysiswhy-coreweave-in-crosshairs-ai-scare-6467006 |
| Earlier than the window; search snippet only, filing HTML not re-fetched | SEC 8-K, CoreWeave Financing DDTL V-V $2.6 billion delayed-draw term loan | 2026-08-07 | https://www.sec.gov/Archives/edgar/data/1769628/000176962826000357/crwv-20260807.htm |
| Earlier; `reuters.com` search snippet, page not re-fetched | “CoreWeave launches $3 billion convertible debt sale” | 2026-09-17 | https://www.reuters.com/legal/transactional/coreweave-launches-3-billion-convertible-debt-sale-2026-09-17/ |

## Accepted India and Vietnam headlines (repo)

From `accepted_public_news.json` and the collect merge. India has **no URL and no source_name** in the packet.

- **Vietnam (accepted).** Headline: “Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%.” `published_at`: `2026-10-16T16:03:00-04:00`. Source on the edge: Bloomberg. URL: https://www.bloomberg.com/news/articles/2026-10-17/vietnam-prime-minister-targets-2027-gdp-growth-of-at-least-10 . Summary: “Vietnam’s Prime Minister Le Minh Hung projected gross domestic product will expand at least 10% next year as he outlined the nation’s economic targets in a speech to parliament.” Salience in collect: score 7 (`tier1_relevance` 2, `transmission` 1, `novelty` 2, `distribution_weight` 2, `recency` 0), `country_codes` `[]`. Bloomberg.com HTML was **not** fetched. Free Malaysia Today fetched the same lede under a different headline, “Vietnam’s prime minister targets 2027 GDP growth of at least 10%,” stamp 17-Oct-2026, 13:14: https://www.freemalaysiatoday.com/category/business/2026/10/17/vietnam-s-prime-minister-targets-2027-gdp-growth-of-at-least-10
- **India (accepted).** Headline: “India Trade Deficit Widened in September on Higher Import Bill.” `published_at`: `2026-10-14T22:34:00-04:00`. `url`: null. `source_name`: null. Summary: “India’s trade gap expanded in September as festive demand and surging oil prices pushed up imports, adding to risks from the drawn-out conflict in the Middle East.” Salience: score 6 (`tier1_relevance` 3, `transmission` 3, others 0), `primary_category` still `macro`, `country_codes` `["US"]`. Public page fetched: Bloomberg Law / Bloomberg News, “India’s Trade Deficit Widened in September on Higher Imports (1),” Oct. 15, 2026, 9:34 AM UTC, same lede: https://news.bloomberglaw.com/international-trade/indias-trade-deficit-widened-in-september-on-higher-imports . Do not treat the packet timestamp and the 9:34 AM UTC stamp as the same clock time.

## Why `MARKET_TOKENS` accepts those two and misses CoreWeave

Surfaces in `scripts/overnight/live_news.py`: Bing News RSS restricted to `site:bloomberg.com` plus a query of Fed/FOMC/inflation/CPI/payrolls/Treasury/yields/oil/Brent/crude/Hormuz/OPEC/FX/dollar/tariff/sanctions/central bank/RBA/Bank of Canada/RBNZ/ECB/Bank of Japan; and the Reuters news sitemap. Each parser keeps 8 items inside a 24-hour window. `_text_matches_market_gate` keeps any `MARKET_TOKENS` hit. `gdp` is in that tuple. `coreweave`, `cds`, `credit`, `debt`, `capex`, and `ai` are not. A hit that is not energy, rates, FX, or a named central bank still passes unless the text also contains `podcast`, `golf`, or `celebrity`. So a Vietnam **GDP** headline passes with `transmission` 1. India’s **summary** contains `oil`, so salience scores energy transmission 3 even though the headline has no token and India is not a country alias (`_COUNTRY_ALIASES` has no India/Vietnam/China). The stored `US` tag is not an India match.

CoreWeave never becomes a candidate. CNBC is not a surface. The Bloomberg query has no credit/AI terms. The Oct 15 and Oct 16 Reuters headlines do not contain a `MARKET_TOKENS` word, so the sitemap gate drops them. At cutoff `2026-10-17T08:58:03-04:00` the live window opens `2026-10-16T08:58:03-04:00`, so the Oct 15 wires are also outside 24 hours. The Oct 16 analysis is inside the window and still fails the token gate. Caps (8 per source, 16 after merge, presentation 6/3) are not why it is missing: it never enters the candidate list. Vietnam did, as the one Bloomberg live item on that surface, and was copied into `accepted_public_news.json`.

## Corpus

`expected_disposition` is the correct product outcome. `discovery_miss` means current Bloomberg-query and token-gated Reuters surfaces cannot emit it. `fixture_safe` is true only for the headline, URL, and date that were fetched or snippet-verified as a set.

```json
[
  {
    "id": "crwv-cds-distress-cnbc-20261015",
    "expected_disposition": "discovery_miss",
    "headline": "CoreWeave credit default swaps hit distress levels as investors sour on AI debt",
    "published_at": "Thu, Oct 15 2026 12:52 PM EDT",
    "source": "CNBC",
    "url": "https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html",
    "why": "G10 credit transmission: AI-capex borrower, 2031 bond yield and CDS at distress levels, with the page tying the move to Oracle CDS and forced selling if an IG name is downgraded. Not a domestic non-G10 print. CNBC is not a discovery surface, and the headline has no MARKET_TOKENS word, so the Bloomberg query and the Reuters gate cannot emit it.",
    "fixture_safe": true
  },
  {
    "id": "crwv-debt-slump-reuters-cna-20261015",
    "expected_disposition": "discovery_miss",
    "headline": "CoreWeave's slump spotlights growing burden of debt behind AI boom",
    "published_at": "15 Oct 2026 07:22PM",
    "source": "Reuters via Channel NewsAsia",
    "url": "https://www.channelnewsasia.com/business/coreweaves-slump-puts-spotlight-debt-behind-ai-boom-6462286",
    "why": "Same credit/AI-capex event (about $50 billion of debt, 2031 bond near 15%, CDS near 1,000 bp). Wire says Oct 15. reuters.com canonical URL was not verified. Headline has no MARKET_TOKENS word, and Oct 15 is outside the 24-hour window at the Oct 17 08:58 ET cutoff.",
    "fixture_safe": true
  },
  {
    "id": "crwv-ai-scare-reuters-cna-20261016",
    "expected_disposition": "discovery_miss",
    "headline": "Analysis:Why CoreWeave is in the crosshairs of the AI scare",
    "published_at": "2026-10-16",
    "source": "Reuters via Channel NewsAsia",
    "url": "https://www.channelnewsasia.com/business/analysiswhy-coreweave-in-crosshairs-ai-scare-6467006",
    "why": "In-window credit transmission: neocloud debt, bond yields near 16%, circular AI financing. Dateline LONDON/BENGALURU, Oct 16. No clock time on the fetched page. reuters.com HTML not verified. Inside the 24-hour sitemap window, but the headline still fails MARKET_TOKENS.",
    "fixture_safe": true
  },
  {
    "id": "india-trade-deficit-accepted-20261015",
    "expected_disposition": "suppress",
    "headline": "India Trade Deficit Widened in September on Higher Import Bill",
    "published_at": "2026-10-14T22:34:00-04:00",
    "source": "packet source_name null; public page Bloomberg News via Bloomberg Law",
    "url": "https://news.bloomberglaw.com/international-trade/indias-trade-deficit-widened-in-september-on-higher-imports",
    "why": "Non-G10 domestic trade print. Accepted in accepted_public_news.json with url null. Public title differs: “India’s Trade Deficit Widened in September on Higher Imports (1),” Oct. 15, 2026, 9:34 AM UTC, same lede. The summary word oil scores ENERGY_TOKENS and tier1 3. That is India’s import bill, not a G10 supply decision. India is not a country alias; the packet still stores country_codes [US].",
    "fixture_safe": true
  },
  {
    "id": "vietnam-gdp-target-accepted-20261016",
    "expected_disposition": "suppress",
    "headline": "Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%",
    "published_at": "2026-10-16T16:03:00-04:00",
    "source": "Bloomberg",
    "url": "https://www.bloomberg.com/news/articles/2026-10-17/vietnam-prime-minister-targets-2027-gdp-growth-of-at-least-10",
    "why": "Non-G10 domestic growth target. The headline token gdp passes the gate with transmission 1. Bing’s query does not include GDP; the article was still the Bloomberg live hit and was copied into the accepted file. No G10 policy rate, oil balance, or FX regime is the subject. bloomberg.com HTML was not fetched. FMT fetched the same lede on 17-Oct-2026 under a different headline.",
    "fixture_safe": true
  },
  {
    "id": "oil-brent-110-hormuz-20261016",
    "expected_disposition": "show",
    "headline": "Oil touches $110 a barrel for first time since May on Middle East, Russia supply fears",
    "published_at": "Fri, 16 October 2026 at 3:34 pm GMT-4",
    "source": "Reuters via Yahoo Finance",
    "url": "https://sg.finance.yahoo.com/news/oil-edges-down-investors-weigh-010642305.html",
    "why": "G10 energy transmission. Fetched page: HOUSTON, Oct 16 (Reuters); Brent settled $109.86 and WTI $101.41, matching the packet’s crude marks; Hormuz bypass and attacks are in the body. Headline token oil would pass the gate. This exact headline is not in accepted_public_news.json. The URL slug is older than the fetched headline.",
    "fixture_safe": true
  },
  {
    "id": "aramco-hormuz-buffer-20261005",
    "expected_disposition": "show",
    "headline": "Global Oil Supply Buffer Running ‘Scarily Thin,’ Aramco CEO Says",
    "published_at": "October 5, 2026",
    "source": "Bloomberg via Yahoo Finance",
    "url": "https://finance.yahoo.com/energy/articles/global-oil-supply-buffer-running-082002010.html",
    "why": "Historical versus the Oct 10–17 window, and still the first story in the accepted file, with no published_at and no URL in the packet. Genuine Hormuz and oil-stock transmission into Brent. Headline tokens oil and Hormuz. Yahoo page is the fetched copy; bloomberg.com HTML was not fetched.",
    "fixture_safe": true
  },
  {
    "id": "china-q3-stimulus-poll-20261015",
    "expected_disposition": "show",
    "headline": "China Q3 growth set to pick up on stimulus, keeping 2026 goal within reach: Reuters poll",
    "published_at": "Thu, October 15, 2026 at 2:25 AM PDT",
    "source": "Reuters via Yahoo Finance",
    "url": "https://finance.yahoo.com/economy/articles/china-q3-growth-set-pick-092516257.html",
    "why": "China spillover that should show: stimulus, property slump, trade surplus, and crude-demand implications for global growth. Dateline BEIJING, Oct 15 (Reuters). The headline has no MARKET_TOKENS word (gdp is only in the body), so today’s headline-only Reuters gate drops it. Not in the accepted file.",
    "fixture_safe": true
  },
  {
    "id": "indonesia-fires-assistance-20261016",
    "expected_disposition": "suppress",
    "headline": "Indonesia's president ready to accept foreign assistance to combat fires, foreign minister says",
    "published_at": "Fri, October 16, 2026 at 5:01 AM EDT",
    "source": "Reuters via Yahoo News",
    "url": "https://www.yahoo.com/news/articles/indonesias-president-ready-accept-foreign-030142336.html",
    "why": "Clear irrelevant domestic non-G10 story: forest-fire assistance. No G10 rates, FX, or energy-policy channel. Headline has no MARKET_TOKENS word, so the headline gate suppresses it. The body mentions palm oil; a full-text snippet would false-hit the oil token. Not in the accepted file.",
    "fixture_safe": true
  },
  {
    "id": "ecb-lagarde-bond-selloff-20261017",
    "expected_disposition": "show",
    "headline": "ECB's Lagarde says bond selloff will slow inflation",
    "published_at": "Sat, Oct 17 2026 6:52 AM EDT",
    "source": "CNBC",
    "url": "https://www.cnbc.com/2026/10/17/ecbs-lagarde-says-bond-selloff-will-slow-inflation.html",
    "why": "G10 rates transmission: ECB president on euro-area borrowing costs, inflation pass-through, and a restrictive policy rate. Headline tokens inflation and ECB. The live merge in collect.json has this headline from the Reuters sitemap at 2026-10-17T04:01:16.133000-04:00, URL https://www.reuters.com/business/finance/ecbs-lagarde-says-bond-selloff-will-slow-inflation-2026-10-17/ (that reuters.com fetch returned 401). It is not in the accepted_public_news.json news array. CNBC’s clock and the sitemap clock differ; both are recorded, not merged.",
    "fixture_safe": true
  },
  {
    "id": "anthropic-us-gdp-clark-20261017",
    "expected_disposition": "show",
    "headline": "AI rapidly improving, could vastly boost US GDP, Anthropic's Clark tells policymakers",
    "published_at": "2026-10-17",
    "source": "Reuters via Channel NewsAsia",
    "url": "https://www.channelnewsasia.com/business/ai-rapidly-improving-could-vastly-boost-us-gdp-anthropics-clark-tells-policymakers-6468116",
    "why": "Contrast with Vietnam. This GDP token is US growth, a G10 transmission, so it should show. Dateline BANGKOK, Oct 17; the fetched CNA page has no clock. Pipeline sitemap time in collect.json is 2026-10-17T05:15:02.848000-04:00 and reuters.com returned 401. The same gdp token is why Vietnam was kept. Not in accepted_public_news.json.",
    "fixture_safe": true
  },
  {
    "id": "china-oil-comeback-packet",
    "expected_disposition": "show",
    "headline": "China Oil Comeback Loses Steam as Iran War Drags On",
    "published_at": null,
    "source": "accepted_public_news.json; publisher not stored",
    "url": null,
    "why": "In the accepted file, with a summary on Chinese oil demand, Iranian supply, and crude prices. That is a China commodity spillover and should show if the underlying story is the late-September Bloomberg piece repeated by secondary pages. Those pages were not fetched, and a display date of 17 Oct 2026 conflicts with a Sept 30 dateline in search snippets. Do not use a date or URL from this row as a fixture fact.",
    "fixture_safe": false
  }
]
```

## UNVERIFIED

- Canonical `reuters.com` HTML for the Oct 15 “slump” wire and the Oct 16 “crosshairs” analysis. Syndication pages were fetched. `site:reuters.com` search did not return those URLs.
- `bloomberg.com` HTML for the Vietnam URL and for the India “Import Bill” headline. The packet and a Bloomberg Law republication are the evidence.
- Any single clock that reconciles India’s packet `2026-10-14T22:34:00-04:00` with Bloomberg Law’s Oct. 15, 2026, 9:34 AM UTC.
- A CoreWeave press release or 8-K in the Oct 10–17 window. The August 7, 2026 8-K and the September 17, 2026 convertible sale are earlier and were not re-fetched.
- OPEC-only headline in this window. The Hormuz cases above are the verified oil fixtures. A Euronext page mentioning an OPEC September production note was not fetched.
