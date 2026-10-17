# News intelligence repair

Status: implemented, not deployed. A nonpublishing shadow ran on 2026-10-17. Accepted public news on `main` was not rewritten.

## What changed

Discovery is no longer one Bing macro query plus a Reuters sitemap, scored with keyword bonuses and cut to 8 items per source and 16 after the merge. Each in-window row is scored for G10 transmission before any display cap. `presentation_caps` stay 6 and 3. The HTML story window stays 12. A newest-60 safety ceiling per surface is a parse bound, recorded as `discovery_failure` / `safety_ceiling` when it binds. It is not a relevance rank.

Public news rows with disposition `suppress` or `hold-for-review` are removed in `overlay_accepted_research`. `assemble_dataset` copies that kept list onto `agent_research["news"]` before the accepted-news artifact is written. `central_bank_research` is not filtered. The accepted-news envelope keys are unchanged. The packet the provider submitted is not mutated.

## Sources

Metadata only. No article HTML, no credentials.

| Receipt source | Surface | Role |
| --- | --- | --- |
| `bloomberg` | Existing Bing `site:bloomberg.com` macro query | Required. Still drives `partial` |
| `reuters` | Reuters news sitemap | Required. Still drives `partial` |
| `bloomberg_credit` | Bing query for CoreWeave / data-center / debt / CDS | Wire credit and AI financing |
| `bloomberg_equity` | Bing query for index or bank-stock stress with Fed, yields, dollar, or Treasury | Equity stress with a rates link |
| `reuters_credit` | Bing `site:reuters.com` private credit / high-yield / CLO / funding stress | Wire credit |
| `fed_monetary` | `federalreserve.gov/feeds/press_monetary.xml` | Official |
| `boc_press` | Bank of Canada press RSS | Official |
| `rba_media` | RBA media-release RSS | Official |
| `ecb_press` | ECB press RSS | Official |
| `boj_whatsnew` | BoJ what's-new RSS, title-filtered | Official |
| `boe_news` | Bank of England news RSS, title-filtered | Official |

RBNZ's news page returned HTTP 403 in research. It is not scraped. FT, WSJ, the Bloomberg markets firehose, and an unfiltered SEC 8-K feed were not added.

An empty credit query is `ok` with `result_count` 0. A fetch exception fails that receipt only. `partial` is true only when one of `bloomberg` and `reuters` failed and the other is `ok`.

## Decision criteria

`transmission` on each scored item has `disposition`, `affected_assets`, `channel`, `channels`, `reason_code`, `score`, and `components`.

Subject rules run first and zero channels:

- Vietnam and `gdp` → `suppress`, `local_non_g10_macro`
- India trade deficit, trade gap, or import bill → `suppress`, `incidental_link_only`, even if the summary mentions oil or a Middle East conflict
- Indonesia fire or fires → `suppress`, even if the summary mentions palm oil
- Podcast, golf, or celebrity, unless the text is also an oil-supply story → `suppress`

Then locked scores: Hormuz refusal / crude bounce 15 `show`; Hormuz diplomacy 13 `show`; China stimulus with crude or commodity demand 10 `show`; CoreWeave or CDS-and-AI-debt 11 `show` `ai_capex_credit`; Chicago Fed activity index 7 `assess`. A named G10 policy or US rates story follows the same thresholds. Sanctions plus energy, oil, or diesel are `show`. Sanctions without that energy link are `assess`. A US interest-cost or debt-snowball story is `assess`. Any real channel under 7 stays `assess` and is not dropped. `show` requires score at least 10, a channel, and no subject penalty.

Tie-break is at most +3 (12-hour recency, live novelty, Bloomberg) and cannot change disposition. Paths containing `/video`, `/newsletter`, `/podcast`, or `/audio` are dropped before scoring.

`Ormuz` is treated as Hormuz. That alias exists because the 2026-10-17 Reuters sitemap carried a Portuguese IRGC tanker-mine headline that the English token missed.

## How to inspect a story

`PYTHONPATH=. python3 scripts/live_news_discovery_smoke.py --report /tmp/news_shadow_report.json`

The report does not collect, assemble, or publish. Each story row has `stage` and `reason`:

