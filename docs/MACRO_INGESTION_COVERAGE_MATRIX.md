# Macro ingestion coverage matrix

## Verification classes (2026-09-23 continuation)

- **66 scored rows are calibration weight rows, not 66 currently ingestible series.** Aliases, license gaps, ceased series, and rows whose transform or methodology does not match stay out of the gauge history.
- **Canonical-merge-ready** when the adapter observation `transformation` equals the calibration `source_transformation`, the component is not `observed: false`, any methodology break is already behind prints the stored series continues, and the fetch status is not `license_gap` or `source_failed`.
- **Observation-key priority:** a scored catalog row outranks an alias or context row with the same `(country, series_id, transform)`. `AU.Inflation.underlying` wins over `AU.Inflation.cpi_core_trimmed_already_scored_note`. Two different scored rows on one key fail closed.
- **Blocked / not merged** (weights unchanged): `US.Labor.wages`, `CA.Activity.gdp_domestic_demand`, `CA.Consumer.confidence`, `AU.Labor.unemployment`, `AU.Consumer.confidence` (transform or methodology), and `AU.Consumer.retail` (ceased; calibration `observed: false`, so a new print is `retired_unobserved` and does not re-enter the gauge).
- **`EA.Activity.flash_composite_pmi`**: the public press PDF `ab6649de01fd4c38a7f2c9a3e52a81bf` is the 2026-09 flash composite (53.1, released 2026-09-23). It is context weight 0. The scored `EA.Activity.business_surveys` series still keeps the August final (52.0) until a final September PDF is retrieved. The bot user agent receives HTTP 403 on the same public URLs; a normal browser fetch does not. Review-001 is unchanged.
- S&P PMI listings that return HTTP 403 remain `license_gap` or `source_failed`.
- `context` rows and `US.Inflation.mapped_bridge` stay weight 0 and are not merged into canonical history.

**Manual commands** (live is `workflow_dispatch` only; it updates canonical history and scores only when a scored point actually appends; it does not start an ACP trader run):

```bash
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli --mode offline --country all
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli --mode live --country all
```

Not every catalog series is live-primary today; see per-country rows below.

Status: **INVENTORY**. This is the parent catalog for the six-economy daily ingestion system.
Machine-readable twin: `data/macro_ingestion/baseline_catalog.json`.
Calibration anchor remains **2026-09-21**. No row in this document adds or changes a temperature weight.

Registry checklist size is **67** (`data/score_source_registry.json`): **66** weighted gauge inputs plus US `Inflation.mapped_bridge`, which is on the checklist and **must stay at weight 0**. `data/temperature_calibration.json` `weights` contains the 66 scored inputs only.

## How to read a row

- **Role** `scored`: existing calibration weight. The adapter may append a verified observation and the existing scorer may recompute LEVEL. It may not change the weight.
- **Role** `registry_unweighted`: on the 67-row checklist without a LEVEL weight. Weight stays 0.
- **Role** `context`: analogous US-style category or previously collected housing/credit/production series. Weight stays 0.
- **Role** `explanatory_alias`: documents a category that is already represented by a scored row, so runners must not create a second weighted component.
- **Classification** `official`: primary statistical agency or central bank. `licensed_public`: public redistribution or public press PDF (FRED, PR Newswire, S&P public release, ANZ/BusinessNZ public page). `proprietary_blocked`: no legal free machine source; do not bypass.
- **Checked-at** is not the observation vintage and not the calibration date. The runner records all three separately.
- A blank series id means the publisher is known and the country worker must pin the official id from the live source. Inventing an id or a print is a defect.

## Release-window fact for 23 September 2026

The public S&P Global PMI calendar (`https://www.pmi.spglobal.com/Public/Release/ReleaseDates?language=en`), retrieved on 23 September 2026, lists **S&P Global Flash Eurozone PMI** on **23 September 2026 at 08:00 UTC**.

| Clock | Instant |
| --- | --- |
| UTC | 2026-09-23 08:00 |
| Europe/Berlin (CEST) | 2026-09-23 10:00 |
| America/New_York (EDT) | 2026-09-23 04:00 |

That is after the trusted freeze at **01:50 ET**, after deterministic final delta at **03:35 ET**, and in the same window as publish **04:07 ET** / Pages around **04:15 ET**. A retrieved primary flash is a **post-freeze** live Market Data delta. It is not part of `overnight-20260923` review-001. This matrix stores **no September flash value**. If the primary PDF cannot be retrieved, the health ledger must show `release_due_missing` or `source_failed` for `EA.Activity.flash_composite_pmi` and must not treat the August final as a newly checked September print.

The same calendar page lists Flash US PMI at **13:45 UTC** on 23 September 2026 (09:45 ET) and Flash Japan PMI at **00:30 UTC** on 24 September 2026.

## US parity check

US scored coverage already includes Core PCE, unemployment, average hourly earnings, payrolls, real GDP growth, ISM services, ISM manufacturing, retail sales, personal income, real PCE, and Michigan sentiment. Headline CPI, core CPI, PPI, import prices, and export prices are **not** separate weighted inputs today (`mapped_bridge` carries CPI/PPI only as an unweighted bridge). Those price indexes are catalogued below as context so the other five economies are not asked to score a series the US gauge does not score. Conference Board confidence is a license gap. NAR existing-home sales are not in `scripts/us_housing_data.py` because that feed is not a maintained free official series; the gap stays explicit.

## US

25 catalog rows.

### `US.Inflation.core_pce`

- Role: `scored` · weight: `1.0` · policy: existing_calibration_weight
- Name: Personal Consumption Expenditures: Chain-type Price Index, Excluding Food and Energy
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `PCEPILFE`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPILFE
- Units: index 2017=100 · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 34 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: PCEPILFE_PC1 not available on FRED graph CSV; y/y and m/m stored as transforms from PCEPILFE index.

### `US.Inflation.mapped_bridge`

