# Canada CPI September 2026 provenance correction

Verified on **2026-10-30** from primary Statistics Canada sources.

## The Daily

- URL: https://www150.statcan.gc.ca/n1/daily-quotidien/261019/dq261019a-eng.htm
- Title: **Consumer Price Index, September 2026**
- **Released: 2026-10-19**
- All-items 12-month change printed as **3.1%**

## WDS (`getDataFromVectorsAndLatestNPeriods`)

Endpoint: `https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods`

| Vector | Period | Value | `releaseTime` |
|--------|--------|-------|----------------|
| 41690973 (all-items index) | 2026-09-01 | 170.0 | 2026-10-19T08:30 |
| 41690973 | 2026-08-01 | 169.8 | 2026-09-14T08:30 |
| 41690973 | 2025-09-01 | 164.9 | (prior vintage) |
| 108785715 (CPI-trim y/y) | 2026-09 | 1.8 | 2026-10-19T08:30 |
| 108785714 (CPI-median y/y) | 2026-09 | 1.9 | 2026-10-19T08:30 |

Derived headline y/y from the September index: `(170.0 / 164.9 - 1) * 100 = 3.092783505154628`, which **exactly matches** the stored `Inflation.headline` value for `2026-09`. That value was **not** rewritten.

## What we corrected

For `data/temperature_history/ca.json`, components **`Inflation.headline`** and **`Inflation.underlying`** only:

- Every observation with `reference_period` **`2026-09`** now has `release_date` **`2026-10-19`** (replacing the inherited August vintage stamp `2026-09-14` on the September rows).
- Removed `gaps` entries with `expected_period` `2026-09` and reason `not yet released`.
- Updated `coverage` (`latest_reference_period`, `latest_release_date`, `gap_count`, and window counts).

August headline `release_date` **`2026-09-14`** is unchanged (real August CPI publication).

`data/temperature_scores.json` keeps the same Canada inflation level (54.34), impulse (-0.44), and component transform values. The only score-file edit is the derived release-date lineage on `CA.Inflation` headline and underlying: `release_date` `2026-10-19` and `release_date_status` `recorded`. That is what `write_state` emits from the corrected history, and the existing byte-compare requires it. No weight, impulse, or level was edited.

## Follow-up: `raw_level` on September headline

The stored September headline row still has **`raw_level` 169.8**, which is the **August** index level mistakenly inherited during ingest. The official September all-items index is **170.0**. We did **not** rewrite `raw_level` or the stored y/y because the committed y/y already matches `170.0 / 164.9`.

## Historical WDS vintage stamps

StatCan WDS can stamp the **current** vintage `releaseTime` on older core index points when queried as a batch. We **did not** rewrite pre-September `release_date` fields on trim/median history rows that still carry batch vintage stamps (for example `2026-09-14` on months before September 2026).

## In-memory guard

`scripts/country_detail/ca_cpi_provenance.repair_ca_cpi_september_2026_provenance` applies the same September-only correction when Canada history is loaded for Country Detail projection, so a refresh that still carries the inherited stamp cannot present September CPI as published on the August date. The committed JSON file remains the persisted source of truth.
