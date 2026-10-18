# Phase 5A — would a material G10 / AI-credit / energy story still be missed?

Review date: 2026-10-17. Reviewer pass only. No code edits. Functions were called in this workspace: `score_transmission`, `recall_candidate`, `apply_transmission`, and `parse_surface` (Reuters sitemap fixture). Locked unit tests in `tests/test_news_intelligence.py` (`RelevanceTests`, plus `test_reuters_sitemap_keeps_coreweave_headline`) were run and passed. Live evidence is `/tmp/news_shadow_report.json` (`cutoff` `2026-10-17T18:28:24.407848-04:00`, `partial` false). This review did not re-fetch feeds or article HTML.

**Verdict: PASS.** The locked CoreWeave CDS headline is `show` / `ai_capex_credit` and is recalled with an empty summary. Sanctions plus diesel/energy is `show`. US interest-cost / debt-snowball is recalled. The old `MARKET_TOKENS` allowlist is not on the acquire path. Remaining misses are outside that locked bar; they are listed below and are not invented.

## Checks

### 1. CoreWeave CDS headline, empty summary

Headline used: “CoreWeave credit default swaps hit distress levels as investors sour on AI debt” (phase 1C verified CNBC headline, 2026-10-15 12:52 PM EDT).

| Summary passed in | `recall_candidate` | disposition | reason | score | channel |
| --- | --- | --- | --- | --- | --- |
| `""` | true | show | `ai_capex_credit` | 11 | `credit_funding` |
| Reuters constant `Headline-only public metadata; article body was not retrieved.` | true | show | `ai_capex_credit` | 11 | `credit_funding` |

Assets: `credit_spreads`, `UST`. A Reuters sitemap fixture parsed by `parse_surface` stamps that constant, not an empty string (`REUTERS_HEADLINE_ONLY`). Recall and `apply_transmission` on that parsed row are the same `show` / `ai_capex_credit` / 11. The empty-summary case the criterion names also passes. `tests/test_news_intelligence.py` asserts the empty-summary case and the injected sitemap path.

The same call on the phase 1C syndication headline “CoreWeave's slump spotlights growing burden of debt behind AI boom” with an empty summary is recalled and `show` / `ai_capex_credit` / 11.

### 2. Vietnam GDP target

“Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%”, summary `""` and summary “Parliament growth target.”

- `score_transmission`: `suppress`, `local_non_g10_macro`, score `-8`, channels empty.
- `recall_candidate`: false (sole `gdp` is not a stage-1 class).

Overlay still scores it and `public_news_rows` drops `suppress`. Live acquire drops it earlier, at recall, so a sitemap copy would not reach the suppress reason. Both paths remove it.

### 3. Sanctions + diesel / energy

“Trump Halts New Russia Energy Sanctions to Ease Diesel Costs”, empty summary.

- `recall_candidate`: true.
- `score_transmission`: `show`, `geopolitics_haven_or_oil`, score 14, primary channel `oil_energy_tot`, assets `Brent`, `USD`.

This is not a discovery miss. The same headline is one of the six rows the shadow marked `shown`. The shadow URL slug is `trump-waives-russia-energy-tariffs-sanctions-in-graham-law`. This review did not open that article; scoring used the headline string.