- Role: `registry_unweighted` · weight: `0.0` · policy: weight_must_remain_zero
- Name: BEA-mapped Core PCE PPI bridge component table (Aug 2026 documentation)
- Publisher: BEA / BLS · distributor: internal_csv · classification: `official`
- Series id: `None`
- Endpoint: data/us_core_pce_ppi_bridge_2026-08.csv
- Units: percent · seasonal adjustment: `True` · transform: `ppi_component_mom_pct`
- Cadence: monthly-between-Core-PCE-releases · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `repository_csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 18 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Blocked / weight note: Only BEA-mapped Core PCE source components can carry dynamic bridge weight; headline CPI/PPI never has standalone weight.
- Notes: No 12-month micro-bridge history; Jul/Aug 2026 component-level PPI moves from documented bridge file only.

### `US.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: Unemployment Rate
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `UNRATE`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: Average Hourly Earnings of All Employees, Total Private
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `CES0500000003`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CES0500000003
- Units: USD per hour · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 37 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Labor.payrolls`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: All Employees, Total Nonfarm
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `PAYEMS`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS
- Units: thousands · seasonal adjustment: `True` · transform: `mm_change_thousands_sa`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 25 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real Gross Domestic Product, Percent Change from Preceding Period, Seasonally Adjusted Annual Rate
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `A191RL1Q225SBEA`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=A191RL1Q225SBEA
- Units: percent · seasonal adjustment: `True` · transform: `saar_pct`
- Cadence: quarterly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Series is total real GDP SAAR percent change (BEA/FRED A191RL1Q225SBEA) as domestic-demand proxy per registry.

### `US.Activity.services_surveys`

- Role: `scored` · weight: `0.28` · policy: existing_calibration_weight
- Name: ISM Services PMI
- Publisher: ISM · distributor: — · classification: `licensed_public`
- Series id: `NMFBAI`
- Endpoint: https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/services/
- Units: diffusion_index · seasonal adjustment: `False` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `ism_prnewswire_press_releases` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T16:30:00Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Activity.manufacturing_surveys`

- Role: `scored` · weight: `0.12` · policy: existing_calibration_weight
- Name: ISM Manufacturing PMI
- Publisher: ISM · distributor: — · classification: `licensed_public`
- Series id: `NAPM`
- Endpoint: https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/
- Units: diffusion_index · seasonal adjustment: `False` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `ism_prnewswire_press_releases` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T16:30:00Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Advance Retail Sales: Retail Trade and Food Services, Total
- Publisher: U.S. Census Bureau · distributor: FRED · classification: `licensed_public`
- Series id: `RSAFS`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=RSAFS
- Units: millions USD SA · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Disposable Personal Income
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `DSPI`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DSPI
- Units: billions USD SA · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Real Personal Consumption Expenditures
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `PCEC96`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEC96
- Units: billions chained 2017 USD SA · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `US.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: University of Michigan Consumer Sentiment
- Publisher: University of Michigan Surveys of Consumers · distributor: FRED · classification: `licensed_public`
- Series id: `UMCSENT`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=UMCSENT
- Units: index · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 23 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:41:19Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: UMCSENT via FRED; CONCCONF graph CSV unavailable (404); OECD CSCICP03USM665S last observation 2024-01. Do not average series. Live ledger cites Conference Board and Michigan Sep-2026 preliminary not present in this FRED vintage.

### `US.Inflation.cpi_headline`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: CPI All Items, seasonally adjusted
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `CPIAUCSL`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL
- Units: index 1982-84=100 · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context only. Headline CPI has no standalone temperature weight. Primary publisher BLS; FRED is the licensed public distributor already used for scored US series.

### `US.Inflation.cpi_core`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: CPI less food and energy, SA
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `CPILFESL`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPILFESL
- Units: index 1982-84=100 · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context only. Not a substitute for scored Core PCE (PCEPILFE).

### `US.Inflation.ppi_final_demand`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: PPI Final Demand
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `WPSFD49207`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=WPSFD49207
- Units: index 2009-11=100 · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context only. Do not assign a temperature weight. Mapped-bridge PPI components stay unweighted.

### `US.Inflation.import_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Import Price Index (End Use): All commodities
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `IR`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=IR
- Units: index · seasonal adjustment: `False` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context only. Primary BLS import/export prices news release.

### `US.Inflation.export_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Export Price Index (End Use): All commodities
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `IQ`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=IQ
- Units: index · seasonal adjustment: `False` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context only.

### `US.Inflation.pce_headline`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: PCE price index headline
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `PCEPI`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=PCEPI
- Units: index 2017=100 · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Scored inflation remains Core PCE only.

### `US.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Labor force participation rate
- Publisher: BLS · distributor: FRED · classification: `licensed_public`
- Series id: `CIVPART`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CIVPART
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Not part of the 70/20/10 labor weights.

### `US.Activity.gdp_level`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Real GDP level
- Publisher: BEA · distributor: FRED · classification: `licensed_public`
- Series id: `GDPC1`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPC1
- Units: billions of chained 2017 dollars · seasonal adjustment: `True` · transform: `index_level`
- Cadence: quarterly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `fredgraph.csv` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context level. Scored activity remains A191RL1Q225SBEA growth.

### `US.Activity.flash_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: S&P Global Flash US PMI
- Publisher: S&P Global · distributor: — · classification: `licensed_public`
- Series id: `None`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/ReleaseDates?language=en
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. ISM manufacturing/services remain the scored US surveys. Flash US PMI is not an ISM substitute and must not receive ISM weight. Schedule fact from S&P calendar fetched 2026-09-23: Flash US PMI 13:45 UTC.

### `US.Consumer.confidence_conference_board`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Conference Board Consumer Confidence
- Publisher: The Conference Board · distributor: — · classification: `proprietary_blocked`
- Series id: `CONCCONF`
- Endpoint: https://www.conference-board.org/topics/consumer-confidence
- Units: index · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `unavailable` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Blocked / weight note: License gap. FRED graph CSV for CONCCONF is unavailable in the existing ledger. Do not scrape a paywall or average with UMCSENT. Scored confidence remains UMCSENT.

### `US.Housing.fhfa_purchase_only`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: FHFA Purchase-Only House Price Index
- Publisher: FHFA · distributor: FRED · classification: `licensed_public`
- Series id: `HPIPONM226S`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=HPIPONM226S
- Units: index · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `existing_us_housing_data` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Previously collected context in scripts/us_housing_data.py. Weight 0.

### `US.Housing.housing_starts`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Housing starts
- Publisher: U.S. Census Bureau / HUD · distributor: FRED · classification: `licensed_public`
- Series id: `HOUST`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=HOUST
- Units: thousands SAAR · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `existing_us_housing_data` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Previously collected context. Weight 0.

