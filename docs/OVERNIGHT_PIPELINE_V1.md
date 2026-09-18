# Market Watch — Overnight Production Pipeline V1

Status: ACTIVE UNATTENDED OPERATIONAL VERSION

This document is the contract for the repository-native overnight production pipeline. It does not replace `docs/DAILY_REFRESH_V0.md` for news selection, score methodology, or the restored front-page format. It adds the deterministic scheduler, one-run-id ledger, persistent 14-seat paper books, freshness/failure matrix, canonical morning dataset, and GitHub Pages publication gate.

Do not edit Global Operating Rules or ACP from this repository.

## 1. Ownership

| Concern | Owner |
| --- | --- |
| Deterministic scheduling and stage orchestration | GitHub Actions (`.github/workflows/overnight-pipeline.yml`) |
| Website publication | GitHub Actions only (`.github/workflows/deploy-pages.yml`) |
| Reasoning-heavy 14-seat portfolio review | Cursor, consuming the frozen evidence packet only |
| Durable overnight state | Git-auditable JSON under `data/overnight/` |
| Front-page news/score authoring | Restricted 00:07 Cursor V0 refresh; GitHub validates and commits only the governed refresh surfaces |

Cursor is not the website publisher. The full adversarial Trader Room (`scripts/trader_room_go.py`) is not the nightly job.

## 2. One immutable `overnight_run_id`

Every night uses one run id that spans all stages:

```
overnight-YYYYMMDD
```

The calendar date is `America/New_York`. Dry-run ids are `overnight-YYYYMMDD-dryrun-<suffix>`.

The ledger `data/overnight/runs/<run_id>/run.json` records, for every stage:

- status (`pending | running | succeeded | failed | skipped | stale`)
- `started_at` / `finished_at` / `as_of`
- inputs, outputs, errors

Stage artifacts stay under the same run directory. The run id is never rewritten.

## 3. Stage schedule

Schedules are declared directly in `America/New_York` using GitHub Actions timezone-aware cron. The scheduled cron string resolves the stage, so a delayed GitHub start does not silently turn a valid stage into an idle no-op.

| Stage | ET | Job |
| --- | --- | --- |
| `collect` | 00:07 | Snapshot macro hard inputs, news, central-bank research, market state |
| `pre_trader_delta` | 01:40 | Refresh pre-trader deltas versus collect |
| `freeze_evidence` | 01:50 | Freeze the common evidence snapshot (SHA-256) |
| `trader_review` | 02:05 | Lightweight 14-seat portfolio-management review |
| `final_delta` | 03:35 | Refresh final market/news delta |
| `assemble` | 03:50 | Build/validate one canonical morning dataset |
| `publish` | 04:07 | Pages build/deploy consumes that dataset |

CLI:

```bash
PYTHONPATH=. python3 scripts/overnight_pipeline.py schedule
PYTHONPATH=. python3 scripts/overnight_pipeline.py which-stage
PYTHONPATH=. python3 scripts/overnight_pipeline.py dry-run --as-of 2026-09-18T12:00:00-04:00
PYTHONPATH=. python3 scripts/overnight_pipeline.py stage collect --dry-run
```

## 4. Collect semantics

At 00:07 the workflow first runs exactly one restricted `grok-4.6` Cursor refresh call against the active V0 contract. The project hook allows repository reads plus Cursor WebSearch/WebFetch, blocks shell/MCP/subagents, and limits writes to the governed V0 news/macro refresh surfaces. GitHub then validates those edits before committing them. A scheduled live run requires the repository Actions secret `CURSOR_API_KEY`; dry-run never invokes Cursor.

After that refresh, `collect` freezes substantive inputs rather than hashes alone:

- `macro_hard` — full `data/temperature_scores.json` state plus the complete score-source registry. Corrupt/unreadable JSON is `invalid`.
- `news` — normalized current news items plus the governed v7/v9 refresh surfaces. Unreadable or unparsable scan state is `invalid`.
- `central_bank_research` — normalized research items plus the active rolling 30-day overlay.
- `market_state` — live `scripts/market_state.py` payload on scheduled collect/pre-trader/final-delta stages. A failed official-source fetch is explicit `unavailable`; no vendor substitute is invented.
- `research_method` and the exact prior 14-seat books are added to the immutable 01:50 packet.

## 5. Frozen evidence and the 02:05 review

The 01:50 snapshot is immutable. At 02:05 GitHub launches exactly 14 independent `grok-4.6` Cursor CLI calls, one per locked seat. Every call receives the same substantive frozen evidence packet plus only that seat's frozen prior book. The `OVERNIGHT_FROZEN_REVIEW_POLICY=1` hook blocks all tools, browsing, file access, shell, MCP and nested agents, so the model cannot acquire evidence outside the packet. Each returned JSON is normalized and checked against the run id, packet SHA and evidence cutoff before book mutation.

This nightly review is **not** the full adversarial Trader Room: there is no conflict aggregator, rebuttal round, or ChatGPT arbitration packet. Each locked seat independently manages its own $100m paper book. The scheduled runtime hard cap is 15 model calls total: one 00:07 refresh call plus fourteen 02:05 seat calls. All are explicitly routed to Cursor Models-pool IDs; nested subagents are blocked.