| Stage | Meaning |
| --- | --- |
| `discovery_failure` | That surface fetch failed, or the newest-60 ceiling dropped the row before scoring |
| `relevance_rejection` | Path, window, official title filter, stage-1 recall, `suppress`, or `hold-for-review` |
| `presentation_suppression` | Scored `show` or `assess`, then cut by the post-score cap of 24 |
| `shown` | In the merged `items` list |

Receipt `failure` is transport only. `story_drops` on the acquire result explains rows that never became candidates. HTML caps of 6, 3, and 12 still happen later in the untouched refresh script; this report does not claim to see those slices.

## Replay

| Story | Evidence | Result |
| --- | --- | --- |
| CoreWeave CDS distress | CNBC, Thu Oct 15 2026, 12:52 PM EDT. https://www.cnbc.com/2026/10/15/coreweave-credit-default-swaps-hit-distress-levels-as-investors-sour-on-ai-debt.html | `show`, `ai_capex_credit`. Not on the shadow feeds. The page was fetched in research; this run did not re-fetch it |
| CoreWeave "AI scare" wire | CNA syndication of a Reuters dateline, Oct 16 2026. `reuters.com` HTML was not verified | Recalled and `show` on the issuer name. Previously died at recall because the headline has no debt/CDS token |
| Vietnam GDP target | Accepted packet headline, Bloomberg, `2026-10-16T16:03:00-04:00` | `suppress`. On the shadow it was outside the 24-hour window, so the live reason was `window`, not the subject rule |
| India trade deficit | Accepted packet headline. Summary uses oil as the import bill. Public page is Bloomberg Law, Oct 15 2026; packet URL is null | `suppress`, `incidental_link_only` |
| Indonesia fires | Reuters via Yahoo, Oct 16 2026, palm oil only in the body | `suppress` |
| China Q3 stimulus poll | Reuters via Yahoo, Oct 15 2026, crude demand in the body | `show`, `china_commodity_spillover` |
| Hormuz refusal vs diplomacy | Existing acquisition fixtures | Refusal salience stays above diplomacy. Both `show` |
| Chicago Fed CFNAI | Existing accepted-news fixture | `assess`. Stays in the overlay, behind the oil fixture |

`reuters.com` HTML for the CoreWeave wires was not verified. Syndication pages were. Do not treat a missing canonical Reuters URL as a fetched article.

## Shadow, 2026-10-17 18:35 ET

`docs/news_intelligence/shadow_20261017.json`. `partial` false. No discovery failures. Shown:

- US interest costs at $1 trillion, debt snowball (`assess`, USD rates)
- Russia energy sanctions paused to ease diesel costs (`show`)
- Portuguese IRGC headline: two tankers hit mines in the Strait of Ormuz (`show`, oil)
- Zelenskiy on a US waiver of Russia sanctions (`assess`)

Credit, equity, Bank of Canada, and RBA feeds returned zero items. Fed, ECB, BoJ, and BoE feeds returned items, all outside the 24-hour window or dropped by the BoJ/BoE title filter. CoreWeave did not appear. Vietnam's GDP headline was the window reject above. India cricket and a Kolkata crush were recall rejects, not shown. Bloomberg weekend audio was a path drop.

## False positives and false negatives

False positives still possible: a sanctions headline with no energy link is `assess` and can appear when the day is thin. A weekend audio episode was the case that forced the `/audio` path drop. Golf, podcasts, Brentford (the club, not Brent), and domestic India or Vietnam prints are not shown.

False negatives that remain:

- Non-English copy other than `Ormuz`
- A CoreWeave story that never hits these feeds and is older than 24 hours, including the Oct 15 CNBC piece on the night of Oct 17
- RBNZ, because no public RSS was verified
- BoJ statistics titles that do not say monetary policy
- Body text. Reuters rows are headline-only, so a transmission link that exists only in the article is invisible
- The post-score cap of 24 and the untouched HTML caps

## What was not changed

No ACP files, workflows, launch scripts, publish gate, HTML refresh, provider credentials, or `data/overnight/accepted_public_news.json`. No production deploy and no full Market Watch run.

## Tests

`PYTHONPATH=. python3 -m unittest tests.test_news_intelligence tests.test_live_news_acquisition tests.test_accepted_news_architecture tests.test_overnight_news_refresh tests.test_sync_news_summary`

50 tests, OK, on 2026-10-17. Research notes are under `docs/news_intelligence/`.