### `US.Credit.mortgage_30y`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: 30-year fixed mortgage rate
- Publisher: Freddie Mac · distributor: FRED · classification: `licensed_public`
- Series id: `MORTGAGE30US`
- Endpoint: https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US
- Units: percent · seasonal adjustment: `False` · transform: `percent`
- Cadence: weekly · timezone: `America/New_York`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/us/`
- Retrieval: `existing_us_housing_data` · adapter: `scripts.macro_ingestion.adapters.us`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Previously collected context. Weight 0.

## CA

18 catalog rows.

### `CA.Inflation.underlying`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: BoC core CPI measures (CPI-trim and CPI-median, year-over-year)
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `CPI_trim_and_median_yoy`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810025601
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 24 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Inflation.headline`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: Consumer Price Index, all-items, 12-month percent change
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v41690973_derived_yoy`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: Labour force survey unemployment rate, seasonally adjusted
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v2062815`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: Average hourly wages, employees, year-over-year change
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v105812645_derived_yoy`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410032001
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Labor.employment`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: Employment monthly change, seasonally adjusted
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v2062811_derived_mom_change`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701
- Units: thousands of persons · seasonal adjustment: `True` · transform: `mom_sa_change_thousands`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real GDP growth (monthly by industry and quarterly expenditure GDP)
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `monthly_v65201210;quarterly_v1594571783`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610043401
- Units: percent · seasonal adjustment: `True` · transform: `mom_sa_pct_and_qoq_sa_pct`
- Cadence: monthly-and-quarterly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 14 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Activity.business_surveys`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: S&P Global Canada Composite PMI Output Index (Ivey PMI conflict-only)
- Publisher: S&P Global · distributor: S&P Global PMI press releases · classification: `licensed_public`
- Series id: `SP_GLOBAL_CA_COMPOSITE`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `s_p_global_services_pmi_pdf_composite_section` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 25 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T18:30:00Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Scored target: S&P Global Canada Composite PMI Output Index (50=neutral) from primary Services PMI PDFs. Ivey PMI is conflict/corroboration only (series_id Ivey_PMI_conflict, not scored). CFIB Business Barometer is not scored (outlook index, not a contemporaneous composite PMI).

### `CA.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Total retail trade sales, seasonally adjusted, month-over-month
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v1446859483`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601
- Units: percent · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 10 · latest period: `2026-06` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household disposable income, quarter-over-quarter percent change
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v62305981_derived_qq`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610011201
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household final consumption expenditure, real q/q percent change
- Publisher: Statistics Canada · distributor: Statistics Canada WDS · classification: `official`
- Series id: `v1594571755`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610010401
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `CA.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Bank of Canada Canadian Survey of Consumer Expectations
- Publisher: Bank of Canada · distributor: — · classification: `proprietary_blocked`
- Series id: `None`
- Endpoint: https://www.bankofcanada.ca/publications/canadian-survey-of-consumer-expectations/
- Units: index_or_balance · seasonal adjustment: `None` · transform: `survey_balance`
- Cadence: quarterly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': False, 'revision': 'none', 'prior': 'none'}`
- Raw provenance: `data/temperature_history/raw/ca/`
- Retrieval: `unavailable` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `2026-09-21T14:45:36Z`
- Verification: `gap_no_observations` · freshness: `pending_daily_check`
- Blocked / weight note: no observations in temperature history

### `CA.Inflation.ippi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Industrial Product Price Index (PPI analog)
- Publisher: Statistics Canada · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.statcan.gc.ca/en/subjects-start/prices_and_price_indexes/industrial_product_price_index
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context weight 0. Country worker must pin the official WDS vector from table 18-10-0265. Do not invent a vector id.

### `CA.Inflation.rmpi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Raw Materials Price Index
- Publisher: Statistics Canada · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.statcan.gc.ca/en/subjects-start/prices_and_price_indexes/raw_materials_price_index
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context weight 0. Pin vector from the official RMPI table. Do not invent.

### `CA.Inflation.import_export_price_indexes`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: International merchandise trade price indexes (import and export)
- Publisher: Statistics Canada · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.statcan.gc.ca/en/subjects-start/prices_and_price_indexes
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Local analog of BLS IR/IQ. Two series required (import and export). Weight 0. Pin vectors from the official international trade price tables.

### `CA.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Labour force participation rate
- Publisher: Statistics Canada · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `statcan_wds_vectors` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Same LFS table as scored unemployment (14-10-0287). Pin the participation vector. Weight 0.

### `CA.Activity.ivey_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Ivey PMI SA
- Publisher: Ivey Business School · distributor: — · classification: `licensed_public`
- Series id: `Ivey_PMI_conflict`
- Endpoint: https://iveypmi.uwo.ca/
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `existing_harvest_ca_pmi` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Conflict/corroboration only. Already excluded from the composite weight. Do not add a weight.

### `CA.Activity.flash_composite_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: S&P Global Canada flash composite, if a public primary release exists
- Publisher: S&P Global · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_CA_COMPOSITE_FLASH`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `s_p_global_services_pmi_pdf_composite_section` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Scored series remains the final composite from the public Services PMI PDF. If no public flash primary exists, mark not_applicable rather than inventing a print.

### `CA.Housing.new_housing_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: NHPI already collected by scripts/canada_housing_data.py
- Publisher: Statistics Canada · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.statcan.gc.ca/en/subjects-start/housing
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `America/Toronto`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ca/`
- Retrieval: `existing_canada_housing_data` · adapter: `scripts.macro_ingestion.adapters.ca`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Reuse scripts/canada_housing_data.py. Weight 0. CMHC starts are a separate previously collected feed in that module.

## AU

20 catalog rows.

### `AU.Inflation.underlying`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Trimmed mean CPI year-ended inflation, Australia
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A130400382R`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/jul-2026/640106.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Latest in-window observation: 2026-07 = 3.6 percent.

