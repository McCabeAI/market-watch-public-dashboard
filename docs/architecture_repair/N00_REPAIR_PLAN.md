# N00 Repair Plan — canonical release-aware run state

Status: **FROZEN CONTRACT.** Later nodes implement this document. They do not renegotiate calibration, trader/PM personalities, packet hash algorithms, book bindings, raw receipt bytes, or country isolation.

- Baseline: `main` `07d6406f2a360c57c52d7be034f3f2530daae7e9`
- Branch: `cursor/market-watch-canonical-data-state-architecture-repair-f998`
- Parent: Grok 4.7 (this provider execution, N00)
- Implementers: Composer 2.5 only
- Reviewers: fresh Grok 4.7 at N11, N14, N17
- Allowlist: `grok-4.7`, `composer-2.5`
- Ceilings: 38 total model invocations, 5 grok-4.7 including the parent, one reserved grok re-review
- Ledger: `docs/architecture_repair/call_ledger.json`

This is an offline architecture migration. No live acquisition, Trader Room, PM models, Pages deploy, workflow_dispatch, or merge.

## 1. Incident truth (validated against the tree)

Launch `mwl-20261005T100821Z-3f9807cb` (session 2026-10-05), freeze `as_of` `2026-10-05T06:08:21.051325-04:00`, `legacy_0150_used: false`.

Surviving ingest rows after `_merge_ingestion_rows`:

| series | status | error | attempts | release_due | due_period |
| --- | --- | --- | --- | --- | --- |
| US.Labor.payrolls / unemployment / wages | source_failed | budget_deferred | 1 | true | 2026-09 |
| US.Activity.gdp_domestic_demand, US.Consumer.confidence, US.Consumer.income, US.Consumer.retail, US.Consumer.spending, US.Inflation.core_pce | source_failed | The read operation timed out | 3 | false | — |

Approved finding, not contradicted by the surviving rows: the three scored labor series were each started once and timed out. The retry pass admitted the six lower series first (catalog identity order). Labor retries were not started. Merge replaced the primary timeout row with the retry `budget_deferred` row, so the timeout is no longer in the row. `attempts: 1` is the leftover counter, not a reconstructable attempt record.

Quality gate outcome PASS, `blocked_expressions: ["macro:US"]`, trade-eligible CA, AU, NZ, EA, JP. That country split is correct and must be preserved.

`trade_permissions.source_health` carries eight US series (`blocks_new_risk: false`, including the six timeout series) while US `eligible` is false. `room_data_caveat` therefore emits "no new release was due" for US and drops US from the block sentence (`real_blocks` subtracts carried countries). Macro notes say both "restrictions: US" and "carry-forward (not-due): US".

Evidence snapshot `data/overnight/runs/overnight-20261005/reviews/review-001/evidence_snapshot.json` holds two unequal temperature-score documents (canonical-JSON prefixes `6b0b1ceb9db8e408` at top level / `macro_hard.temperature_scores`, and `d5acf744e9285f96` at `macro_hard.extra.temperature_scores`). Lineage file SHA-256 is `304760ad8c1f57ace7502ed5464f32678ee008daf0890974c09b70bc5940d1d6`. Gate, freeze, trader evidence, and public evidence must bind one hash.

`scripts/macro_ingestion/calendar.py` `release_due()` returns False when `country_local_schedule_required` has empty `dates`. That is a silent unknown-to-not-due conversion. The legacy bool stays for existing calendar tests. Canonical expectations use a tri-state and must not call that bool as proof of "not due".

Catalog rows for the labor series currently have empty `release_rule.dates`, but the Oct 5 launch rows already carry `due_period: 2026-09` and `release_due: true`. The offline replay pins the expectation the run actually used: Employment Situation `2026-10-02T08:30:00-04:00`, reference period `2026-09`. That pin is fixture/overlay input to the expectation builder, not a scheduler special case.

