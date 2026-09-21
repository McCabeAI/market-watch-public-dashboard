# Temperature history backfill audit (C5)

**Auditor:** C5 (independent Composer data auditor)  
**Repository:** McCabeAI/market-watch-public-dashboard  
**Branch reviewed:** `cursor/rebase-market-watch-temperature-gauges-on-one-year-of-data-5986`  
**Audit as-of:** 2026-09-21 (UTC)  
**Contract:** `data/temperature_history/SCHEMA.md`, `data/score_source_registry.json`, `docs/TEMPERATURE_CALIBRATION_G0.md`  
**Ledger:** `data/temperature_scores.json` used for cross-check only (not a time-series source of truth).

## Executive verdict

**PASS-WITH-FINDINGS**

No evidence of invented numeric history in official-agency series after independent refetch. Proprietary survey components are mostly explicit gaps; the exceptions are **single latest ISM PMI prints** (US Activity) and **one ANZ confidence print** (NZ Consumer), documented as ledger-assisted and not re-validated against a paywalled primary extract in this audit.

**Blocking issues (must fix before G1 calibration):** none identified.

**Non-blocking issues G1 should internalize:** see [Non-blocking findings](#non-blocking-findings-for-g1).

---

## 1. Schema compliance

| Check | Result |
|--------|--------|
| All registry components present per country (US 12 incl. `Inflation.mapped_bridge`; CA/AU/NZ 11 each) | **Pass** |
| Component keys `{Dimension}.{component}` match registry | **Pass** |
| Country `window` = 2025-09-21 … 2026-09-21 | **Pass** |
| Observations: required fields (`reference_period`, `value`, `units`, `transformation`, `publisher`, `source_url`, `vintage`, `retrieved_at`) | **Pass** (0 violations across all observation rows) |
| No `value: null` inventions; missing periods use `gaps` | **Pass** |
| Gap objects include `expected_period`, `reason`, `as_of` | **Pass** |
| Raw US FRED CSVs under `data/temperature_history/raw/us/` align with live FRED pulls (spot-checked) | **Pass** |

**Notes**

- `Inflation.mapped_bridge` observation `source_url` values are repo-relative (`data/us_core_pce_ppi_bridge_2026-08.csv`); canonical raw file is `data/temperature_history/raw/us/us_core_pce_ppi_bridge_2026-08.csv`. Provenance is recoverable but URLs are not absolute HTTPS links.
- `CA Inflation.underlying` stores **both** CPI-trim and CPI-median y/y in one component (`series_id` `CPI_trim_and_median_yoy`), doubling row count; `coverage.observed_periods_in_window: 24` counts rows, not distinct calendar months.

Deterministic tests added: `tests/test_temperature_history_audit.py` (no network).

---

## 2. Coverage matrix (2025-09-21 … 2026-09-21)

Legend: **Exp** = `coverage.expected_periods_in_window`; **Obs** = `coverage.observed_periods_in_window` (file metadata); **Gaps** = gap row count; **Latest** = `latest_reference_period`.

### 2.1 Sixteen country × dimension summary

| Country | Inflation | Labor | Activity | Consumer |
|---------|-----------|-------|----------|----------|
| **US** | Core PCE partial (11/13); bridge partial (2/13) | Mixed partial–ok (unemp 11/13; wages & payrolls 12/13) | GDP Q2 ok; ISM **1/13 each** + proprietary gaps | Retail ok (12/13); income/spend partial (11/13); confidence partial (11/13 FRED UMCSENT) |
| **CA** | Headline ok (12/12); underlying ok† (24 rows / 12 months) | ok (12/12 unemp & wages; employment **11/12** in metadata) | GDP ok (13/14); Ivey/BoC **unavailable** | Retail partial (9/10 to Jun); HEA quarterly ok; BoC CSCE **unavailable** |
| **AU** | ok (11/13 monthly CPI to Jul) | ok (11/13); wages partial (4/5 quarterly) | GDP partial (4/5); RBA surveys **unavailable** | MHSI ok (11/13); retail **0/13** (cessation); Westpac **2/13** + proprietary gaps |
| **NZ** | ok (4/4 quarterly) | ok (4/4 quarterly) | GDP ok (4/4); BusinessNZ/ANZ **unavailable** | Retail ok (4/4); income **3/4**; ANZ confidence **1/12** + proprietary gaps |

† CA underlying: 12 distinct months × 2 measures (trim + median).

### 2.2 Full component coverage (45 governed components)

#### United States (12)

| Component | Exp | Obs | Gaps | Status | Latest |
|-----------|-----|-----|------|--------|--------|
| Inflation.core_pce | 13 | 11 | 2 | partial | 2026-07 |
| Inflation.mapped_bridge | 13 | 2 | 11 | partial | 2026-08 |
| Labor.unemployment | 13 | 11 | 1 | partial | 2026-08 |
| Labor.wages | 13 | 12 | 1 | ok | 2026-08 |
| Labor.payrolls | 13 | 12 | 1 | ok | 2026-08 |
| Activity.gdp_domestic_demand | 4 | 3 | 1 | partial | 2026-Q2 |
| Activity.manufacturing_surveys | 13 | 1 | 12 | partial | 2026-08 |
| Activity.services_surveys | 13 | 1 | 12 | partial | 2026-08 |
| Consumer.retail | 13 | 12 | 1 | ok | 2026-08 |
| Consumer.income | 13 | 11 | 2 | partial | 2026-07 |
| Consumer.spending | 13 | 11 | 2 | partial | 2026-07 |
| Consumer.confidence | 13 | 11 | 15 | partial | 2026-07 |

#### Canada (11)

| Component | Exp | Obs | Gaps | Status | Latest |
|-----------|-----|-----|------|--------|--------|
| Inflation.headline | 12 | 12 | 1 | ok | 2026-08 |
| Inflation.underlying | 12 | 24† | 1 | ok | 2026-08 |
| Labor.unemployment | 12 | 12 | 1 | ok | 2026-08 |
| Labor.wages | 12 | 12 | 1 | ok | 2026-08 |
| Labor.employment | 12 | 11 | 1 | ok | 2026-08 |
| Activity.gdp_domestic_demand | 14 | 13 | 2 | ok | 2026-Q2 |
| Activity.business_surveys | 12 | 0 | 12 | unavailable | — |
| Consumer.retail | 10 | 9 | 3 | ok | 2026-06 |
| Consumer.income | 4 | 4 | 0 | ok | 2026-Q2 |
| Consumer.spending | 4 | 4 | 0 | ok | 2026-Q2 |
| Consumer.confidence | 4 | 0 | 5 | unavailable | — |

#### Australia (11)

| Component | Exp | Obs | Gaps | Status | Latest |
|-----------|-----|-----|------|--------|--------|
| Inflation.headline | 13 | 11 | 2 | ok | 2026-07 |
| Inflation.underlying | 13 | 11 | 2 | ok | 2026-07 |
| Labor.unemployment | 13 | 11 | 2 | ok | 2026-07 |
| Labor.employment | 13 | 11 | 2 | partial | 2026-07 |
| Labor.wages | 5 | 4 | 1 | partial | 2026-Q2 |
| Activity.gdp_domestic_demand | 5 | 4 | 1 | partial | 2026-Q2 |
| Activity.business_surveys | 13 | 0 | 13 | unavailable | — |
| Consumer.retail | 13 | 0 | 13 | partial | 2025-06‡ |
| Consumer.income | 5 | 4 | 1 | partial | 2026-Q2 |
| Consumer.spending | 13 | 11 | 2 | ok | 2026-07 |
| Consumer.confidence | 13 | 2 | 11 | partial | 2026-09 |

‡ One lookback observation `2025-06` only; ABS monthly retail marked ceased.

#### New Zealand (11)

| Component | Exp | Obs | Gaps | Status | Latest |
|-----------|-----|-----|------|--------|--------|
| Inflation.headline | 4 | 4 | 0 | ok | 2026-Q2 |
| Inflation.underlying | 4 | 4 | 0 | ok | 2026-Q2 |
| Labor.unemployment | 4 | 4 | 0 | ok | 2026-Q2 |
| Labor.wages | 4 | 4 | 0 | ok | 2026-Q2 |
| Labor.employment | 4 | 4 | 0 | ok | 2026-Q2 |
| Activity.gdp_domestic_demand | 4 | 4 | 0 | ok | 2026-Q2 |
| Activity.business_surveys | 12 | 0 | 12 | unavailable | — |
| Consumer.retail | 4 | 4 | 0 | ok | 2026-Q2 |
| Consumer.income | 4 | 3 | 1 | partial | 2026-Q1 |
| Consumer.spending | 4 | 4 | 0 | ok | 2026-Q2 |
| Consumer.confidence | 12 | 1 | 11 | partial | 2026-08 |

---

## 3. Independent refetch comparison

Refetches performed 2026-09-21 via `scripts.market_state.fetch_bytes` (FRED graph CSV, StatCan WDS POST, ABS release pages/XLSX, Stats NZ release HTML). Tolerance: ±0.05 pp for rates, ±0.02 index points, ±1k for payroll **change** in thousands.

| Jurisdiction | Series (period) | Official source (URL) | Fetched | File | Match |
|--------------|-----------------|------------------------|---------|------|-------|
| US | Core PCE index (2026-07) | [FRED PCEPILFE](https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPILFE) | 130.658 | 130.658 (`index_level`) | Yes |
| US | Core PCE m/m SA % (2026-07) | derived from PCEPILFE Jun→Jul | 0.245516 | 0.245516 | Yes |
| US | UNRATE (2026-08) | [FRED UNRATE](https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE) | 4.1 | 4.1 | Yes |
| US | PAYEMS m/m change (2026-08, 000s) | [FRED PAYEMS](https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS) levels 158913→159075 | +162.0 | +162.0 | Yes |
| US | Real GDP SAAR (2026-Q2) | [FRED A191RL1Q225SBEA](https://fred.stlouisfed.org/graph/fredgraph.csv?id=A191RL1Q225SBEA) | 1.5 | 1.5 | Yes |
| US | Retail sales m/m (2026-08) | [FRED RSAFS](https://fred.stlouisfed.org/graph/fredgraph.csv?id=RSAFS) | 1.2407% | 1.240742% | Yes |
| US | UMCSENT (latest on FRED) | [FRED UMCSENT](https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT) | 55.2 (2026-07) | 55.2 (2026-07) | Yes; Aug/Sep gapped |
| CA | CPI all-items y/y (2026-08) | [StatCan v41690973](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401) + derived | index 169.8; y/y 3.034% | 3.03% (raw_level 169.8) | Yes (rounded) |
| CA | CPI trim y/y (2026-08) | [StatCan v108785715](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810025601) | 1.9 | 1.9 | Yes |
| CA | CPI median y/y (2026-08) | [StatCan v108785714](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810025601) | 2.0 | (stored in underlying component) | Yes |
| CA | LFS unemployment (2026-08) | [StatCan v2062815](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701) | 6.4 | 6.4 | Yes |
| CA | LFS employment Δ (2026-08, 000s) | [StatCan v2062811](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701) 21214.8→21173.1 | −41.7 | −41.7 | Yes |
| CA | GDP q/q SA (2026-Q2) | [StatCan v1594571755](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610040101) | 0.8 | 0.8 | Yes |
| AU | CPI headline y/y (2026-07) | [ABS CPI Jul 2026](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/jul-2026) | 3.5% | 3.5 | Yes |
| AU | CPI trimmed mean y/y (2026-07) | same release | 3.6% | 3.6 | Yes |
| AU | Unemployment (2026-07) | [ABS LFS Jul 2026 / 62020001.xlsx](https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/jul-2026/62020001.xlsx) | 4.4618247 | 4.4618247 | Yes |
| AU | Domestic final demand q/q (2026-Q2) | [ABS National Accounts Jun 2026](https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/jun-2026) table | 0.3% | 0.3 (`A2304183K`) | Yes |
| AU | MHSI m/m (2026-07) | [5682001.xlsx](https://www.abs.gov.au/statistics/economy/finance/monthly-household-spending-indicator/jul-2026/5682001.xlsx) | 1.1% | 1.1 | Yes |
| NZ | CPI y/y & q/q (2026-Q2) | [CPI Jun 2026 quarter](https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/) | 4.1% / 1.5% | 4.1 / 1.5 | Yes |
| NZ | Unemployment (2026-Q2) | [HLFS Jun 2026](https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/) | 5.6% | 5.6 | Yes |
| NZ | GDP production q/q (2026-Q2) | [GDP Jun 2026](https://www.stats.govt.nz/information-releases/gross-domestic-product-june-2026-quarter/) | 0.2% | 0.2 | Yes |
| NZ | Retail volume q/q (2026-Q2) | [Retail Jun 2026](https://www.stats.govt.nz/information-releases/retail-trade-survey-june-2026-quarter/) | −0.5% | −0.5 | Yes |

**Not independently refetched in this audit (documented single prints):**

| Component | File value | Provenance in file | Ledger cross-check |
|-----------|------------|--------------------|--------------------|
| US ISM Manufacturing (2026-08) | 54.6 | ISM URL; note: ledger cross-check | Matches `temperature_scores.json` bootstrap basis |
| US ISM Services (2026-08) | 55.4 | ISM URL; note: ledger cross-check | Matches ledger |
| NZ ANZ consumer confidence (2026-08) | (see `nz.json`) | ANZ URL | Not re-fetched from ANZ site |

---

## 4. Fabrication hunt

| Pattern searched | Finding |
|------------------|---------|
| Observations missing `publisher` / `source_url` | None |
| Round-number runs without authority | None in official series; proprietary gaps not filled |
| Full 12-month proprietary paths | **Not found** (ISM/Westpac/ANZ/Ivey/BoC CSCE correctly gapped except allowed latest-only prints) |
| Ledger-only numbers without URL | **Not found** in observation rows |
| Contradictions vs refetch | **None** above tolerance |
| `temperature_scores.json` Sep UMich 47.8 | **Not** written into `us.json` (correctly gapped for 2026-09 UMCSENT / proprietary Conference Board) |

---

## 5. Gap quality

| Area | Assessment |
|------|------------|
| US ISM / Conference Board confidence | Honest `proprietary no free history` gaps; ISM latest month only |
| US Core PCE / BEA income & outlays Aug–Sep | Honest `not yet released` (FRED ends Jul for PCE; DSPI/PCEC96 lag) |
| CA Ivey / BoC CSCE | Fully gapped `unavailable` — appropriate |
| AU ABS monthly retail post-Jun 2025 | Gaps exist but many labeled `not yet released` though file documents **ABS cessation** — **mislabeled** (should be `source inaccessible` / methodology) |
| AU Westpac MI | Mostly proprietary gaps; 2 observation rows only |
| NZ business surveys | All proprietary gaps — appropriate |

---

## 6. Transformation integrity (spot-check)

- **US `Inflation.core_pce`:** m/m and y/y transforms recomputed from stored `index_level` rows match file to ≤0.01 pp (see test `test_us_core_pce_mom_matches_levels`).
- **US `Consumer.retail`:** Aug 2026 m/m matches RSAFS levels in raw CSV and live FRED.
- **CA `Inflation.headline`:** y/y 3.03% consistent with StatCan index 169.8 vs Aug 2025 level (3.034% unrounded).
- **CA `Labor.employment`:** m/m thousands change matches StatCan employment level vectors.

---

## 7. Ledger cross-check (non-authoritative)

`data/temperature_scores.json` bootstrap events align with US ISM Aug 2026 prints and US file notes on PCE/retail/income rounding vs ledger narrative. No instance found where the ledger supplied a full unsourced 12-month series in country JSON.

---

## Non-blocking findings for G1

1. **CA `Inflation.underlying`:** trim **and** median y/y coexist in one registry component; G1 must define collapse rule for the 60% underlying weight (trim only, average, or split — not specified in G0 files).
2. **CA coverage metadata:** `observed_periods_in_window: 24` on underlying double-counts series; `Labor.employment` reports 11 observed vs 12 monthly rows.
3. **US `Inflation.mapped_bridge`:** only Jul/Aug 2026 component table rows; relative CSV URLs; not a continuous 12-month bridge history.
4. **US ISM PMI:** single-month observations explicitly tied to operational ledger language; consider requiring ISM press-release citation URL before calibration anchors.
5. **AU `Activity.gdp_domestic_demand`:** mixes **real GDP** and **domestic final demand** q/q in one component (different `series_id`); G1 must pick the Activity 60% domestic-demand series.
6. **AU retail:** monthly retail effectively **ceased** after Jun 2025 reference; expect persistent Consumer coverage hole unless registry/source changes.
7. **AU / NZ confidence:** proprietary; sparse by design.
8. **NZ `Consumer.income`:** missing one quarterly point in window (3/4).
9. **BEA/FRED publication lag:** US Consumer income/spending and Core PCE trail BLS/Census — partial status expected through Sep audit date.

---

## Artifacts

- Audit tests: `tests/test_temperature_history_audit.py`
- Raw downloads reviewed: `data/temperature_history/raw/{us,ca,nz}/**`
- Refetch tooling: `scripts/market_state.py::fetch_bytes`, FRED `fredgraph.csv`, StatCan WDS `getDataFromVectorsAndLatestNPeriods`

**C5 did not modify country JSON files** (no fabricated values requiring gap replacement).