### `AU.Inflation.headline`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: Headline CPI year-ended inflation (all groups), Australia
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A130393721F`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/jul-2026/640101.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Latest in-window observation: 2026-07 = 3.5 percent.

### `AU.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: Unemployment rate, seasonally adjusted
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A84423050A`
- Endpoint: https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/jul-2026/62020001.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `unemployment_rate_sa`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Latest in-window observation: 2026-07 = 4.4618247 percent.

### `AU.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: WPI total hourly rates (ex bonuses), all sectors, y/y, seasonally adjusted
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A83895396W`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia/jun-2026/634501.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `yoy_pct`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `AU.Labor.employment`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: Monthly change in employed persons, seasonally adjusted
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A84423043C`
- Endpoint: https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia/jul-2026/62020001.xlsx
- Units: thousands · seasonal adjustment: `True` · transform: `mom_change_thousands_sa`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Employment change is the first difference of employed-persons level series A84423043C.

### `AU.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real GDP and domestic final demand (chain volume, SA q/q)
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A2304370T;A2304183K`
- Endpoint: https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/jun-2026/5206001_Key_Aggregates.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 8 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `AU.Activity.business_surveys`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: S&P Global / Judo Bank Australia Composite PMI Output Index
- Publisher: S&P Global / Judo Bank · distributor: S&P Global PMI press releases · classification: `licensed_public`
- Series id: `SP_GLOBAL_AU_COMPOSITE_PMI`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `s_p_global_australia_services_or_flash_pmi_pdf` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T17:20:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: No maintained free numerical business-conditions history on rba.gov.au statistical tables identified.

### `AU.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Retail turnover, total industry, seasonally adjusted m/m
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A3348586T`
- Endpoint: https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025/850102.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'none'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 1 · latest period: `2025-06` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `AU.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household gross disposable income, seasonally adjusted q/q
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A2302939L`
- Endpoint: https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product/jun-2026/5206020_Household_Income.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook_derived_qoq` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 5 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `AU.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Monthly household spending indicator, total (current price), m/m, seasonally adjusted
- Publisher: Australian Bureau of Statistics · distributor: ABS · classification: `official`
- Series id: `A130200586W`
- Endpoint: https://www.abs.gov.au/statistics/economy/finance/monthly-household-spending-indicator/jul-2026/5682001.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `mom_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 12 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Latest in-window observation: 2026-07 = 1.1 percent.

### `AU.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Westpac-Melbourne Institute Consumer Sentiment Index
- Publisher: Westpac-Melbourne Institute · distributor: Westpac IQ · classification: `unverified`
- Series id: `None`
- Endpoint: https://www.westpaciq.com.au/economics
- Units: index · seasonal adjustment: `False` · transform: `index_level_or_mom_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/au/`
- Retrieval: `ledger_cross_check_single_prints` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 3 · latest period: `2026-09` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:49:33Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `AU.Inflation.cpi_core_trimmed_already_scored_note`

- Role: `explanatory_alias` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Trimmed mean already scored as Inflation.underlying
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `A130400382R`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia
- Units: percent · seasonal adjustment: `True` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Not a second weight. Listed so CPI underlying is not mistaken for a missing category. Adapter must not duplicate the scored row.

### `AU.Inflation.ppi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Producer Price Indexes
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/producer-price-indexes-australia
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context weight 0. Pin the final-demand or output-of-manufacturing series id from the official workbook. Do not invent an A-number.

### `AU.Inflation.import_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: International Trade Price Index, import
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/international-trade-price-indexes-australia
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official import price analog. Weight 0. Pin series id from the ITPI workbook.

### `AU.Inflation.export_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: International Trade Price Index, export
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/international-trade-price-indexes-australia
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official export price analog. Weight 0.

### `AU.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Participation rate
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.abs.gov.au/statistics/labour/employment-and-unemployment/labour-force-australia
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Same labour-force release as scored unemployment. Pin the participation series id. Weight 0.

### `AU.Activity.domestic_final_demand`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Domestic final demand (already stored as context beside scored GDP A2304370T)
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `A2304183K`
- Endpoint: https://www.abs.gov.au/statistics/economy/national-accounts/australian-national-accounts-national-income-expenditure-and-product
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: History notes DFD is context. Weight must stay 0. GDP A2304370T remains the scored series.

### `AU.Activity.flash_composite_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Flash Australia composite PMI
- Publisher: S&P Global / Judo Bank · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_AU_COMPOSITE_PMI_FLASH`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/ReleaseDates?language=en
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `s_p_global_australia_services_or_flash_pmi_pdf` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: S&P calendar: Flash Australia PMI is released at 23:00 UTC the day before many finals. Flash is not scored once a final primary PDF exists (see docs/ACTIVITY_SURVEY_SOURCES.md). Weight 0.

### `AU.Housing.dwelling_values_and_approvals`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Dwelling values, building approvals, lending indicators
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/total-value-dwellings/latest-release
- Units: mixed · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `existing_australia_housing_data` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Reuse scripts/australia_housing_data.py. Weight 0.

### `AU.Consumer.retail_ceased`

- Role: `explanatory_alias` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Retail Trade monthly series ceased after June 2025
- Publisher: Australian Bureau of Statistics · distributor: — · classification: `official`
- Series id: `A3348586T`
- Endpoint: https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025
- Units: percent · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: ceased · timezone: `Australia/Sydney`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/au/`
- Retrieval: `abs_time_series_workbook` · adapter: `scripts.macro_ingestion.adapters.au`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Already in history with one observation. Coverage stays down. Do not invent a post-2025-06 retail print. Weight remains the calibration weight on an unobserved component.

## NZ

18 catalog rows.

### `NZ.Inflation.underlying`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: CPI excluding food, household energy and vehicle fuels
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `CPIQ.SE9NS1450`
- Endpoint: https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_xlsx_table_3` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 10 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Inflation.headline`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: CPI all groups
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `CPIQ.SE9A`
- Endpoint: https://www.stats.govt.nz/information-releases/consumers-price-index-june-2026-quarter/
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_xlsx_tables_3.02_3.03` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 10 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: HLFS unemployment rate (seasonally adjusted)
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `HLFQ.S1F3S`
- Endpoint: https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_zip_hlfs_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 5 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: Labour Cost Index – all salary and wage rates
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `LCIQ.SD53Z9`
- Endpoint: https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_zip_lci_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 5 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Labor.employment`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: HLFS employed persons quarterly change
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `HLFQ.S1A3S`
- Endpoint: https://www.stats.govt.nz/information-releases/labour-market-statistics-june-2026-quarter/
- Units: thousands_of_persons · seasonal adjustment: `True` · transform: `qoq_change_thousands_sa`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_zip_hlfs_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 5 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real GDP – production measure
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `SNEQ.SG01RSC01B01PC`
- Endpoint: https://www.stats.govt.nz/information-releases/gross-domestic-product-june-2026-quarter/
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_infoshare_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 10 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Expenditure-measure GDP q/q stored as secondary series_id SNEQ.SG02RSC31B15PC in observations.

