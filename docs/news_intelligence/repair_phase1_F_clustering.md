# Repair phase 1F — cluster false merges and noise

Diagnosis only. No scorer change, no test change, no data change. Evidence is `scripts/overnight/news_cluster.py` as executed in this workspace, its callers, `scripts/overnight/news_relevance.py`, `scripts/overnight/news_sources.py`, and the false-positive section of `docs/NEWS_INTELLIGENCE_REPAIR.md` (lines 91–93) plus `docs/news_intelligence/phase5_B_false_positives.md`.

Pairwise numbers below are `_tokenize_headline` / `_same_event` / `cluster_and_rank` on these strings at cutoff `2026-09-27T18:00:00-04:00`.

## 1. Current cluster key and how false merges happen

The cluster key is the headline token set. Issuer, geography, and event type are stored on the item and ignored by the match.

Token set (`news_cluster.py:23-33`): regex `[a-z0-9']+`, lowercased, length greater than 2, minus `DEDUP_STOP` = `the and for after with says said its won will not`. Summary, URL, `country_codes`, `primary_category`, and `transmission` are not tokenized.

Match (`news_cluster.py:36-45`): at least 4 shared tokens and Jaccard at least 0.55. `ormuz` and `hormuz` are different tokens. There is no alias map in this file.

Loop (`news_cluster.py:209-233`): greedy single link. Each item is compared only to `cluster["headline"]`, the first member's headline. Baseline is seeded first, then live. The seed headline is not updated when later edges join.

After a hit, `_merge_cluster` (`news_cluster.py:87-141`) keeps one row:

- Display headline is the newest Bloomberg edge, else the newest edge (`:108-114`).
- Summary is `baseline_items[0]` when any baseline exists, else `live_items[0]` (`:124`). That summary can belong to the other story.
- `country_codes` and `primary_category` come from `live_items[0]` if any live row exists, else `baseline_items[0]` (`:119-129`). They are not a union and they are not the display edge.
- `published_at` is the max edge time (`:117`).
- `verification_status` becomes `corroborated` when two publisher families are present (`:74-80`), including a false merge of Bloomberg with Reuters.
- `id` is `news:` plus the sha256 of the sorted edge URLs (`:67-71`). The swallowed story has no id.
- `cluster_and_rank` then calls `apply_transmission` once on that mixed row (`:240-243`). Disposition is whatever the display headline plus the chosen summary scores. The other event is an edge, not a row.

`country_codes` cannot be the geography key. `attribute_country_codes` (`live_news.py:83-154`) only emits `US CA AU NZ EA JP`. India and Vietnam are absent. The stamp happens in `_apply_recall_and_ceiling` (`live_news.py:229`) before merge, and merge copies one side's list.

`reason_code` cannot be the event-type key. Hormuz diplomacy and Hormuz supply both return `oil_supply_shock` (`news_relevance.py:396-418`). The split is only shock 2 / score 13 versus shock 3 / score 15, and only when `_hormuz_diplomatic` is true and `_hormuz_acute` is false (`:190-192`, `:400-409`). CoreWeave CDS distress and a CoreWeave AI-scare headline both return `ai_capex_credit` (`:202-207`, `:381-394`). Scoring runs after the merge, so it cannot un-merge.

Callers do not add a second key. `live_news.py:11` re-exports `merge_live_news`. `collect.py:295-302` passes baseline packets plus live candidates. `scripts/live_news_discovery_smoke.py:31-35` merges with an empty baseline. `news_relevance.py` does not import `news_cluster`.

### Measured merges that violate the gate

Fixture headlines that already stay apart are low-overlap, not a facet check.

| Pair | Shared | Jaccard | `_same_event` |
| --- | --- | --- | --- |
| Refusal fixture "Iran Says Won't Soften Demands After Trump Rejects Hormuz Offer" vs diplomacy fixture "US and Iran signal diplomatic progress on Hormuz reopening" | `hormuz iran` (2) | 0.167 | false |
| Same refusal vs Reuters wire "Iran refuses to soften demands as Trump rejects Hormuz plan" | 6 | 0.600 | true (the existing same-event test) |
| "Trump rejects Iran Hormuz oil tanker supply demands" (acute: `rejects`, `demands`) vs "Trump diplomatic Iran Hormuz oil tanker supply reopening" (diplomatic: `diplomatic`, `reopening`) | `hormuz iran oil supply tanker trump` (6) | 0.600 | **true** |
| "CoreWeave investors sour on AI debt as credit distress hits record levels" vs "Nvidia investors sour on AI debt as chip distress hits record levels" | `debt distress hits investors levels record sour` (7) | 0.636 | **true** |
| "India September trade gap widens on higher oil import bill" vs "India September oil gap widens on higher Hormuz" | `gap higher india oil september widens` (6) | 0.600 | **true** |
| "Vietnam GDP growth target of at least 10 percent this year" vs "Vietnam oil growth target of at least 10 percent this year" | 7 | 0.778 | **true** |