Oct 2 recovery launch id `mwl-20261002T094056Z-1d0ebea5` stays on its canonical path. New tests must not rewrite it. Default tests read immutable extracts under `tests/fixtures/run_state/`.

## 2. Ownership and state algebra

One canonical writer: `scripts/run_state/`. During migration it projects shadow state beside legacy rows. Consumers cut over in N06–N08. N10 deletes a path only after a reference audit shows no remaining reader.

Deterministic code owns whether a release occurred, whether a fetch started, which vintage is selected, freshness class, and carry reason. Models are not invoked by this migration.

### Objects

All documents use canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Identity hashes are SHA-256 hex of that UTF-8 text. Validators reject unknown enum values. They do not coerce them.

**SeriesDefinition** (`series-definition/1`). Compiled from the catalog. `definition_id = "sd_" + sha256(body without definition_id)[:20]`.

- `publisher` is the catalog `publisher`. `provider` is `distributor` or the retrieval method. They are different fields. BLS is not FRED.
- `source_authority` is `primary` unless the catalog already names an equivalent fallback. The compiler does not invent fallbacks.
- `fallback_series_ids` lists only declared equivalents. A fallback is not a silent value substitution.
- `calendar_status` is `known` only when `schedule_parseable` is true and at least one date exists. Empty dates are `unknown`, never `not_due`.
- `trade_critical` is true exactly when `role == "scored"` and `weight > 0`. This is the expression-dependency rule for `macro:{country}`, not a list of series-name exceptions.
- `units`, `transform`, `policy_version` (`quality-policy/1`) are stored on the definition.
- Weights are copied. The compiler refuses a weight that differs from the catalog row.

**ReleaseExpectation** (`release-expectation/1`). One per `(run_id, series_id)`.

- `calendar_status: known | unknown`
- `scheduled_release_occurred_by_cutoff: true | false | null`
- `expectation_satisfied_by_verified_evidence: bool`
- These two facts are never stored in one `release_due` field.
- Invariant: `unknown` iff `scheduled_release_occurred_by_cutoff is null`. `known` iff the flag is boolean. A validator raises otherwise. No silent null-to-false.
- `known` + instant <= cutoff => true, and `expected_period` is the period bound to that slot.
- `known` + instant > cutoff => false.
- Satisfaction is true only when a verified ObservationVersion covers `expected_period` with matching units and transform.

**AcquisitionAttempt** (`acquisition-attempt/1`). Append-only. Exists only if work was queued and started.

Required clocks: `queued_at`, `started_at`, `ended_at`, `elapsed_ms`, `deadline_at`. `kind` is `primary` or `retry`. `ordinal` starts at 1 and never reuses. `result` is one of `success`, `timeout`, `http_404`, `http_429`, `http_5xx`, `schema_drift`, `transport_error`, `license_gap`, `empty_parse`. A retry points at `supersedes_attempt_id` and does not delete the earlier attempt.

**SchedulerEvent** (`scheduler-event/1`). Not an attempt.

- `kind`: `skipped_admission` | `skipped_retry`
- `skipped_retry.related_attempt_id` is the attempt that was not retried.
- `budget_deferred` on a row that never started is a `skipped_admission` or `skipped_retry`, never an AcquisitionAttempt with a fabricated start.

**ObservationVersion** (`observation-version/1`). Immutable.

Identity is `(series_id, period, transformation, raw_sha256)`. The same identity with a different value or units is a hard conflict. The same period and value with a different `raw_sha256` is a new version; the prior version remains. `publication_time` may be null only with `publication_time_uncertainty: unknown`. `exact` requires a timestamp. `date_only` requires a date and must not be treated as an exact instant. Flash and final are both retained. Selection may prefer `final` for a period; it does not erase `flash`.

**SeriesRunState** (`series-run-state/1`). One per `(run_id, series_id)`.

`state_id = "{run_id}:{series_id}"`. Holds definition id, expectation id, ordered attempt ids, scheduler event ids, `selected_observation_id`, `score_input_observation_id`, `prior_observation_id`, `carry_forward_reason`, `policy_version`, `state_sha256`.