### `NZ.Activity.business_surveys`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: BNZ-BusinessNZ Performance of Composite Index, GDP-weighted
- Publisher: BusinessNZ / BNZ · distributor: BNZ Markets Research PDF (co-publisher with BusinessNZ) · classification: `licensed_public`
- Series id: `BUSINESSNZ_PCI_GDP_WEIGHTED`
- Endpoint: https://businessnz.org.nz/psi/
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `harvest_nz_pci_publications_psi_pdf` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T17:06:39Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Total retail sales volume (seasonally adjusted)
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `SF91KS`
- Endpoint: https://www.stats.govt.nz/information-releases/retail-trade-survey-june-2026-quarter/
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `information_release_xlsx_table_11` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 5 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household net disposable income (experimental national accounts)
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `household_net_disposable_income_sa`
- Endpoint: https://www.stats.govt.nz/experimental/national-accounts-income-saving-assets-and-liabilities-march-2026-quarter/
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `experimental_release_key_facts` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 4 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Uses Stats NZ experimental quarterly sector accounts (not the annual HES pin). June 2026 quarter release scheduled after window end.

### `NZ.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household final consumption expenditure
- Publisher: Stats NZ · distributor: Stats NZ · classification: `official`
- Series id: `SG02RSC30P30E`
- Endpoint: https://www.stats.govt.nz/information-releases/gross-domestic-product-june-2026-quarter/
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `gdp_supplementary_xlsx_table_4` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 5 · latest period: `2025-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: ANZ-Roy Morgan Consumer Confidence
- Publisher: ANZ · distributor: — · classification: `licensed_public`
- Series id: `None`
- Endpoint: https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'none'}`
- Raw provenance: `data/temperature_history/raw/nz/`
- Retrieval: `official_web_page_text` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 1 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T14:51:02Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `NZ.Inflation.ppi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Business price indexes (PPI outputs/inputs)
- Publisher: Stats NZ · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.stats.govt.nz/information-releases/business-price-indexes
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `information_release_infoshare_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context weight 0. Pin the official Infoshare or information-release series id. Do not invent.

### `NZ.Inflation.import_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Overseas trade index, import prices
- Publisher: Stats NZ · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.stats.govt.nz/information-releases/overseas-trade-indexes-prices
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `information_release_infoshare_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official import price analog. Weight 0.

### `NZ.Inflation.export_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Overseas trade index, export prices
- Publisher: Stats NZ · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.stats.govt.nz/information-releases/overseas-trade-indexes-prices
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `information_release_infoshare_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official export price analog. Weight 0.

### `NZ.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Labour force participation rate
- Publisher: Stats NZ · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.stats.govt.nz/information-releases/labour-market-statistics
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `information_release_zip_hlfs_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Same HLFS release as scored unemployment. Weight 0. Pin series id.

### `NZ.Activity.gdp_expenditure`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Expenditure-measure GDP q/q already stored as secondary context
- Publisher: Stats NZ · distributor: — · classification: `official`
- Series id: `SNEQ.SG02RSC31B15PC`
- Endpoint: https://www.stats.govt.nz/information-releases/gross-domestic-product
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct`
- Cadence: quarterly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `information_release_infoshare_csv` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Scored activity remains production GDP SNEQ.SG01RSC01B01PC only. Weight 0.

### `NZ.Activity.manufacturing_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: BNZ-BusinessNZ Performance of Manufacturing
- Publisher: BusinessNZ / BNZ · distributor: — · classification: `licensed_public`
- Series id: `BUSINESSNZ_PMI`
- Endpoint: https://www.bnz.co.nz/institutional-banking/research/publications
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `harvest_nz_pci_publications_psi_pdf` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context beside scored GDP-weighted PCI. Reuse scripts/harvest_nz_pci.py. Weight 0. BusinessNZ HTML is Cloudflare-blocked; use BNZ public PDFs only.

### `NZ.Consumer.confidence`

