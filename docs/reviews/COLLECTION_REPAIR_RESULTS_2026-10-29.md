# Collection repair integration results — 2026-10-29

Integrator: Composer 2.5 on branch `cursor/reliable-usable-market-watch-collection-grok-4-7-composer-graph-e865` at `a6d63bdc` (pre-run). No code fixes were required; acquisition and acceptance commits fit the targeted suite as-is.

## Targeted tests

```text
PYTHONPATH=. python3 -m unittest \
  tests.macro_ingestion.test_runner \
  tests.macro_ingestion.test_calendar \
  tests.macro_ingestion.test_integrity \
  tests.macro_ingestion.test_adapter_us \
  tests.macro_ingestion.test_adapter_nz \
  tests.macro_ingestion.test_adapter_ca \
  tests.macro_ingestion.test_adapter_au \
  tests.macro_ingestion.test_cli_data_only_catch_up \
  tests.macro_ingestion.test_launch_ingest_acceptance \
  tests.test_source_health_and_cross_assets
```

| Result | Count |
| --- | ---: |
| Passed | 95 |
| Failed | 0 |
| Errors | 0 |

## Isolated live collection

Command (exit code **0**; ~4.8 minutes):

```text
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli \
  --data-only-catch-up --mode live \
  --output-dir /tmp/mw-repair-live \
  --country US,CA,NZ,AU \
  --run-id repair-20261029
```

Output stays under `/tmp/mw-repair-live` (not committed): observations, health, raw pulls, and a copy of research builder JSON.

### Research builders vs live observations

`run_data_only_catch_up` calls `render_dashboard_sections(root)` with the **repository root** (`scripts/macro_ingestion/cli.py`), then writes `research_builders/country_detail_sections.json` under `--output-dir`. That HTML snapshot is **not** rebuilt from `/tmp/mw-repair-live/observations`. For this review, the live artifact inspected was an observation in the isolated store, e.g. **`UNRATE` period `2026-09`, value `4.2`** in `/tmp/mw-repair-live/observations/us.json`.

## Health ledger (`/tmp/mw-repair-live/health/latest.json`)

- **Row count:** 176 — matches catalog series for US+CA+NZ+AU (93+29+37+17) and CLI `ingestion.row_count`, not a retry-only subset.
- **`run_id`:** `repair-20261029`

### Status totals (all countries in run)

| Status | Count |
| --- | ---: |
| new_observation | 130 |
| source_failed | 29 |
| license_gap | 10 |
| not_applicable | 5 |
| checked_unchanged | 1 |
| calendar_unparsed | 1 |

### By country (status mix)

| Country | new_observation | source_failed | license_gap | not_applicable | checked_unchanged | calendar_unparsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| US | 70 | 17 | 6 | 0 | 0 | 0 |
| CA | 23 | 2 | 2 | 2 | 0 | 0 |
| NZ | 11 | 4 | 0 | 1 | 1 | 0 |
| AU | 26 | 6 | 2 | 2 | 0 | 1 |

**Freshness note:** Only **one** series (`NZ.Labor.participation`) is `checked_unchanged` with `publication_state: not_yet_due`. The 130 `new_observation` rows include first-time seeding into an empty isolated store and are not treated as proof of publisher updates alone.

## Spot checks from files

### US labor vs FRED deferral

Anchor labor series (`US.Labor.unemployment`, `payrolls`, `initial_claims`, `continuing_claims`, `participation`, etc.) finished **`new_observation`** with **no `attempt_history`**. Where recorded, BLS primary succeeded and FRED validation was **`skipped`** (not a failed non-`budget_deferred` attempt). Ten other US series show **`host_deferred`** on the FRED host (PCE, CPI core, PPI, FHFA, etc.); none of the unemployment/payrolls/claims/participation rows show a non-`budget_deferred` attempt tied to those FRED failures.

### NZ periods (not run-date relabel)

From `/tmp/mw-repair-live/observations/nz.json` and matching health rows:

| Series | Health status | Stored period |
| --- | --- | --- |
| `NZ.Inflation.headline` | new_observation | `2026-Q2` (`CPIQ.SE9A`) |
| `NZ.Activity.gdp_domestic_demand` | new_observation | `2026-Q2` (`SNEQ.SG01RSC01B01PC`) |
| `NZ.Consumer.retail` | new_observation | `2026-Q2` (`SF91KS`) |
| `NZ.Labor.wages` | new_observation | `2026-Q2` (`LCIQ.SD53Z9`) |

Run date was 2026-10-29; periods remain June-quarter vintage, not relabeled to the run date.

### CA IPPI / RMPI

| Catalog id | Health status | Observation vector | Period | Value |
| --- | --- | --- | --- | ---: |
| `CA.Inflation.ippi` | new_observation | `v1230995983` | `2026-09` | 150.7 |
| `CA.Inflation.rmpi` | new_observation | `v1230998135` | `2026-09` | 182.7 |

### AU domestic final demand

`AU.Activity.domestic_final_demand`: **`new_observation`**, `observation_vintage: latest_available`, no error in `latest.json`.

## Residual external / catalog gaps (this run)

Still **`source_failed`**, **`license_gap`**, or **unpinned** where noted:

- **US FRED-only / host budget:** BEA-linked and FRED-hosted series deferred after host failures (`host_deferred`): e.g. `US.Activity.gdp_level`, `US.Inflation.core_pce`, `US.Inflation.pce_headline`, `US.Inflation.cpi_core`, `US.Inflation.ppi_final_demand`, trade prices, `US.Housing.fhfa_purchase_only`, `US.Housing.housing_starts`, `US.Credit.mortgage_30y`. **`US.Inflation.mapped_bridge`:** transform not wired. **Census / UMCSENT path:** `US.Consumer.retail`, `income`, `spending`, `confidence`, and `US.Activity.gdp_domestic_demand` hit **read timeouts** (no alternate parse this run). **UMCSENT** is not named in health rows; consumer confidence timed out on fetch.
- **US license:** ADP, Challenger, Conference Board labor/consumer series — `proprietary_blocked`. **Flash PMI** — PDF not parsed.
- **CA unpinned:** `CA.Inflation.import_export_price_indexes`, `CA.Labor.participation` — vector id unpinned in catalog fragment. **License:** BoC CSCE confidence, CREA existing home sales.
- **NZ:** `NZ.Consumer.income` — `experimental_income_unparsed`; **PPI / import / export price** — HTTP 404 (URLs still unpinned). **NZ policy rates** — no scored catalog row in this four-country slice; vendor fallback remains out of scope here.
- **AU:** **Westpac confidence** — `westpac_unverified_no_primary_adapter`; **Seek job ads** — missing period on primary page; **JSA REOS / IVI** — transport timeouts; **PMI listings** — `pmi_listing_challenge` license gaps; **`AU.Housing.dwelling_values_and_approvals`** — `calendar_unparsed` only.
- **EA / JP:** not requested in `--country`; **0** health rows.

## Conclusion

Targeted tests and one isolated live catch-up completed successfully. Health row count aligns with the full four-country catalog. Core US labor, NZ headline macro periods, CA IPPI/RMPI pins, and AU domestic final demand behaved as intended in the isolated store. Documented gaps remain external, unpinned, or license-bound rather than integration regressions on this branch tip.
