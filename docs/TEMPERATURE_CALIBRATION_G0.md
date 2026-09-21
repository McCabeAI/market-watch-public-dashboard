# Temperature gauges — G0 architecture map

Status: G0 parent brief for the 12-month calibration rebuild. Not the final methodology.

Starting ref: `c39ea027c78a911c73c7260662c26f84478fd875` (`main`).

## Current live system (must be replaced, not incrementally summed)

Live scores in `data/temperature_scores.json` are a **path-dependent operational index**:

`score = 50.0 + Σ (component_weight × classified_impulse)` since activation **2026-09-17**.

Inspected pre-rebuild current scores (comparison only, not target anchors):

| | Inflation | Labor | Activity | Consumer |
|---|---:|---:|---:|---:|
| US | 52.0 | 50.2 | 49.92 | 48.5 |
| CA | 50.0 | 48.8 | 53.2 | 52.5 |
| AU | 49.2 | 47.8 | 49.2 | 51.0 |
| NZ | 51.6 | 47.0 | 52.0 | 48.5 |

50 currently means “reindexed operational baseline on 2026-09-17”, not an economic state. That meaning is retired by this work.

Display mapping 1–20 Cold / 21–40 Cool / 41–60 Neutral / 61–80 Warm / 81–100 Hot is retained unless calibration proves it unusable.

## Preserved weights (do not change unless G1 finds a concrete incompatibility)

- **US Inflation:** Core PCE 100%. CPI/PPI only via BEA-mapped Core PCE bridge (`docs/US_INFLATION_SCORE_V1.md`).
- **CA/AU/NZ Inflation:** underlying 60% / headline 40%.
- **Labor (all):** unemployment 70% / wages 20% / employment or payrolls 10% (`docs/LABOR_SCORE_V1.md`).
- **Activity:** GDP/domestic demand 60% / business surveys 40%. US survey block: services 70% / manufacturing 30% → 28% / 12% of Activity (`docs/ACTIVITY_SCORE_V1.md`).
- **Consumer:** retail 25% / income 25% / spending 25% / confidence 25% (`docs/CONSUMER_SCORE_V1.md`).

Missing inputs reduce coverage; never renormalize.

## Target product (G1 will specify formulas after C1–C5)

Two separate objects per country-dimension:

1. **LEVEL (1–100):** current economic state, reproducible from **latest underlying observations + documented anchors/scaling parameters + deterministic code**. A stable economy with no new information does not drift. 50 has an explicit economic meaning per component.
2. **IMPULSE / direction:** whether recent new/revised releases are heating or cooling the LEVEL. Not inferred solely from a one-day score move, and not accumulated into LEVEL.

Historical one-year LEVEL paths are reconstructed by applying the same LEVEL function to each vintage of latest observations. They are **not** a replay of cumulative +/- impulses from 50.

## Known integration defects G0 (closed by I1/I2/G2)

1. Dashboard live scores come from `scripts/apply_temperature_scores.py` overwriting `patch_v8` placeholders at Pages build time. **Closed:** patched values are V1 LEVELs from `data/temperature_scores.json` v3.
2. Trader Room `load_temperature_gauges()` previously parsed unpatched `patch_v8/*.html` prototype numbers. **Closed:** it now reads version-3 JSON (LEVEL + impulse + coverage).
3. Deploy workflow previously asserted `Reindexed to 50 on 2026-09-17` sixteen times. **Closed:** it now asserts `50 = structural/policy neutral anchor`.
4. Notion country-temperature DB is retired; GitHub is canonical. Do not write Notion.

## Backfill graph

C1 US, C2 CA, C3 AU, C4 NZ write `data/temperature_history/{us,ca,au,nz}.json` under `data/temperature_history/SCHEMA.md`. C5 audits. G1 then freezes anchors and LEVEL/IMPULSE formulas.