- Role: `explanatory_alias` · weight: `0.0` · policy: weight_must_remain_zero
- Name: ANZ-Roy Morgan consumer confidence already a scored component
- Publisher: ANZ · distributor: — · classification: `licensed_public`
- Series id: `None`
- Endpoint: https://www.anz.co.nz/about-us/economic-markets-research/consumer-confidence/
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `Pacific/Auckland`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/nz/`
- Retrieval: `official_web_page_text` · adapter: `scripts.macro_ingestion.adapters.nz`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Do not create a second weighted confidence series. This row documents the existing single-print limitation (Aug 2026 only in the calibration note).

## EA

20 catalog rows.

### `EA.Inflation.underlying`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: HICP excluding energy, food, alcohol and tobacco, 12-month rate of change (ECOICOP v2)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `PRC_HICP_MINR.M.RCH_A.TOT_X_NRG_FOOD.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/PRC_HICP_MINR?geo=EA21&unit=RCH_A&coicop18=TOT_X_NRG_FOOD&sinceTimePeriod=2024-01
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:51:07Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Inflation.headline`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: HICP all-items, 12-month rate of change (ECOICOP v2 TOTAL)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `PRC_HICP_MINR.M.RCH_A.TOTAL.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/PRC_HICP_MINR?geo=EA21&unit=RCH_A&coicop18=TOTAL&sinceTimePeriod=2024-01
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:51:07Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: Unemployment rate, seasonally adjusted (LFS)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `UNE_RT_M.M.SA.TOTAL.PC_ACT.T.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/UNE_RT_M?geo=EA21&sex=T&s_adj=SA&age=TOTAL&unit=PC_ACT&sinceTimePeriod=2025-09
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: ECB indicator of negotiated wage rates, annual rate of change
- Publisher: European Central Bank · distributor: ECB Data Portal · classification: `official`
- Series id: `INW.Q.I10.N.INWR.000000.4F0.GY.IX`
- Endpoint: https://data-api.ecb.europa.eu/service/data/INW/INW.Q.I10.N.INWR.000000.4F0.GY.IX?format=csvdata&startPeriod=2024-Q1
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `ecb_sdmx_csvdata` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Labor.employment`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: Employment (LFS), quarter-over-quarter change in thousands (derived from SA levels)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `LFSI_EMP_Q.Q.SA.EMP_LFS.T.Y15-74.THS_PER.EA21_derived_qq_thousands`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/LFSI_EMP_Q?geo=EA21&indic_em=EMP_LFS&sex=T&age=Y15-74&s_adj=SA&unit=THS_PER&sinceTimePeriod=2024-Q1
- Units: thousands · seasonal adjustment: `True` · transform: `qq_change_thousands`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api_derived` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real GDP, chain-linked volumes, q/q % change (SCA)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `NAMQ_10_GDP.Q.CLV_PCH_PRE.SCA.B1GQ.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.EA21?format=JSON&startPeriod=2024-Q1
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_sdmx_json` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Activity.business_surveys`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: S&P Global Eurozone Composite PMI Output Index
- Publisher: S&P Global · distributor: S&P Global public press releases · classification: `licensed_public`
- Series id: `SP_GLOBAL_EA_COMPOSITE_PMI`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:21:07Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Retail trade volume of sales, m/m % (SCA)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `STS_TRTU_M.M.SCA.VOL_SLS.G47.PCH_PRE.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/STS_TRTU_M?geo=EA21&indic_bt=VOL_SLS&nace_r2=G47&s_adj=SCA&unit=PCH_PRE&sinceTimePeriod=2025-09
- Units: percent · seasonal adjustment: `True` · transform: `mom_sa_pct`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Adjusted gross disposable income of households, real per capita q/q % (SCA)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `NASQ_10_KI.Q.PC.SCA.S14_S15.B7G_R_HAB_GR.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/NASQ_10_KI?geo=EA21&sector=S14_S15&na_item=B7G_R_HAB_GR&unit=PC&s_adj=SCA&sinceTimePeriod=2024-Q1
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 3 · latest period: `2026-Q1` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Household final consumption expenditure (P31_S15), real q/q % (SCA)
- Publisher: Eurostat · distributor: Eurostat · classification: `official`
- Series id: `NAMQ_10_GDP.Q.CLV_PCH_PRE.SCA.P31_S15.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/namq_10_gdp/Q.CLV_PCH_PRE.SCA.P31_S15.EA21?format=JSON&startPeriod=2024-Q1
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_sdmx_json` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: European Commission consumer confidence indicator (balance)
- Publisher: European Commission (DG ECFIN) · distributor: Eurostat · classification: `official`
- Series id: `EI_BSCO_M.M.SA.BS-CSMCI.BAL.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/EI_BSCO_M?geo=EA21&indic=BS-CSMCI&s_adj=SA&unit=BAL&sinceTimePeriod=2025-09
- Units: balance · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T20:24:59Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `EA.Inflation.hicp_flash`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: HICP flash estimate
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://ec.europa.eu/eurostat/web/hicp
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Scored headline/underlying remain the monthly HICP in prc_hicp_minr. Flash must be a distinct vintage and must not overwrite the final. Weight 0.

### `EA.Inflation.ppi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Industrial producer prices
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://ec.europa.eu/eurostat/databrowser/view/sts_inpp_m
- Units: percent or index · seasonal adjustment: `None` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: PPI analog. Weight 0. Pin the EA21 domestic-output series key from the live Eurostat dataset. Do not invent a key or a value.

### `EA.Inflation.import_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Import price index, industry
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://ec.europa.eu/eurostat/web/short-term-business-statistics
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Weight 0. If Eurostat has no EA21 import-price series, mark not_applicable with the dataset that was checked. Do not use a national German index as the euro-area print.

### `EA.Inflation.export_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Export / output price index analog
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://ec.europa.eu/eurostat/web/short-term-business-statistics
- Units: index · seasonal adjustment: `None` · transform: `index_level`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Weight 0. Domestic PPI output is not an export price index. If no EA export-price index exists, mark not_applicable explicitly.

### `EA.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Labour force participation, EA
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://ec.europa.eu/eurostat/web/lfs
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_statistics_api` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Weight 0. Quarterly LFS activity rate if published for EA21. Do not invent a monthly participation rate.

### `EA.Activity.gdp_components`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Household consumption is already scored as Consumer.spending; this row is the domestic-demand component set (gross capital formation, government, net exports) as context
- Publisher: Eurostat · distributor: — · classification: `official`
- Series id: `NAMQ_10_GDP.Q.CLV_PCH_PRE.SCA.P31_S14.EA21`
- Endpoint: https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/namq_10_gdp/Q.CLV_PCH_PRE.SCA.P31_S14.EA21?format=JSON
- Units: percent · seasonal adjustment: `True` · transform: `qoq_sa_pct`
- Cadence: quarterly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `eurostat_sdmx_json` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Weight 0. Pin P51G, P3_S13 and B11 if those keys validate. Scored GDP remains B1GQ.

### `EA.Activity.flash_composite_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: S&P Global Flash Eurozone PMI
- Publisher: S&P Global · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_EA_COMPOSITE_PMI_FLASH`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/ReleaseDates?language=en
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `explicit_timestamp` · dates: `['2026-09-23T08:00:00Z']`
- New York release instant: `2026-09-23T04:00:00-04:00` · Berlin: `2026-09-23T10:00:00+02:00`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: SEE SEP23 FIXTURE. Schedule verified from the public S&P PMI calendar on 2026-09-23: 'S&P Global Flash Eurozone PMI' at 08:00 UTC on 23 September 2026, which is 04:00 America/New_York (EDT). This is after the 01:50 ET trusted freeze. No flash value is stored in this catalog. Secondary news reports are not a primary source.
- Fixture: `{"name": "missed_or_unverified_sep23_ea_flash_composite_pmi", "period": "2026-09", "value_in_catalog": null, "prohibited_values": "Do not copy secondary-wire figures into the ledger. A number reported by Reuters or a squawk is not the primary PDF.", "primary_listing": "https://www.pmi.spglobal.com/Public/Release/PressReleases", "if_primary_pdf_unavailable": "status release_due_missing or source_failed, alert visible, August final remains the latest scored vintage, no September observation is appended"}`

### `EA.Activity.manufacturing_pmi_final`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Eurozone manufacturing PMI final
- Publisher: S&P Global · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_EA_MANUFACTURING_PMI`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Scored survey remains the composite. Weight 0. Final manufacturing releases are 08:00 UTC on the first working day pattern; October 2026 calendar shows 1 Oct 08:00 UTC.

