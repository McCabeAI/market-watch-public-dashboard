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
| Front-page news/score/market-data format | Existing V0 patch chain; overnight collect does not rewrite it |

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

Windows are `America/New_York` wall-clock and deliberately avoid top-of-hour cron load. GitHub cron is UTC-only, so the workflow lists both EDT (UTC-4) and EST (UTC-5) expressions. Each job still self-gates with the NY clock and no-ops when idle.

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

`collect` snapshots the current repository inputs. It does **not** author a new front page and does **not** undo the Sep 18 news fixes.

- `macro_hard` — `data/temperature_scores.json` plus the score-source registry. Corrupt/unreadable JSON is `invalid`.
- `news` — current v7/v9/Sep 18 patch chain. Unreadable or unparsable Last scanned/refreshed state is `invalid`.
- `central_bank_research` — current rolling 30-day transform files.
- `market_state` — optional live `scripts/market_state.py`. Offline/dry-run or a failed fetch is `unavailable`, not catastrophic.

## 5. Frozen evidence and the 02:05 review

The 01:50 snapshot is immutable. The 02:05 review must include the same `overnight_run_id`, `packet_sha256`, and `evidence_cutoff`. It must not privately fetch new evidence (`web_search`, `web_fetch`, etc.).

This nightly review is **not** the 14-advocate adversarial Trader Room. There is no conflict aggregator, no rebuttal round, and no ChatGPT arbitration packet. Each locked seat is a portfolio manager of its own $100m paper book.

Live Cursor spend is refused unless `OVERNIGHT_TRADER_REVIEW_LIVE=1` and a complete 14-seat payload is supplied. GitHub Actions never calls trader models. If the live payload is missing, the stage records a failed/stale review and leaves the prior book in place.

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
PYTHONPATH=. python3 -m unittest tests.test_overnight_pipeline
PYTHONPATH=. python3 scripts/overnight_pipeline.py dry-run --suffix ci
```

The dry-run exercises every stage with fixture reviews and zero trader model calls. `workflow_dispatch` on `.github/workflows/overnight-pipeline.yml` with `mode=dry-run` is the same path.

## 12. Repo map

- `scripts/overnight/` — ledger, freshness, books, collect/delta/freeze/review/assemble/publish
- `scripts/overnight_pipeline.py` — CLI
- `data/overnight/` — books, run artifacts, latest pointer
- `docs/OVERNIGHT_PIPELINE_V1.md` — this contract
- `.github/workflows/overnight-pipeline.yml` — NY-aware scheduler + dry-run
- `patch_v13/` — additive Trader Book tab
- `tests/test_overnight_pipeline.py` — stage, freshness, P&L, publication, and tab tests
