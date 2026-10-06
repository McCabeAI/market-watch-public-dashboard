# US Labor Employment Situation — BLS primary ingestion

## Native BLS series (confirmed on data.bls.gov, 2026-10-05)

| Catalog id | Score `series_id` (unchanged) | Native BLS id | Transform |
| --- | --- | --- | --- |
| `US.Labor.payrolls` | `PAYEMS` | `CES0000000001` | `mm_change_thousands_sa` (level difference) |
| `US.Labor.unemployment` | `UNRATE` | `LNS14000000` | `percent` (rate level) |
| `US.Labor.wages` | `CES0500000003` | `CES0500000003` | `yoy_pct` (12-month level ratio; catalog `derived_transforms`: `mom_sa_pct`) |
| `US.Labor.participation` | `LNS11300000` | `LNS11300000` | `percent` (context, weight 0) |

Temperature scoring continues to filter observations by the score ids (`PAYEMS`, `UNRATE`, `CES0500000003`) using each row's calibration `source_transformation`. For wages, the scored observation is **`yoy_pct` derived from CES0500000003 dollar levels 12 months apart**; `data/temperature_calibration.json` remains `yoy_pct` and is not edited. Ingestion also emits **`mom_sa_pct` only when listed in catalog `derived_transforms`** — contextual evidence, not the canonical score lookup key (`lookup` uses catalog `transform`, i.e. `yoy_pct`). Weights and calibration JSON are unchanged.

## Source precedence (scored rows only)

1. **Primary** — one BLS Public Data API v2 POST batch `empsit` with exactly `CES0000000001`, `LNS14000000`, `CES0500000003`, and `LNS11300000` (separate from the existing 24-id CPS batch). The batch window is `startyear=end_year-1`, `endyear=end_year`, which includes month *t−12* for a monthly print.
2. **Derive** — for wages, `_derive_us_labor_wage_points` in `scripts/macro_ingestion/adapters/us.py` from official dollar levels (yoy required; optional mom when prior month is adjacent). Other scored rows use `_derive_latest_point`; only the latest derived point is emitted for those (prior month in `derivation`, not extra scored history).
3. **Validation** — independent FRED read via `_fetch_fred_series` using catalog fallback ids (`PAYEMS`, `UNRATE`, `CES0500000003`), applying the same yoy (and optional mom) derivation for wages. FRED timeouts do not fail a good BLS point.
4. **Conflict** — compare **only** the scored transform (`yoy_pct` for wages): same period and transform but `values_close` false → `source_failed` / `verification_conflict`, no observation, no averaging. Mom disagreement alone does not fail when yoy agrees (or one side has no yoy point).
5. **FRED missing period or failed** — keep BLS.
6. **BLS failed, FRED ok** — accept FRED with `accepted_source=fred_fallback` and `retrieval_method=fredgraph.csv`.
7. **Both failed** — `source_failed`, dual error text, US remains blocked in the quality gate.

Provenance on accepted points includes `publisher=BLS`, full `derivation` (native id, score id, batch, FRED id, prior level/period, raw level, preliminary when BLS footnote `P`), `raw_sha256`, and ledger `acquisition` metadata.

## Runner protection

When a scored labor row is **due** (`latest_due_release` not null after the scheduled Employment Situation instant), it is admitted and retried before other series. Budget deferrals record `scheduler_events` (`skipped_admission` / `skipped_retry` with `protected_budget_exhausted`, `starved_by_critical_reservation`, or `budget_exhausted`) without relabeling started failures as `budget_deferred`.

## Tests

`tests/macro_ingestion/test_us_empsit_bls_primary.py` is fully hermetic (injected openers, tempfile observations, cleared employment caches). No live Market Watch cycle or network ingestion is required to verify this contract.