“Trump Pauses Russia Energy Sanctions, Houthis Hit Yemen Airport” is the same `show` / score 14. Sanctions without an energy token (“Zelenskiy criticizes Trump's waiver of sanctions on Russia as 'wrong'”) is recalled and `assess` / score 8, not dropped.

### 4. US interest-cost / debt-snowball

“US Interest Costs Hit Record $1 Trillion, Risking Debt Snowball”, empty summary.

- `recall_candidate`: true. Not dropped at recall.
- `score_transmission`: `assess`, `usd_rates_repricing`, score 9, channel `usd_rates`, assets `USD`, `UST`. Not `show` (threshold 10).

`cluster_and_rank` keeps `assess` inside the 24-item list, so the shadow stage is `shown` with reason `usd_rates_repricing`. That stage name is the cluster bucket, not disposition `show`.

### 5. What the shadow run showed

Cutoff `2026-10-17T18:28:24.407848-04:00`. Window opens `2026-10-16T18:28:24.407848-04:00`. Counts: `discovery_failure` 0, `relevance_rejection` 183, `presentation_suppression` 0, `shown` 6. Every receipt `status` is `ok`. No surface failed.

Surfaces with `result_count` 0:

| source | candidate_count | result_count | what the zero is |
| --- | --- | --- | --- |
| `bloomberg_credit` | 0 | 0 | Bing returned no items. Not a recall drop. |
| `bloomberg_equity` | 0 | 0 | Bing returned no items. |
| `reuters_credit` | 0 | 0 | Bing returned no items. |
| `boc_press` | 0 | 0 | Feed parsed to zero items. |
| `rba_media` | 0 | 0 | Feed parsed to zero items. |
| `fed_monetary` | 15 | 0 | All 15 `window`. No in-window Fed press row. |
| `ecb_press` | 15 | 0 | 14 `window`, 1 in-window `stage1_recall` (below). |
| `boj_whatsnew` | 51 | 0 | 46 `official_title_filter`, 5 `window`. |
| `boe_news` | 50 | 0 | 43 `official_title_filter`, 7 `window`. |

Non-zero: `bloomberg` 8 candidates / 5 results; `reuters` 50 / 1. Bloomberg losses before recall: Vietnam and a Japanese ECB/Lagarde headline (`window`), plus “Bloomberg Readers Share the Money Moments That Changed Their Lives” (`path_drop`, newsletter URL).

Shown (6):

1. “Zelenskyy Slams 'Deliberate' Starlink Slowdown, Russia Sanctions” — Bloomberg audio, `2026-10-17T04:54:00-04:00`, `geopolitics_haven_or_oil`.
2. “Bloomberg This Weekend: Trump Halts Russia Sanctions” — Bloomberg audio, slug ends `-podcast`, path is `/news/audio/` so the `/podcast` path drop does not fire. `2026-10-17T03:30:00-04:00`.
3. “US Interest Costs Hit Record $1 Trillion, Risking Debt Snowball” — Bloomberg article, `2026-10-17T01:00:00-04:00`, `usd_rates_repricing`.
4. “Trump Pauses Russia Energy Sanctions, Houthis Hit Yemen Airport” — Bloomberg audio, `2026-10-17T00:58:00-04:00`.
5. “Trump Halts New Russia Energy Sanctions to Ease Diesel Costs” — Bloomberg article, `2026-10-16T22:45:00-04:00`.
6. “Zelenskiy criticizes Trump's waiver of sanctions on Russia as 'wrong'” — the one Reuters survivor, `2026-10-16T21:17:48.703000-04:00`.

CoreWeave itself is absent. The string `coreweave` occurs in zero shadow headlines. `bloomberg_credit` (the query that names CoreWeave, neocloud, data center, hyperscaler, bond, debt, CDS) has `candidate_count` 0. Nothing CoreWeave-shaped was fetched and then rejected. The phase 1C CNBC story is dated Thu, Oct 15 2026, 12:52 PM EDT, which is outside this run’s 24-hour window (open 2026-10-16 18:28 ET). CNBC is not a discovery surface. This review did not re-fetch the CNBC page or the Reuters sitemap; absence is what this shadow file records.

Vietnam is in the shadow as `relevance_rejection` / `window`, not as `local_non_g10_macro`. The drop row stores `published_at` null. Reason `window` means a date was parsed and fell outside 24 hours. The packet time in phase 1C (`2026-10-16T16:03:00-04:00`) is before this window opened. Bloomberg HTML for that URL was not fetched in phase 1C and was not fetched here.

## Remaining false negatives

These are verified headlines or shadow rows. They are not the locked CDS / sanctions-diesel / debt-snowball cases.

1. **Phase 1C CoreWeave “AI scare” wire still dies at recall.** Headline: “Analysis:Why CoreWeave is in the crosshairs of the AI scare” (CNA syndication, dateline 2026-10-16, no clock on the fetched page, `reuters.com` HTML not verified in phase 1C). Empty summary: `score_transmission` is `show` / `ai_capex_credit` / 11 because `_coreweave_rule` fires on the issuer name alone, but `recall_candidate` is **false**. Stage 1 requires AI-side and financing-side together (`debt` / `bond` / `financing` / `cds` / `capex`). This headline has CoreWeave and AI, and not those financing tokens. Body debt and bond yields never arrive on a Reuters headline-only row. Acquire would drop it as `stage1_recall` before scoring. It was not on tonight’s shadow feeds, so this is a function miss, not an observed drop of that URL tonight. The Oct 15 CDS headline does not have this hole.

2. **Phase 1C US-GDP Anthropic headline still dies at recall.** “AI rapidly improving, could vastly boost US GDP, Anthropic's Clark tells policymakers”, empty summary: `recall_candidate` false, and if scored, `hold-for-review` / `ambiguous_transmission` / 0. Phase 2 §12.3 says a sole `gdp` hit is not a candidate. Phase 1C still marks this headline `show`. It is not in the shadow. The Portuguese sitemap row that is in the shadow, “Cofundador da Anthropic afirma que impacto da IA acelera rapidamente e pode impulsionar PIB dos EUA” (`2026-10-17T12:14:25.636000-04:00`), also died at `stage1_recall`. English tokens `ai` and `gdp` are not in that title (`IA`, `PIB`). This review did not fetch an English twin from tonight’s sitemap.

3. **In-window Portuguese Hormuz mine headline died at recall.** Shadow Reuters row, `2026-10-17T12:55:02.803000-04:00`, reason `stage1_recall`: “Guarda Revolucionária do Irã afirma que dois petroleiros atingiram minas no Estreito de Ormuz”. The title says the IRGC reported two tankers striking mines in the Strait of Ormuz. `recall_candidate` on that string is false: the list has `hormuz`, not `ormuz`, and no English `oil` / `mine` / `tanker` token. No English Hormuz headline is in this shadow. An English Hormuz headline would be recalled. This is a language miss of a story that was on the sitemap, not the old English keyword gate dropping the diesel sanctions article (that article was shown).

4. **In-window ECB title with no policy token.** “Christine Lagarde: IMFC Statement”, shadow `ecb_press`, `published_at` `2026-10-17T01:00:00-04:00`, reason `stage1_recall`. `recall_candidate` is false. ECB is not under the BoJ/BoE title filter; this row survived the parser and died at stage 1. The speech body was not fetched. The title alone does not support a claim that a rate decision was missed.

5. **BoJ private-credit review dies at the title filter, date not recorded.** “(BOJ Review)The Expansion and Diversification of Private Credit Funds” is `official_title_filter`. `_boj_boe_title_kept` is false (no “monetary policy” / “policy rate” / “interest rate” pattern). The shadow row has `published_at` null because the filter returns before the window reason is stored, so this review cannot say the review was inside 24 hours. If it had reached stage 1, `recall_candidate` on that title is true. Score would be `assess` / `g10_policy_path` / 9 because the token `boj` fires before the credit branch. Not claimed as an in-window miss.

## Not recall deaths

- “China Q3 growth set to pick up on stimulus, keeping 2026 goal within reach: Reuters poll”, empty summary: recalled, `show`, `china_commodity_spillover`, score 10. The phase 1C headline-only sitemap miss for this title is closed. It is not in tonight’s shadow (Oct 15 dateline; likely outside this window). Not re-fetched here.
- “Oil touches $110 a barrel for first time since May on Middle East, Russia supply fears”, empty summary: recalled, `assess`, `oil_supply_shock`, score 7. Phase 2 locks bare oil (no Hormuz pattern) at assess. It does not die at recall. It was not in the shadow.
- “China Oil Comeback Loses Steam as Iran War Drags On”: recalled via `oil`, then `hold-for-review` / `ambiguous_transmission` because the China branch returns before the oil channel. Phase 1C marks `fixture_safe` false. Not treated as a verified live event.
- Indonesia fires with a palm-oil summary: recalled (the word `oil`), then `suppress` / `local_non_g10_macro`. That is the intended drop.
- India deficit with the oil-import summary: recalled, then `suppress` / `incidental_link_only`. Headline-only India is `recall_candidate` false and still `suppress` if scored.
- September BoE “Bank rate maintained at 3.75%” and Fed FOMC statements in the shadow are `window`. They passed, or never faced, the keyword gate. They are outside 24 hours on this cutoff.
- “Liverpool labour to a win over Brentford” stays `recall_candidate` false. The club name is not the Brent token. The shadow sports row was `stage1_recall`.

## Unverified

- That any CoreWeave headline was on Bloomberg or Reuters tonight. The shadow’s credit queries are empty and the sitemap rows do not contain the name. Absence is not a recall rejection.
- `reuters.com` HTML for the Oct 15 slump wire and the Oct 16 AI-scare analysis (phase 1C: syndication only).
- The body of “Christine Lagarde: IMFC Statement”.
- Whether the BoJ private-credit review, or other `official_title_filter` rows, were inside the 24-hour window. Those diagnostic rows have no timestamp.
- An English wire of the Portuguese Hormuz mine headline or of the Portuguese Anthropic PIB headline on this run’s feeds.
- Bloomberg HTML for the Vietnam URL. The shadow only records `window`.