If any seat call or normalization fails, the apply job records the trader review as stale/failed and preserves the prior books. That failure does not block the website. `OVERNIGHT_TRADER_REVIEW_LIVE=1` is set only by the deterministic apply step after all 14 validated seat artifacts exist.

## 6. Persistent $100m paper books

Roster, remits, and models remain the standing 14 seats from `scripts/trader_room/constants.py`.

Each seat starts at `$100,000,000` paper NAV and may `OPEN / ADD / HOLD / REDUCE / HEDGE / CLOSE`.

Persisted per seat:

- positions and entry/exit history
- realized and unrealized P&L where prices exist (missing marks stay `pnl_unavailable`; prices are never invented)
- conviction, thesis, invalidation, alerts
- prior action / last action
- evidence cutoff
- `required_pitch` separately from `risk_put_on`

Expression rules:

- `dollar-king` and `cross-merchant` are dedicated spot-FX seats and stay spot-oriented.
- Every other seat is rates-first: evaluate outright duration / curve / cross-market rates RV, compare a spot candidate, then select the cleaner expression.
- Options/vol are last-resort. `vol-convexity` may select options only with an explicit last-resort rationale after comparing rates and spot.

Canonical book file: `data/overnight/books/latest.json`.

## 7. Freshness and publication failure matrix

Required families for expanding risk (`OPEN`, `ADD`): `macro_hard`, `news`, `market_state`.

| Condition | OPEN/ADD | HOLD/REDUCE/CLOSE | Website publish |
| --- | --- | --- | --- |
| Required family `fresh` | allowed | allowed | allowed when core is valid |
| Required family `stale` / `missing` / `unavailable` | blocked | allowed | allowed; surface the stale family |
| `macro_hard` or `news` `invalid` | blocked | allowed | **fail closed** (`catastrophic_fail`) |
| Trader review `failed` / `stale` / missing | n/a | n/a | **publish** with explicit stale trader-books status and last successful review id |
| Assembled dataset missing on an overnight publish | n/a | n/a | fail if `--require-dataset`; ordinary dashboard pushes may still publish seed/stale books |

A failed trader review must not block the website. A catastrophically invalid core macro/news input must not publish a false fresh state.

## 8. Canonical morning dataset

`assemble` writes `data/overnight/runs/<run_id>/assembled_dataset.json` and points `data/overnight/latest.json` at it.

The dataset includes core family status, the public trader-book projection, the publication decision, and the stage ledger. Pages publication consumes this file, validates freshness/completeness, and emits `_site/trader-books.json`.

## 9. Dashboard surface

The Trader Book tab is additive (`patch_v13/` + `scripts/apply_trader_book_tab.py`). It does not redesign the restored front page, news rollup, score board, or Market Data tab.

## 10. Persistence and the Supabase boundary

Shipped durable state is git JSON under `data/overnight/`. That is intentional.

The existing Supabase path (`docs/SUPABASE_PERSISTENCE_V1.md`, `SUPABASE_DB_URL`, `scripts/persist_market_watch.py`) is a public-feed writer. It is not credentialed or scoped for unattended overnight books, and this pipeline does not block on it.

Migration boundary, when a least-privilege overnight writer exists:

1. Keep `data/overnight/` as the audit snapshot written by Actions.
2. Mirror the same JSON objects into private `market_watch` tables.
3. Do not make the public dashboard query Supabase directly.
4. Do not store secrets, paid research, or raw evidence pointers in git or in the public `trader-books.json`.

## 11. Dry-run / CI path

```bash
PYTHONPATH=. python3 -m unittest tests.test_overnight_pipeline tests.test_overnight_cursor_runtime
PYTHONPATH=. python3 scripts/overnight_pipeline.py dry-run --suffix ci
```

The dry-run exercises every deterministic stage with fixture reviews and zero Cursor/model calls. `workflow_dispatch` on `.github/workflows/overnight-pipeline.yml` with `mode=dry-run` is the same path. Live-stage/scheduled execution fails loudly before model work if `CURSOR_API_KEY` is not available to the repository.

## 12. Repo map

- `scripts/overnight/` — ledger, freshness, books, collect/delta/freeze/review/assemble/publish plus the scheduled Cursor runtime boundary
- `.cursor/hooks/enforce-overnight-runtime.py` — runtime tool boundary for V0 refresh and evidence-closed seat reviews
- `scripts/overnight_pipeline.py` — CLI
- `data/overnight/` — books, run artifacts, latest pointer
- `docs/OVERNIGHT_PIPELINE_V1.md` — this contract
- `.github/workflows/overnight-pipeline.yml` — timezone-aware scheduler, V0 refresh, 14-seat review matrix, persistence, and dry-run
- `patch_v13/` — additive Trader Book tab
- `tests/test_overnight_pipeline.py` / `tests/test_overnight_cursor_runtime.py` — stage, freshness, P&L, model-boundary, evidence, publication, and tab tests
