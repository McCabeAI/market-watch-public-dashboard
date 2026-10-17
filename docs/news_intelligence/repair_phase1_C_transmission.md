# Repair phase 1C — G10 transmission predicates

Diagnosis only. No scorer change. Evidence is `scripts/overnight/news_relevance.py` as executed in this workspace, plus the locks in `tests/test_news_intelligence.py`, `docs/NEWS_INTELLIGENCE_REPAIR.md`, and `docs/news_intelligence/phase1_B_g10_transmission.md`.

`score_transmission` builds one lowercase blob (`news_relevance.py:40-41`, `:358-359`) and returns `_subject_rule` immediately when it matches (`:360-362`). Channel functions below that line are not called. `_word` is a case-insensitive `\b` token (`:48-51`). `_phrase` / `_any_phrase` is a substring (`:44-45`, `:58-59`).

## 1. Name-keyed conditions

### Suppress, inside `_subject_rule` (`:112-164`)

Vietnam GDP. `:114`:

```text
_word(text, "vietnam") and _word(text, "gdp")
```

Return: `suppress`, `local_non_g10_macro`, score `-8`, `subject_penalty` `-8`, channels `[]` (`:115-124`).

India trade gap. `:125-127`:

```text
_word(text, "india") and _any_phrase(text, ("trade deficit", "trade gap", "import bill"))
```

Return: `suppress`, `incidental_link_only`, score `-8`, channels `[]` (`:128-137`). There is no `country == India` test and no test that oil, credit, rates, or FX failed.

Indonesia fires. `:138-140`:

```text
_word(text, "indonesia") and (_any_word(text, ("fire", "fires", "forest")) or "forest fire" in text)
```

Return: `suppress`, `local_non_g10_macro`, score `-8`, channels `[]` (`:141-150`). Palm oil is not an exception.

Noise, not a country, but it keys off Hormuz. `:151-153`:

```text
_any_word(text, ("podcast", "golf", "celebrity"))
and not _any_word(text, ("hormuz", "opec", "brent", "wti", "crude"))
```

`ormuz` is not in that escape tuple. Return: `suppress`, `noise_non_market`, score `-10` (`:154-163`).

### Early returns after the subject rule, still name-keyed

Chicago Fed. `_chicago_fed_activity` (`:194-199`), taken at `:366-379` before every other channel:

```text
_phrase(text, "chicago fed") or _word(text, "cfnai") or _phrase(text, "national activity index")
```

Literal `score = 7`, disposition `assess`, reason `us_activity_index`, channel `usd_rates`, assets `["USD"]`. This is a keep, not a suppress.

CoreWeave / CDS. `_coreweave_rule` (`:202-207`):

```text
_word(text, "coreweave")
or (
    (_word(text, "cds") or _phrase(text, "credit default"))
    and _any_word(text, ("ai", "debt", "distress", "coreweave"))
)
```

Taken at `:381-394`. The first disjunct is the issuer name alone.

Hormuz / Ormuz. `_hormuz_mentioned` (`:167-174`), taken at `:396`:

```text
_phrase(text, "strait of hormuz") or _word(text, "hormuz") or _word(text, "ormuz")
or _phrase(text, "estreito de ormuz")
```

Acute vs diplomatic only changes the locked score (`:400-409`): acute phrases `won't soften` / `wont soften` / `rejected` / `demands` / `bounced` / `crude bounced` (`:176-187`) → score `15`; otherwise if `reopening` / `diplomatic` / `easing` (`:190-191`) → score `13`. Both are `show`, reason `oil_supply_shock`.

China. `:420-435`. Gate is `_word(text, "china")`. Spillover is `_china_spillover_match` (`:210-219`):

```text
_word(text, "china")
and _any_word(text, ("stimulus", "property", "crude", "commodity", "demand", "pboc"))
and _any_word(text, ("stimulus", "crude", "commodity", "iron", "oil", "copper", "aud"))
```

Match → literal `score = 10`, `show`, `china_commodity_spillover`. Any other China blob returns `_hold_review` (`:435`, `:345-355`): score `0`, `ambiguous_transmission`, channels `[]`. `public_news_rows` drops both `suppress` and `hold-for-review` (`:693-694`).

Recall has a second issuer shortcut, `recall_candidate` → `_recall_positive_classes` (`:569-571`):

```text
if _word(text, "coreweave"):
    return True
```

That is before the AI-and-financing conjunction (`:593-598`).

The same country strings are restated as normative in `docs/news_intelligence/phase2_design.md:356-361` and `docs/NEWS_INTELLIGENCE_REPAIR.md:39-42`: India stays incidental even when the summary says oil or a Middle East conflict; Indonesia stays suppressed even when the summary says palm oil.