`cluster_and_rank` on those four false pairs:

- Hormuz supply vs Hormuz diplomacy: 1 item, `corroborated`, `show`, `oil_supply_shock`, score 15. Both headlines are edges. Diplomacy is gone.
- When the diplomacy row is the baseline and the supply-worded live row is newer Bloomberg, display is the live headline and summary is the baseline sentence "Officials described diplomatic reopening talks." Score falls to 13 because `apply_transmission` reads headline plus summary (`news_relevance.py:40-41`, `:665-669`). One cluster, one shock value.
- CoreWeave vs Nvidia: 1 item, `corroborated`, `show`, `ai_capex_credit`. The Nvidia headline is a Reuters edge on the CoreWeave row.
- India, trade headline is the Bloomberg display: 0 items. Stage `relevance_rejection`, reason `incidental_link_only`. The Hormuz supply wire is an edge on the suppressed row, so the supply shock is dropped.
- India, Hormuz headline is the Bloomberg display and the trade summary is the other live row's summary that does not contain the trade phrase: 1 item, `show` 15, `corroborated`. The domestic trade-gap headline is an edge on a Hormuz shock.
- India, Hormuz live display plus baseline summary "India's trade gap expanded on the import bill.": 0 items, `incidental_link_only` on the Hormuz headline. The subject rule sees `trade gap` / `import bill` in the baseline summary and suppresses the supply shock.
- Vietnam, GDP headline is the Bloomberg display: 0 items, `local_non_g10_macro`. The G10 oil wire is dropped with the GDP row.
- Vietnam, oil headline is the Bloomberg display and its own summary names Hormuz: 1 item, `show` 15, `corroborated`, GDP headline attached as an edge.
- Vietnam, oil live display plus baseline summary "Parliament GDP target.": 0 items, `local_non_g10_macro` on the oil headline. `vietnam` and `gdp` in the baseline summary suppress the supply story.

### Measured same-event failures

| Pair | Shared | Jaccard | `_same_event` |
| --- | --- | --- | --- |
| "CoreWeave credit default swaps hit distress levels as investors sour on AI debt" vs "CoreWeave CDS hit distress as investors sour on AI debt" | 6 | 0.545 | **false** (threshold is 0.55) |
| "Strait of Hormuz tanker mines" vs "Strait of Ormuz tanker mines" | `mines strait tanker` (3) | 0.600 | **false** (`ormuz` ≠ `hormuz`, shared count under 4) |
| "IRGC says two tankers hit mines in the Strait of Hormuz" vs the same sentence with Ormuz | 6 | 0.750 | true without an alias, because the other six tokens match |
| Portuguese sitemap title "Guarda Revolucionária do Irã afirma que dois petroleiros atingiram minas no Estreito de Ormuz" vs the English IRGC mine sentence | 0 | 0.000 | false |
| Refusal fixture vs "Crude bounced after Iran refused to soften Hormuz demands" | 4 | 0.364 | false |

`ai` has length 2, so it is deleted before the Jaccard. The issuer token `coreweave` is only one shared token against "Analysis:Why CoreWeave is in the crosshairs of the AI scare" (shared 1, Jaccard 0.071, already separate). That scare row is a different event from CDS distress. The false merge is a different issuer copying the credit boilerplate, measured above.

## 2. Noise drops and what still gets through

Path drop, before recall (`news_sources.py:254-261`, applied at `:301` for Bing and `:362` for the Reuters sitemap). The path string must contain `/video`, `/newsletter`, `/podcast`, or `/audio`. Reason on the parser row is `path_drop`. `live_news.py:299-307` rewrites that parser drop to stage `relevance_rejection`. Host and query are not checked. A slug ending in `-podcast` on `/news/articles/...` does not contain `/podcast` and is not dropped. `/news/audio/...` is dropped. Tests: `tests/test_live_news_acquisition.py:119-153` (video and newsletter) and `tests/test_news_intelligence.py:189-202` (audio path).

Word drop (`news_relevance.py:151-163` and the recall short-circuit `:563-566`): whole words `podcast`, `golf`, `celebrity`, unless the blob also has `hormuz`, `opec`, `brent`, `wti`, or `crude`. Disposition `suppress`, reason `noise_non_market`, score `-10`. Recall returns false, so the row never becomes a candidate. `NOISE_EXCLUDE` in `live_news.py:69` is the same three words and is not read. The golf fixture in `tests/test_live_news_acquisition.py:38-39` dies at recall, not at the path check. "McIlroy wins the Masters in a golf playoff" is `suppress` / `noise_non_market`. "Liverpool labour to a win over Brentford" does not recall (`\bbrent\b` misses Brentford); `tests/test_news_intelligence.py:139`.

