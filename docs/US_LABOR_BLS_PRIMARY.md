# US Labor Employment Situation — BLS primary ingestion

## Native BLS series (confirmed on data.bls.gov, 2026-10-05)

| Catalog id | Score `series_id` (unchanged) | Native BLS id | Transform |
| --- | --- | --- | --- |
| `US.Labor.payrolls` | `PAYEMS` | `CES0000000001` | `mm_change_thousands_sa` (level difference) |
| `US.Labor.unemployment` | `UNRATE` | `LNS14000000` | `percent` (rate level) |
| `US.Labor.wages` | `CES0500000003` | `CES0500000003` | `mom_sa_pct` (prior-month ratio) |
| `US.Labor.participation` | `LNS11300000` | `LNS11300000` | `percent` (context, weight 0) |

Temperature scoring continues to filter observations by the score ids (`PAYEMS`, `UNRATE`, `CES0500000003`) using each row's calibration `source_transformation` (for example wages remain `yoy_pct` in `data/temperature_calibration.json`). Ingestion still emits only the catalog transform on each observation (`mom_sa_pct` for wages); this change does not emit `yoy_pct` or edit calibration. Weights and calibration JSON are unchanged.

## Source precedence (scored rows only)

1. **Primary** — one BLS Public Data API v2 POST batch `empsit` with exactly `CES0000000001`, `LNS14000000`, `CES0500000003`, and `LNS11300000` (separate from the existing 24-id CPS batch).
2. **Derive** — `_derive_latest_point` in `scripts/macro_ingestion/adapters/us.py` from official levels; only the latest derived point is emitted (prior month in `derivation`, not extra scored history).
3. **Validation** — independent FRED read via `_fetch_fred_series` using catalog fallback ids (`PAYEMS`, `UNRATE`, `CES0500000003`). FRED timeouts do not fail a good BLS point.
4. **Conflict** — same period and transform but `values_close` false → `source_failed` / `verification_conflict`, no observation, no averaging.
5. **FRED missing period or failed** — keep BLS.
6. **BLS failed, FRED ok** — accept FRED with `accepted_source=fred_fallback` and `retrieval_method=fredgraph.csv`.
7. **Both failed** — `source_failed`, dual error text, US remains blocked in the quality gate.

Provenance on accepted points includes `publisher=BLS`, full `derivation` (native id, score id, batch, FRED id, prior level/period, raw level, preliminary when BLS footnote `P`), `raw_sha256`, and ledger `acquisition` metadata.

## Runner protection

When a scored labor row is **due** (`latest_due_release` not null after the scheduled Employment Situation instant), it is admitted and retried before other series. Budget deferrals record `scheduler_events` (`skipped_admission` / `skipped_retry` with `protected_budget_exhausted`, `starved_by_critical_reservation`, or `budget_exhausted`) without relabeling started failures as `budget_deferred`.

## Tests

`tests/macro_ingestion/test_us_empsit_bls_primary.py` is fully hermetic (injected openers, tempfile observations, cleared employment caches). No live Market Watch cycle or network ingestion is required to verify this contract.
