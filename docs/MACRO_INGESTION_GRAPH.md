# Ingestion graph log

Parent model: Grok 4.7. Subagent allowlist: `composer-2.5` only. Caps: 1 frontier parent call, up to 9 Composer tasks. No second Grok call, no other model.

| Step | Model | State |
| --- | --- | --- |
| Audit main at `54673b377165a21911f6569665bbc17ff5cdb1a5`, write matrix, architecture, Drive plan, baseline catalog | Grok 4.7 parent | done (`8f8fdaa`) |
| Shared platform contract | Composer 2.5 | done (`3929605`, then graph note `06d2ff2`) |
| Country US | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country CA | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country AU | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country NZ | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country EA | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Country JP | Composer 2.5 | done (parallel task; committed in `7efb3b0`) |
| Integration / QA | Composer 2.5 | done (`27bc50a`, 73 tests at that commit) |
| Bounded correction | Composer 2.5 | done (`7617bdb`, scheduled windows set to live) |
| Independent final review | Grok 4.7 parent (same call) | done, this section |

Parallelism: the six country tasks were launched together after the shared contract was on the branch. They did not run as one sequential generalist.

## Continuation (2026-09-23)

| Stage | State |
| --- | --- |
| Canonical bridge (`merge_scored_points`, `persist_if_changed`) | landed |
| Integrity statuses (transform mismatch, methodology breaks, license_gap) | wired in bridge + runner ledger |
| CI / verification | `macro-ingestion` workflow: `ingest` on manual `workflow_dispatch` only; `validate` on pull requests (unittest, no live CLI, no commits) |
| Live canonical persist | CLI `--mode live` sets `persist_canonical`; history/scores written only when merge appends |

Manual commands:

```bash
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli --mode offline --country all
PYTHONPATH=. python3 -m scripts.macro_ingestion.cli --mode live --country all
```

## Call 3 fixes (2026-09-23)

Parent: Grok 4.7, no Composer worker. Two defects only.

- Observation-key lookup keeps the scored row when an alias shares `(country, series_id, transform)`. Two different scored ids on one key raise `ScoredSeriesKeyCollision`.
- An unchanged fetch after the bound expected period is already in the payload and the store is `checked_unchanged`. A later date bound to a period the fetch does not contain stays `due_missing`. A due date with no bound period and no pinned `known_fixture.period` stays `calendar_unparsed`. `EA.Activity.flash_composite_pmi` still requires period `2026-09`.

## Call 4 (2026-09-23) Eurozone flash retrieval

Parent: Grok 4.7. No Composer worker. The public S&P listing and press PDF are fetched with the existing browser user agent. The English flash title and the key-findings line are parsed by `scripts/harvest_ea_pmi.py`. Archived finals stay on the final collector only. The September flash PDF is archived under `data/temperature_history/raw/ea/` and is not written into review-001.

## Parent review

Grok 4.7 review of the continuation on top of `a84d1e0`. Composer 2.5 only: canonical bridge, ingestion integrity, CI/verification. No fourth correction was required. No cron schedules were added. `743d82a` remains the manual-only dispatch choice.

Preserved SHA-256 after the local unittest run:

- calibration `f28d68f846c87a8f675398620d59c5a7bc1ab30c8771b316817251a08ba1cb5b`
- review-001 evidence `41ad9248149d7f4337f20f8080a63a6932a618fc987f12afe048371d0b7a944b`
- trader books `4fbbab25b8961ea25932ed6768088dbaef86341c2ddbc8ff04aba85a67cd2d81`
- PM books `a72838cde87470b91e650381136cc6cb28ae14156f601eadb26a121323320676`

Local validation command (the pull_request job): macro ingestion discover **75 passed**; freshness, temperature level/scores, and overnight contract tests **143 passed, 1 skipped**.

What the bridge actually does: a scored point is appended to `data/temperature_history/{country}.json` only when its transformation equals the calibration `source_transformation`, the series id matches, the component is not `observed: false`, any methodology break is already behind prints the stored series continues, the value is finite, and the period is a forward print or a non-flash revision of an existing period. `data/temperature_scores.json` and `score_paths.json` are rewritten only when that append happens. Offline tests and `--mode offline` do not persist them. `--mode live` does, and only then.

Remaining blockages, not claimed live:

- Transform mismatch, bridge skips: `US.Labor.wages`, `CA.Activity.gdp_domestic_demand`, `CA.Consumer.confidence`, `AU.Labor.unemployment`, `AU.Consumer.retail`, `AU.Consumer.confidence`.
- Non-empty `methodology_breaks` on a history component skips the merge (`methodology_break_guard`). AU trimmed-mean CPI is in that set.
- `EA.Activity.flash_composite_pmi`: S&P listing HTTP 403, value stays null, August final stays. No substitute and no paywall bypass.
- S&P public listings that return 403 stay `license_gap` or `source_failed`.
- Context rows and `US.Inflation.mapped_bridge` stay weight 0 and are not merged.
- A parsed release instant that is already past still yields `due_missing` when the payload period is not newer than the stored period. That is correct for the missing September flash. It will also keep a series `due_missing` after the calendar instant if the fragment date refers to a print already stored.
- Manual live ingestion is `workflow_dispatch` or the CLI. It does not start an ACP trader or PM run and does not edit review-001.
