# Country Score Evidence V1 — Interrogation Standard

Status: ACTIVE

This document governs how the four 1–100 temperature inputs are presented and interrogated on the United States, Canada, Australia and New Zealand country pages.

## 1. Objective

A score must never be a dead-end number. A trader looking at a country page must be able to select any Inflation, Labor, Activity or Consumer score and immediately answer:

1. What hard inputs mathematically define this score?
2. What are the current values and weights of those inputs?
3. What tangential evidence confirms, contradicts or qualifies the score?
4. What is current versus stale, revised or unresolved?
5. Which observations can move the score and which are context only?

## 2. Interaction standard

Each score row / bar is an expandable interrogation control.

The collapsed state shows:

- dimension name;
- current 1–100 score;
- temperature bar.

The expanded state has two evidence layers.

### Hard score inputs

Show every input that is allowed to move the score under the governing methodology. For each hard input, show when available:

- fixed score weight or mapped bridge weight;
- latest observation and reference period;
- useful short trend;
- release / revision state;
- current score role (`DIRECT` or `BRIDGE`);
- authoritative source link;
- enough lineage to understand why the score is where it is.

If the displayed score is a transition anchor rather than a score historically reconstructed from the current methodology, say that explicitly. Do not manufacture component contributions that were never calculated.

### Context / corroboration

Show material evidence that helps interpret the dimension but has no independent score weight. Examples include ADP, JOLTS, claims, survey subindexes, population and participation data, headline inflation measures, alternative core measures, confidence surveys and related cross-checks.

Label these observations `CONTEXT ONLY`. Context evidence can strengthen or weaken conviction in the score but must not silently alter it.

## 3. Missing lineage

If a score's current V0 methodology does not uniquely identify the active source series, display an explicit `LINEAGE GAP` in the expanded score rather than choosing a plausible series.

A transition-anchor score may remain visible while this gap is resolved, but the page must distinguish:

- a current observable relevant to the dimension;
- a formally defined hard score input;
- a context-only series.

Do not imply mathematical auditability where it does not exist.

## 4. Trend standard

Retain material evidence as time series. Present trend statistics when they answer an economic question and the history is structurally comparable.

Useful treatments include:

- latest versus prior;
- 3- or 6-period rolling trend;
- surprise versus reliable consensus;
- historical percentile / z-score when valid;
- rolling annualized inflation or growth rates;
- population- or labor-force-adjusted comparisons;
- cross-series discrepancies such as payrolls versus ADP, openings versus unemployment, or headline versus underlying inflation.

Do not add statistics merely to fill the drawer.

## 5. United States Core PCE display rule

For the US Inflation score, `docs/US_INFLATION_SCORE_V1.md` remains the governing score methodology.

The primary trend lens for actual Core PCE is **seasonally adjusted month-over-month Core PCE annualized**, because it gives more weight to the current inflation run rate than a backward-looking 12-month comparison.

Display when data permit:

- latest 1-month annualized Core PCE rate;
- rolling 3-month annualized Core PCE rate;
- rolling 6-month annualized Core PCE rate;
- year-over-year Core PCE as secondary context.

For monthly rate `m` expressed as a decimal:

`1m annualized = ((1 + m)^12 - 1) × 100`

For an N-month window:

`N-month annualized = ((Π(1 + m_i))^(12/N) - 1) × 100`

Prefer calculations from BEA index levels or sufficiently precise official data. If only rounded published monthly percentage changes are used, mark the annualized rates as approximate.

CPI/PPI bridge evidence must remain distinct from actual Core PCE. It can update the provisional score only under `docs/US_INFLATION_SCORE_V1.md`.

## 6. Refresh ownership

The scheduled 04:00 refresh owns the score drawers as part of each country page.

When a material observation is released or revised, the refresh must:

1. update the relevant hard input or context series;
2. preserve the source, reference period and revision state;
3. update score lineage only when the governing methodology permits a score move;
4. retain material context even when its score weight is zero;
5. remove or flag stale statements that have been superseded;
6. validate that the deployed page still exposes both evidence layers by tap/click.

## 7. Duplication rule

The expandable score evidence is the canonical country-page home for evidence supporting that dimension. Do not maintain a second independent evidence panel containing the same facts unless it has a distinct analytical purpose.
