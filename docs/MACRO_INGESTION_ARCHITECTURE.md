# Six-economy macro ingestion architecture

Status: **PARENT PLAN, before Composer implementation.**
Author: Grok 4.7 parent on branch `cursor/build-six-country-daily-macro-ingestion-system-dd5b`.
Baseline: `main` at `54673b377165a21911f6569665bbc17ff5cdb1a5` (PR #108, release-aware macro freshness).

This document is the shared contract. Composer workers implement it. They do not renegotiate weights, the 2026-09-21 calibration anchor, ACP clocks, or the Sep 23 review-001 packet.

## 1. What PR #108 already does (preserve)

`scripts/macro_freshness.py` and `scripts/macro_source_refresh.py` already:

- build a catalog from the 66 weighted components plus history context rows;
- treat `data/temperature_calibration.json` `as_of` as a structural anchor, not a freshness clock;
- keep `checked_at` separate from the observation period;
- live-read only `fredgraph.csv` and `statcan_wds_vectors`;
- leave other retrieval methods as explicit unsupported gaps;
- use a 12-business-day (monthly) / 30-business-day (quarterly) quiet window **only as a due-date backstop** off the ledger anchor;
- block new risk only for expressions that need the affected country;
- run from overnight `collect` when `refresh_macro` is on.

Do not delete that path and do not weaken `tests/test_macro_freshness.py`. The new runner adds local calendars for known releases. It does not relabel the 12-business-day backstop as a publisher calendar.

## 2. Graph and file ownership

| Stage | Model | Owns |
| --- | --- | --- |
| Parent plan and final review | Grok 4.7 (this provider call) | `docs/MACRO_INGESTION_*.md`, `data/macro_ingestion/baseline_catalog.json`, review notes |
| Shared platform | Composer 2.5, one task | `scripts/macro_ingestion/**` except `adapters/{us,ca,au,nz,ea,jp}.py`, shared tests under `tests/macro_ingestion/test_*.py` that are not `test_adapter_*.py` |
| Country worker | Composer 2.5, one task per economy, parallel | `scripts/macro_ingestion/adapters/{cc}.py`, `tests/macro_ingestion/test_adapter_{cc}.py`, `tests/macro_ingestion/fixtures/{cc}/**`, `data/macro_ingestion/fragments/{cc}.json` |
| Integration / QA | Composer 2.5, one task | `data/macro_ingestion/catalog.json`, `.github/workflows/macro-ingestion.yml`, coverage gate, post-freeze wiring that does not edit protected files |
| Bounded correction | Composer 2.5, only if the parent review finds defects | files the parent names |

Country workers must not edit `scripts/macro_freshness.py`, `scripts/macro_source_refresh.py`, `scripts/temperature_level.py`, `data/temperature_calibration.json`, `data/score_source_registry.json`, workflows, overnight books, or another country's files.

No worker may edit:

- `data/overnight/runs/overnight-20260923/reviews/review-001/**`
- `data/overnight/books/**`
- `data/pm/books/**`
- `.cursor/hooks/**`, `.cursor/agents/**`, `.cursor/commands/overnight-scheduled.md`
- `scripts/trader_room/**`, `scripts/overnight/constants.py` stage clocks, `scripts/funding/**`
- trader seat rosters, PM personas, funding economics, gauge anchors

ACP 02:05 stays an ACP clock. This repo must not add a second trader/PM run. A future clock change is a separate note to Kevin, not a code change.

## 3. Catalog

`data/macro_ingestion/baseline_catalog.json` is the parent inventory (120 rows):

- 66 scored components, weights copied from calibration and then frozen;
- 1 registry-unweighted row (`US.Inflation.mapped_bridge`);
- context rows for CPI/PPI/import/export prices, participation, GDP level or domestic-demand components, flash and sector surveys, and housing/credit/production feeds the repo already collects;
- explanatory aliases that must not be fetched as extra weighted components.

Country fragments overlay release dates, pinned series ids, and adapter results. They may fill a null `series_id` after a live official response proves it. They may not drop a baseline id, change a weight, or store a September 2026 flash PMI number that did not come from a primary S&P PDF saved in the fixture or raw tree.

Integrator writes `data/macro_ingestion/catalog.json` as baseline plus fragments. The runner refuses to start if any baseline id is missing or if any context/registry-unweighted weight is not 0.

## 4. Adapter contract

Each country module exposes:

```python
COUNTRY = "US"  # CA, AU, NZ, EA, JP

def fetch_series(spec: dict, *, opener, now) -> dict:
    """Return a JSON-ready payload. Never invent observations."""
```

Payload:

| Field | Meaning |
| --- | --- |
| `ok` | bool. False on transport failure, empty parse, or license wall |
| `status` | optional override: `license_gap`, `not_applicable`, `source_failed` |
| `points` | list of `{period, value, transformation, revision_status, prior, source_url}` |
| `vintage` | publisher vintage if known, else `latest_available` plus the raw hash |
| `checked_at` | set by the runner, not the adapter |
| `raw_sha256` | hash of the bytes actually retrieved |
| `error` | short string, no secrets |
| `http_status` | int or null |
| `challenge_page` | true when the body is a bot/paywall interstitial rather than the document |

Rules:

- Reuse `scripts/macro_source_refresh.py` FRED and StatCan parsers, `scripts/euro_area_macro_data.py`, `scripts/japan_macro_data.py`, `scripts/harvest_*_pmi.py`, and the housing modules before writing a new client.
- Adapters are acquisition-only. No model calls, no trading text.
- A failed primary fetch stays failed. There is no silent fallback number.
- Flash and final are different series ids. A final supersedes a flash only when the final primary document is stored. Until then the flash, if itself primary-sourced, is preliminary (`revision_status=flash`).
- `opener` is injectable so unit tests never hit the network. Live smoke tests call the real opener once per country and record the outcome, including failure.

## 5. Status vocabulary

The health ledger uses these statuses and no others:

| Status | When |
| --- | --- |
| `checked_success_no_new_release` | Source responded, latest period and value match the ledger, and the local calendar says the next print is not due |
| `new_observation` | A new period was parsed from the primary payload and appended |
| `revision_applied` | Same period, value changed beyond the existing `values_close` tolerance, and the source is a verified revision |
| `revision_pending` | Source says preliminary/flash or the change is inside a known revision window without a final document |
| `release_due_missing` | Local calendar instant has passed and the payload still lacks that period |
| `source_failed` | Transport, parse, or unexpected document |
| `license_gap` | Proprietary or challenge page. Not a successful check |
| `not_applicable` | No local equivalent, recorded with the page that was checked |
| `calendar_unparsed` | Fetch succeeded but the country fragment has no local dates, so "not due" cannot be claimed |
| `incomplete_country` | Adapter module missing. The country is visibly incomplete |

`calendar_unparsed` is an uncertainty flag on an otherwise successful fetch when dates are missing. It is not a 12-business-day guess. Scored series with `calendar_unparsed` do not clear a country risk gate.

## 6. Calendars, time zones, holidays

`scripts/macro_ingestion/calendar.py` evaluates release rules with `zoneinfo`. It must:

- accept `explicit_timestamp` rules (the Sep 23 flash is one);
- accept a list of publisher-local datetimes;
- roll weekends and country holidays forward in that country's zone, not the US holiday set;
- handle DST because the zone database does;
- treat a release as due only at or after that zoned instant.

Holiday sets for 2025–2027, owned by the shared platform: US federal (keep the PR #108 dates), Canada federal, Australia national, New Zealand national, ECB TARGET2, Japan national. State-level Australian holidays stay out unless a fragment names a state series.

Country fragments for scored series must include at least the next known official release instant, or an explicit `schedule_unparsed` reason with the schedule URL that was attempted. Absence of that field becomes `calendar_unparsed`.

## 7. Vintages, raw files, idempotency

Append observations only. Identity is `(series_id, period, transformation, raw_sha256)`. A rerun with the same hash does not duplicate the row and returns `checked_success_no_new_release` when nothing else changed.

Raw bytes go to `data/macro_ingestion/raw/{country}/{series_id}/{checked_at_compact}-{raw_sha256[:12]}` when the runner is in live mode. Tests use fixtures and do not require new committed binaries except the Sep 23 miss fixture, which is JSON describing the attempted URL and the non-PDF/challenge outcome if that is what the live smoke saw.

Observation `retrieved_at` / runner `checked_at` / calibration `as_of` are three fields. Tests must fail if they are collapsed.

Google Drive: `docs/MACRO_INGESTION_DRIVE_ARCHIVE_PLAN.md` lists the raw prefixes to archive and states that this change adds **no** Drive credential, token, or sync job. Notion stays operational metadata only; this change performs no Notion write.

No Supabase migration.

## 8. Scoring bridge

When the runner appends a verified observation for a **scored** series, it calls the existing temperature LEVEL functions. It writes the recomputed public score state only through the existing score writer if one already persists `data/temperature_scores.json`. If persisting scores would require changing calibration, skip the write, record `score_recompute=blocked_calibration_lock`, and leave prior scores in place.

Context rows never enter weights or coverage.

`US.Inflation.mapped_bridge` stays out of LEVEL, matching the calibration document.

## 9. Freeze boundary

Session date is America/New_York.

| NY time | `cutoff_class` | Writes |
| --- | --- | --- |
| before 01:50 | `pre_freeze` | ingestion ledger only. Overnight collect may keep using PR #108 refresh. This runner must not create or edit `evidence_snapshot.json` |
| 01:50 and after | `post_freeze` | `data/macro_ingestion/post_freeze/{session_date}.json` and the health ledger. Never `data/overnight/runs/*/reviews/*/evidence_snapshot.json`. Never `open-review`. Never a new ACP dispatch |

The post-freeze file records `freeze_cutoff=01:50 America/New_York`, `observed_at`, the series that changed, and the sentence that these points were **not** in the trusted trader packet. It is immutable once written for a given `run_id`; a later run appends a new file `post_freeze/{session_date}-{stamp}.json` and does not rewrite an earlier one.

GitHub workflow `.github/workflows/macro-ingestion.yml` (integrator) uses `timezone: America/New_York` and weekday crons that stay inside a 35-minute job:

| ET | Why |
| --- | --- |
| 00:20 | pre-freeze catch-up after the 00:07 collect, Asia leftovers |
| 04:10 | Eurozone flash 04:00 ET and other 03:30–04:15 ET prints, after 03:35 final delta |
| 09:50 | US 08:30 ET releases and 09:45 ET S&P flash US PMI |
| 10:10 | ISM 10:00 ET window |
| 21:00 | Australasia morning / Japan evening ET |

`workflow_dispatch` runs one country or `all` with `live` or `offline`. Offline is the default for CI. Live smoke is a separate job with `continue-on-error: false` for the ledger write of failures, and it must not fail the build solely because a foreign agency returned a challenge; it fails the build if a challenge is stored as a successful observation.

Retries: 3 attempts, exponential backoff capped at 8 seconds, per-source timeout 20 seconds. The job aborts remaining series for a country after 8 minutes so the workflow stays inside 35 minutes. Unrun series are `source_failed` with error `budget_deferred`, not `checked_success_no_new_release`.

Commit/rebase serialization: the workflow pushes only `data/macro_ingestion/**` and, when a scored observation was appended, the existing temperature history files for that country. It rebases onto `main` once before commit. It does not touch overnight review paths. If the push races, it retries the rebase twice and then fails visibly.

## 10. Sep 23 Eurozone flash fixture

Required test `tests/macro_ingestion/test_ea_flash_sep23.py` (EA worker creates the fixture, integrator wires the assertion if the EA file exists):

- Calendar rule is `2026-09-23T08:00:00Z`.
- At `2026-09-23T03:59:00-04:00` the release is not due.
- At `2026-09-23T04:00:00-04:00` it is due and `cutoff_class` is `post_freeze`.
- A fixture body that is HTML, a challenge, or empty yields `release_due_missing` or `source_failed`, writes no `2026-09` observation, and does not change the August composite value.
- The test's forbidden path is any September value supplied by the test author without a `%PDF` primary body.
- `evidence_snapshot.json` for review-001 keeps SHA-256 `41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b`.

## 11. Acceptance tests the shared platform must land

- Catalog load rejects a changed weight or a missing baseline id.
- Time zone cases: US EDT, EU CEST, Auckland, Sydney, Tokyo, and a US DST boundary date.
- Idempotent rerun.
- Revision changes value; identical value does not.
- Post-freeze writer refuses paths containing `reviews/` or `evidence_snapshot`.
- Missing adapter yields `incomplete_country` for that economy only.
- `temperature_calibration.json` bytes unchanged.
- Review-001 evidence hash unchanged.
- Existing `tests/test_macro_freshness.py` still passes.

## 12. Drive archive plan

See `docs/MACRO_INGESTION_DRIVE_ARCHIVE_PLAN.md`.

## 13. Known parent limits handed to workers

- Several context series ids are intentionally null until the country worker reads the official table. Those rows start `catalogued_adapter_pending`.
- S&P public PDFs often return HTTP 202 or a challenge. That outcome is a first-class gap, not a cue to use a news wire.
- ABS, Stats NZ, e-Stat, ESRI, METI, and BOJ adapters should wrap the collectors already in the repo. A full historical re-backfill is out of scope; daily checks append only new or revised points.
- PR #108 unsupported methods stay unsupported inside `macro_source_refresh.live_fetch` unless the new runner calls a country adapter. Do not silently mark ABS "checked" from the old refresh module.
