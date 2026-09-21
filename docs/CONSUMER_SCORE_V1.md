# Consumer Score V1 — Cross-Country Structure

Status: ACTIVE

This document governs the **Consumer** input inside the lightweight Market Watch 1–100 temperature interface for the United States, Canada, Australia and New Zealand. It overrides the generic Consumer weights in `docs/DAILY_REFRESH_V0.md` wherever they conflict.

## 1. Fixed cross-country weights

Use four equally weighted hard components:

- **Retail sales: 25%**
- **Household / personal income: 25%**
- **Broad consumer spending / consumption: 25%**
- **Consumer confidence: 25%**

Do not renormalize these weights because of release timing, stale data or missing inputs.

Consumer **LEVEL** is governed by `docs/TEMPERATURE_LEVEL_CALIBRATION_V1.md`. **50** maps to documented nominal/real flow anchors and index-specific confidence par values. `data/temperature_scores.json` (v3) stores LEVEL, coverage-weighted IMPULSE, and direction under the fixed 25% buckets. Missing series reduce coverage; they are omitted from the LEVEL average rather than imputed as 50.

## 2. Interpretation

The Consumer score is intended to answer four distinct questions:

1. **Retail sales:** what is happening in fast, high-frequency goods demand?
2. **Income:** what capacity do households have to spend?
3. **Broad spending / consumption:** what are households actually spending across the wider economy, including services where the national accounts permit it?
4. **Consumer confidence:** what do households say about current and expected conditions, willingness to spend and financial outlook?

Retail sales and broad consumption intentionally overlap partially. Retail sales provide a faster, narrower read; broad consumption provides a more complete household-demand measure.

## 3. Survey evidence

Consumer confidence is inherently survey-based and may be a hard score input when the governing country methodology explicitly identifies the consumer-confidence series or composite.

Business surveys are different. Their demand, sales expectations, hiring plans, pricing plans and confidence components can provide useful evidence about the household outlook, but they do **not** receive additional independent Consumer score weight unless explicitly promoted into the methodology.

Route relevant business-survey evidence into Consumer as `CONTEXT ONLY` when it informs customer demand, sales expectations, household income prospects or spending conditions.

## 4. Source ownership

Each score event must identify the source series or current proxy used for its hard bucket. Canonical source ownership should still be tightened over time, but an unresolved long-run source choice does not freeze an otherwise usable live score.

When a bucket's permanent source is not yet pinned:

- preserve the 25% hard weight;
- record the actual current observable/proxy used and its provenance in the score ledger;
- show the unresolved source ownership in lineage;
- apply the observable's classified impulse when evidence is sufficient;
- otherwise use a zero impulse for that bucket;
- do not invent or silently renormalize weights.

## 5. Score mechanics

Use the existing temperature-impulse scale:

- clearly hotter / stronger: `+4`
- modestly hotter / stronger: `+2`
- mixed / economically unchanged: `0`
- modestly cooler / weaker: `-2`
- clearly cooler / weaker: `-4`
- exceptional shock: `+6` / `-6` only when genuinely warranted

Orientation:

- stronger retail sales = hotter Consumer;
- stronger income / purchasing power = hotter Consumer;
- stronger broad consumption = hotter Consumer;
- stronger consumer confidence = hotter Consumer.

`Consumer move = 25% × retail impulse + 25% × income impulse + 25% × spending impulse + 25% × confidence impulse`

A component that did not release or revise receives zero impulse for that refresh. Its weight is not reassigned.

Preserve fractional score moves internally.

## 6. Country-page display

The expanded Consumer score must separate:

### Hard score inputs

- retail sales — 25%;
- household / personal income — 25%;
- broad consumer spending / consumption — 25%;
- consumer confidence — 25%.

For each, show the exact source owner once defined, latest observation, period, trend, revision state, score role and lineage.

### Context / corroboration

Show material household and business evidence that helps interpret the Consumer score without receiving independent weight. Examples include:

- business-survey customer demand / sales expectations;
- hiring intentions and wage expectations relevant to household income;
- credit-card / household-credit growth;
- delinquency / default / household-finance stress;
- savings rates;
- major-purchase intentions;
- alternative confidence surveys;
- housing / mortgage stress where economically relevant.

Follow `docs/COUNTRY_SCORE_EVIDENCE_V1.md` for the interrogation standard.