Subject drops that are not path noise, same function: Vietnam and `gdp` → `suppress` / `local_non_g10_macro` (`:114-124`); India plus `trade deficit` / `trade gap` / `import bill` → `suppress` / `incidental_link_only` even when the summary says oil (`:125-137`); Indonesia plus fire/forest → `suppress` (`:138-150`). `tests/test_news_intelligence.py:310-329` covers the India row alone.

What still reaches `items`:

- Sanctions with no energy token: `assess`, score 8, reason `geopolitics_haven_or_oil`, assets `USD` (`news_relevance.py:471-497`). `cluster_and_rank` treats `assess` like `show` for the 24-row cap (`news_cluster.py:246-248`), so a thin day shows them. Locked by `tests/test_news_intelligence.py:130-132` and by `docs/NEWS_INTELLIGENCE_REPAIR.md:44` and `:93`. The 2026-10-17 shadow showed three of these (`phase5_B_false_positives.md:84-92`).
- The weekend-audio carrier is a path drop only when the path contains `/audio` or `/podcast`. Headline "Bloomberg This Weekend: Trump Halts Russia Sanctions" has none of `podcast` / `golf` / `celebrity`, scores `assess` 8, and is kept if the URL is an article slug. That is the residual of the shadow row in `phase5_B_false_positives.md:64-78` after the `/audio` fix.
- Supply escape: "McIlroy wins golf playoff as crude settles" recalls and scores `assess` / `oil_supply_shock` / 7. "Golf event cancelled near Hormuz" scores `show` 15. The escape list does not include `oil`, `diesel`, `energy`, or `ormuz` (`news_relevance.py:152`, `:565`).
- Indonesia palm-oil exports with no fire token: `assess` 7, `oil_supply_shock` (`phase5_B_false_positives.md:98`). The fires rule does not run.
- "India faces crude supply crunch" with no trade-gap phrase: `assess` 7. The India suppress needs the trade phrase.
- "Vietnam oil exports to Japan rise": `assess` 7. The Vietnam suppress needs `gdp`. Adding Hormuz to that headline makes it `show` 15.
- Bare oil, Chicago Fed (`assess` 7), and the US interest-cost / debt-snowball row (`assess` 9) stay in `items` by design (`docs/NEWS_INTELLIGENCE_REPAIR.md:44`).
- Reuters rows are headline-only (`news_sources.py:41`, `:360`). A noise word that exists only in the article body is never seen. A transmission link that exists only in the body is also never seen (`docs/NEWS_INTELLIGENCE_REPAIR.md:101`).

Clustering sits in front of these drops. A domestic India or Vietnam row that shares a boilerplate token set with an oil wire is scored only as the merged display plus the chosen summary, so the subject rule can either hide the oil shock or publish the domestic headline as corroboration. Section 1 measured both directions.

## 3. Smallest clustering change

Edit `_tokenize_headline` and `_same_event` only. Keep the greedy loop, the Bloomberg display edge, the cap of 24, and Jaccard 0.55 for rows that have no facet. Do not add a model, a package, or a new module. `news_cluster.py` already imports `news_relevance`. Call the existing predicates. Do not key off `reason_code` or `country_codes`.

Alias, inside the tokenizer: replace token `ormuz` with `hormuz`. That is the same spelling the scorer already accepts (`news_relevance.py:167-173`). It is not a translation. The Portuguese IRGC sentence still shares zero tokens with the English mine sentence after the alias and must stay its own row.

Facet, from the headline only, first match:

| Facet | Predicate already in `news_relevance.py` |
| --- | --- |
| `india_trade` | `india` and `trade deficit` / `trade gap` / `import bill` (`:125-127`) |
| `india_oil` | `india` and `oil` / `crude` / `hormuz` / `supply`, and not `india_trade` |
| `vietnam_gdp` | `vietnam` and `gdp` (`:114`) |
| `vietnam_oil` | `vietnam` and `oil` / `crude` / `hormuz` / `supply`, and not `vietnam_gdp` |
| `hormuz_diplomacy` | `_hormuz_mentioned` and `_hormuz_diplomatic` and not `_hormuz_acute` (`:167-192`) |
| `hormuz_supply` | `_hormuz_mentioned` otherwise (`:396-409`) |
| `coreweave_cds` | token `coreweave` and (`cds` or `credit default` or `debt` or `distress`) |
| `coreweave_other` | token `coreweave` otherwise |
| empty | none of the above |

Issuer bit: `coreweave` when that token is present, otherwise empty. No entity list. Nvidia, Broadcom, and a generic AI headline have an empty bit.

`_same_event` after alias tokens:

1. Both facets non-empty and different → false.
2. Exactly one side has the `coreweave` bit → false.
3. Fewer than 4 shared tokens → false.
4. Both facets non-empty and equal → true.
5. Else Jaccard ≥ 0.55, unchanged.

