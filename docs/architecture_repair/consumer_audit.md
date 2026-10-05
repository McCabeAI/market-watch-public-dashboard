# N10 consumer audit

Conservative reference audit for consolidation candidates. **DELETE** only when production has zero callers outside the definition (tests may still import). Semantic parity lives in `scripts/run_state/`.

Audit method: repository-wide search for imports and call sites (Python sources and workflows). Counts are distinct referencing files, excluding the definition file unless noted.

## 1. Lossy merge overwrite (`_merge_ingestion_rows`)

| Item | Caller files | Decision | Rationale |
| --- | ---: | --- | --- |
| `_merge_ingestion_rows` | `scripts/market_watch_launch/ingest.py` (definition), `scripts/run_state/replay.py`, `tests/run_state/test_fixtures_and_incident.py` | **KEEP** | Sole merge writer; production ingest and replay depend on it. |

**Repair status:** Already repaired, no second writer. For an existing primary row, `budget_deferred` secondary rows no longer replace a started primary: the branch at `sec_error == "budget_deferred" and _primary_has_started_attempt(merged)` records `skipped_retry` / `skipped_admission` and keeps the primary `error` (e.g. timed out) in `attempt_history`. Assignment `by_id[sid] = secondary_row` occurs only when `sid not in by_id`.

No redundant merge function exists to delete.

## 2. Duplicate temperature score writers at freeze

| Item | Caller files | Decision | Rationale |
| --- | ---: | --- | --- |
| Lineage staging (`stage_verified_lineage` / `temperature_scores.json` under launch lineage) | `scripts/market_watch_launch/ingest.py`, `lineage.py`, `finalize.py`, `acquire.py`, tests | **KEEP** | Canonical score document writer for launches. |
| `apply_lineage_to_macro_hard` (`extra["temperature_scores"]`) | `scripts/market_watch_launch/freeze.py` (3 call paths), `acquire.py` | **KEEP** | Still attaches staged scores to `macro_hard.extra` for evidence snapshots. |
| `bind_scores` (`scripts/run_state/scores.py`) | `tests/run_state/test_policy_scores.py`, run_state score binding path | **KEEP** | Canonical bind path; tests import it. |
| `reject_unequal_score_copies` / freeze `_verify_score_payload` | `freeze.py`, `replay.py`, `tests/run_state/test_oct5_replay.py` | **KEEP** | Guards against unequal nested copies; does not add a second writer. |
| `data/temperature_scores.json` writers (`temperature_level`, `macro_source_refresh`, `apply_temperature_scores.py`) | Pages build, trader room, macro refresh, many docs | **KEEP** | Outside launch freeze duplicate; still consumed. |

**Decision:** **DELETE nothing.** No standalone “second freeze writer” function with zero callers was found. Duplicate-hash incident is mitigated by conflict detection at freeze/replay, not by removing `apply_lineage_to_macro_hard` (still imported).

## 3. Implicit reacquisition in `publish_offline`

| Item | Caller files | Decision | Rationale |
| --- | ---: | --- | --- |
| `scripts/run_state/publication.py` | `tests/run_state/test_lifecycle.py` | **KEEP** | Offline publication entry point. |

**Imports:** Does not import `run_ingestion`, `temperature_level`, or an `opener` module. Forbidden bundle keys (`opener`, `fetch`, `rescore`) are rejected by name only.

**Decision:** Already clean; nothing to delete.

## 4. Dated patch directories (`patch_v7`, `patch_v8`, `patch_v9`, `patch_v12`, `patch_v13`, `patch_v14`, …)

| Item | Caller files | Decision | Rationale |
| --- | ---: | --- | --- |
| `patch_v*` trees | `.github/workflows/deploy-pages.yml` (path filters and build steps: `patch_v7`, `patch_v8`, `patch_v9`, `patch_v12`, `patch_v13`, `patch_v14`), docs, tests | **KEEP** | Still the GitHub Pages base reconstruction. |

**Decision:** **KEEP** all patch directories referenced by deploy workflow.

## 5. `calendar.release_due` (false on empty dates)

| Item | Caller files | Decision | Rationale |
| --- | ---: | --- | --- |
| `scripts/macro_ingestion/calendar.py` `release_due` | `ingest.py`, `tests/macro_ingestion/test_calendar.py`, adapter tests, … | **KEEP** | Legacy bool; tests assert false-on-empty-dates behavior. |
| `scripts/macro_freshness.py` `release_due` | `macro_source_refresh.py`, `tests/test_macro_freshness.py` | **KEEP** | Separate freshness helper; still called. |
| `build_expectation` (`scripts/run_state/expectations.py`) | `compiler` tests, `replay.py`, `run_state` package | **KEEP** | Canonical tri-state: `calendar_status == "unknown"` ⇒ `scheduled_release_occurred_by_cutoff` is `None`. |

**Decision:** **KEEP** `calendar.release_due`. Changing empty-dates to tri-state in the legacy bool would break `tests/macro_ingestion/test_calendar.py` and downstream ingest row flags that still read `release_due` on rows.

## N10 production deletions

**None.** Every candidate path or function above still has production or test consumers.