## 2. Rules that zero a real channel

`_subject_rule` does not read `_bare_oil`, `_hormuz_mentioned`, `_credit_funding`, `_g10_policy_fires`, `_usd_rates_fires`, or `_fiscal_interest`. A hit replaces those results.

Executed `score_transmission` on the blob (headline + summary):

| Probe | Predicate that fired | Result |
| --- | --- | --- |
| Accepted India headline + oil-price / Middle East summary (`tests/test_news_intelligence.py:21-25`) | India and `trade deficit` / `trade gap` / `import bill` | `suppress` `-8` `incidental_link_only`. Recall true because the summary contains `oil` |
| `India halts crude exports as a supply shock lifts Brent` | India, and none of the three phrases | `assess` `7` `oil_supply_shock`. Not suppressed |
| `India oil-export halt widens the trade deficit` plus crude / Brent / import bill | India and `trade deficit` | `suppress` `-8`. Oil channel not scored |
| `India trade deficit widens after Hormuz closure` / Strait of Hormuz, crude, Brent bounced | India and `trade deficit` | `suppress` `-8`. The Hormuz `show` 15 branch never runs |
| `India trade deficit and import bill` plus SOFR and credit spreads | India and the phrases | `suppress` `-8`. `_credit_funding` never runs |
| `India trade gap` plus Fed and Treasury yields | India and `trade gap` | `suppress` `-8`. The G10 branch never runs |
| `India election rally draws crowds` | India only | `hold-for-review` `0`. Country alone does not suppress |
| Vietnam GDP + parliament summary | `vietnam` and `gdp` | `suppress` `-8` `local_non_g10_macro`. Recall false |
| `Vietnam GDP slump cuts crude exports` / oil supply shock, Brent | `vietnam` and `gdp` | `suppress` `-8` even though recall is true via crude |
| `Vietnam GDP target` plus Fed cut and Treasury yields | `vietnam` and `gdp` | `suppress` `-8` |
| `Vietnam halts crude exports` (no `gdp`) | no subject hit | `assess` `7` `oil_supply_shock` |
| Indonesia fires + palm oil (test strings `:31-34`) | `indonesia` and `fires` | `suppress` `-8` |
| `Indonesia refinery fire halts crude exports` / Brent | `indonesia` and `fire` | `suppress` `-8` |
| `China Oil Comeback Loses Steam as Iran War Drags On` | `_word(china)` and spillover match is false (`oil` is only in clause B, `:216-218`) | `hold-for-review` `0`, dropped by `public_news_rows`. Bare-oil `assess` never runs |
| `Podcast: Estreito de Ormuz tanker mines` | noise, and `ormuz` is absent from `supply_escape` (`:152`) | `suppress` `-10`. The same podcast with `Hormuz` and `crude` is `show` `15` |

Exact India predicate, from `:125-127` and `:44-59`. This is the whole condition. Oil, Hormuz, SOFR, Fed, and yields are not conjuncts and not exceptions:

```text
suppress_india(text) =
    re.search(r"\bindia\b", text, IGNORECASE) is not None
    and (
        "trade deficit" in text
        or "trade gap" in text
        or "import bill" in text
    )
```

An India oil-export or supply shock is suppressed because the blob also contains one of those three phrases, including when the same blob names Hormuz, Brent, a crude export halt, SOFR, or the Fed. It is not suppressed because `country == India`. India plus a crude export halt and none of those phrases is `assess` / `oil_supply_shock` / score 7 and stays in `public_news_rows`.

Vietnam is the same shape with a different pair: `\bvietnam\b` and `\bgdp\b` (`:114`). A crude export halt or a Fed move in the same blob does not matter. Vietnam without `gdp` is not this rule.

There is no FX channel to escape into. `global_risk` is weighted (`:15`, `:35`) and never passed to `_set_channel`. `dollar` and `fx` are recall tokens only (`:626-627`). A rupee-to-dollar spillover with no yield, Fed, SOFR, or oil-supply role is `hold-for-review` unless an India phrase already forced `suppress`.

Phase 1B asked for the opposite structure. Local non-G10 macro suppresses when there is no firing channel (`docs/news_intelligence/phase1_B_g10_transmission.md:73`). The India worked example says a later item that is itself the oil shock, or that names INR stress feeding USD funding, can fire `oil_energy_tot` or `credit_funding` (`:145`). The code never performs that role test.

## 3. Issuer-name auto-promotion — locked score

The locked score is the literal `score = 11` at `news_relevance.py:385`, inside the `_coreweave_rule` return at `:381-394`.

