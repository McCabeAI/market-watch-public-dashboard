# Canada physical energy and hard-activity source contract (Market Watch issue #139)

Status: **ACTIVE** for the standard macro ingestion pull (`scripts/macro_ingestion/`, CA adapter).
Scope: **data acquisition only.** No GDP nowcast, no regression, no temperature weight, no trading or narrative logic.
Every row below is `role: context`, `weight: 0.0`, and is skipped by the score bridge (`context_not_scored`).

Collector: `scripts/canada_energy_data.py` (parsers, calendar-day normalisation).
Adapter dispatch: `scripts/macro_ingestion/adapters/ca.py` (`aer_st3_oil_workbook`, `statcan_wds_vector_history`, `unavailable`).
Catalog rows: `data/macro_ingestion/baseline_catalog.json` and `data/macro_ingestion/catalog.json` (tagged `added_by: market-watch-issue-139-canadian-physical-energy`).
Tests: `tests/macro_ingestion/test_adapter_ca_energy.py`. Live record: `tests/macro_ingestion/fixtures/ca/live_smoke_report_energy.json`.

## Sources verified live (2026-09-29, Cloud Agent environment)

| Source | URL | Result |
|---|---|---|
| AER ST3 report page | `https://www.aer.ca/providing-information/data-and-reports/statistical-reports/st3` | HTTP 200; lists `Oil_current.xlsx` (XLSX) beside the PDF |
| AER ST3 oil workbook, current year | `https://www.aer.ca/documents/sts/st3/Oil_current.xlsx` → 303 → `https://static.aer.ca/prd/documents/sts/st3/Oil_current.xlsx` | HTTP 200, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, 42,885 bytes, SHA-256 `64799b435ffb9500d2abc9c43337bb654f181cf0ca8be10f837d7d900c6ea51b`, Run Date 27 August 2026, months Jan–Jul 2026 published |
| AER ST3 oil workbook, 2025 archive | `https://www.aer.ca/prd/documents/sts/st3/Oil_2025.xlsx` | HTTP 200, Run Date 27 February 2026, Jan–Dec 2025 |
| StatCan WDS vectors | `https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods` (POST JSON) | HTTP 200 for all six vectors, 36 monthly points each, per-point `releaseTime` |
| StatCan WDS metadata used to pin vectors | `getCubeMetadata`, `getSeriesInfoFromCubePidCoord`, `getCodeSets` | Used once to resolve coordinates → vector ids and code sets; not called by the runner |

The AER `static.aer.ca` host returned one transient TLS reset during verification; the retry succeeded. The runner's normal retry policy covers this. A structured AER workbook was preferred over the ST3 PDF as the issue requested.

## AER ST3 — Alberta crude oil and equivalent production

Workbook `Oil_current.xlsx`, sheet `Data`, block `SUPPLY`. Unit line `Unit = cubic metres (m3)`. Row 4 holds `Run Date: <d Month yyyy>` (publication vintage); row 5 holds the month headers `Jan..Dec` and the calendar year under `Year To Date`.

| Catalog id | `series_id` | Workbook row (SUPPLY block) | AER definition (Documentation sheet) |
|---|---|---|---|
| `CA.Energy.ab_oil_total_production` | `AER_ST3_OIL_TOTAL_PRODUCTION_M3` | `Total Production` | Total conventional crude oil + condensate + total oil sands |
| `CA.Energy.ab_oil_sands_production` | `AER_ST3_OIL_SANDS_TOTAL_PRODUCTION_M3` | `Total Oil Sands Production` | Nonupgraded total (in situ + mined − sent for further processing) + upgraded |
| `CA.Energy.ab_conventional_crude_production` | `AER_ST3_CONVENTIONAL_CRUDE_PRODUCTION_M3` | `Total Crude Oil Production` | Light + medium + heavy + ultra-heavy conventional crude |
| `CA.Energy.ab_condensate_production` | `AER_ST3_CONDENSATE_PRODUCTION_M3` | `Condensate Production` | `ACTIVITY=PROD, FLUID=COND` |

