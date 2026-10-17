# Phase 1B — G10 FX/rates transmission relevance

Policy only. No scorer code in this phase. Plug into items that already exist. Do not add a model, embedding, or classifier.

## Defect

`_salience_components` (`scripts/overnight/live_news.py:583-613`) scores keyword tiers, a second keyword bonus named `transmission` (minimum 1), Bloomberg (+2), recency (+2), and live novelty (+2). None of those is a G10 channel. Bare `gdp` sits in `MARKET_TOKENS` (`live_news.py:66`) and is enough for `_text_matches_market_gate` (`live_news.py:227-231`).

The hard gate runs only on Bloomberg RSS and Reuters sitemap parse (`live_news.py:333`, `live_news.py:379`). Accepted research bypasses it: `overlay_accepted_research` copies `research_supplement.news` (`scripts/overnight/accepted_news.py:53-60`) and `build_accepted_public_news` persists that list (`accepted_news.py:139-149`). Publishability checks title, summary, and optional `published_at` only (`scripts/overnight/research_publishability.py:32-46`).

`data/overnight/accepted_public_news.json` as of `2026-10-17T08:58:03-04:00` includes:

- "Vietnam Prime Minister Targets 2027 GDP Growth of at Least 10%" (`accepted_public_news.json:57-60`). Parliament growth target. No policy body, commodity, China mechanism, or funding link.
- "India Trade Deficit Widened in September on Higher Import Bill" (`accepted_public_news.json:63-66`). The subject is India's gap. The summary uses oil prices and the Middle East as the cause of the import bill, not as a supply shock.

`_impact` (`scripts/apply_overnight_news_refresh.py:143-155`) can still mark a story HIGH if the blob contains `oil`. A local print that mentions oil as color is promoted, not rejected. `_primary_category` falls through to `macro` (`live_news.py:275`) and does not distinguish domestic non-G10 macro from a G10 driver.

`attribute_country_codes` (`live_news.py:93-164`) emits only US, CA, AU, NZ, EA, JP. UK Treasury is intentionally empty (`tests/test_live_news_acquisition.py:567`). BoE/GBP are absent from `MARKET_TOKENS` (`live_news.py:29-67`). China is not a country code. Asset lists in this policy must not depend on `country_codes`.

## What this is

A two-stage, integer, channel policy for desk news: broad recall, then an explainable transmission score. It decides whether a story can move USD rates, a named G10 policy path, G10 FX, global risk, credit/funding, oil terms of trade, or China into AUD/NZD/JPY/EUR/commodities.

G10 policy bodies for this desk: Fed, ECB, BoE, BoJ, BoC, RBA, RBNZ. G10 currencies: USD, EUR, GBP, JPY, CAD, AUD, NZD. CHF is a haven asset when a story names haven demand. SNB is out of scope. China is a spillover source, not a local-noise country and not a G10 policy body.

## Channels

A channel fires only when the role below is met. A bare token is not a fire.

| Channel id | Fires when | Typical assets |
| --- | --- | --- |
| `usd_rates` | Treasuries, yields, SOFR/funding, or a US inflation or payrolls print that reprices the US curve | UST, SOFR, USD |
| `g10_policy` | A named decision, hold, hike, cut, or path comment from Fed, ECB, BoE, BoJ, BoC, RBA, or RBNZ | That currency, its policy path |
| `global_risk` | A megacap or index shock that reprices yields, the dollar, or risk appetite. An earnings recap with no rates, FX, or credit link does not fire | SPX, UST, USD |
| `credit_funding` | Bank or funding stress, a spread or SOFR move, or debt issuance large enough to matter for spreads, Treasury supply, or risk appetite | Credit spreads, SOFR, UST |
| `oil_energy_tot` | Oil, Brent, WTI, crude, Hormuz, OPEC, LNG, or a pipeline as supply, price, shipping, or embargo | Brent, WTI, CAD, USD, UST |
| `china_spillover` | China growth, property, PBOC, or stimulus tied to commodities or to AUD, NZD, JPY, or EUR | AUD, NZD, JPY, EUR, iron ore, copper, oil |
| `geopolitics_haven` | Sanctions, blockade, or conflict that moves oil or a safe haven (USD, JPY, gold, Treasuries). Local politics do not fire | Oil, USD, JPY, gold, UST |

Primary channel is the highest-weight firing channel. Ties: `oil_energy_tot`, then `g10_policy`, then `usd_rates`, then `credit_funding`, then `china_spillover`, then `geopolitics_haven`, then `global_risk`.

## Decision record

Add one object. Do not remove or rename existing keys.