### `EA.Activity.services_pmi_final`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Eurozone services PMI final
- Publisher: S&P Global · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_EA_SERVICES_PMI`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Europe/Berlin`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/ea/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.ea`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Context. Weight 0. October 2026 calendar shows Eurozone Composite (services day) at 08:00 UTC on 5 Oct 2026.

## JP

19 catalog rows.

### `JP.Inflation.underlying`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: CPI less fresh food and energy, 12-month percent change (2025 base; BOJ core-core style)
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `CPI_2025BASE_LESS_FRESH_FOOD_ENERGY_YOY`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032103932&fileKind=1
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_csv` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Inflation.headline`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: Consumer Price Index, all items, 12-month percent change (2025 base)
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `CPI_2025BASE_ALL_ITEMS_YOY`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032103932&fileKind=1
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_csv` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Labor.unemployment`

- Role: `scored` · weight: `0.7` · policy: existing_calibration_weight
- Name: Unemployment rate, seasonally adjusted, whole Japan
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `LFS_1A1_UNEMPLOYMENT_RATE_SA`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031831358&fileKind=0
- Units: percent · seasonal adjustment: `True` · transform: `rate_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_xlsx` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 10 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Labor.wages`

- Role: `scored` · weight: `0.2` · policy: existing_calibration_weight
- Name: Total cash earnings, year-on-year percent change, establishments with 5+ employees
- Publisher: Ministry of Health, Labour and Welfare · distributor: Ministry of Health, Labour and Welfare · classification: `official`
- Series id: `MLS_TOTAL_CASH_EARNINGS_YOY_5PLUS`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032189720&fileKind=4
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_xls` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 10 · latest period: `2026-06` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Nominal total cash earnings (現金給与総額), includes scheduled and non-scheduled pay; overtime-sensitive versus contractual/scheduled-only series also published in the same table set.

### `JP.Labor.employment`

- Role: `scored` · weight: `0.1` · policy: existing_calibration_weight
- Name: Month-on-month change in employed persons (seasonally adjusted), derived from LFS 1-a-1
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `LFS_1A1_EMPLOYED_PERSONS_SA`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031831358&fileKind=0
- Units: thousands · seasonal adjustment: `True` · transform: `mom_change_thousands_sa`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_xlsx_derived` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 9 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Employed persons level is published in 万人 (ten-thousand persons); mom_change_thousands_sa = (level_t - level_t-1) * 10.

### `JP.Activity.gdp_domestic_demand`

- Role: `scored` · weight: `0.6` · policy: existing_calibration_weight
- Name: Real GDP, seasonally adjusted quarter-on-quarter annualized rate (expenditure approach)
- Publisher: Cabinet Office (ESRI) · distributor: Cabinet Office (ESRI) · classification: `official`
- Series id: `ESRI_REAL_GDP_QOQ_SAAR`
- Endpoint: https://www.esri.cao.go.jp/jp/sna/data/data_list/sokuhou/files/2026/qe262_2/tables/nritu-jk2622.csv
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct_saar`
- Cadence: quarterly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `esri_sna_sokuhou_csv` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 4 · latest period: `2026-Q2` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: Uses real GDP (first column) from nritu-jk* SA q/q annualized table; latest vintage revises historical quarters each release.

### `JP.Activity.business_surveys`

- Role: `scored` · weight: `0.4` · policy: existing_calibration_weight
- Name: au Jibun Bank / S&P Global Japan Composite PMI Output Index
- Publisher: S&P Global / au Jibun Bank · distributor: S&P Global / au Jibun Bank · classification: `licensed_public`
- Series id: `SP_GLOBAL_JP_COMPOSITE_PMI`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/PressReleases
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 8 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:58Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Consumer.retail`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Retail sales value, year-on-year percent change (Current Survey of Commerce)
- Publisher: Ministry of Economy, Trade and Industry · distributor: Ministry of Economy, Trade and Industry · classification: `official`
- Series id: `METI_CSC_RETAIL_SALES_YOY`
- Endpoint: https://www.meti.go.jp/statistics/tyo/syoudou/result/excel/DB_202607S.xlsx
- Units: percent · seasonal adjustment: `True` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `meti_commerce_survey_excel` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Consumer.income`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Real income, nominal year-on-year percent change, worker households (two-or-more-person)
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `FIES_WORKER_HH_REAL_INCOME_NOMINAL_YOY`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040270658&fileKind=4
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_xlsx` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`
- Notes: FIES Table 2 long-term series (e-Stat statInfId=000040270658): worker households among two-or-more-person households; 実収入 nominal y/y.

### `JP.Consumer.spending`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Consumption expenditure, nominal year-on-year percent change, two-or-more-person households
- Publisher: Statistics Bureau of Japan · distributor: Statistics Bureau of Japan · classification: `official`
- Series id: `FIES_TWO_PLUS_HH_CONSUMPTION_NOMINAL_YOY`
- Endpoint: https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040270657&fileKind=4
- Units: percent · seasonal adjustment: `False` · transform: `yoy_pct`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `estat_file_download_xlsx` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 11 · latest period: `2026-07` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Consumer.confidence`

- Role: `scored` · weight: `0.25` · policy: existing_calibration_weight
- Name: Consumer Sentiment Index (seasonally adjusted), two-or-more-person households
- Publisher: Cabinet Office · distributor: Cabinet Office · classification: `official`
- Series id: `CO_CONSUMER_SENTIMENT_INDEX_SA`
- Endpoint: https://www.esri.cao.go.jp/en/stat/shouhi/shouhi2.xlsx
- Units: index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': True, 'revision': 'vintage_latest_available_only', 'prior': 'prior_observation_in_ledger'}`
- Raw provenance: `data/temperature_history/raw/jp/`
- Retrieval: `esri_cabinet_office_shouhi2_xlsx` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 12 · latest period: `2026-08` · ledger vintage: `latest_available` · retrieved_at: `2026-09-21T22:23:30Z`
- Verification: `held_in_temperature_history` · freshness: `pending_daily_check`