Disposition is hardcoded `show`. Reason is `ai_capex_credit`. Channel is forced `credit_funding` (`:382`) with `asset_named = 3`, `shock = 3`, assets `["credit_spreads", "UST"]`. The 5+3+3 arithmetic is not computed, and nothing checks spreads, Treasury supply, funding stress, or a financing verb.

`_coreweave_rule` (`:202-204`) returns true on `\bcoreweave\b` before the CDS clause. Executed:

| Text | Result |
| --- | --- |
| `CoreWeave opens a London office` | `show` `11` `ai_capex_credit` |
| `Analysis:Why CoreWeave is in the crosshairs of the AI scare` (test `:99-101`) | `show` `11` `ai_capex_credit`, recall true |
| `Investors debate CDS and AI debt at a conference` | `show` `11` via the second disjunct: `cds` and (`ai` or `debt`) |
| `CoreWeave credit default swaps hit distress levels as investors sour on AI debt` | `show` `11`. This one does have the channel; the name short-circuit is not what qualifies it |

The same score `11` / `show` / `ai_capex_credit` is assigned again at `:545-558` by `_ai_financing_recall` (`:337-342`): AI-side (`ai`, `coreweave`, `hyperscaler`, `neocloud`, `data center`) and financing-side (`debt`, `bond`, `financing`, `capex`). The early return makes that function unreachable whenever the issuer name is present. `docs/NEWS_INTELLIGENCE_REPAIR.md:44` and `phase2_design.md:370` lock this assignment: CoreWeave, or (`cds` or `credit default`) plus (`ai` or `debt` or `distress`), score 11 show.

## 4. Channels and thresholds

Weights (`news_relevance.py:9-16`): `usd_rates` 5, `g10_policy` 5, `oil_energy_tot` 5, `china_spillover` 5, `credit_funding` 5, `global_risk` 4, `geopolitics_haven` 4. Primary order is oil, g10 policy, usd rates, credit, china, geopolitics, global risk (`:19-27`). `global_risk` has no fire site.

| Path | Lines | What fires | Score | Disposition |
| --- | --- | --- | --- | --- |
| Hormuz / Ormuz acute | `:396-409` | `oil_energy_tot` + `geopolitics_haven` | 15 | show |
| Hormuz diplomatic | `:400-404` | same channels | 13 | show |
| China spillover | `:421-433` | `china_spillover` | 10 | show |
| China, no spillover match | `:435` | none | 0 | hold-for-review |
| CoreWeave / CDS+AI-debt | `:381-394` | `credit_funding` forced | 11 | show |
| Chicago Fed | `:366-379` | `usd_rates` | 7 | assess |
| G10 policy and/or USD rates | `:437-468` | `g10_policy` and/or `usd_rates` | channel sum + asset 2 or 3 + shock 2. Both channels → 15. One channel → 9 | `show` if `score >= 10` (`:454-455`); `assess` if `score >= 7` (`:456-457`); `assess` again below 7 (`:458-459`) |
| Sanctions + energy (`oil`, `crude`, `diesel`, `energy`, `lng`, `brent`, `wti`, `opec`, `hormuz`) | `:471-481`, `:308-309` | oil + geopolitics | 14 | show `geopolitics_haven_or_oil` |
| Sanctions, no energy | `:482-488` | `geopolitics_haven` only | 8 | assess |
| US interest cost / debt snowball | `:499-511` | `usd_rates` | 9 | assess |
| Bare oil / Brent / WTI / crude, no Hormuz | `:513-525` | `oil_energy_tot`, shock 0 | 7 | assess `oil_supply_shock` |
| Credit/funding phrase, acute `distress` or `emergency` | `:528-542` | `credit_funding` | 10 show, else 9 assess | |
| AI + debt/bond/financing/capex | `:545-558` | `credit_funding` | 11 | show |

`show` is score at least 10 on the paths that use the comparison, and on the literals 10, 11, 13, 14, and 15. `assess` is kept. `public_news_rows` (`:693-694`) drops only `suppress` and `hold-for-review`. The repair note states the same gate: show requires at least 10; any real channel under 7 stays `assess` and is not dropped (`docs/NEWS_INTELLIGENCE_REPAIR.md:44`). With current weights every fired channel lands at 7 or above, so the `< 7` arm (`:458-459`) does not change a live path. It still means a fired channel is not a drop.

Bare `oil` is not a supply-shock role. It is the score-7 assess path, and it is also why the India import-bill summary is recalled. The noise escape (`:152`) deliberately omits `oil` and keeps only `hormuz`, `opec`, `brent`, `wti`, `crude`.

## 5. Smallest logic change

Do not add a country allow-list or a country deny-list. Keep the Vietnam, India, and Indonesia patterns as the domestic/incidental subject test, and fail them closed only when no transmission role is present.