Step 4 is what lets the CDS pair through at Jaccard 0.545 (6 shared tokens, same `coreweave_cds` facet). Lowering the global 0.55 cutoff would also accept more boilerplate collisions, so the cutoff stays. Step 1 splits the measured Hormuz pair (`hormuz_supply` vs `hormuz_diplomacy`, Jaccard 0.600), the India pair (`india_trade` vs `india_oil`), and the Vietnam pair (`vietnam_gdp` vs `vietnam_oil`). Step 2 splits CoreWeave vs Nvidia (Jaccard 0.636) without merging every AI headline that happens to share `investors` / `sour` / `levels`.

Rows the current tests already lock, under this rule:

- `tests/test_live_news_acquisition.py:292-302` refusal vs "Iran refuses to soften demands…": both `hormuz_supply`, 6 shared, still one corroborated item, Bloomberg edge kept.
- `tests/test_live_news_acquisition.py:179-207` refusal vs the diplomacy fixture: facets differ, and Jaccard is already 0.167. Two items. Salience order is unchanged because they never shared a cluster.
- `tests/test_news_intelligence.py:204-218` identical CoreWeave headline on Bloomberg and Reuters: same facet, still one `show` row.

Residual, left alone on purpose:

- "Two oil tankers hit mines in Strait of Hormuz after Iran attack" vs "Two oil tankers await mines in Strait of Hormuz after Iran talks" still merges (shared 7, Jaccard 0.636). Both are `hormuz_supply`. `talks` is not in `_hormuz_diplomatic`. Adding it would be a new cue, not the smallest fix. The acceptance diplomacy wording already uses `diplomatic` / `reopening` / `easing`.
- Two different `hormuz_supply` incidents that share 4 or more tokens merge. The refusal fixture vs the crude-bounce wire is shared 4 at Jaccard 0.364; step 4 would join them. Those two strings are the same refusal incident in the existing fixtures. A later, genuinely different supply shock that copies `iran hormuz oil trump` can still join.
- The Portuguese mine headline does not join the English wire. Recall already scores it on its own (`tests/test_news_intelligence.py:102-107`). Clustering must not grow a translator to finish that join.
- A same-event CDS wire that omits the word CoreWeave fails step 2 against a wire that includes it. Both locked wires use the name.

### Tests that do not exist yet

No test mentions a facet, an issuer, `ormuz` as a cluster alias, or a parallel-boilerplate collision. The cluster tests that exist are `test_same_event_keeps_bloomberg_edge`, `test_hormuz_bloomberg_outranks_stale_diplomacy` (low-overlap fixtures only), and `test_reuters_sitemap_keeps_coreweave_headline` (byte-identical headline).

Add these next to the cluster calls in `tests/test_news_intelligence.py` / `tests/test_live_news_acquisition.py`:

1. `test_hormuz_supply_does_not_merge_with_diplomacy` — "Trump rejects Iran Hormuz oil tanker supply demands" vs "Trump diplomatic Iran Hormuz oil tanker supply reopening". Expect two items. The current diplomacy test does not cover Jaccard 0.600.
2. `test_coreweave_cds_wires_merge` — "credit default swaps … AI debt" vs "CoreWeave CDS hit distress as investors sour on AI debt". Expect one item, both URLs as edges. Today this is two `single_source` rows.
3. `test_coreweave_cds_does_not_merge_unrelated_ai` — the CoreWeave credit boilerplate vs the Nvidia credit boilerplate. Expect two clusters. Today they are one `corroborated` row.
4. `test_india_trade_gap_does_not_merge_oil_shock` — the India pair in section 1, both display orders (trade headline as Bloomberg, and Hormuz headline as Bloomberg with the trade-gap sentence as the other summary). Expect the Hormuz row to remain `show` and the trade-gap row to remain `incidental_link_only`, as two assessments, not one edge list.
5. `test_vietnam_gdp_does_not_merge_g10_oil` — the Vietnam pair in section 1, both display orders, including a baseline GDP summary behind a live oil headline. Expect the oil row to survive and the GDP row to stay `local_non_g10_macro`.
6. `test_ormuz_alias_merges_with_hormuz_wire` — "Strait of Hormuz tanker mines" vs "Strait of Ormuz tanker mines". Expect one item. Today shared count is 3.
7. Keep `test_same_event_keeps_bloomberg_edge` as the guard that same-incident refusal wires still merge.

## 4. Proposed cluster key

`(facet, coreweave_bit, alias_tokens)` with the seven-line predicate in section 3.

False-merge mechanism in one line: `_same_event` joins any headlines that share 4 tokens at Jaccard ≥ 0.55, then `_merge_cluster` scores one display headline plus one side's summary and treats the other URL as corroboration.