### `JP.Inflation.cgpi_ppi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Corporate Goods Price Index, domestic (PPI analog)
- Publisher: Bank of Japan · distributor: — · classification: `official`
- Series id: `BOJ_CGPI_DOMESTIC`
- Endpoint: https://www.boj.or.jp/en/statistics/pi/cgpi_release/index.htm
- Units: index · seasonal adjustment: `False` · transform: `index_level`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `boj_cgpi` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official PPI analog is the BOJ CGPI, not a Statistics Bureau CPI variant. Weight 0. Pin the domestic corporate goods index from the official BOJ release.

### `JP.Inflation.import_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: BOJ Import Price Index (yen basis)
- Publisher: Bank of Japan · distributor: — · classification: `official`
- Series id: `BOJ_CGPI_IMPORT`
- Endpoint: https://www.boj.or.jp/en/statistics/pi/cgpi_release/index.htm
- Units: index · seasonal adjustment: `False` · transform: `index_level`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `boj_cgpi` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official import-price analog inside CGPI. Weight 0.

### `JP.Inflation.export_price_index`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: BOJ Export Price Index (yen basis)
- Publisher: Bank of Japan · distributor: — · classification: `official`
- Series id: `BOJ_CGPI_EXPORT`
- Endpoint: https://www.boj.or.jp/en/statistics/pi/cgpi_release/index.htm
- Units: index · seasonal adjustment: `False` · transform: `index_level`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `boj_cgpi` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Official export-price analog inside CGPI. Weight 0.

### `JP.Labor.participation`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Labour force participation rate
- Publisher: Statistics Bureau of Japan · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.stat.go.jp/english/data/roudou/index.html
- Units: percent · seasonal adjustment: `True` · transform: `percent`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `estat_file_download_xlsx` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Same Labour Force Survey family as scored unemployment. Weight 0. Pin the official table column. Do not invent.

### `JP.Activity.domestic_demand`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Domestic demand contribution / component in the same sokuhou table as scored real GDP
- Publisher: Cabinet Office (ESRI) · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.esri.cao.go.jp/en/sna/sokuhou/sokuhou_top.html
- Units: percent · seasonal adjustment: `True` · transform: `qoq_pct_saar`
- Cadence: quarterly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `esri_sna_sokuhou_csv` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Scored series remains ESRI real GDP SAAR. Domestic-demand column is context weight 0. Pin the column from nritu-jk CSV. Do not change the GDP weight.

### `JP.Activity.flash_composite_pmi`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Flash Japan PMI
- Publisher: S&P Global / au Jibun Bank · distributor: — · classification: `licensed_public`
- Series id: `SP_GLOBAL_JP_COMPOSITE_PMI_FLASH`
- Endpoint: https://www.pmi.spglobal.com/Public/Release/ReleaseDates?language=en
- Units: diffusion_index · seasonal adjustment: `True` · transform: `diffusion_index`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `sp_global_press_release_pdf` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: S&P calendar fetched 2026-09-23 lists Flash Japan PMI at 00:30 UTC on 24 September 2026 (09:30 Asia/Tokyo, 20:30 previous calendar day in America/New_York). Weight 0. Final composite remains the scored series.

### `JP.Activity.tankan_large_manufacturing`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Tankan large-manufacturing business conditions DI
- Publisher: Bank of Japan · distributor: — · classification: `official`
- Series id: `BOJ_TANKAN_LARGE_MFG_BUSINESS_CONDITIONS_DI`
- Endpoint: https://www.boj.or.jp/en/statistics/tk/gaiyo/2026/tka2606.zip
- Units: diffusion_index · seasonal adjustment: `False` · transform: `diffusion_index`
- Cadence: quarterly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `boj_tankan_zip` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Already present in jp.json with zero observations. Context weight 0. A failed zip parse stays source_failed or explicit gap. Do not add a survey weight.

### `JP.Activity.industrial_production`

- Role: `context` · weight: `0.0` · policy: weight_must_remain_zero
- Name: Indices of industrial production
- Publisher: METI · distributor: — · classification: `official`
- Series id: `None`
- Endpoint: https://www.meti.go.jp/english/statistics/tyo/iip/index.html
- Units: index · seasonal adjustment: `True` · transform: `index_level`
- Cadence: monthly · timezone: `Asia/Tokyo`
- Release rule: `country_local_schedule_required` · dates: `[]`
- Actual / revision / prior metadata: `{'actual': 'when_primary_retrieved', 'revision': 'when_publisher_marks_revision', 'prior': 'when_series_has_history'}`
- Raw provenance: `data/macro_ingestion/raw/jp/`
- Retrieval: `meti_iip` · adapter: `scripts.macro_ingestion.adapters.jp`
- Held observations: 0 · latest period: `None` · ledger vintage: `None` · retrieved_at: `None`
- Verification: `catalogued_adapter_pending` · freshness: `not_yet_checked_by_new_runner`
- Notes: Previously relevant production indicator. Weight 0. Reuse METI retrieval style from japan_macro_data.py. If the workbook cannot be parsed, mark source_failed.

## Not applicable and license gaps (explicit)

| Item | Treatment |
| --- | --- |
| US Conference Board Consumer Confidence | `proprietary_blocked` / `license_gap`. Scored series remains UMCSENT. |
| US NAR existing-home sales | No maintained free official feed in `scripts/us_housing_data.py`. Do not add a vendor scrape. |
| CA Bank of Canada CSCE | Already `unavailable` with zero observations. Stays `license_gap` until an official machine-readable file is published. |
| AU monthly retail after June 2025 | Series ceased. Component stays unobserved. Do not backfill from a card-spend vendor. |
| NZ BusinessNZ HTML | Cloudflare challenge. Use BNZ public PDFs only. |
| S&P Global PDF behind a bot challenge | Record the challenge URL and status. Do not copy a wire-service number into the ledger. |
| German national CPI/PMI as a euro-area substitute | Not applicable. EA rows use EA21 / euro-area aggregates only. |

## Counts

- Catalog rows: **120**
- Scored: **66**
- Registry unweighted: **1**
- Context: **50**
- Explanatory aliases: **3**

Country workers may add a missing official series id only inside their own fragment, with the endpoint they actually called. They may not delete a row and may not set a non-zero weight on a context row.
