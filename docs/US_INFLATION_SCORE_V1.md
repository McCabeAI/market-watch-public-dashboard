# US Inflation Score V1 — Core PCE Bridge

Status: ACTIVE

This document governs the United States **Inflation** input inside the lightweight Market Watch 1–100 temperature interface. It overrides the generic V0 inflation weighting for the United States only.

## 1. Target variable

The US Inflation score is a **Core PCE score**.

- Authoritative target: BEA Personal Consumption Expenditures Price Index excluding food and energy.
- Headline CPI, Core CPI, headline PPI, and broad core PPI are **not independent score components**.
- CPI and PPI can affect the score only to the extent that released CPI/PPI source components map into the next Core PCE print.

The objective is to update our estimate of the Core PCE inflation temperature between BEA releases without accidentally turning the score into a CPI/PPI composite.

## 2. Authoritative anchor

When a new Core PCE release arrives:

1. Core PCE becomes the new authoritative inflation observation.
2. Apply the full Core PCE release impulse at 100% weight under the existing temperature-impulse framework.
3. Reset all provisional CPI/PPI bridge adjustments for that PCE month to zero because the actual Core PCE observation supersedes the nowcast inputs.
4. Preserve the actual release, revisions, period, source and score lineage.

The current anchor is the most recently verified Core PCE release.

### V1 transition anchor

V1 retains the recovered `72.0` US Inflation score as the transition anchor. Do not retroactively rebuild the entire 1–100 history merely to adopt this methodology. From V1 activation onward, the US Inflation score can move only from an actual Core PCE release or an eligible mapped CPI/PPI bridge input under this document.

The anchor score is therefore a transition state, not a claim that `72.0` was historically derived from a Core-PCE-only backtest.

## 3. Core PCE trend lens

The primary trend lens for actual Core PCE is the **seasonally adjusted month-over-month Core PCE rate annualized**, not the year-over-year rate.

Show, when the official data permit:

- latest 1-month annualized Core PCE;
- rolling 3-month annualized Core PCE;
- rolling 6-month annualized Core PCE;
- year-over-year Core PCE as secondary context.

For monthly Core PCE change `m` as a decimal:

`1m annualized = ((1 + m)^12 - 1) × 100`

For an N-month window:

`N-month annualized = ((Π(1 + m_i))^(12/N) - 1) × 100`

Use compounding, not `m × 12`, as the preferred calculation. Prefer BEA index levels or sufficiently precise official monthly data. If the calculation uses rounded published monthly percentage changes, label the resulting annualized rate as approximate.

The year-over-year rate remains useful for persistence and public communication, but it is not the primary indicator of the current run rate on the country page.

## 4. Interim CPI/PPI bridge

Between Core PCE releases, update the score only from CPI/PPI components that are used to construct Core PCE.

Use BEA source mapping and expenditure shares:

- **Source mapping:** BEA Table 2.4.4 U-D, `Price Indexes for PCE: Source Data`, identifies the source indexes used for detailed PCE price categories.
- **Approximate relative weights:** latest available current-dollar PCE expenditures from BEA underlying detail Table 2.4.5U. BEA states that current-dollar expenditure shares approximate relative-importance weights for the chain-type PCE indexes.

For each eligible detailed Core PCE category `i`:

`bridge contribution_i = core-PCE expenditure share_i × temperature impulse_i`

where:

`core-PCE expenditure share_i = current-dollar expenditure_i / current-dollar expenditure of the full Core PCE basket`

Then:

`provisional US inflation score = Core PCE anchor score + Σ bridge contribution_i`

Use the latest available expenditure shares. Do **not** impose a permanent fixed CPI/PPI split: PCE is Fisher chain-weighted and the relative weights change over time.

## 5. Component rules