Rules:

- **Unpublished months are not zero.** The publisher zero-fills months not yet reported. A month is an observation only when it is strictly before the run-date month and at least one production row is non-zero. A partially reported run-date month is excluded even if non-zero.
- Only the first `SUPPLY` occurrence of a label is read; the `DISPOSITION` block is ignored.
- The current workbook is required. The prior-year archive workbook (`backfill_endpoints`) is a best-effort backfill: its failure is recorded in the payload `backfill_errors` and never fails the current read. Overlapping periods take the current workbook.
- `release_date` = workbook Run Date. Payload `vintage` = `aer_st3_run_date:<YYYY-MM-DD>`. `revision_status` = `latest_available` (AER restates prior months without a flag; a restatement beyond the ledger tolerance is stored as `revision_applied` with `earliest_release_vintage` / `latest_release_vintage`).
- Units on every observation: `cubic metres` (level) and `cubic metres per calendar day` (derived).
- Raw bytes archived under `data/macro_ingestion/raw/ca/<series_id>/<checked_at>-<sha12>` in live mode (current workbook only; the archive URL is on each backfilled point's `source_url`).

## Statistics Canada WDS

All rows use `retrieval_method: statcan_wds_vector_history`, `latestN = 36`, and store **every** returned point (not just the latest print). Each point carries the publisher's own `releaseTime` (stored as `release_date`), `symbolCode` (0 → `final`, 1 → `preliminary`, 3 → `revised`, stored as `revision_status`), `scalarFactorCode` (folded into `units`), and `statusCode` (kept on the point).

| Catalog id | Table | Coordinate | Vector | Units stored | SA |
|---|---|---|---|---|---|
| `CA.Energy.gas_marketable_production` | 25-10-0086-01 Natural gas supply and disposition, monthly | `1.8.1.0.0.0.0.0.0.0` (Canada / Marketable production, supply / Cubic metres) | `v1864626177` | thousands of cubic metres (+ derived per calendar day) | No |
| `CA.Activity.real_manufacturing_sales` | 16-10-0013-01 Real manufacturing sales …, 2017 dollars, SA | `1.1.1.0.0.0.0.0.0.0` | `v123263908` | millions of 2017 dollars | Yes |
| `CA.Consumer.retail_sales_volume` | 20-10-0067-01 Monthly retail sales, price, and volume, SA | `1.1.2.0.0.0.0.0.0.0` (Retail trade / Chained Fisher volume) | `v1446870181` | millions of chained (2017) dollars | Yes |
| `CA.Activity.wholesale_sales_volume` | 20-10-0003-01 Wholesale sales, price and volume, by industry, SA | `1.2.1.0.0.0.0.0.0.0` (Chained Fisher volume / Wholesale trade) | `v120586538` | millions of chained (2012) dollars | Yes |
| `CA.Activity.real_building_investment` | 34-10-0293-01 Investment in Building Construction | `1.1.1.4.0.0.0.0.0.0` (Canada / total / all work / SA constant) | `v1705315927` | constant 2017 dollars | Yes |
| `CA.Activity.crude_export_volume` | 12-10-0168-01 International merchandise trade, by commodity, price and volume indexes, monthly | `1.2.2.2.2.2.15.0.0.0` (Export / BoP / SA / Volume index / Laspeyres / Crude oil and crude bitumen) | `v1566916256` | Laspeyres volume index, 2017=100 | Yes |

Notes:

- WDS labels the retail and wholesale volume members "Chained Fisher volume index (scaled to equal 100 in 20xx)" but publishes them with UOM `Dollars` and scalar factor `millions`; the values are millions of chained dollars (July 2026: retail volume 60,501 vs 73,697 current prices; wholesale 111,429 vs 137,297). Units are recorded accordingly.
- Table 25-10-0063 / 25-10-0014 style monthly crude supply–disposition volumes (m³) are not exposed as a current WDS cube (25-10-0014 ended 2016-02). The trade volume index is the maintained official real/volume crude export series.
- Existing canonical rows are not touched: `CA.Consumer.retail` remains `v1446859483` (nominal m/m SA percent, table 20-10-0056). The volume row is a different table, measure, and id.

## Recorded gap

`CA.Housing.existing_home_sales` — CREA national resale sales. No stable, lawful, machine-readable primary endpoint exists (CREA terms of use; interactive stats page only). The row is `retrieval_method: unavailable`, `classification: proprietary_blocked`; the adapter returns `license_gap` with error `crea_existing_home_sales_no_stable_lawful_machine_readable_primary_series` and never fetches. Do not scrape the stats page or a news wire.

## Calendar-day normalisation (derived transform)

Physical production rows declare `derived_transforms: ["calendar_day_rate"]`. For each official `monthly_level` point the adapter emits a second point on the same `series_id`:

```
calendar_day_rate = monthly_level / days_in_calendar_month(period)
```

`days_in_calendar_month` uses the proleptic Gregorian calendar (`calendar.monthrange`), so February in leap years is 29. The derived observation carries `units = "<level units> per calendar day"` and a `derivation` block (`formula`, `days_in_month`, `derived_from_transformation`). The official level is never overwritten; both rows share `raw_sha256`, `release_date`, `vintage`, and `revision_status`.

Runner semantics (`scripts/macro_ingestion/runner.py`): a point's `transformation` is honoured only when the catalog row lists it in `derived_transforms`; rows without that field keep the legacy single-transform behaviour. Observation identity stays `(series_id, period, transformation, raw_sha256)`; the existing `values_close` tolerance (0.1% of scale) decides revision vs duplicate for both transforms.

## Reproduced July 2026 direction (from recorded live points, not hard-coded)

From `live_smoke_report_energy.json` retrieved 2026-09-29:

| Series | Jun 2026 level | Jul 2026 level | Level m/m | Jun daily rate | Jul daily rate | Daily-rate m/m |
|---|---|---|---|---|---|---|
| Alberta total oil sands (m³) | 16,513,522 | 18,423,653 | +11.6% | 550,451 | 594,311 | **+8.0%** (material rebound) |
| Canada marketable gas (thousand m³) | 17,078,082 | 17,568,810 | +2.9% | 569,269 | 566,736 | **−0.4%** (flat / slightly softer) |

`TestLiveSmokeEnergy` asserts the direction from the recorded points (oil-sands daily rate up more than 2%; gas daily rate between −2% and +0.5% and below its level change). Regenerate the report with `MACRO_INGESTION_LIVE_SMOKE=1 PYTHONPATH=. python3 -m unittest tests.macro_ingestion.test_adapter_ca_energy.TestLiveSmokeEnergy`.

## Release calendars

No machine-readable publisher calendar is pinned for these rows (`release_rule.dates = []`, `schedule_unparsed` recorded with the schedule URL). A rerun with no new data therefore reports `calendar_unparsed`, the same as the other CA context rows; it never reports `checked_unchanged` on an unpinned calendar. StatCan per-point `releaseTime` is preserved as the observation `release_date`.

## Source failure behaviour

- Transport failure, non-XLSX AER body, invalid WDS JSON, or a vector missing from the payload → `source_failed`; **no observation is written**, and prior observations are not re-stamped as fresh.
- A challenge/interstitial body (`access denied`, `captcha`, `cf-challenge`) → `license_gap`.
- The CREA row is always `license_gap` with no fetch.

## Manual commands

```bash
# Offline (fixtures; no network)
PYTHONPATH=. python3 -m unittest tests.macro_ingestion.test_adapter_ca_energy

# Live, CA only, standard runner (writes data/macro_ingestion/{observations,health,raw}; live is workflow_dispatch-only in CI)
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli --mode live --country CA
```
