# Phase 5B — false positives

**Verdict: PASS**

India, Vietnam, and the Indonesia forest-fire story that also mentions palm oil stay suppressed. Brentford does not recall. A golf headline suppresses. None of those would be shown. The live shadow set still shows plain Russia-sanctions rows at `assess`, which is the intended supplement band. One of those rows is a weekend audio episode, and that carrier is a moderate false positive.

## Method

Scored with `score_transmission` and `recall_candidate` in `scripts/overnight/news_relevance.py`. `public_news_rows` drops `suppress` and `hold-for-review`. `cluster_and_rank` marks both `show` and `assess` as stage `shown` inside the presentation cap. Tie-break is applied later in `news_cluster._apply_tie_break` and is excluded from the scores below.

Shadow file: `/tmp/news_shadow_report.json`, cutoff `2026-10-17T18:28:24.407848-04:00`. Counts: `shown` 6, `relevance_rejection` 183, `presentation_suppression` 0, `discovery_failure` 0.

## Specified strings

| Case | Recall | Disposition | Score | Reason | Kept by `public_news_rows` |
| --- | --- | --- | --- | --- | --- |
| Vietnam GDP headline + parliament-speech summary | false | suppress | -8 | `local_non_g10_macro` | no |
| India trade-deficit headline + oil / Middle East import-bill summary | true | suppress | -8 | `incidental_link_only` | no |
| Indonesia fires headline + palm-oil summary | true | suppress | -8 | `local_non_g10_macro` | no |
| China Q3 stimulus headline + crude-demand summary | true | show | 10 | `china_commodity_spillover` | yes |
| Hormuz refusal / crude bounced | true | show | 15 | `oil_supply_shock` | yes |
| Hormuz diplomatic reopening | true | show | 13 | `oil_supply_shock` | yes |
| Chicago Fed national activity index | true | assess | 7 | `us_activity_index` | yes |
| "Liverpool labour to a win over Brentford" | false | hold-for-review | 0 | `ambiguous_transmission` | no |
| "Bloomberg This Weekend: Trump Halts Russia Sanctions" | true | assess | 8 | `geopolitics_haven_or_oil` | yes |

Vietnam summaries tried: "Parliament growth target." and a parliament-speech sentence. Both suppress. The subject rule is `vietnam` and `gdp` on the combined blob, penalty `-8`, channels empty.

India text: headline "India Trade Deficit Widened in September on Higher Import Bill" and summary "India's trade gap expanded in September as festive demand and surging oil prices pushed up imports, adding to risks from the drawn-out conflict in the Middle East." Recall is true because `oil` is a stage-1 token. Stage 2 runs the subject rule first (`india` plus `trade deficit` / `import bill`), so the oil mention never fires `oil_energy_tot`.

Indonesia text: "Indonesia's president ready to accept foreign assistance to combat fires, foreign minister says" / "Officials also mentioned palm oil plantations near the fire zone." Recall is true because `\boil\b` matches inside "palm oil". Stage 2 matches `indonesia` plus `fires` first and suppresses with channels at 0.

China text: "China Q3 growth set to pick up on stimulus, keeping 2026 goal within reach: Reuters poll" / "The poll cited stimulus and a rebound in crude demand." Components: `channel_china_spillover` 5, `asset_named` 3, `shock` 2. Assets `AUD`, `iron_ore`. This is a transmission show, not a false positive.

Chicago Fed: "Chicago Fed national activity index slips to -0.04 in August" plus a CFNAI sentence. Components: `channel_usd_rates` 5, `asset_named` 2, `shock` 0. Assets `USD`. This is the US activity rule. It is kept as `assess`. It is transmission.

## Hormuz, before tie-break

Refusal fixture: "Iran Says Won't Soften Demands After Trump Rejects Hormuz Offer" / "Iran said it will not soften demands after President Trump rejected a Hormuz offer, and crude bounced." The alternate "Crude bounced after Iran refused to soften Hormuz demands" scores the same.

Diplomatic fixture: "US and Iran signal diplomatic progress on Hormuz reopening" / "Officials described productive talks on easing Hormuz tensions."

| Row | Oil | Geopolitics | Asset | Shock | Score | Assets |
| --- | --- | --- | --- | --- | --- | --- |
| Refusal / crude bounced | 5 | 4 | 3 | 3 | **15** | Brent, USD, WTI, CAD, UST |
| Diplomatic reopening | 5 | 4 | 2 | 2 | **13** | Brent, USD |

Both are `show`, primary channel `oil_energy_tot`, reason `oil_supply_shock`. The refusal score is higher before tie-break (15 > 13). Acute phrases (`won't soften`, `rejected`, `demands`, `bounced`, `crude bounced`) select shock 3. Diplomatic-only text (`reopening`, `diplomatic`, `easing`) with no acute phrase selects shock 2.

## Brentford and golf

"Liverpool labour to a win over Brentford" does not recall. `\bbrent\b` does not match `Brentford`, and the blob has no `podcast`, `golf`, or `celebrity` token, so the noise rule does not fire either. If stage 2 were reached anyway, the disposition would be `hold-for-review` at score 0, and `public_news_rows` would drop it. The shadow Reuters headline "Barcola shines as Liverpool labour to 2-1 win over Brentford" is `relevance_rejection` / `stage1_recall`.