- Only use a CPI/PPI series when BEA documentation maps that source to the relevant PCE category.
- If a PCE category uses a mixed source, apply only the documented source-linked portion when it can be established. Otherwise treat the release as context-only until the mapping is resolved.
- Do not double count a category appearing in both CPI and PPI reporting. BEA source mapping determines the controlling input.
- Food and energy categories are excluded from the Core PCE bridge even when they dominate a CPI/PPI headline.
- A headline CPI or PPI surprise can be important market information and should appear on the country page, but it receives no direct score weight merely because the headline moved.
- Missing or unavailable bridge inputs receive zero interim impulse. Their weights are not reassigned.

## 6. Temperature impulse

Use the existing release impulse scale at the mapped component level:

- clearly hotter: `+4`
- modestly hotter: `+2`
- mixed / economically unchanged: `0`
- modestly cooler: `-2`
- clearly cooler: `-4`
- exceptional shock: `+6` / `-6` only when genuinely warranted

Classify each component using its current release versus the prior verified observation, current trend, and reliable consensus when available. Do not classify a component from market price action or commentary.

Component weights always apply. Example: a clearly hotter component with a 7% Core PCE weight contributes `0.07 × 4 = +0.28`, not `+4`.

Carry fractional score changes internally and display at least one decimal place when a bridge adjustment is active.

## 7. Score lineage displayed on the country page

The US country page must make the score auditable under `docs/COUNTRY_SCORE_EVIDENCE_V1.md`. Inflation should show:

- Core PCE anchor period and actual m/m value;
- 1m / 3m / 6m annualized Core PCE trend where available;
- year-over-year Core PCE as secondary context;
- anchor score;
- current CPI/PPI bridge adjustment;
- provisional score after the bridge;
- bridge coverage / unresolved mappings when relevant.

Example score lineage:

`Core PCE anchor 72.0 + interim CPI/PPI bridge +0.6 = 72.6`

Do not imply precision when bridge coverage is incomplete.

## 8. Country-page data standard

A release can matter without changing a score. Important US data must still be visible on the US country page and retained as a time series.

For each material series, show when data permit:

1. latest observation, reference period and release date;
2. prior observation and short rolling trend;
3. surprise versus reliable consensus when available;
4. historical mean / median and range for a suitable stable sample;
5. percentile and/or z-score when the series history is structurally comparable;
6. relevant rolling annualized rates for inflation/growth series;
7. a comparable-series or indexed relationship when it tests an economically meaningful discrepancy;
8. score role: `DIRECT`, `BRIDGE`, or `CONTEXT ONLY`;
9. official source link and revision status.

Do not manufacture historical comparability across methodology breaks. Do not show a z-score or percentile merely because it can be calculated; use it when it improves interpretation.

This presentation standard follows the Market Watch empirical workflow: establish the macro trajectory, compare current readings with their own history and suitable analogues, identify discrepancies, and keep the factual data layer separate from the trading conclusion.

## 9. Current August 2026 PPI bridge

The August 2026 PPI release is a material US inflation release and belongs inside the expandable US Inflation evidence.

The headline final-demand PPI (`+0.4% m/m`, `+5.4% y/y`) does **not** directly change the Core PCE score. Energy drove much of the headline increase and Core PCE excludes energy.

The current evidence file is `data/us_core_pce_ppi_bridge_2026-08.csv`. Using BEA source mapping and Q2 2026 current-dollar PCE expenditure shares:

- clean PPI-sourced categories identified in the current Core PCE basket total about `21.7%` of Core PCE;
- about `95%` of that mapped PPI weight has an observed August source move in the current bridge;
- the observed mapped subset contributes roughly `+0.07pp` to monthly Core PCE inflation in August versus roughly `+0.08pp` in July.

That PPI-linked subset is economically unchanged to slightly cooler versus July, despite the hot headline PPI. Under the current temperature-impulse framework, the PPI bridge therefore does not move the transition score from `72.0`. August CPI remains pending; its eligible mapped Core PCE components should be added when released, without double counting categories already controlled by PPI source mapping.

Official methodology references:

- https://www.bea.gov/help/faq/521
- https://www.bea.gov/help/faq/1006
- https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy
- https://www.bls.gov/news.release/ppi.htm
