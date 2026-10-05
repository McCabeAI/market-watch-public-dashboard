# N14 adversarial review

- Reviewer: grok-4.7 (parent session)
- Node: N14
- Tree: working tree after N13, 111 `tests/run_state` tests passing, not yet committed
- Process deviation: a fresh grok-4.7 subagent was denied again by the repository hook (allowlist `composer-2.5`, `grok-4.6`, `grok-4.5`). ACP forbids a grok-4.6 fallback. This is the parent Grok 4.7 adversarial pass, not an additional model invocation.

## Findings

### A1 — high — same-period wrong transform marks the release satisfied

`scripts/run_state/expectations.py` `apply_satisfaction` sets `expectation_satisfied_by_verified_evidence` true when `observation.period == expected_period` only. Units and transformation are not compared. The frozen contract says satisfaction requires a verified observation of the expected period with matching units and transform.

Failing input: expectation period `2026-09`, transform required `mom_sa_pct`, units `percent`. Observation `{period: "2026-09", transformation: "index_level", units: "index", value: 100}`. Result: satisfied true. A due trade-critical series then gets `carry_forward_reason` null and the country is not blocked. That is a wrong-transform success.

### A2 — high — naive timestamp after cutoff is published

`scripts/run_state/publication.py` `publish_offline` parses evidence `timestamp` with `_parse_aware_datetime`. A string without a timezone returns None, and None skips the post-cutoff check.

Failing input: cutoff `2026-10-05T06:08:21.051325-04:00`, evidence timestamp `2026-10-06T12:00:00` (no offset), other fields valid, `timestamp_uncertainty` `exact`. `publish_offline` writes `public.json`. The item is after the cutoff date and is not rejected.

## Probes that held

- Wrong period (`2026-08` vs expected `2026-09`) does not satisfy.
- Unknown calendar stays null and is not tiered as not-due. Unscoped “no new release was due” still conflicts.
- Two raw hashes for one period both remain; `select_preferred` returns final.
- Budget 1 with three critical series admits one and skips two; none disappear.
- Missing `provenance.source_name` raises `ContractError`.
- Score hash mismatch writes nothing. Artifact mismatch on deploy ack does not store.
- Duplicate deploy receipt is idempotent.
- Definition `calendar_status` unknown does not demote a known occurred expectation.

## Verdict

FAIL. Unresolved high: A1, A2. No critical filed. N15 must fix both highs with targeted tests. Do not waive them.