```text
transmission.disposition       assess | show | suppress | hold-for-review
transmission.affected_assets   list of tickers from the closed list below
transmission.channel           primary channel id
transmission.channels          every channel that fired
transmission.reason_code       closed code below
transmission.score             transmission_score (int, penalties allowed)
transmission.components        dict[str, int]
```

Closed assets: `USD`, `EUR`, `GBP`, `JPY`, `CAD`, `AUD`, `NZD`, `CHF`, `UST`, `SOFR`, `Brent`, `WTI`, `SPX`, `credit_spreads`, `gold`, `iron_ore`, `copper`.

Closed reason codes: `oil_supply_shock`, `china_commodity_spillover`, `g10_policy_path`, `usd_rates_repricing`, `global_risk_beta`, `credit_funding_stress`, `ai_capex_credit`, `geopolitics_haven_or_oil`, `local_non_g10_macro`, `incidental_link_only`, `noise_non_market`, `ambiguous_transmission`.

Disposition:

- `show` — public drivers and the rolling window. Requires `transmission_score >= 10`, at least one real channel, no penalty.
- `assess` — keep in the research supplement below the caps. `transmission_score` 7–9 and a real channel. Not a Top Market Driver and not one of the six last-24 cards.
- `hold-for-review` — a G10 or China or commodity word is present but the role test failed. Exclude from caps. Do not treat as accepted public news.
- `suppress` — drop from `research_supplement.news` on the public artifact and from HTML. Keep an audit row outside the item list if a later phase wants one. Do not invent that row in the item schema.

`presentation_caps` stay `{last_24_hours: 6, top_market_drivers: 3}` (`live_news.py:774-781`). Only `show` competes for those slots. Tests assert those integers (`tests/test_live_news_acquisition.py:244-245`).

## Negative rules

Apply the subject test before any channel points.

