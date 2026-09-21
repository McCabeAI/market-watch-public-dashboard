# Euro Area + Japan Expansion Graph

Status: EXECUTION-READY PLAN / G0 REBASE GATE SATISFIED / CURSOR NOT LAUNCHED

## Objective

Expand Market Watch from the current US / Canada / Australia / New Zealand architecture to a six-economy system by adding:

- **EA** = euro area, aligned to EUR and the ECB reaction function
- **JP** = Japan, aligned to JPY and the Bank of Japan reaction function

The expansion must cover:

1. calibrated temperature gauges,
2. official/free macro data and release discovery,
3. sovereign rates and curve analytics,
4. priced policy paths and paper-tradable short-rate curves,
5. cross-market rates RV,
6. housing / monetary-transmission context,
7. dashboard presentation,
8. Trader Room common-packet delivery and rates-expression support.

EA/JP scoring must inherit the merged V1 LEVEL + IMPULSE calibration contract on `main` at `94aa0ddd` (PR #66). Never recreate the retired 2026-09-17-at-50 cumulative-impulse model.

## Non-negotiable constraints

- Preserve one canonical score methodology across all six economies.
- Prefer official/free machine-readable sources. No paid data dependency.
- Do not substitute vendor or media data when an official required series is inaccessible; mark the source unavailable/stale.
- EA means the **euro area**, not the EU and not Germany. Germany is the EUR cash-rates benchmark only.
- Trader Room seats, remits and model assignments do not change.
- Trader Room must consume canonical score state directly; do not add more HTML scraping as a data interface.
- Housing is useful context but must not block the core EA/JP macro/rates launch.
- Shared core files should be integrated by one owner after isolated worker outputs are accepted. Avoid concurrent edits to `market_state.py`, the canonical score ledger/schema, or Trader Room preflight files.
- Future Cursor execution is Grok/Composer only unless Kevin explicitly changes that instruction.
- No Cursor execution is authorized by this planning artifact.


## Frozen V1 temperature contract inherited from PR #66

G0 is satisfied by merged PR #66, commit `94aa0ddd3e4e9fdb91c56dddcdae865aa6e56a59`.

EA and JP must use the same V1 semantics now canonical for US/CA/AU/NZ:

- LEVEL is current economic state on 1–100; it is not accumulated release impulses.
- 50 is structural/policy neutral, not a date baseline or trailing-sample median.
- IMPULSE/direction is latest print versus prior print and is never accumulated into LEVEL.
- Calibration history is latest-vintage reconstruction over 2025-09-21 through 2026-09-21; extend forward naturally as releases arrive.
- Dimension LEVEL is the coverage-weighted mean of observed fixed-weight components. Missing components reduce explicit coverage; they do not receive an imputed 50.
- Inflation target anchors, u*, wage anchors, potential growth and other country-specific neutral anchors must be documented in `data/temperature_calibration.json` with provenance.
- Activity GDP LEVEL uses the frozen two-quarter smoothing convention; GDP IMPULSE uses the latest single-quarter move.
- Monthly PMI-style business surveys use 3-month mean for LEVEL, latest print versus prior print for IMPULSE, anchor 50 and the frozen survey scale unless an explicitly reviewed non-PMI alternative is required.
- Current weights remain unchanged: Labor 70/20/10; Activity 60/40; Consumer 25/25/25/25; generic non-US Inflation 60/40 unless a reviewed central-bank-target reason justifies a different country mapping without changing the cross-country methodology.
- Trader Room already consumes canonical v3 `data/temperature_scores.json` directly. The EA/JP task is to generalize that loader from 4 countries/16 gauges to 6 countries/24 gauges, not to replace HTML scraping.

---

# Dependency graph

```text
                          ┌──────────────────────────────┐
                          │ G0 FOUR-COUNTRY REBASE GATE  │
                          │ SATISFIED @ 94aa0ddd         │
                          └──────────────┬───────────────┘
                                         │
          SOURCE/ARCHITECTURE WORK        │              IMPLEMENTATION WORK
       (can now begin immediately)        │          (inherits frozen V1 contract)
                                         │
┌──────────────┐  ┌──────────────┐       │       ┌────────────────────┐
│ P1 EA macro  │  │ P2 JP macro  │       │       │ I1 Generic 6-ctry  │
│ source       │  │ source       │       ├──────▶│ country/config core│
│ contract     │  │ contract     │       │       └─────────┬──────────┘
└──────┬───────┘  └──────┬───────┘       │                 │
       │                 │               │       ┌─────────┴──────────┐
┌──────▼───────┐  ┌──────▼───────┐       │       │                    │
│ P3 EA rates  │  │ P4 JP rates  │       │  ┌────▼─────┐        ┌────▼─────┐
│ / policy     │  │ / policy     │       │  │ I2 EA    │        │ I3 JP    │
│ contract     │  │ contract     │       │  │ macro    │        │ macro    │
└──────┬───────┘  └──────┬───────┘       │  │ history  │        │ history  │
       │                 │               │  └────┬─────┘        └────┬─────┘
┌──────▼─────────────────▼───────┐       │       │                   │
│ P5 Four-country assumption /   │       │  ┌────▼─────┐        ┌────▼─────┐
│ hard-code impact audit         │       │  │ I4 EA    │        │ I5 JP    │
└──────────────┬─────────────────┘       │  │ market   │        │ market   │
               │                         │  │ state    │        │ state    │
┌──────────────▼─────────────────┐       │  └────┬─────┘        └────┬─────┘
│ P6 Target six-country schema + │       │       └────────┬──────────┘
│ validation / rollout design    │       │                │
└──────────────┬─────────────────┘       │       ┌────────▼─────────┐
               │                         │       │ I6 Generic rates │
┌──────────────▼─────────────────┐       │       │ RV matrix        │
│ P7 Housing source contract     │       │       │ 15 pairs × 3Ylds │
│ EA + JP (non-blocking)         │       │       └────────┬─────────┘
└────────────────────────────────┘       │                │
                                         │       ┌────────▼─────────┐
                                         │       │ I7 EA sovereign  │
                                         │       │ spread context   │
                                         │       └────────┬─────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ C1 EA calibration/backfill│
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ C3 Cross-country score  │
                                         │   │ comparability review    │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ D1 Dashboard + registry │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ D2 Trader Room canonical│
                                         │   │ score/evidence delivery │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ D3 Rates/preflight +    │
                                         │   │ paper mark replay       │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ V1 End-to-end validator │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ BURN-IN: 5 scheduled    │
                                         │   │ business-day runs       │
                                         │   └────────────┬────────────┘
                                         │                │
                                         │   ┌────────────▼────────────┐
                                         │   │ V2 Promote EA/JP to     │
                                         │   │ required core coverage  │
                                         │   └─────────────────────────┘
```

JP calibration/backfill runs in parallel with C1 after I3/I5; it joins C3. Housing implementation can run in parallel after P7 and is not on the critical path.

---

# Node contracts

## G0 — Four-country temperature rebase gate

**Status: SATISFIED.** Merged PR #66 at `94aa0ddd3e4e9fdb91c56dddcdae865aa6e56a59` on 2026-09-21.

**Verified gate conditions:**

- US/CA/AU/NZ rebase is merged to `main`.
- The canonical score schema is stable and documented.
- Historical level score and direction/impulse semantics are frozen.
- Backfill/calibration method and minimum history window are explicit.
- Release-update mechanics and revision handling are tested.
- Trader Room score interface after rebase is known.
- Dashboard score rendering after rebase is known.

**Gate output:** future implementation dispatch must resolve the then-current live `main` branch and verify it contains PR #66 or a descendant. Never dispatch from this planning branch.

---

## P1 — Euro-area macro source contract

**Write scope:** planning/source-contract artifact only.

Pin exact machine-readable series IDs/endpoints, cadence, units, revision behavior, expected lag and history for:

### Inflation
- headline HICP
- preferred underlying HICP consistent with the frozen rebase methodology

### Labor
- unemployment rate
- wage/compensation measure
- employment growth

### Activity
- real GDP / domestic-demand measure
- preferred scored monthly survey: S&P Global Eurozone Composite PMI, harvested from public primary S&P releases using the same final-over-flash discipline as CA/AU
- European Commission ESI/sector surveys retained as official context/corroboration unless source review proves they can be mapped into V1 without changing scale semantics

### Consumer
- retail sales
- household income
- household consumption/spending
- consumer confidence

**Preferred authorities:** Eurostat and ECB for hard macro; S&P Global public primary releases for the scored Composite PMI if accessible/repeatable; European Commission BCS as official context/corroboration.

**Acceptance:**
- exact series IDs and endpoint examples, not webpage-only references;
- at least the rebase-required historical window is downloadable;
- release/revision semantics documented;
- automated fetch tested from GitHub-hosted runner or equivalent environment;
- no paid/private series required for a score component.

---

## P2 — Japan macro source contract

Pin exact official machine-readable sources for:

### Inflation
- headline CPI
- frozen-methodology underlying CPI

### Labor
- unemployment
- wages/earnings
- employment

### Activity
- real GDP / domestic demand
- preferred scored monthly survey: au Jibun Bank / S&P Global Japan Composite PMI, harvested from public primary S&P releases using final-over-flash discipline
- BOJ Tankan retained as high-value quarterly context/corroboration, including business conditions, demand, employment and price subcomponents

### Consumer
- retail
- household income
- household consumption
- consumer confidence

**Preferred authorities:** Statistics Bureau / e-Stat, Cabinet Office, Bank of Japan, MHLW, METI as appropriate.

**Acceptance:** same as P1, including GitHub-runner accessibility.

---

## P3 — Euro-area rates / policy source contract

Pin:

- ECB €STR overnight history
- Eurex 3M €STR futures (`FST3`) delayed settlements/marks, volume and OI where public
- German 2Y/5Y/10Y/30Y sovereign benchmark yields
- ECB euro-area analytical zero / forward / par curve data
- Italy-Bund, France-Bund and Spain-Bund official/free inputs for 2Y/5Y/10Y spread context where technically reliable

**Critical distinction:** Germany is the benchmark cash curve; ECB/euro-area analytical curves and peripheral sovereign spreads are separate instrument/context families.

**Acceptance:**
- source is machine-accessible without credentials;
- contract naming, quotation convention and maturity mapping are proven;
- FST3 mark replay can be reproduced deterministically;
- no futures data is labeled tradable until actual public settlements/marks can be fetched reliably.

---

## P4 — Japan rates / policy source contract

Pin:

- BOJ TONA / uncollateralized overnight call-rate benchmark used by the policy block
- OSE 3M TONA futures public settlement/mark data, contract convention, volume/OI
- MOF JGB 2Y/5Y/10Y/30Y yields/history
- official curve data if a richer machine-readable MOF/BOJ term structure is available
- JPX JGB futures context where useful

**Acceptance:** same as P3.

---

## P5 — Four-country assumption / hard-code impact audit

Produce a complete list of code/tests/docs/UI surfaces that currently assume four countries or three required tradable rate curves.

At minimum inspect:

- `scripts/market_state.py`
  - `RATE_COUNTRIES`
  - `RV_PAIRS`
  - freshness rules
- policy-path / tradable-curve collectors
- official curve collectors
- `data/score_source_registry.json`
- canonical post-rebase score state
- score-source validator expected counts
- dashboard country metadata/rendering
- `scripts/trader_room/evidence.py`
  - hard-coded country files
  - HTML score scraping
  - required policy paths
  - required tradable curves
- rate candidate / expression validators
- PM review packet surfaces
- tests, fixtures and synthetic packets
- overnight/deploy workflows

**Acceptance:** no known four-country assumption is left uncatalogued.

---

## P6 — Target six-country schema / rollout design

Define the target architecture before implementation.

### Country registry
One canonical metadata registry should own country/economy codes and capabilities rather than scattering tuples across code.

Example capabilities:

- `has_temperature`
- `has_sovereign_curve`
- `has_policy_path`
- `has_tradable_short_rate_curve`
- `has_housing_context`
- `required_for_trader_preflight`

### Target core universe
- US
- CA
- AU
- NZ
- EA
- JP

### Target priced-rate universe
- SOFR
- CORRA
- AONIA
- €STR / FST3
- TONA

NZ remains context-only until a reliable free policy/tradable path is deliberately supported.

### RV engine
Generate matching-tenor spreads from country capability/configuration instead of a hard-coded pair whitelist.

For 6 countries:
- 15 unique country pairs
- 3 standard tenors (2Y/5Y/10Y)
- 45 RV series when both legs are valid on an exact common date

### Trader score interface
Trader Room already reads canonical v3 `data/temperature_scores.json` directly. Generalize its hard-coded four-country loop and 16-gauge assertion to the country registry / 24 gauges. The dashboard and Trader Room remain peer consumers of canonical score state.

### Rollout states
1. `observe_only`: data collected, not required
2. `scored`: calibrated temperature history validated
3. `tradable`: short-rate curve has deterministic mark/replay
4. `required`: promoted into Trader Room preflight after reliability burn-in

---

## P7 — EA/JP housing / transmission source contract

Non-blocking context work.

### Euro area target families
- residential property prices
- housing permits/construction
- mortgage lending / household housing credit
- new/outstanding mortgage rates
- household debt-service or closest official monetary-transmission burden measure

### Japan target families
- residential property prices where official continuity is adequate
- housing starts
- housing lending / household mortgage credit
- mortgage rates
- transaction/land-price context where official and maintained

**Rule:** a disrupted or weak official Japanese property-price series may remain unavailable. Never substitute paid private housing data silently.

---

# Post-gate implementation

## I1 — Generic six-country country/config core

**Dependency:** G0 + P5 + P6.

Implement the minimal generic configuration required so EA/JP are configuration additions rather than duplicated special cases.

**Integrator-owned shared files:** canonical country registry, canonical score schema hooks, shared Market State country lists, shared freshness/capability logic.

**Acceptance:**
- existing four countries are behaviorally unchanged under the new registry;
- country capability tests pass;
- no UI redesign;
- no score recalibration in this node.

---

## I2 / I3 — EA and JP macro history collectors

**Dependencies:** G0, P1/P2, I1.

Independent workers.

Each collector must output normalized historical observations with:

- series ID
- source
- reference period
- release date where available
- revision/vintage state where available
- units
- frequency
- value
- score role
- freshness

**Acceptance:**
- covers the rebase-required history window;
- deterministic parser fixtures;
- live-source smoke;
- no model interpretation in the raw collector.

---

## I4 / I5 — EA and JP Market State rates/policy collectors

**Dependencies:** P3/P4, I1.

### EA
- `rates.EA`: Germany 2Y/5Y/10Y/30Y
- `policy_paths.countries.EA`: €STR + FST3
- `tradable_rate_curves.curves.ESTR` or the final canonical curve ID
- ECB analytical curve block
- EA sovereign fragmentation context

### JP
- `rates.JP`: JGB 2Y/5Y/10Y/30Y
- `policy_paths.countries.JP`: TONA + OSE 3M TONA
- `tradable_rate_curves.curves.TONA`
- JGB curve/futures context

**Acceptance:**
- deterministic mark arithmetic;
- exact contract/replay identity;
- source outages fail loudly;
- no invented forward/OIS curve;
- existing US/CA/AU/NZ output unchanged.

---

## I6 — Generic rates RV matrix

**Dependencies:** I4 + I5 + I1.

Replace `RV_PAIRS` with configuration-driven exact-common-date generation.

**Target:** 45 possible 2Y/5Y/10Y country-pair spreads across six economies.

**Acceptance:**
- exact common date on both legs;
- no forward fill;
- null/unavailable when either source fails;
- same percentile/z-score/analog analytics as existing RV series;
- deterministic count tests based on capabilities, not hard-coded 45 if a leg is unavailable.

---

## I7 — Euro-area fragmentation block

**Dependency:** P3 + I4.

Separate from `rates.EA`.

Target:
- Italy-Germany 2Y/5Y/10Y
- France-Germany 2Y/5Y/10Y
- Spain-Germany 2Y/5Y/10Y

Include level, changes, percentile/z-score and historical move analogs when source history supports it.

**Rule:** fragmentation is market context, never an EA temperature input.

---

## H1 — Housing implementation

**Dependency:** P7.

Can run in parallel with I2-I7 and must not block core launch.

Output `euro_area_housing` and `japan_housing` only when official/free feeds satisfy provenance and maintenance requirements.

---

# Calibration and score integration

## C1 / C2 — EA and JP historical calibration

**Dependencies:** G0 + I2/I3.

Run the exact frozen rebase methodology used for US/CA/AU/NZ.

No bespoke “Europe score” or “Japan score” methodology may be invented merely to get a number.

**Acceptance:**
- same level-score semantics;
- same direction/impulse semantics;
- same historical calibration window or a documented justified exception;
- fixed country-specific input mappings are explicit;
- revisions handled consistently;
- full event/history lineage retained.

---

## C3 — Cross-country comparability review

**Dependencies:** C1 + C2 + re-based US/CA/AU/NZ state.

Independent verification of all 24 dimensions:

- 6 economies × 4 dimensions
- no scale drift caused by source frequency differences
- no hidden renormalization
- no country-specific center shift without documented economic reason
- coverage/confidence separated from score arithmetic
- direction signal is not mechanically conflated with level

**Failure routing:** back to C1/C2 or the frozen-methodology owner. Do not patch scores manually.

---

# Dashboard and release discovery

## D1 — Six-country dashboard + source registry

**Dependencies:** C3 + I4/I5.

Extend:

- top score board from 4 to 6 economies
- country drawers from 16 to 24 dimensions
- EA and JP evidence drawers
- official source lineage
- source registry / release discovery
- current market/rates context

Do the smallest necessary renderer generalization. Do not redesign the dashboard while adding countries.

**Acceptance:**
- all 24 score controls render from canonical score state;
- registry validator is count-independent/config-driven;
- no duplicated score source;
- actual deployed page inspected.

---

# Trader Room

## D2 — Six-country canonical score evidence delivery

**Dependencies:** C3 + I1.

Trader Room already consumes canonical v3 `data/temperature_scores.json`. Generalize the current four-country loop and `expected 16 temperature gauges` invariant to the country registry and 24 gauges, then emit:

- `temp:EA:inflation`
- `temp:EA:labor`
- `temp:EA:activity`
- `temp:EA:consumer`
- `temp:JP:inflation`
- `temp:JP:labor`
- `temp:JP:activity`
- `temp:JP:consumer`

plus the existing four economies.

**Acceptance:** packet hash/freeze behavior unchanged; source index continues to point to canonical score state; US/CA/AU/NZ outputs are byte/semantically unchanged except for ordering/config generalization.

---

## D3 — EA/JP policy/rates trading integration

**Dependencies:** I4/I5/I6 + D2.

Add:

- `rates:EA`
- `rates:JP`
- `policy:EA`
- `policy:JP`
- FST3/€STR curve family
- TONA curve family
- six-country rates RV scan support
- deterministic paper position mark/replay for the new curve families

Do not add or modify trader seats.

### Initial preflight behavior
EA/JP begin as `observe_only` / `tradable` but not immediately required to launch the entire Trader Room.

After burn-in, promote them to the same required policy/tradable coverage class as US/CA/AU if reliability meets the gate.

---

# Validation graph

## V1 — Integrated deterministic validation

Must include:

- macro parser fixtures
- live macro source smoke
- sovereign/rates parser fixtures
- live rates/policy smoke
- score-source registry validation
- 24-dimension score validation
- 6-country Market State schema validation
- RV exact-common-date tests
- FST3/TONA mark/replay tests
- Trader Room packet freeze/preflight tests
- synthetic rates-trade tests using EA and JP
- dashboard build and DOM assertions

---

## V1b — Independent model verifier

Review accepted implementation against this plan and the frozen rebase contract.

Focus on:
- silent four-country assumptions
- accidental score-methodology divergence
- wrong market conventions
- futures/spot quotation errors
- stale-source handling
- Trader Room blind spots
- shared-file integration errors

Repairs return only to the owning node; maximum two worker repair attempts before architectural escalation.

---

## Burn-in gate — five scheduled business-day runs

Before EA/JP become required Trader Room preflight dependencies:

- 5 consecutive scheduled Market State runs complete without source-contract failure attributable to the new collectors;
- score release discovery works on actual live schedules;
- no manual intervention required;
- FST3 and TONA marks/replay remain stable;
- dashboard deploy retains both new countries;
- frozen Trader Room packet contains all expected EA/JP evidence.

A source can be stale because no release was due; that is not a failure. A parser/access failure is.

---

## V2 — Final promotion

After burn-in:

- mark EA and JP as core six-economy temperature coverage;
- promote reliable EA/JP policy/tradable rate curves into required Trader Room preflight;
- retain explicit capability flags for any still-noncore context feed such as housing;
- run one real on-demand Trader Room review only with current explicit model-launch authorization;
- inspect actual submissions to confirm agents use EA/JP context rather than merely receiving it.

Success is merged code + green deterministic/live validation + inspected artifacts + stable burn-in, not merely a passing unit test.

---

# Execution topology for future Cursor run

Do not launch yet.

G0 is satisfied. When Kevin explicitly authorizes the build, use one native Cursor parent orchestrator with subagents. ChatGPT supplies this graph, acceptance criteria, write ownership, retry limits and stop conditions; Cursor owns routine handoffs.

## Suggested parallelism

### Wave 1
Parallel planning/research workers:
- P1 EA macro source contract
- P2 JP macro source contract
- P3 EA rates/policy source contract
- P4 JP rates/policy source contract
- P5/P6 four-country hard-code audit + target schema

Parent/integrator accepts the source contracts before implementation.

### Wave 2 after accepted source contracts + I1 generic-country core
Parallel:
- I2 EA macro
- I3 JP macro
- I4 EA rates
- I5 JP rates
- H1 housing, if source contract is ready

### Wave 3
Parallel where safe:
- I6 RV matrix
- I7 EA fragmentation
- C1 EA calibration
- C2 JP calibration

### Wave 4
- C3 independent score comparability review

### Wave 5
Parallel:
- D1 dashboard / registry
- D2 Trader Room canonical score delivery
- D3 rates-expression integration

### Wave 6
- integrator
- V1 deterministic/live end-to-end checks
- V1b independent verifier
- bounded repairs
- final approval

## Write ownership

Workers should add isolated modules/tests/fixtures. The integrator owns edits to shared high-conflict files such as:

- canonical country registry
- canonical score state/schema
- `scripts/market_state.py`
- shared policy/tradable curve registry
- `scripts/trader_room/evidence.py`
- Trader Room preflight constants
- deploy/overnight workflows

This is intended to prevent concurrent subagents from repeatedly merging the same core files.

## Model routing

At launch, resolve the current authenticated Cursor model catalog and use **Grok/Composer only**. Do not guess model IDs now.

Role pattern:
- strongest permitted Grok/Composer route: parent planning, architecture escalation, final approval
- cheaper reliable permitted route: implementation workers
- independent permitted route: verification

## Run ceilings

Proposed execution budget for this graph, to be finalized against the authenticated Cursor catalog immediately before dispatch:

- planned model/agent invocations: 18
- proposed hard total invocation cap: 36
- planned strongest-route/Grok invocations: 4 (parent plan/ownership, one architecture escalation allowance if actually needed is not planned, independent integration review, final approval)
- proposed hard strongest-route cap: 5
- routine implementation/research volume: Composer standard/non-Fast
- difficult architecture/review: Grok standard/non-Fast
- maximum two worker repair attempts per failed node before escalation

Caps never auto-expand. Exact model IDs/parameter mappings must be read from the current authenticated registry before dispatch.

---

# Deferred / explicitly out of scope

- UK / GBP macro and rates build
- Switzerland / CHF
- Norway / NOK
- Sweden / SEK
- redesign of Trader Room seats or PMs
- paid PMI dependencies
- full dashboard redesign
- swap-spread trading
- forcing NZ into the priced-policy/tradable short-rate universe
- replacing missing official data with Bloomberg/Reuters/private-vendor values

These can be future expansions once the six-economy architecture proves stable.


---

# Confirmed source anchors before execution

These are verified planning anchors, not a substitute for P1-P4's exact end-to-end source contract.

## Euro area
- ECB €STR canonical series key: `EST.B.EU000A2X2A25.WT`.
- ECB negotiated wages publishes quarterly euro-area series; current EA21 key surfaced by ECB Data Portal: `INW.Q.I10.N.INWR.000000.4F0.GY.IX`. P1 must confirm composition continuity across the one-year history.
- Eurostat unemployment dataset: `une_rt_m` with monthly seasonally adjusted unemployment-rate dimensions.
- Eurostat quarterly GDP dataset: `namq_10_gdp`.
- Eurostat HICP annual-rate dataset: `prc_hicp_manr`; P1 must pin the exact 2026 ECOICOP-v2 special-aggregate code and EA21 geography rather than assuming the pre-2026 code.
- Bundesbank daily current Federal-security yield keys are confirmed for 2Y `BBSSY.D.REN.EUR.A610.000000WT0202.A`, 5Y `...A620...WT0505.A`, 10Y `...A630...WT1010.A`, and 30Y `...A640...WT3030.A`.
- S&P Global publishes monthly Eurozone Composite PMI public releases; final readings should control over flash readings if P1 confirms repeatable primary retrieval.
- European Commission BCS has API/download support and remains a strong official context layer.

## Japan
- Cabinet Office ESRI publishes quarterly GDP time-series CSVs and revises the historical seasonally adjusted series each release.
- BOJ Tankan comprehensive datasets are publicly downloadable and provide business-conditions, demand, employment and pricing context.
- BOJ publishes uncollateralized overnight call-rate / TONA results each business day.
- JPX/OSE 3-Month TONA Futures are quoted as 100 minus 3-month compounded TONA (Act/365), with 20 March-cycle contract months and official JSCC daily settlement prices.
- JPX publishes daily settlement CSVs covering OSE products; P4 must prove stable product identification and contract-month parsing before declaring the curve tradable.
- S&P Global publishes monthly Japan Composite PMI public releases; final readings should control over flash readings if P2 confirms repeatable primary retrieval.
- MOF/JGB exact machine-readable 2Y/5Y/10Y/30Y history remains a P4 contract item; do not substitute an unverified vendor path.

# Known plan correction from the pre-rebase draft

The earlier draft proposed EC business surveys for EA and Tankan for JP as likely scored Activity surveys. The merged V1 calibration strongly favors a comparable **monthly PMI-style 50-threshold survey** for the 40% scored survey block. Therefore the current preferred scored series are Eurozone Composite PMI and Japan Composite PMI, with EC BCS and Tankan as official contextual evidence. This preserves the V1 3-month LEVEL / latest-month IMPULSE mechanics and avoids inventing a new survey scale solely for EA/JP.
