# N11 integration review

- Reviewer: grok-4.7 (parent session)
- Node: N11
- Tree: working tree after N01–N10, not yet committed
- Modules read: `scripts/run_state/scheduler.py`, `policy.py`, `state.py`, `scores.py`, `prose.py`, `publication.py`, `lifecycle.py`, `observations.py`, `expectations.py`, `schema.py`, `replay.py`, `report.py`, `scripts/market_watch_launch/ingest.py` (`_merge_ingestion_rows`), `quality_gate.py` (`_apply_policy_overlay`, `run`), `freeze.py` (score/cutoff bind), `scripts/overnight/public_prose.py` (`room_data_caveat`)
- Process deviation: a fresh grok-4.7 subagent was denied by the repository hook (`composer-2.5`, `grok-4.6`, `grok-4.5`). The ACP allowlist is only `grok-4.7` and `composer-2.5`, so grok-4.6 was not used as a fallback. This review is the parent Grok 4.7 pass, not a second model invocation.

## Findings

### F1 — critical — canonical policy overlay clears an uncovered legacy block

`scripts/market_watch_launch/quality_gate.py` `_apply_policy_overlay` replaces `blocked_expressions` and sets `countries[code].eligible` from `evaluate_policy`. `evaluate_policy` marks every country eligible unless one of the supplied states is trade-critical and `overdue_unverified`. A partial `series_run_states` list therefore erases a correct legacy US block.

Failing scenario: legacy `evaluate_gate` result has `blocked_expressions: ["macro:US"]` and US `eligible: false`. `series_run_states` contains only a CA `old_but_current` state. After overlay, `blocked_expressions` is `[]` and US `eligible` is true. A due US labor failure drops out of the gate.

### F2 — high — catalog-unknown definition demotes a known due expectation

`scripts/run_state/scheduler.py` `tier_for` returns `unknown_calendar` whenever `definition.calendar_status == "unknown"`, before reading the expectation. The run-level expectation is the resolved calendar, including an overlay that pins a release. Labor catalog rows still have empty dates, so a known Employment Situation expectation (`scheduled_release_occurred_by_cutoff: true`, `trade_critical: true`) is scheduled as unknown and can be starved by a lower tier.

Failing scenario: definition `{calendar_status: "unknown", trade_critical: true}` and expectation `{calendar_status: "known", scheduled_release_occurred_by_cutoff: true}`. `tier_for` returns `unknown_calendar`. With one budget slot and a `due_context` series, the due trade-critical series is skipped.

`tests/run_state/test_scheduler.py` `test_unknown_from_definition_over_false_flag` currently locks the wrong precedence. That assertion is part of the defect, not a waiver.

### F3 — high — deploy acknowledgement ignores the receipt artifact

`scripts/run_state/publication.py` `acknowledge_deploy` checks `receipt["launch_id"]` but not `receipt["artifact_sha256"]` against the `artifact_sha256` argument. The store key uses the argument. The stored record is the receipt.

Failing scenario: `acknowledge_deploy(launch_id="L", artifact_sha256="aaa", receipt={"launch_id": "L", "artifact_sha256": "bbb"}, store={})` succeeds. `store["L:aaa"]` records artifact `bbb`. The acknowledgement is not bound to the artifact it claims.

### F4 — medium — assemble accepts an invalid expectation and fails open

`scripts/run_state/state.py` `assemble_series_run_state` does not call `validate_release_expectation`. An expectation with `calendar_status: "known"` and `scheduled_release_occurred_by_cutoff: null` is illegal in the schema, but assemble returns `carry_forward_reason: null`. `evaluate_policy` then does not block that series.

### F5 — medium — policy instant parser reads the wall clock

`scripts/run_state/policy.py` `_parse_aware_instant` attaches `datetime.now().astimezone().tzinfo` to a naive date-only string. Deterministic tests must not depend on the host zone. Date-only comparisons should use the calendar date only.

## Not filed

- Unknown calendar staying non-blocking matches the frozen plan, provided the series is listed and prose cannot say not-due. That path holds.
- Append-only merge keeps a started timeout when the secondary row is `budget_deferred` and `attempt_history` is present. Oct 5 replay tests cover that.
- `publish_offline` has no opener and rejects a score hash mismatch.
- `bind_scores` ignores `use_for_score: false` and does not change the hash.
- URL-less evidence validates.
- Checkpoint resume with the same input does not write a second output.

## Verdict

FAIL. Unresolved critical: F1. Unresolved high: F2, F3. F4 and F5 are required in the same remediation because they are fail-open and clock-boundary holes in the same policy path.
