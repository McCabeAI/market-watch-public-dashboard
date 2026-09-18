# Market Watch — Daily Refresh V0

Status: ACTIVE LIGHT OPERATIONAL VERSION

This document governs the lightweight current-state refresh content and methodology used by the overnight production pipeline. The native schedule begins its integrated V0 source refresh at 00:07 America/New_York and GitHub Pages publishes the assembled morning product at 04:07. It is not the full Ivory / historical research architecture and must not expand into one without an explicit decision.

GitHub Pages publication for the overnight production path is 04:07 ET and is owned by `docs/OVERNIGHT_PIPELINE_V1.md`. This V0 document still owns news selection, score methodology, and the restored front-page content rules. The 00:07 restricted Cursor refresh executes this V0 runbook; GitHub validates its narrow edits, then the overnight collect stage freezes the substantive refreshed state.

## 1. Daily ownership

One integrated daily refresh owns:

1. Last 24 Hours news desk summary.
2. Top Market Drivers.
3. Rolling 7-Day Quick Digest.
4. X Signal.
5. Rolling 30-Day Central-Bank Research.
6. Current lightweight US / Canada / Australia / New Zealand macro snapshot already used by the dashboard.
7. The four 1–100 temperature-input scores for each of those four economies: Inflation, Labor, Activity, Consumer.
8. Dashboard publication and end-to-end validation.

Do not split these into separate scheduled jobs unless reliability evidence later justifies it.

## 2. Operating objective

The integrated overnight refresh should answer: what changed since the prior refresh, and does any existing dashboard state need to change?

The default is incremental refresh, not reconstruction. No new observation means unchanged state. A missing or inaccessible source means an explicit stale / needs-attention condition, not an invented replacement.

## 3. News refresh

The news desk is a sparse trader feed, not a general G10 or macro-news digest. Its purpose is to surface developments that can plausibly change the USD/CAD/AUD/NZD rates or FX view.

### Coverage hierarchy

**Tier 1 — core universe**

- United States / USD
- Canada / CAD
- Australia / AUD
- New Zealand / NZD
- Fed, BoC, RBA and RBNZ policy expectations

**Tier 2 — spillover universe**

China, euro area, United Kingdom, Japan, Switzerland, Norway, Sweden, global rates, commodities / energy, trade policy and geopolitics are eligible only when there is a direct and material transmission channel into the Tier 1 universe or broad G10 rates pricing.

Do not scan Tier 2 as a standalone world-news feed.

### Admission gate

Adopt an item only when at least one of the following is true:

1. It materially changes or could immediately reprice the expected path of the Fed, BoC, RBA or RBNZ, or creates a material global-rates spillover into those curves.
2. It materially changes the inflation, labor, growth, fiscal or trade outlook for the United States, Canada, Australia or New Zealand.
3. It is a China, commodity or energy development with a direct terms-of-trade, growth, inflation or risk channel for CAD, AUD or NZD.
4. It is a geopolitical development with an observable or credible near-term transmission channel through rates, oil / gas, trade, funding or risk premia.
5. It is a market-structure, liquidity or financial-stability event that is already affecting or is credibly capable of affecting G10 FX / rates price formation.

Exclude:

- generic equity-market or cross-asset recaps
- single-company news unless systemically or commodity relevant
- domestic politics without a concrete macro, fiscal, trade or policy channel
- routine central-bank speeches that repeat the known reaction function
- opinion, forecasts or strategist commentary presented as news
- speculative geopolitical developments without a defined market transmission channel
- repeated coverage of an event already represented in the feed
- stories included merely because they are recent or mention a G10 economy

### Ranking rule

Score every candidate before adoption:

- direct Tier 1 FX / rates relevance: `0–3`
- novelty versus current dashboard state: `0–2`
- strength of market / macro transmission channel: `0–3`
- verification / source quality: `0–2`

A normal news item must score at least `6/10` and at least `2/3` on direct Tier 1 relevance. A Top Market Driver should normally score at least `8/10`.

If an item does not clear the gate, omit it. Do not lower the threshold to fill space.

### Last 24 Hours

Use an exact rolling one-day window ending at the run cutoff.

Hard cap: **6 items**. Fewer is better when fewer qualify.

Prefer sources in this order:

1. first-party official source
2. Reuters for timely confirmed reporting and market context
3. another established financial publication only when it adds a material fact or confirmation not available from the first two

Each adopted item must preserve:

- publication time
- source name
- canonical source URL
- country / region
- primary and secondary category
- verification state
- admission score and qualifying gate
- factual summary
- separate concise market read
- provenance / corroboration where relevant

Verification states remain:

- `official`
- `corroborated`
- `single_source`
- `unverified`

Do not present `unverified` material as established fact.

### Top Market Drivers

Hard cap: **3 items**.

Select only the highest-ranked developments most likely to change price formation, policy expectations, growth / inflation trajectories, risk premia or cross-asset transmission for the Tier 1 universe. Do not promote an item merely because it was widely reported.

### 7-Day Quick Digest

Maintain a rolling seven-day set of at most **12 distinct events** that still matter to the current USD/CAD/AUD/NZD macro / rates setup. Remove items that age out or have ceased to matter even if they are still inside seven days. Do not duplicate the same event merely because several outlets repeated it.

The News & Research summary card and the front-page **MARKET NEWS · 7-DAY WINDOW** alert must be derived from this same rolling digest state on every build. Their scan date, story count/window and current driver content must match the current 7-Day Quick Digest / Top Market Drivers. A mismatch is a publication failure; never leave either surface on an older snapshot while the underlying digest is current.

## 4. Central-bank research refresh

Maintain a strict rolling 30-day publication window from official sources for:

- Federal Reserve Board
- Federal Reserve Bank of New York
- Boston Fed
- Philadelphia Fed
- Cleveland Fed
- Richmond Fed
- Atlanta Fed
- Chicago Fed
- St. Louis Fed
- Minneapolis Fed
- Kansas City Fed
- Dallas Fed
- San Francisco Fed
- Bank of Canada
- Reserve Bank of Australia
- Reserve Bank of New Zealand
- European Central Bank
- Bank of England
- Bank of Japan
- Swiss National Bank
- Norges Bank
- Sveriges Riksbank

Scan official publication, research, speech, working-paper and related pages as appropriate. Add genuinely new publications and remove items outside the 30-day window.

A research paper, staff paper or speech is evidence about analysis / communication. It is not automatically a policy decision or official committee view.

## 5. X Signal

X is supplemental and must obey the same Tier 1 / spillover admission gate as the news desk. Do not use X as a separate broad discovery feed.

When the personalized X source universe is populated in Supabase, use accounts classified as Market Watch sources as a preferred discovery seed. Until then, use publicly discoverable official and high-quality media X posts only.

Evidence levels must remain distinct:

- official account posting its own information: may be primary evidence for that account / institution
- media X post: media-social signal
- individual commentator X post: individual-social signal

Corroborate material media/commentator claims before promoting them to confirmed news. If the underlying development would not qualify for the news desk, do not promote it merely because it appeared on X.

## 6. Quick macro data scope

Refresh only the small current-state dataset already used by the dashboard. Do not perform broad historical backfills.

### United States

- Core PCE as the authoritative Inflation-score target, with CPI/PPI interim bridge inputs handled only under `docs/US_INFLATION_SCORE_V1.md`
- headline and core CPI/PPI measures that materially inform the inflation trajectory, even when they are not direct score inputs
- employment / payroll growth
- unemployment rate
- wage growth
- current GDP / domestic-demand measure used by the dashboard
- current consumer / household indicator used by the dashboard
- current Fed policy-rate state

### Canada

- headline CPI and current preferred core measures
- employment
- unemployment rate
- wage growth
- current GDP / activity measure used by the dashboard
- current consumer / household indicator used by the dashboard
- current BoC policy-rate state

### Australia

- headline inflation and current trimmed / core measure used by the dashboard
- employment
- unemployment rate
- wage / earnings measure when part of the current quick set
- current GDP / activity measure used by the dashboard
- current consumer / household indicator used by the dashboard
- current RBA policy-rate state

### New Zealand

- headline inflation and current core / ex-volatile measure used by the dashboard
- employment / unemployment
- wage / earnings measure when part of the current quick set
- current GDP / activity measure used by the dashboard
- current consumer / household indicator used by the dashboard
- current RBNZ policy-rate state

Official statistical agencies and central banks are the preferred authorities for macro observations. Preserve period, release date, units and revisions when available.