`score_input_observation_id` changes only when a verified observation version is selected. A fetch failure, a skip, or a freshness inference must not change it.

Carry-forward reason, mutually exclusive:

| reason | when |
| --- | --- |
| `null` | known calendar, due release, satisfied by the selected verified observation |
| `overdue_unverified` | known calendar, scheduled release occurred by cutoff, not satisfied |
| `old_but_current` | known calendar, release had not occurred by cutoff, latest verified vintage still current (check succeeded or no failed check) |
| `old_after_failed_check` | known not-due, a started attempt failed, prior verified observation retained |
| `unknown_calendar` | calendar_status unknown. Not a not-due claim |

**EvidenceItem** (`evidence-item/1`). News and research.

`provenance.source_name`, `provenance.acquired_at`, and `provenance.method` are required. `url` may be absent or null. `timestamp_uncertainty` is required (`exact`, `date_only`, `unknown`). `disposition` is `accepted`, `rendered`, or `excluded`. Excluded items require `exclusion_reason`. Accepted + excluded = discovered. Rendered <= accepted. A reconciliation that does not balance raises.

**RunManifest** (`run-manifest/1`).

Binds `cutoff_at`, `freeze_cutoff`, `policy_version`, `state_tree_sha256`, the single `score_state_sha256`, `trader_packet_id`, `public_packet_id`, coverage counts (`due`, `satisfied`, `attempted_failed`, `never_attempted`, `unknown_calendar`), budget (`protected_slots`, `consumed_slots`, `remaining_slots`), `first_divergence_stage`, `publication_mode: offline`.

`gate_bound_to` repeats cutoff, freeze cutoff, and policy version. Freeze refuses to seal when any of those differ from the gate receipt or when the score hash differs.

## 3. Scheduler rule

Tiers, admitted in this order only:

1. `due_trade_critical` — known calendar, scheduled release occurred, `trade_critical`
2. `due_context` — known, occurred, not trade-critical
3. `unknown_calendar`
4. `non_due_check` — known, release had not occurred

Within a tier, order is `(country, series_id)` ascending. Catalog identity is not the admission key.

Protected budget: every `due_trade_critical` series claims a primary slot before any lower tier is admitted. If the slot or time budget cannot cover them, the remainder are `skipped_admission` and no lower tier is admitted. A due trade-critical scored release cannot be starved by GDP, confidence, income, retail, spending, or core PCE.

Retries use the same tier order on the residual budget. A retry that is not admitted is `skipped_retry` pointing at the primary attempt. It is not a second AcquisitionAttempt and it does not overwrite the primary result.

The Oct 5 replay records historical truth (labor primary timeout, labor retry not admitted). The scheduler tests prove a future run with the same budget admits the three labor retries before the six lower series.

## 4. Quality, scores, prose, publication

Policy evaluator `quality-policy/1` reads SeriesRunState only (after cutover). Expression map: `macro:{country}` depends on that country's `trade_critical` series. A country is blocked when any dependency is `overdue_unverified` or when a due trade-critical series has no satisfying observation. `unknown_calendar` does not count as not-due and does not by itself invent a due release; prose must say the calendar is unknown. Other countries stay eligible. Cross-country expressions block only when they declare both dependencies. No expression is inferred from prose.

Scores: `scripts/temperature_level.py` `component_level` / `score_component` stay the arithmetic. Binding passes the same observation history the legacy engine would see. Identical observations must produce identical component levels. Failure and skip do not call the scorer with a new value.

`assert_single_score_payload` rejects a packet that contains two temperature-score documents with different canonical hashes. Gate, freeze, trader packet, and public packet store the same `score_state_sha256` and the same state ids.

Factual prose is a pure function of canonical state:

- Blocked country: "New risk stays restricted in {codes} because a due release could not be verified."
- Not-due carry, and only for countries that are not blocked: "Latest verified vintages for {codes} are carried forward; no new release was due."
- Unknown calendar: "The release calendar for {codes} is unknown; a not-due claim is not allowed."
- `assert_prose_consistent` raises when the text says "no new release was due" for a country that has `scheduled_release_occurred_by_cutoff` true or null, or when the sentence is unscoped and any such series exists.

`room_data_caveat` must stop subtracting blocked countries from the block sentence. The Oct 5 shape (US carried on not-due series AND US blocked on labor) must produce both a not-due clause that does not cover US and a due-release clause that does.

Publication reads an approved candidate bundle plus manifest. It has no opener, no catalog fetch, and no score recompute. Deploy acknowledgement is idempotent on `(launch_id, artifact_sha256)` and rejects a mismatched launch id. PR #166 optional URL behavior stays: a valid research item without a URL is publishable.

## 5. Lifecycle and report

Checkpoints, in order: `series_plan`, `admission`, `attempts`, `observations`, `scores`, `gate`, `freeze`, `candidate_bundle`, `publication`, `deploy_ack`.

Each checkpoint stores `input_sha256`, `output_sha256`, and `generation`. Resume with the same input returns the existing output and does not append another observation, score promotion, book, or publication. Compare-and-swap conflict raises. A timeout envelope is recorded per checkpoint and does not roll back a prior committed checkpoint. Duplicate deploy receipts are no-ops.

`run-report.json` and `run-report.html` are rendered from the same manifest structure. One HTML screen shows due / satisfied / attempted-failed / never-attempted / unknown-calendar, budget, eligibility and expression dependencies, carry-forward reasons, score hash, trader packet id, public packet id, and `first_divergence_stage`.

## 6. Migration gates

| phase | node | gate |
| --- | --- | --- |
| 0 | N01 | Immutable Oct 5 and Oct 2 fixtures exist outside canonical mutable paths. Tests inject clocks. No network. |
| 1 | N02 | Oct 5 replay packet is internally consistent: labor primary timeout preserved, retry not an attempt, US blocked, other countries eligible, one score hash, gate cutoff equals freeze cutoff, prose does not claim no release was due. Optional URL still accepted. |
| 2 | N02 | Shadow objects may be absent. Legacy readers still run. |
| 3 | N03–N05 | Canonical objects validate. Compiler is deterministic. Unknown stays unknown. Observations are immutable. |
| 4 | N04 | Critical-first tests pass, including all-critical outage, 404/429/5xx/timeout/schema. |
| 5 | N06 | Gate, score binding, and freeze consume canonical state. Calibration bytes and `component_level` outputs unchanged for identical inputs. |
| 6 | N07–N08 | Public contract and offline publication. Checkpoint kill/restart does not duplicate state. |
| 7 | N09–N10 | Report exists. Delete only paths the consumer audit marks unused. |

Do not delete `patch_v*`, calibration, trader-room personalities, book ledgers, raw receipts, or the Pages base reconstruction. They still have consumers. N10 must write `docs/architecture_repair/consumer_audit.md` and a rollback note listing what was removed and what was kept.

Legacy `release_due()` bool is not redefined in N02. Canonical code adds `calendar_resolution()` and stops treating the bool as not-due when status is unknown. N10 may remove consumer reliance on the bool for gate and prose after parity tests pass. `tests/macro_ingestion/test_calendar.py` and `tests/test_macro_freshness.py` must stay green.

`_merge_ingestion_rows` becomes append-only in N02: the primary attempt is kept in `attempt_history`, and a retry row with `error == budget_deferred` does not replace a started primary result. N10 removes any remaining writer that still overwrites.

## 7. Node DAG, file ownership, dependencies

Serial first: N00 (this file). Then:

| node | model | depends | owns |
| --- | --- | --- | --- |
| N01 | composer-2.5 | N00 | `tests/fixtures/run_state/**`, `tests/run_state/test_fixtures_and_incident.py`, clock helper `tests/run_state/clock.py` |
| N03 | composer-2.5 | N00 | `scripts/run_state/schema.py`, `compiler.py`, `expectations.py`, `__init__.py`, `tests/run_state/test_schema.py`, `test_compiler.py` |
| N02 | composer-2.5 | N00, N01, and the locked N03 interface | `scripts/market_watch_launch/ingest.py` merge, `scripts/overnight/public_prose.py` caveat, `scripts/market_watch_launch/quality_gate.py` cutoff echo, `scripts/market_watch_launch/freeze.py` score-conflict and cutoff bind, `scripts/run_state/replay.py`, `tests/run_state/test_oct5_replay.py` |
| N04 | composer-2.5 | N01, N03 | `scripts/run_state/scheduler.py`, `tests/run_state/test_scheduler.py` |
| N05 | composer-2.5 | N01, N03 | `scripts/run_state/observations.py`, `tests/run_state/test_observations.py` |
| N06 | composer-2.5 | N02, N04, N05 | `scripts/run_state/policy.py`, `scores.py`, `state.py`, consumer cutover in quality gate and freeze, `tests/run_state/test_policy_scores.py` |
| N07 | composer-2.5 | N02, N03, N06 | `scripts/run_state/evidence.py`, `prose.py`, publication prose hook, `tests/run_state/test_evidence_prose.py` |
| N08 | composer-2.5 | N03, N06 | `scripts/run_state/lifecycle.py`, `publication.py`, `tests/run_state/test_lifecycle.py` |
| N09 | composer-2.5 | schema lock; finish after N04–N08 | `scripts/run_state/report.py`, `tests/run_state/test_report.py` |
| N10 | composer-2.5 | N07–N09 | consumer audit, deletion of only proven-redundant writers, `tests/run_state/test_no_redundant_writers.py` |
| N11 | fresh grok-4.7 | N01–N10 | findings only, `docs/architecture_repair/N11_REVIEW.md` |
| N12 | composer-2.5 | N11 | only N11 findings |
| N13 | composer-2.5 | N12 | `tests/run_state/test_e2e_matrix.py` offline |
| N14 | fresh grok-4.7 | N13 | findings only, `docs/architecture_repair/N14_REVIEW.md` |
| N15 | composer-2.5 | N14 if findings | bounded fixes only |
| N16 | composer-2.5 | exact tree | one deterministic E2E, `docs/architecture_repair/N16_E2E.md` |
| N17 | fresh grok-4.7 | exact N16 tree | `docs/architecture_repair/N17_APPROVAL.md` PASS or REJECT bound to SHA |
| N18 | composer-2.5 | N17 PASS | no code edits except ledger/PR text; commit, push, one PR |

Deviation recorded in the ledger: N02 starts after the N03 interface is on disk so containment writes the locked shadow types. N01 still runs in parallel with N03.

N02 must not edit `scripts/run_state/policy.py`, `evidence.py`, or `publication.py`. N06 must not edit `public_prose.py` except to call the already-frozen caveat helper if N02 left a hook. N07 owns prose projection. Overlap on `quality_gate.py` is serial: N02 adds cutoff echo and conflict detection; N06 switches the decision source to SeriesRunState.

## 8. Invariants (every defect has an owner)

| defect | invariant | owner |
| --- | --- | --- |
| Lossy merge drops primary timeout | Attempt log is append-only; a skip does not replace a started result | N02 merge, N05/N06 state |
| Retry of lower series starves labor | Due trade-critical series take protected slots first | N04 |
| budget_deferred stored as the only labor truth | Skip is a SchedulerEvent; attempts require start/end | N02, N04 |
| `release_due()` false on empty dates | Expectation flag is null when calendar is unknown | N03 |
| Mixed carry and block prose | Not-due sentence cannot name a blocked country; block sentence still fires | N02, N07 |
| Two score documents | One `score_state_sha256` or hard conflict | N02 detect, N06 single writer |
| Gate/freeze clocks can diverge | Both store the same `cutoff_at` and policy version | N02, N06, N08 |
| Publish could refetch | `publish_offline` has no opener and does not call the scorer | N08 |
| Oct 2 recovery drifts if tests touch canonical launches | Fixtures are copies/extracts; recovery hash test stays | N01 |
| Optional URL regression | EvidenceItem URL optional; existing accepted-news test stays | N07 |

