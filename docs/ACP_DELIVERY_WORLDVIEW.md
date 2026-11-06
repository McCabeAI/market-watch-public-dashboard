# ACP delivery: ChatGPT PM worldview memory

Control-plane issue: https://github.com/McCabeAI/agent-control-plane/issues/404

Target: `McCabeAI/market-watch-public-dashboard`

Pull request: https://github.com/McCabeAI/market-watch-public-dashboard/pull/319

Branch: `cursor/build-chatgpt-pm-evolving-macro-worldview-memory-atop-market-watch-grok-4-7-composer-2-5-only-b405`

The full SHA is the pull-request head that contains this file. It is printed in the agent report from `git rev-parse HEAD` after the repair commit. This file does not invent a SHA before that commit exists.

## Repair at this head

`worldview_patch` now updates the records a belief refers to, not only belief prose.

- Country score foundations, dated observations, interpretation, and channel support.
- Global active drivers and belief links.
- Contradictions, signposts, research questions, and watchlist metadata.
- Unknown mutation keys are rejected.
- A failed or missing refresh keeps the prior observation.
- A new contradiction or signpost stores its id, so a later patch can update that row.
- Archives stay append-only. Replay, stale hash, and revision conflict behavior is unchanged. A no-change review does not reset `first_stated_at`.
- Cold-start retrieval shows live scores, interpretation, mechanism, expectation, and recent changed fields. Large bundles stay within 48,000 characters by capping drivers and links and leaving omission pointers.

`suggest-worldview` accepts an explicit snapshot plus file and packet hashes. The seed still reads only `data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json`. There is no newest-file discovery. Future comparison is demonstrated with `tests/fixtures/worldview_synthetic_future.json` only.

## Preserved memory

Main is merged into this branch. The research index keeps edge revision `rev-edge-portfolio-pass-20260920-05`, the existing hypotheses, and main's `as_of` `2026-11-06T15:18:13.773151-05:00`. `research_sha256` was recomputed with the worldview block: `fcd1a4c8c4321673185f05b523c7bbe4c923e35b645bdc657a2b5364fc8b1f3b`.

`scope.approved_foundation_and_tail_lessons` on the edge profile is cited as sixteen numbered lessons. They were not replaced or retired. The earlier note that they were absent was wrong and is removed.

## Seed

`rev-worldview-0001` remains provisional: `acceptance: awaiting_pm`, `learned_edge: false`. Persistence clock `persisted_at` is `2026-11-06T22:22:06.628733+00:00`. The fabricated `2026-11-06T20:00:00-05:00` stamp is gone. Observation vintages and the freeze label `2026-11-06T06:25:49.281876-05:00` stay separate.

Canada's transmission text is Kevin's qualitative mechanism: new borrowing versus outstanding loans, floating borrowing repricing sooner, fixed-rate mortgage and corporate refinancing lags, possible debt-service pressure, and a possible benefit to savers and energy producers. It is not a measured magnitude. Unemployment at 6.5 percent and rates at 3 percent are calibration assumptions to test. An actual Bank of Canada hike is recorded as contrary evidence to investigate, not as a claim that a hike occurred. The owned CORRA question does not use excluded meeting-price levels.

The deleveraging tail does not say it is "not yet credible enough". Credibility and trade selection remain undecided by the PM. The seed does not recommend a trade.

## Validation

```bash
PYTHONPATH=. python3 -m unittest tests.test_chatgpt_worldview tests.test_chatgpt_research_memory tests.test_chatgpt_research_cold_start -q
```

`Ran 31 tests in 0.999s` — `OK`.

Covered: score and metadata patch through dry-run and native `apply-from-env`, archive retention, replay, failed-refresh retention, unknown keys, new contradiction and signpost ids, synthetic snapshot binding, the pinned November 6 default, a bounded large bundle, `authorize-from-env`, the sixteen lessons, and unchanged lessons, edge profile, frozen snapshot, and other-seat files.

## Independent verifier

A `grok-4.7-high` call was denied by the repository hook because that handle is outside the default allowlist. The review ran on `grok-4.7`.

The first review returned **FAIL**: new contradictions and signposts did not store their ids. The parent sent that defect back to Composer. A second `grok-4.7` review returned **PASS**. Residual limitation: the seed cites lesson number, id, and title, and does not copy each lesson's rule text. The profile remains the source.

## Model accounting

These are calls this session made, not token totals.

- Parent planning and integration: this Grok 4.7 session. No separate planner subagent.
- Composer 2.5: 5 calls. Storage and history, retrieval and snapshot binding, seed and tests, then two correction calls for record ids and mechanism length.
- Grok 4.7: 2 completed verifier calls (FAIL, then PASS). One `grok-4.7-high` attempt was denied by the hook and did not run.

## Limitations

- `suggest-worldview` without a snapshot still reads the pinned November 6 seed file. Another snapshot must be passed explicitly with hashes.
- The 48,000-character cap can clear interpretation text after drivers and links are already capped.
- `runtime_autoload` is false. A fresh session does not remember this state until someone runs `retrieve`.
- Not merged and not deployed. The seed is awaiting PM acceptance.