If a series has no new release, retain the last verified value and mark it unchanged.

### Country-page data presentation

A material macro release belongs on the relevant country page even when it does not change one of the four 1–100 scores. Do not hide a release merely because its score weight is zero.

Retain material series as time series and, where the data support it, show:

- latest and prior observations, reference period and release date;
- short and medium rolling trend;
- surprise versus a reliable consensus when available;
- historical mean / median, range, percentile or z-score when the sample is structurally comparable;
- relevant rolling annualized rates for inflation or growth series;
- economically meaningful comparable-series, indexed or spread relationships when they test a real discrepancy;
- score role: `DIRECT`, `BRIDGE`, or `CONTEXT ONLY`;
- official source and revision state.

Use these statistics to answer an economic question, not to decorate the page. Preserve methodology breaks and conflicting signals rather than forcing them into a single summary number.

## 7. Lightweight 1–100 scoring V0

### Purpose

The V0 score is a compact operational interface for the current quick-data set. It is DERIVED evidence. It is not the canonical Country Expert temperature model and must not be represented as one.

All four dimensions for all four economies were reindexed to a neutral **50.0 baseline on 2026-09-17**. The recovered prototype scores are no longer authoritative starting anchors.

Current score state is deterministic and versioned in `data/temperature_scores.json`. The dashboard score is:

`current score = 50.0 + cumulative fixed-weight qualifying release impulses since activation`

The activation ledger contains a one-time bootstrap classification of the current hard evidence already present in the dashboard. This is deliberately not a historical backfill. If the scale later proves poorly centered, reindex explicitly rather than freezing current scores while waiting for a perfect historical calibration.

Display mapping:

- 1–20 Cold
- 21–40 Cool
- 41–60 Neutral
- 61–80 Warm
- 81–100 Hot

### Update principle

Do not rebuild the score from a large historical distribution. V0 is an incremental release-update model indexed to the 50.0 activation baseline.

### Scored-source checklist

`data/score_source_registry.json` is the mandatory release-discovery checklist for the live score layer. Every daily refresh must inspect every registry entry whose cadence could have produced a new or revised observation since the prior successful refresh. Do not rely on the news scan to discover score releases. The registry is a coverage contract, not a second data warehouse.

`scripts/validate_score_sources.py` must pass before publication. It verifies that every fixed score component has an explicit source/cadence entry and that the governed US CPI/PPI bridge remains explicitly covered.

If a registry source is inaccessible, keep the prior verified observation, record the source failure in the refresh result, and do not invent a release or silently mark that component checked.

The top-level dashboard score board is derived from the same `data/temperature_scores.json` ledger as the country drawers. The older contextual country cards are a macro snapshot, not an independent score source, and must not display a competing set of 1–100 scores.


A dimension score changes when one of its defined hard inputs changes or is materially revised. Record that release as a new event in `data/temperature_scores.json` using the fixed component weight and the temperature impulse below. Missing or unresolved inputs contribute zero; they do not freeze the whole dimension and their weights are not redistributed.

For each new observation, classify its **temperature impulse** relative to the immediately prior verified observation, the direction of the series, and a reliable consensus / policy-neutral reference only when such a reference is actually available.

Orientation:

- higher inflation = hotter Inflation
- stronger employment / payroll growth = hotter Labor
- lower unemployment = hotter Labor
- stronger wage growth = hotter Labor
- stronger GDP / domestic demand / production / business activity = hotter Activity
- stronger retail / consumption / household income / confidence = hotter Consumer
- higher delinquencies / defaults / financial stress = colder Consumer

Base release adjustment:

- clearly hotter / stronger: `+4`
- modestly hotter / stronger: `+2`
- mixed or economically unchanged: `0`
- modestly cooler / weaker: `-2`
- clearly cooler / weaker: `-4`

Large, unambiguous shocks may use `+6` or `-6`, but only when the underlying release is genuinely exceptional. Do not use the extreme bucket merely because a headline is surprising.

For each dimension, calculate the refresh move across the full fixed component set:

`raw dimension move = Σ(component weight × component impulse)`

A component that did not release or revise on that refresh has an impulse of `0`. Its weight is not reassigned to components that did release. Missing or inaccessible expected inputs also do not transfer their weight to other components; they reduce coverage instead.