A golf headline ("McIlroy wins the Masters in a golf playoff") recalls false and scores `suppress` / `noise_non_market` / -10. It would not be shown.

## Plain sanctions with no energy

`assess` is acceptable.

"Zelenskyy Slams Russia Sanctions", the shadow Starlink/sanctions headline, and "Zelenskiy criticizes Trump's waiver of sanctions on Russia as 'wrong'" all score the same: `geopolitics_haven` 4, `asset_named` 2, `shock` 2, total 8, assets `USD`, reason `geopolitics_haven_or_oil`, disposition `assess`. No oil, crude, diesel, energy, LNG, Brent, WTI, OPEC, or Hormuz token is required.

That matches the supplement band (7–9) and the locked expectation that a sanctions headline is recalled and not suppressed. The same function sends an energy sanctions headline to `show` at 14 (`oil_energy_tot` plus `geopolitics_haven`), as with "Trump Halts New Russia Energy Sanctions to Ease Diesel Costs". Plain sanctions stay below the show threshold. They can still appear in the shown list because `assess` is eligible for `items`. That is a soft over-include when the copy is a political complaint and names no haven bid. It is the designed disposition, not a false `show`.

## Bloomberg This Weekend

**False positive. Severity: moderate.**

Exact headline "Bloomberg This Weekend: Trump Halts Russia Sanctions" with an empty summary, and again with the Reuters headline-only placeholder summary: recall true, `assess`, score 8, `geopolitics_haven_or_oil`. `public_news_rows` keeps it.

The shadow row is in the shown set:

- Headline: Bloomberg This Weekend: Trump Halts Russia Sanctions
- URL: `https://www.bloomberg.com/news/audio/2026-10-17/bloomberg-this-weekend-trump-halts-russia-sanctions-podcast`
- Stage: `shown`
- Reason: `geopolitics_haven_or_oil`

The path is `/news/audio/2026-10-17/bloomberg-this-weekend-trump-halts-russia-sanctions-podcast`. `_path_blocked` looks for `/podcast`. This path does not contain that segment, so the audio item is not a path drop. The noise rule only sees headline and summary. Those strings do not contain `podcast`. Putting the word `podcast` into the headline does suppress and fails recall. The live row never gets that token into the scored blob.

Severity is moderate because the row is one of the six stories the shadow marked shown, so it is desk-visible. It stays moderate rather than material because the disposition is `assess` at 8, under the show threshold, and the scored topic is the same plain-sanctions path judged acceptable above. The false part is the carrier: a weekend audio episode whose slug ends in `podcast`.

## Shadow shown set

All six `stage: shown` rows, scored on the headline (Reuters row also scored with the headline-only summary; result unchanged):

| Headline | Score | Disposition | Class |
| --- | --- | --- | --- |
| Zelenskyy Slams 'Deliberate' Starlink Slowdown, Russia Sanctions | 8 | assess | Plain sanctions. Acceptable assess. Audio URL, no energy token. |
| Bloomberg This Weekend: Trump Halts Russia Sanctions | 8 | assess | Moderate false positive (weekend audio). |
| US Interest Costs Hit Record $1 Trillion, Risking Debt Snowball | 9 | assess | Transmission. `usd_rates_repricing`, assets USD, UST. |
| Trump Pauses Russia Energy Sanctions, Houthis Hit Yemen Airport | 14 | show | Transmission. Energy token. Audio URL, in-policy content. |
| Trump Halts New Russia Energy Sanctions to Ease Diesel Costs | 14 | show | Transmission. Energy and diesel. |
| Zelenskiy criticizes Trump's waiver of sanctions on Russia as 'wrong' | 8 | assess | Plain sanctions. Acceptable assess. |

Vietnam's shadow row is `relevance_rejection` / `window` with `published_at` null. It is absent from `shown`. The India shadow hit is a T20 cricket headline at `stage1_recall`. No Indonesia headline is in the file. No golf headline is in `shown`.

## Residual, outside this verdict

An Indonesia palm-oil export headline with no `fire`, `fires`, or `forest` token is a different string from the fires case. "Indonesia palm oil exports rise on stronger shipments" / "Palm oil inventories fell as exports increased" recalls true and scores `assess` 7, `oil_supply_shock`, assets Brent, WTI, and `public_news_rows` keeps it. The subject rule keys off fire or forest, so palm oil alone is bare oil. That leak was not in the shadow shown set and is not the fires-plus-palm-oil case.

## Verdict

**PASS.** India suppresses (`incidental_link_only`, -8) and is dropped from public rows. Vietnam suppresses (`local_non_g10_macro`, -8) and does not recall. Indonesia with `fires` plus a palm-oil summary suppresses (`local_non_g10_macro`, -8) and is dropped from public rows. Brentford does not recall. Golf suppresses. China, Hormuz, and Chicago Fed are transmission keeps. Plain sanctions at `assess` are acceptable. The weekend sanctions audio row is a moderate false positive and does not move the verdict.
