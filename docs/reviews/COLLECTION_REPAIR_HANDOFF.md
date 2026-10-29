# Collection repair handoff — 2026-10-29

Parent: Grok 4.7. Workers, integrator, and verifiers: Composer 2.5.
Starting commit: `0392af31a3ac2921ae578509fe79d9784fba08d9` on `repair/data-collection-2026-10-29`.
Working branch for the PR: the cloud agent branch that contains that commit.
Diagnosis: `docs/reviews/DATA_COLLECTION_REVIEW_2026-10-29.md`. No second broad audit.

## Invocation ledger

Cap: 18 accepted agent invocations. Frontier/Grok cap: 2 including parent. Max 4 concurrent workers. Two attempts per worker node.

| # | Node | Model | Role | Status |
| --- | --- | --- | --- | --- |
| 1 | P | grok-4.7 | plan, ownership, escalation, final approval | PASS. See COLLECTION_REPAIR_VERDICT_2026-10-29.md. Invocations used: 9 of 18. Grok calls: 1 of 2. |
| 2 | A | composer-2.5 | shared runner, retries, observation state, calendar backstop | done bc-2931222b-b590-528a-acb3-01cff6e83439. Original commit 6ddf6b71 was rewritten by a later reset; content is e438ff8c. Runner/calendar/integrity/NZ tests on 7130c08c: 56 OK. |
| 3 | B | composer-2.5 | US acquisition and employment batching | done bc-b14d82a8-60fb-57e9-a3f0-e572ed766d46 at 8c3b7f6c. Parent restored US.Consumer.income, US.Consumer.spending, US.Consumer.confidence after that commit deleted them. ISM PR Newswire routes verified live. BLS CPI/PPI/IR/IQ alternates wired. BEA, Census, UMCSENT, FHFA remain FRED-only. |
| 4 | C | composer-2.5 | NZ acquisition and NZ rates fallback | done bc-68c4ad24-abe1-5bbd-bc45-512b749eed13 at 54b02c0f. Topic-listing discovery. June 2026 periods kept when that is the file vintage. Income live parse and NZ rates vendor fallback remain gaps. PPI/import/export still unpinned. |
| 5 | D | composer-2.5 | CA/AU and bounded EA/JP adapter gaps | done bc-334a3450-977f-5fb0-b75b-773009a7f36e at 4218f6e8. Baseline catalog pins IPPI v1230995983 and RMPI v1230998135. Import/export prices, CA participation, and Westpac confidence left unpinned. EA/JP unchanged. Focused CA/AU tests re-run on the recovered tip: 41 OK. |
| 6 | E | composer-2.5 | launch acceptance, cadence display, CI, data-only catch-up | done bc-73930622-f521-56f4-93e9-e15b5bdd3356 at a6d63bdc. 26 tests passed. Retry health is merged. PR CI no longer live-gates. |
| 7 | I | composer-2.5 | integrate, targeted tests, one isolated live collection/build | done bc-3746c26d-a72f-5644-94da-fb3d1516ad7b at 718fce9e. 95 tests passed. Live exit 0, 176 rows in /tmp/mw-repair-live. |

History note: a later NZ amend reset the branch and dropped the runner commit. Cherry-pick e438ff8c restored it. Merge 7130c08c kept the newer NZ adapter. The four acquisition nodes wrote one working tree. B's catalog commit deleted three scored US series; 3c23e8b1 restored them.
| 8 | V1 | composer-2.5 | read-only identity/period/units/fallback review | PASS bc-a4e7758e-7853-5f50-95e8-266d09cb7185. CA totals, NZ Q2 periods, BLS labor, ISM headlines, and AU A2304183K checked against the live store. |
| 9 | V2 | composer-2.5 | read-only state, freshness, CI, frozen-evidence review | PASS bc-1288e485-8f41-5eba-a767-f5eaeb25fa04. Host isolation, merged health path, seeded unchanged test, cadence backstop, PR CI, and frozen-evidence catch-up checked in code and live files. |

## File ownership

- A: `scripts/macro_ingestion/runner.py`, `retries.py`, `vintage.py`, `ledger.py`, `calendar.py`, and tests `tests/macro_ingestion/test_runner.py`, `test_calendar.py`, `test_integrity.py`. No catalog edits. No launch/workflow edits.
- B: `scripts/macro_ingestion/adapters/us.py`, `scripts/macro_ingestion/us_employment/**`, US-focused tests, and US rows in `data/macro_ingestion/catalog.json`. No runner edits.
- C: `scripts/macro_ingestion/adapters/nz.py`, NZ tests, NZ catalog rows, and only the NZ rate functions in `scripts/market_state.py` plus their tests. No runner edits.
- D: `scripts/macro_ingestion/adapters/ca.py`, `au.py`, `ea.py`, `jp.py`, `scripts/macro_ingestion/au_leading/**`, `au_labor_*.py`, matching tests, and CA/AU/EA/JP catalog rows. Reuse `scripts/prima_pressure/contract.py` `PRODUCER_SERIES`; do not change those vectors. No runner edits.
- E: `scripts/market_watch_launch/ingest.py`, `quality_gate.py`, `scripts/macro_source_health.py`, `scripts/macro_ingestion/cli.py`, existing workflows `macro-ingestion.yml` and `daily-market-state.yml`, and focused tests for those surfaces. No adapter URL rewrites.
- I: merge only. Combined catalog conflict resolution. No new raw dump committed. No frozen trader evidence mutation.

## Runner interface A must land

Optional `run_ingestion` arguments, defaults preserving current tests:

- `write_health: bool = True` — retry passes set this false so `health/latest.json` is not replaced by the retry subset.
- `seed_observations_from: Path | None = None` — copy missing country observation files into `observations_dir` before fetch. Never overwrite a file already in the destination. Never write back to the source.
- `prior_rows: list[dict] | None = None` — series ids whose prior error is `budget_deferred` sort ahead of cold context.
- `group_parallelism: int = 4`, `per_host_limit: int = 1`, `host_failure_limit: int = 2`.

Scheduling: group by endpoint host. Round-robin across hosts so one slow host cannot occupy the country budget before other hosts are attempted. After `host_failure_limit` transport timeouts on a host in the pass, defer the rest of that host without further fetches (`error` remains distinguishable, use `host_deferred`). Retry only series that failed. Serialize observation-store mutation.

`vintage.seed_stores(dest, source) -> list[str]`.

`calendar.cadence_backstop_due(spec, *, latest_period, when) -> bool` when the publisher calendar is absent or unparsed and the latest period is older than the series cadence plus grace. It does not make the stored value wrong. Monthly grace 45 days after period end, quarterly 120, weekly 14. Unknown cadence returns false.

Classification: a retrieved observation with a clear period and value is `checked_unchanged` or `new_observation`/`revision_*` even when the calendar is missing. `calendar_unparsed` must not be the status of a usable point. A 404 with an empty calendar and `cadence_backstop_due` is not `checked_unchanged`.

## Economic pins already verified in repo

- `CA.Inflation.ippi` is PRIMA `ippi_total`: vector `1230995983`, table `18-10-0265-01`, monthly NSA index. `scripts/prima_pressure/contract.py`.
- `CA.Inflation.rmpi` is PRIMA `rmpi_total`: vector `1230998135`, table `18-10-0268-01`, monthly NSA index.
- Do not use RMPI as the import/export price index. Pin participation or trade-price vectors only from an existing official mapping in the repo. Otherwise leave them unpinned and say so.