## 9. Fixtures

`tests/fixtures/run_state/oct5/incident.json` is a reduced extract, committed, and the only input to the Oct 5 replay. Do not read `data/market_watch_launches/**` or `data/overnight/runs/**` from default tests.

Required contents:

- `run_id`: `mwl-20261005T100821Z-3f9807cb`
- `cutoff_at` / `freeze_cutoff`: `2026-10-05T06:08:21.051325-04:00`
- Employment expectation for the three labor series
- Reconstructed primary attempts: result `timeout`, ordinal 1, started
- Labor `skipped_retry` events, not attempts
- The six series as started attempts that ended in timeout (historical retry admission)
- Surviving lossy rows (budget_deferred, attempts 1) as `defect_rows` so the reproduction can show what the old merge did
- Gate expectation: US blocked, others eligible
- Two unequal miniature score documents labeled `score_copy_a` and `score_copy_b` (synthetic stand-ins for the two hashes; do not copy the 34KB score file)
- `lineage_score_sha256`: the real file hash above
- Injected clock equal to the cutoff

`tests/fixtures/run_state/oct2/recovery_identity.json` records launch id `mwl-20261002T094056Z-1d0ebea5`, run id `overnight-20261002`, and the SHA-256 of the canonical launch file at N01 time. The test asserts that hash still matches. It does not rewrite the file.

Network: tests install a socket guard that raises. No `workflow_dispatch`.

## 10. Validation matrix

Cover with hermetic tests, injected clocks, no network:

successful baseline; due verified; due failed; due not attempted; non-due checked; bounded carry-forward; stale/unknown calendar; license/unsupported; 404; 429; 5xx; timeout; schema drift; wrong period; wrong unit; wrong transform; multi-period revision; flash and final both retained; partial-country isolation; mixed carry/block prose; URL-less news; empty discovery; mismatched duplicate scores; post-cutoff observation rejected; concurrent promotion CAS conflict; interrupt at every checkpoint; deploy before ack; duplicate receipts.

`tests/test_temperature_level.py` and calibration file bytes stay unchanged. `tests/test_mw_launch_pages_recovery.py` stays unchanged in behavior.

## 11. First milestone

N02's `replay_october5(fixture)` returns one packet:

- labor attempt history contains a primary timeout
- labor retry is a skip, not an attempt
- expectation period `2026-09`, occurred by cutoff true
- `macro:US` blocked, other five countries eligible
- one score hash
- gate cutoff equals freeze cutoff equals the fixture cutoff
- public caveat does not contain "no new release was due" as a claim covering US
- public caveat does say a due US release could not be verified

## 12. Review loops

N11 findings only. N12 fixes those findings or returns an unresolved policy choice to this document; it does not waive a critical/high integrity finding. N13 runs the matrix. N14 adversarial findings only. N15 only if N14 has findings. Any code edit after N17 invalidates the PASS. N18 verifies the tree hash and opens one unmerged PR.

Adversarial probes for N14: wrong-period success, stale and unknown calendar, carry across transforms, simultaneous revisions, all-critical outage, malformed news, hash mismatch, out-of-order receipts, clock skew.

## 13. Execution status (updated through N17)

Nodes N01–N16 completed on this branch. N11 and N14 returned FAIL; N12 and N15 closed those findings. N10 deleted nothing. Parent Grok 4.7 performed N11, N14, and N17 in-process because the repository hook rejected a fresh `grok-4.7` subagent (hook allowlist was composer-2.5, grok-4.6, grok-4.5). Those reviews are not extra provider invocations, and grok-4.6 was not used. Actual counts are in `call_ledger.json`. The Oct 2 Pages recovery suite fails the same way on clean `07d6406`; it was not patched and the canonical launch file was not rewritten.