Cap the net daily dimension move at `+8` / `-8`.

Example: if payroll / employment growth alone is clearly stronger (`+4`) while unemployment and wages have no new observation, the Labor move is `10% × 4 = +0.4`, not `+4`. If unemployment alone is clearly cooler / looser (`-4`), its Labor contribution is `70% × -4 = -2.8`.

Do not move a score because of market price action, news commentary or a model opinion. Only the defined macro inputs can move these four data scores.

### Simple within-dimension weights

Use these fixed V0 weights. Do not renormalize them because of release timing, stale data, or missing inputs.

**Inflation — Canada / Australia / New Zealand**
- core / trimmed / preferred underlying inflation: 60%
- headline inflation: 40%

**Inflation — United States exception**
- `docs/US_INFLATION_SCORE_V1.md` overrides the generic V0 inflation weights for the United States.
- The US Inflation score is a Core PCE score. Actual Core PCE is the authoritative target.
- Between Core PCE releases, CPI/PPI can move the score only through BEA-mapped Core PCE source components at their current Core PCE expenditure-share weights.
- Headline CPI/PPI receive no standalone score weight; missing bridge weights are not renormalized.

**Labor — all four economies**
- `docs/LABOR_SCORE_V1.md` is the governing cross-country Labor methodology.
- unemployment rate: 70%
- wage / earnings growth: 20%
- employment / payroll growth: 10%
- private payroll estimates, vacancies/JOLTS, claims, survey employment, participation, employment-to-population, population/migration context and payroll revisions are important contextual evidence but receive no additional independent score weight.

**Activity**
- `docs/ACTIVITY_SCORE_V1.md` governs Activity.
- GDP / domestic-demand measure: 60%
- business survey composite: 40%
- for the US survey block: 70% services / 30% manufacturing, equivalent to 28% / 12% of the total Activity score.

**Consumer**
- `docs/CONSUMER_SCORE_V1.md` governs Consumer.
- retail sales: 25%
- household / personal income: 25%
- broad consumer spending / consumption: 25%
- consumer confidence: 25%

### Coverage rule

Store / report which inputs were available for each score update. Coverage affects confidence, not the arithmetic. A valid observed hard input may move the score at its fixed weight even when other buckets are missing.

- observed qualifying component: apply its fixed weight × impulse;
- component with no new/revised observation: impulse `0`;
- missing or unresolved component: impulse `0` and flag the gap;
- never renormalize remaining weights to compensate for missing data.

This intentionally favors a usable live index over freezing the score until every lineage question is perfect.

### Direction remains separate

The 1–100 score measures the current data temperature interface. `Cooling / Static / Warming` remains a separate directional judgment / state and must not be mechanically inferred from a one-day score move.

## 8. Supabase use

Use the existing `market-watch-dev` operational store for normalized feed items, provenance and ingest-run state when available.

Do not turn Supabase into a duplicate raw macro warehouse during V0. Raw evidence / numeric canonical history remains in the designated Drive / spreadsheet evidence layer. Supabase may store the compact current derived score state and its lineage only when the workflow actively uses it.

## 9. Publication

After the refresh:

1. update the affected dashboard sections only;
2. preserve unrelated known-good content;
3. let GitHub Actions run deterministic score/news validation and commit the governed refresh surfaces;
4. freeze the refreshed state into the overnight evidence packet before the trader review;
5. let the 04:07 GitHub Pages workflow deploy only the assembled morning product;
6. validate the actual deployed artifact / page when practical;
7. report stale or failed components explicitly.

A green workflow alone is not sufficient evidence that the intended dashboard content is correct.

## 10. Failure behavior

Fail loudly.

Examples:

- official source inaccessible: preserve last verified value, mark stale / inaccessible
- conflicting releases / source ambiguity: do not choose a plausible value silently
- news source claim not corroborated where corroboration is required: retain as signal only or omit
- GitHub / deployment failure: do not claim dashboard current
- insufficient score coverage: preserve prior score and flag coverage problem

## 11. Cost discipline

Use deterministic calculations and simple transformations for the numeric refresh. Use model reasoning where it adds value: news selection, deduplication, source-quality judgment, market-read synthesis and ambiguous classification.

Do not invoke the full Ivory → Country/Thematic Experts → Validator pipeline as part of the ordinary 04:00 V0 refresh.