```text
subject_suppress =
    (vietnam_gdp or india_trade_gap or indonesia_fire)
    and not transmission_role(text)
```

`transmission_role` has to be narrower than the token `oil`. The accepted India summary contains `oil` (`tests/test_news_intelligence.py:23-24`). Treating `_bare_oil` or `\boil\b` as the escape would `assess` that fixture and miss the gate.

Use a supply role the fixture does not meet and a crude export halt does:

```text
oil_supply_role =
    _hormuz_mentioned(text)          # hormuz, ormuz, estreito de ormuz
    or _word(text, "opec")
    or (
        _any_word(text, ("oil", "crude", "brent", "wti"))
        and _any_word(text, ("export", "exports", "halt", "halts",
                             "embargo", "blockade", "outage", "shutdown", "supply"))
    )
```

Plus the role tests that already exist and that the subject rule currently ignores: `_credit_funding`, `_ai_financing_recall`, `_g10_policy_fires`, `_usd_rates_fires`, `_fiscal_interest`, and sanctions conjoined with `_energy_context`. Same escape for Vietnam and Indonesia, so a domestic GDP or fire story still suppresses, and an EM crude-supply shock is scored by the oil branch whether or not the country is India.

On a hit of `oil_supply_role`, do not return from `_subject_rule`. Fall through. Hormuz still locks `show` 13/15. A non-Hormuz export halt still hits `_bare_oil` and stays `assess` 7, which `public_news_rows` retains. That is the current retain path for `India halts crude exports…` and for `Brazil halts crude exports…`.

China: the `:420` branch should not `hold-for-review` when `oil_supply_role` is already true. `China` plus `oil` and no other spillover token is a hold today (`:435`).

Noise: build `supply_escape` from `_hormuz_mentioned`, not from the Hormuz-only tuple at `:152`, so `ormuz` is the same escape as `hormuz`.

CoreWeave: delete the issuer short-circuit at `:203-204`.

```text
# delete: if _word(text, "coreweave"): return True
```

The score `11` return at `:381-394` then runs only for the second disjunct (CDS or `credit default`, and `ai` or `debt` or `distress`). A name-only line (`CoreWeave opens a London office`, the AI-scare headline) falls through. It reaches `show` only if a later channel matches: `_ai_financing_recall` (name plus `debt` / `bond` / `financing` / `capex`) or `_credit_funding`. The CDS distress headline still matches `_ai_financing_recall` because it has CoreWeave and `debt`, so it stays `show` / `ai_capex_credit` / 11 without the name shortcut. The recall shortcut at `:570-571` still admits the name into stage 1; that does not by itself assign `show`. Leaving it means a name-only story is scored and then `hold-for-review`, which `public_news_rows` drops. Deleting `:570-571` as well stops the name from being a candidate unless the financing conjunction (`:593-598`) hits.

### Tests

Must stay green, and they fail if the India escape is the bare word `oil`:

- `RelevanceTests.test_vietnam_and_india_suppress` (`tests/test_news_intelligence.py:109-116`)
- `RelevanceTests.test_overlay_keeps_oil_and_chicago_in_order` (`:149-182`)
- `DiscoveryTests.test_india_oil_color_is_not_shown` (`:310-329`)
- `DiscoveryTests.test_public_rows_do_not_mutate_inputs` (`:331-335`)
- `RelevanceTests.test_china_shows_and_indonesia_suppresses` (`:141-147`) — palm oil must not count as `oil_supply_role`

Must change if the issuer short-circuit is removed:

- `RelevanceTests.test_coreweave_shows_without_macro_tokens` (`:99-101`). The AI-scare string is asserted `recall_candidate` true and `reason_code == ai_capex_credit`. After the deletion, `score_transmission` on that string is `hold-for-review` / `ambiguous_transmission`, not `ai_capex_credit`. The CDS headline assertions at `:94-98` stay if `_ai_financing_recall` still scores it. The `recall_candidate(scare)` assertion stays only if `:570-571` is left in place.

Stays if the CDS headline still scores `show` through the financing channel:

- `DiscoveryTests.test_reuters_sitemap_keeps_coreweave_headline` (`:204-218`), which uses `COREWEAVE_HEADLINE` (`:17-18`)

No current test covers India (or any EM) plus a crude export halt in the same blob as `trade deficit` / `trade gap` / `import bill`, or Vietnam GDP plus a crude supply role, or Indonesia fire plus a crude export halt. Those three are suppress today. A retain assertion would be new, not an edit of an existing assertion. Chicago Fed (`:118-121`), China stimulus (`:141-144`), Hormuz/Ormuz (`:102-107`), sanctions/fiscal (`:123-138`) are untouched by this shape.
