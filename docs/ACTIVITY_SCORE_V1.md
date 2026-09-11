# Activity Score V1 — Real Activity + Business Survey Structure

Status: ACTIVE

This document governs the **Activity** input inside the lightweight Market Watch 1–100 temperature interface. It overrides the generic Activity language in `docs/DAILY_REFRESH_V0.md` wherever they conflict.

## 1. Top-level structure

Activity has two hard components:

- **GDP / domestic-demand measure: 60%**
- **Business survey composite: 40%**

Do not renormalize these weights because of release timing, stale data or missing inputs.

The current displayed Activity scores remain transition anchors unless separately rebuilt under this methodology. New qualifying releases move the score prospectively under the fixed weights above.

## 2. United States business-survey weighting

Within the US 40% business-survey component, use a fixed sector split:

- **Services surveys: 70% of the survey block**
- **Manufacturing surveys: 30% of the survey block**

This is a deliberate Market Watch model weight intended to reflect the much greater importance of services to broad US activity. It is not presented as a literal contemporaneous BEA sector-share calculation.

Effective weights inside the full US Activity score are therefore:

- GDP / domestic demand: **60%**
- services survey signal: **28%** (`40% × 70%`)
- manufacturing survey signal: **12%** (`40% × 30%`)

## 3. Survey-source ownership

The 70% services / 30% manufacturing split is fixed. The exact source mix inside the services and manufacturing survey buckets must be explicitly defined before those buckets are treated as fully auditable hard inputs.

Potential evidence families include ISM, S&P Global PMI and small-business surveys such as NFIB, but this document does **not** assign provider weights among them.

Until the provider/source mix is formally pinned:

- preserve the 70/30 sector structure;
- show relevant survey releases and subcomponents as evidence;
- visibly retain a `LINEAGE GAP` for the unresolved provider mix;
- do not invent a provider weighting merely to move the score.

## 4. Survey decomposition and contextual routing

Ingest a business survey once, then route its economically relevant components across country-page evidence drawers without double counting score weight.

Examples:

- output / business activity / new orders / backlogs → Activity context;
- employment / hiring intentions → Labor context;
- prices paid / input costs / selling prices → Inflation context;
- customer demand / sales expectations → Consumer context;
- business confidence / capex intentions → primarily Activity context and secondarily other dimensions when economically relevant.

Only the formally defined Activity survey composite may receive Activity score weight. Routed subcomponents elsewhere are `CONTEXT ONLY` unless another methodology explicitly makes them hard inputs.

## 5. Score mechanics

Use the existing temperature-impulse scale:

- clearly hotter / stronger: `+4`
- modestly hotter / stronger: `+2`
- mixed / economically unchanged: `0`
- modestly cooler / weaker: `-2`
- clearly cooler / weaker: `-4`
- exceptional shock: `+6` / `-6` only when genuinely warranted

For the US survey block, once source ownership is fully defined:

`US survey impulse = 70% × services survey impulse + 30% × manufacturing survey impulse`

and:

`US Activity move = 60% × GDP/domestic-demand impulse + 40% × US survey impulse`

Equivalent direct decomposition:

`US Activity move = 60% × GDP impulse + 28% × services survey impulse + 12% × manufacturing survey impulse`

Preserve fractional score moves internally.

## 6. Country-page display

The expanded Activity score should show:

### Hard score inputs

- GDP / domestic-demand hard input and 60% weight;
- business-survey block and 40% weight;
- for the US, the 70% services / 30% manufacturing split inside the survey block;
- exact provider/source lineage once defined;
- latest observations, periods, revisions and sources.

### Context / corroboration

Show material survey subcomponents and alternative activity indicators even when they do not independently move the score. Examples include new orders, output, inventories, backlogs, hiring intentions, prices, capex intentions, industrial production, freight and other country-relevant activity signals.

Follow `docs/COUNTRY_SCORE_EVIDENCE_V1.md` for the interrogation standard.