1. **Local non-G10 macro.** The grammatical subject is a country outside the G10 desk set, and the story is a domestic GDP target, trade balance, CPI, budget, or parliament speech, with no firing channel. Vietnam and India match. Same pattern for other non-G10 local prints. Reason `local_non_g10_macro`. Disposition `suppress`. Force every channel to 0. Penalty `-8`.
2. **Incidental link.** A local non-G10 print mentions oil, China, or a G10 name only as color for the local number (India's deficit widened because the oil import bill was already high). That mention does not fire `oil_energy_tot`, `china_spillover`, or `g10_policy`. Reason `incidental_link_only`. Disposition `suppress`. Penalty `-8` once. Do not also apply the local penalty.
3. **Noise.** Podcasts, sports, celebrity, and local politics with no haven or oil channel. `NOISE_EXCLUDE` is already `podcast`, `golf`, `celebrity` (`live_news.py:69`). Reason `noise_non_market`. Disposition `suppress`. Penalty `-10`.
4. **Ambiguous proper noun.** "China", "India", "yields", or "AI" without the role in the channel table. Reason `ambiguous_transmission`. Disposition `hold-for-review`. Channel points 0. No penalty. This is not `show`.

China growth, property, or stimulus is not rule 1. A US, euro-area, Japan, UK, Canada, Australia, or New Zealand domestic print is not rule 1. It still needs a firing channel.

## Positive rules

These fire channels. They do not require `MARKET_TOKENS`.

1. **Oil supply shock.** Hormuz, OPEC, blockade, export halt, or a Brent/WTI price shock. `oil_energy_tot` and, if conflict or a haven is named, `geopolitics_haven`. Reason `oil_supply_shock` or `geopolitics_haven_or_oil`.
2. **China spillover.** Growth, property, or stimulus that names commodities or AUD, NZD, JPY, or EUR. Reason `china_commodity_spillover`. A China dateline with no commodity and no Asian G10 FX link stays `hold-for-review`.
3. **AI capex financing.** A data-center or hyperscaler bond or loan that the story ties to credit spreads, Treasury supply, or risk appetite. Reason `ai_capex_credit`. The word "AI" alone does not fire. Phase 1C owns any single-name fact pattern. This policy uses the structure only.
4. **Bank or funding stress.** Deposit, repo, SOFR, or spread stress. Reason `credit_funding_stress`.
5. **Megacap or index shock that reprices yields.** `global_risk` and `usd_rates`. Reason `global_risk_beta`. A stock story that does not reprice yields, FX, or credit stays off the desk.
6. **Named G10 policy or USD rates.** Fed/ECB/BoE/BoJ/BoC/RBA/RBNZ path, or a US curve move. Reasons `g10_policy_path`, `usd_rates_repricing`. BoE counts even though country attribution will not emit a UK code.

## Two-stage replacement of the keyword hard gate

Stage 1 is recall. Stage 2 is the score. `_text_matches_market_gate` must stop being a sufficient-token allowlist.

**Stage 1 — candidate.** Keep the existing non-macro drops: `/video`, `/newsletter`, `/podcast` paths (`live_news.py:330-331`) and hard noise with no channel. Pass the item into stage 2 when any of these is true:

- a current macro, energy, FX, or policy token, **except** bare `gdp`, bare `recession`, or bare `unemployment` as the only hit;
- credit, funding, spread, bank-stress, bond, or loan language;
- index, megacap, or equity-shock language;
- AI, data-center, or capex language together with financing language;
- China plus commodity or AUD/NZD/JPY/EUR language;
- a named G10 body, including Bank of England.

A story that misses `MARKET_TOKENS` and hits stage 1 through credit, equity stress, or AI financing is a candidate. It is not dropped. Stage 1 does not assign `show`.

**Stage 2 — transmission score.** Replace the meaning of the keyword `transmission` component. Sort key stays `market_salience.score` (`live_news.py:708`, `live_news.py:760-765`). Set that score to `max(0, transmission_score) + tie_break` so a penalty cannot rank a suppressed row on recency. Tie-break does not change disposition.

Accepted packets must run stage 2 before `build_accepted_public_news` writes `news`. Live parse alone cannot catch Vietnam or India, because those rows are not live-news candidates.

## Score components

Channel weights (0 if the role test fails):

| Component | Weight if fired |
| --- | --- |
| `channel_usd_rates` | 5 |
| `channel_g10_policy` | 5 |
| `channel_oil_energy` | 5 |
| `channel_china_spillover` | 5 |
| `channel_credit_funding` | 5 |
| `channel_global_risk` | 4 |
| `channel_geopolitics` | 4 |
| `asset_named` | 0, or 2 for one asset, or 3 for two or more |
| `shock` | 0 routine, 2 material, 3 acute (blockade, emergency funding, policy surprise) |
| `subject_penalty` | 0, or -8 local/incidental, or -10 noise |

`transmission_score` is the sum. Tie-break, reported and excluded from the threshold:

| Component | Weight |
| --- | --- |
| `recency` | 1 if published within 12 hours, else 0 |
| `novelty` | 1 if the cluster contains a live candidate, else 0 |
| `distribution_weight` | 1 if any edge is Bloomberg, else 0 |

Today those three can add +6 and the keyword bonus floors `transmission` at 1 (`live_news.py:597-605`). A local GDP story with `tier1_relevance` 2 can outrank a thinner real channel. Tie-break max is now +3, and it cannot create a channel.

Invariant for later code: the live Hormuz Bloomberg item must keep `market_salience.score` strictly above the older diplomacy baseline (`tests/test_live_news_acquisition.py:203-206`). Both remain `show`. The live row has the higher shock and the tie-break.

## Worked examples

Tie-break is shown separately. Disposition uses `transmission_score` only.

**(a) Vietnam GDP target.** Subject is a domestic growth speech. No channel role. `subject_penalty -8`. All channels 0. Score `-8`. `market_salience.score` 0. Disposition `suppress`. Reason `local_non_g10_macro`. Assets `[]`.

**(b) India trade deficit.** Subject is the local gap. Oil and the Middle East explain the import bill (`accepted_public_news.json:64-65`). Incidental rule. Channels forced to 0. Penalty `-8` once. Score `-8`. Disposition `suppress`. Reason `incidental_link_only`. Assets `[]`. A later story that is itself the oil shock, or that names INR stress feeding USD funding, is a different item and can fire `oil_energy_tot` or `credit_funding`.

**(c) Hormuz / oil.** Fixture shape: Iran refuses to soften Hormuz demands and crude bounces (`tests/test_live_news_acquisition.py:123-126`). `channel_oil_energy 5`, `channel_geopolitics 4`, `asset_named 3` (Brent, USD), `shock 3`. Score `15`. Live tie-break `3` (recency, novelty, Bloomberg). Sort score `18`. Disposition `show`. Reason `oil_supply_shock`. Assets `Brent`, `WTI`, `USD`, `CAD`, `UST`. Older diplomacy on reopening: oil 5 + geopolitics 4 + asset 2 + shock 2 = `13`, tie-break `0`. Still `show`, still below the live row.

**(d) China stimulus.** Generic: property and infrastructure stimulus aimed at commodity demand. `channel_china_spillover 5`, `asset_named 3` (AUD, iron ore), `shock 2`. Score `10`. Disposition `show`. Reason `china_commodity_spillover`. Assets `AUD`, `NZD`, `iron_ore`, `copper`. If the text names China and no commodity and no AUD/NZD/JPY/EUR link: score `0`, `hold-for-review`, `ambiguous_transmission`.

**(e) Large AI data-center financing.** Generic structure, not a reported headline and not a named borrower. A data-center borrower prices a bond and loan to fund compute capex, and the story ties that supply to credit spreads and Treasury yields. `channel_credit_funding 5`, `asset_named 3` (credit spreads, UST), `shock 2`. Score `10`. Disposition `show`. Reason `ai_capex_credit`. Assets `credit_spreads`, `UST`, `SPX`. No `gdp`, `fed`, or `oil` token is required. A small vendor loan that names neither spreads nor yields nor risk appetite does not fire. Disposition `hold-for-review`, reason `ambiguous_transmission`.

Bank stress and an index shock that reprices yields follow the same arithmetic. Funding stress: credit 5 + usd_rates 5 + asset 3 + shock 3 = `16`, `show`, `credit_funding_stress`. Index shock into yields: global_risk 4 + usd_rates 5 + asset 3 + shock 2 = `14`, `show`, `global_risk_beta`.

## Fields

Preserve every key tests and the publisher already read. Add `transmission` beside them. Items that have not been scored must stay valid: refresh and publishability already tolerate missing `primary_category`, `country_codes`, `url`, and `market_salience`.

Publishability requires non-empty `headline` or `title`, and `summary` (`research_publishability.py:18-46`). Malformed `published_at` is invalid. Absent `published_at` is undated and still renderable. Urlless news is kept (`tests/test_overnight_news_refresh.py` asserts undated and urlless rows still render).

Keys tests assert or require on live acquisition (`tests/test_live_news_acquisition.py`):

- Acquisition: `mode`, `partial`, `candidates`, `receipts`, and on each receipt `status`, `checked_at`, `candidate_count`, `result_count`, `failure`.
- Candidate and merged item: `source_name`, `url`, `headline`, `verification_status`, `country_codes`, `id`.
- `source_edges`, `source_edges[].source_name`, `source_edges[].url`.
- `market_salience.score` (ordering only; component names are not asserted).
- `research_supplement.top_market_driver_candidates`, `presentation_caps.last_24_hours`, `presentation_caps.top_market_drivers`.

Keys the accepted-news and refresh fixtures rely on (`tests/test_accepted_news_architecture.py`, `tests/test_overnight_news_refresh.py`, `apply_overnight_news_refresh.py:143-167`):

- `headline`, `summary`, `published_at`, `url`, `source_name`, `primary_category`, `country_codes`.
- Central-bank rows may use `title` and `institution` when `headline` or `source_name` is absent (`apply_overnight_news_refresh.py:72-73`).
- Artifact envelope: `schema_version`, `type`, `overnight_run_id`, `as_of`, `summary`, `news`, `central_bank_research`, `source` (`accepted_news.py:107-116`).

Merged items also carry `discovery_surface` and string `distribution_weight` on candidates (`live_news.py:338-350`, `live_news.py:387-399`). Leave those. The new integer `distribution_weight` lives only inside `transmission.components` and `market_salience.components`.

`market_salience` stays `{score, distribution, components}` (`live_news.py:616-624`). `distribution` remains `high` or `standard`. When stage 2 runs, `components` should be the channel table plus the three tie-break keys, and `score` should be the sort score defined above. Do not keep `tier1_relevance` as a way to pass the gate.

`_market_label` may later read `transmission.affected_assets`. Until then it keeps using `country_codes` and `primary_category` (`apply_overnight_news_refresh.py:158-162`). Missing `transmission` must not change HTML.

## Hook order for the implementer

1. Stage 1 inside `_text_matches_market_gate`. Delete bare `gdp` as a sufficient pass. Add the recall classes above, including BoE.
2. Stage 2 inside `_salience_components` / `_apply_salience`, writing `transmission` and the compatible `market_salience`.
3. The same stage 2 function on each accepted `news` row before the public list is stored. `suppress` and `hold-for-review` do not enter `news` on the public artifact. `assess` enters the supplement and is excluded from driver caps. `show` is eligible for caps.
4. Do not filter `central_bank_research` with this policy. Those rows are already official-source research.
5. Do not change receipt shape, verification rules, or country-code tests. UK attribution staying empty is expected; GBP still belongs in `affected_assets` when BoE or gilt yields are the channel.
