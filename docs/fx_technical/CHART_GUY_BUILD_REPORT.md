# Chart Guy build report

Close-only G10 FX technical research, a shared pre-freeze evidence block, an original playbook, and a real ECB case bank. Chart Guy is an **active** paper seat on this branch as of 2026-11-07, with a separate `$100m` book and empty learning identity. Participation starts on the next separately authorized freeze on or after that date. The accepted 2026-11-06 snapshot was not rewritten, and no Market Watch or Trader Room run was launched.

## Activation on 2026-11-07

Kevin retired the 75%/3-trade blind exam as an activation gate. The stored rehearsal stays a fail (`passed_trade_ids` is only `USDNOK-2019-11-27`, `qualifies_production_seat` is false, `production_exam.ran` is false). That file was not re-scored into a pass. Learning happens on future authorized paper runs through Trader Lessons.

The earlier hook denial, `Active Market Watch agent run is missing its run-policy marker`, fired when any `/tmp/mw-*-active.json` budget file existed and the transcript had no marker. A leftover file from another conversation was treated as this run. The hook now denies only when that file's recorded root or child conversation is the current parent. An unreadable budget file still denies. The file is not deleted and no marker is invented.

`scripts/fx_technical/smoke.py` is the activation gate: agent routing to `grok-4.7` with `composer-2.5` subagents, one no-trade learning scope, one in-memory close-only EURUSD mark and realized P&L, no lookahead past the decision date, stale versus unavailable closes, shared `FX_TECHNICAL_RESEARCH` with `vetoes_unrelated_trades` false, 15-seat budgets 21/19/2 and 61/31/30, and the frozen 14-seat 2026-11-06 replay. The on-demand command now launches every pin seat, keeps Chart Guy technical-only and allowed to no-trade, and states the 61/31/30 ceiling without applying it to a 14-seat packet.

`onboard_trader --activate --confirm-live-activation` wrote the cold book and identity after that gate passed. Incumbent seat hashes and identity files were unchanged. The agent instruction file was already present and was not rewritten.

## What landed

- Close-only indicators in `scripts/fx_technical/indicators.py`: SMA 20/50/200, Wilder RSI(14), SMA-seeded MACD(12,26,9), Bollinger(20,2) with population standard deviation, close-to-close realized vol, 20/60 closing-price range levels, breakout and failed-breakout, and Dow-style swings confirmed only after two later closes. Insufficient samples stay null. FX is stale after 4 calendar days and unavailable after 21, matching the existing source clock. No OHLC, ATR, or candlestick fields are computed.
- `scripts/fx_technical/research.py` builds one `FX_TECHNICAL_RESEARCH` block during `build_snapshot` while the ECB series are still in memory. `scripts/fx_technical/packet.py` copies that block into the overnight freeze and the on-demand packet. `vetoes_unrelated_trades` is forced false, including when the feed is missing. `trade_recommendation` stays null.
- `docs/fx_technical/CHART_GUY_PLAYBOOK.md` is the original close-only curriculum. RSI above 70 is not treated as automatically bearish. Candlestick and ATR methods are excluded until real OHLC exists.
- `data/fx_technical/case_bank.json` holds 40 authentic ECB episodes. `data/fx_technical/blind_holdout.json` is the examinee view of the eight holdout cases. Subsequent closes, setup class, holdout split, and the conflict label are removed.
- `chart-guy` is on the roster with status `active`, activation date `2026-11-07`, model file `grok-4.7[]`, spot G10 only, and `may_no_trade`. Pins dated before that day stay at 14 seats. The cold `$100m` book and empty identity are the activation written by `onboard_trader --activate` after the smoke gate. Incumbent seat rows were not rewritten.
- Learning records an optional `technical_setup` on the existing journal and scope path (`scripts/fx_technical/learning_ext.py`, `scripts/trading/learning.py`, `scripts/trading/journal.py`). Absent keys leave old lessons unchanged. Outcome classification compares the recorded daily close (`actual_mark`) with the invalidation level. It does not infer an intraday fill.

## Indicators and provenance

ECB Data Portal SDMX `EXR/D.{currency}.EUR.SP00.A` was retrieved on 2026-11-07. Each of USD, GBP, JPY, CHF, AUD, NZD, CAD, NOK, and SEK had 2011 observations from 2019-01-02 through 2026-11-06. Crosses are same-date ratios of those EUR legs, the same construction as `scripts/market_state.py`. The raw series was not committed.

Rounding is applied at the research boundary: prices and MACD to 6 decimals, RSI to 2, volatility and percent measures to 4. Realized vol is the population standard deviation of close-to-close log returns, annualized with `sqrt(252)` and expressed in percent, consistent with existing FX metrics. US 10Y context, when present, is a 20-observation change in basis points with a publication-lag note. Futures series used only as context carry a roll caveat. A missing or failed technical calculation does not fail the snapshot and does not change trade permissions.

## Case bank and qualification

The bank has 40 cases, one per pair, drawn from 5084 candidates. Classes are 8 each of disagreement, breakout, failed breakout, trend continuation, and range. The `no_trade` class did not occur under the expanded-volatility-without-structure rule in this diversity sample. Disagreement episodes are the stand-aside cases. Decision dates in the selected set run from 2019-10-11 through 2020-03-17 because selection prefers the least-used pair and then the earlier date. Each case has a real subsequent 5-session and 20-session close in the answer key only.

Holdout, withheld from the exam prompt: NOKJPY-2019-10-11 (failed breakout), GBPNZD-2019-11-05 (disagreement), GBPSEK-2019-11-22 (range), USDNOK-2019-11-27 (trend continuation), NZDUSD-2019-11-29 (range), EURJPY-2019-12-04 (range), EURNZD-2020-02-18 (range), NZDNOK-2020-03-17 (range).

The first exam was not a qualification of the production seat. Composer 2.5 answered the original eight holdout cases. That file still contained `setup_class`, `conflict`, and `split`, so the rehearsal was not blind. The mix was seven `NO_TRADE` decisions and one `TRADE` (USDNOK long base, 20D). Re-scored with the current gate, which requires at least three passing trades plus no failed disagreement or no-trade case, the individual scores are 8/8 and the gate is `fail` because `passed_trade_ids` is only `USDNOK-2019-11-27`. That result is stored under `rehearsal` in `data/fx_technical/qualification_result.json` with `qualifies_production_seat: false`.

A Grok 4.7 exam was not run. A nested `grok-4.7` task was denied by the repository hook: `Active Market Watch agent run is missing its run-policy marker.` No Market Watch or Trader Room cycle was started to get around that hook. The same hook denied a later Composer 2.5 read-only review task. The parent that selected a replacement case list had already seen setup classes, so a self-graded exam would not have been blind. The production gate in the qualification file remains `pending`, `production_exam.ran` is false, and that rehearsal was not re-scored into a pass. Kevin retired that exam as an activation gate on 2026-11-07. The smoke gate above is what activated the seat.

## Seat, books, and budgets

The registry row and `.cursor/agents/chart-guy.md` remain. The agent instruction no longer says to express macro views through USD or cross spot. It states a technical-only spot G10 mandate, 5D/20D primary and 1D/10D context, daily-close invalidation, and it embeds `docs/fx_technical/CHART_GUY_PLAYBOOK.md` so the seat does not open a file after the freeze. The shared evidence-closed closing used by the other seats is unchanged.

The cold `$100m` book, the trading-index row, and `data/trading/trader/chart-guy/` are present on this branch. They are the `onboard_trader --activate` result. Incumbent seat objects and identity files are unchanged from the parent of this activation. The accepted 2026-11-06 snapshot was not rewritten.

| Pin | Traders | Daily calls | On-demand calls |
| --- | ---: | --- | --- |
| live pin on 2026-11-06, chart-guy not yet effective | 14 | 20 total, 18 Grok, 2 Composer | 57 / 29 / 28 |
| live pin on 2026-11-07, chart-guy active | 15, including chart-guy | 21 / 19 / 2 | 61 / 31 / 30 |
| fixture with chart-guy status active, as of 2026-11-06 | 14 | 20 / 18 / 2 | 57 / 29 / 28 |
| fixture with chart-guy status active, as of 2026-11-07 | 15, including chart-guy | 21 / 19 / 2 | 61 / 31 / 30 |
| legacy grok-4.6 pin | 14, chart-guy excluded | 20 / 18 / 2 | unchanged legacy shape |

The live head pin on 2026-11-07 is 15 seats, 21/19/2 daily and 61/31/30 on-demand. A session dated 2026-11-06 stays at 14 seats and 20/18/2. Review coverage, assembled seat count, scheduled-output checks, memory sidecars, and public books follow the session pin or the seats in the book being replayed. A historical 14-seat freeze does not require a chart-guy memory sidecar.

## Validation before this activation

Code commit `23fe556ae82aa098d7286fc8351f4afd5bcfa8f1`. The report sentence naming that commit is `8bf7b511b4741af3c2b52c7be36b9108c12276e3`. PR #320 head is the commit that records both hashes. Commands were run from the repo root with `PYTHONPATH=.` on 2026-11-07. Parent model for this repair is Grok 4.7. Composer 2.5 was not able to sit a new exam or a read-only review: both Task launches were denied by the hook above.

- `python3 scripts/validate_trader_room.py` — exit 0. It reports 14 grok-4.7 advocates. `docs/TRADER_ROOM_PROTOCOL.md` names `chart-guy` and allows that seat to return no trade.
- `python3 -m scripts.trader_room.agent_config check-agents` — exit 0.
- Overnight, PM, memory, psychology, roster, and technical modules (`tests.test_overnight_pipeline`, `tests.test_overnight_scheduled_output`, `tests.test_overnight_acceptance_handoff`, `tests.test_overnight_review_identity`, `tests.test_pm_scheduled_output`, `tests.test_pm_overnight_packets`, `tests.test_pm_launch`, `tests.test_pm_dashboard`, `tests.test_pm_portfolio`, `tests.test_trading_memory`, `tests.test_trader_learning_v2`, `tests.test_learning_obligations`, `tests.test_trader_psychology`, `tests.test_trader_psychology_state`, `tests.test_trader_psychology_gate`, `tests.test_trader_psychology_integration`, plus the fx-technical, agent-config, call-graph, roster, and catalog modules) — 425 tests, then a 89-test rerun of the modules touched after that run, both OK aside from four failures that were fixed before the 89-test rerun. A repo hook prints `overnight run policy total_model_cap must equal 20` when a test emits a non-20 marker. That hook did not fail the process. The live cap is 20.
- `python3 scripts/overnight_pipeline.py dry-run --suffix ci --state-root /tmp/overnight-ci-state --site-dir /tmp/overnight-site --as-of 2026-09-18T12:00:00-04:00` — exit 0, all seven stages succeeded. Run `overnight-20260918-dryrun-ci`. Pin is 14 traders, budget 20/18/2, chart-guy absent. The frozen packet contains `fx_technical` type `FX_TECHNICAL_RESEARCH` with `vetoes_unrelated_trades` false and `trade_recommendation` null. Published trader books have 14 seats.
- Frozen `data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json` is unmodified: 14 traders, budget 20, no `chart-guy`, and no `fx_technical`.

GitHub Actions on `84304b1c50898afe5335efa97b1905bf7e90aca7` concluded success for all seven required workflows. The prior head `f790fc554405c23e60305114c90c39eac33b70a6` had failed the first five.

| Workflow | Run | Conclusion |
| --- | --- | --- |
| Macro ingestion | [42393429398](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429398) | success |
| Validate Trader Room | [42393429438](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429438) | success |
| Overnight Deterministic Pipeline | [42393429429](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429429) | success |
| Validate PM Layer | [42393429449](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429449) | success |
| Deploy Market Watch Dashboard | [42393429422](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429422) | success |
| Daily Market State | [42393429462](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429462) | success |
| Launch Market Watch | [42393429461](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42393429461) | success |

On the deploy workflow the `build` job passed. The `deploy` and `Reconcile Stage 08` jobs were skipped, so nothing was deployed. Launch orchestration jobs were skipped. Apply ChatGPT PM Decision also concluded success on the same SHA and did not apply a decision. The documentation commit `3819af2f247aaa6bd23bc1e45e3eb3d5e9782330` then failed Deploy Market Watch Dashboard. Run [42395753163](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42395753163), job `build`, step `Apply dashboard repair`: three release-calendar tests expected the committed seed timestamp `2026-11-06T18:00:00Z` and saw `2026-11-07T17:07:45Z` from the Actions cache restored by the previous green deploy. The other six workflows on that commit succeeded. `57ca2cd966266b03b706fed16442d90da2902601` moved the overlay to after those tests, but the workflow file itself failed to parse: push run [42397263801](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/42397263801) has no jobs because the inlined Python was not indented inside the YAML block. The six other workflows on that commit succeeded. The following commit indents that block so the deploy workflow can start.

Two pre-existing market-state tests still error on a missing `openpyxl` import (`test_rbnz_workbook_ignores_collapsed_dimension`, `test_rbnz_workbook_parser`). They do not import this feature.

## Validation of the 2026-11-07 activation

Activation commit `052577af28154452845717ef7cd7fe637d5021f7`. Commands were run from the repo root with `PYTHONPATH=.` on 2026-11-07. Parent model is Grok 4.7. No Market Watch or Trader Room production run was started. Both dry-runs used temp state roots and made zero model calls.

- `python3 scripts/validate_trader_room.py` — exit 0. It reports 15 grok-4.7 advocates.
- `python3 -m scripts.trader_room.agent_config check-agents` — exit 0.
- `tests.test_fx_technical_smoke` — pass. The stored exam stays `fail` and is not the activation gate. Paper P&L on the in-memory EURUSD close is positive and matches realized increment. No-trade scope stays `no_trade`. Budgets are 20/18/2 before 2026-11-07, 21/19/2 on that date, and on-demand 61/31/30.
- Hook regressions in `tests.test_mw_role_guards`: a budget file owned by another conversation does not deny; a live run whose own parent or child is in that file still denies when the marker is missing; an unreadable file still denies. The v1 required caps stay 20/18/2.
- `tests.test_agent_config.ChartGuySeatTests`, `tests.test_mw_current_call_graph`, `tests.test_trading_memory.TradingMemoryTests.test_empty_books_initialize_all_eighteen_identities`, `tests.test_overnight_pipeline.ExpressionRuleTests`, and `tests.test_trader_learning_v2` — pass. September books stay 14 seats. A 2026-11-07 empty book has 15, including chart-guy.
- Psychology, learning obligations, trader-room on-demand, overnight pipeline, PM scheduled output, and PM overnight packets were re-run after the roster helpers stopped indexing today's standing list into a historical book. The October psychology shadow fixture matches its stored report. A September on-demand persist follows the seats in that book and does not require chart-guy.
- `python3 scripts/overnight_pipeline.py dry-run --suffix ci --state-root /tmp/overnight-ci-state --site-dir /tmp/overnight-site --as-of 2026-09-18T12:00:00-04:00` — exit 0, seven stages, `model_calls` 0, run `overnight-20260918-dryrun-ci`. Pin is 14 traders, budget 20/18/2, chart-guy absent. `fx_technical` is present with status `unavailable`, `vetoes_unrelated_trades` false, and no pairs, because the fixture has no technical feed. Temp books have 14 seats.
- The same command with `--suffix ci15`, `--state-root /tmp/overnight-ci-15`, `--site-dir /tmp/overnight-site-15`, and `--as-of 2026-11-07T12:00:00-05:00` — exit 0, seven stages, `model_calls` 0, run `overnight-20261107-dryrun-ci15`. Pin is 15 traders, budget 21/19/2, chart-guy included. His temp book is `$100m`, flat, `spot_only`. `vetoes_unrelated_trades` is false.
- Canonical incumbent seat objects and identity files match the parent commit. `qualification_result.json`, the 2026-11-06 evidence snapshot, and `.cursor/agents/chart-guy.md` are byte-unchanged.

Composer 2.5 inspected the uncommitted diff and approved the hook, smoke gate, historical book roster, October shadow fixture, activation artifacts, and trader-room command. The reviewer did not re-run the full suite or the dry-runs. One gap the reviewer noted is now closed: the smoke gate fails if the committed registry row is not `status: active`. A live psychology shadow of this repo still omits chart-guy until a run book lists him. That is prospective, not a rewrite of the October fixture.

Two tests still fail for reasons that predate this activation and were not repaired by editing books or inventing marks. `tests.test_trader_book_lifecycle.TraderBookLifecycleTests.test_no_trade_skeptic_cap` blocks `SOFR_2027-03` with `implied rate missing for SOFR_2027-03 on frozen SOFR curve`. `tests.test_profit_harvest.ProfitHarvestTests.test_dollar_king_usdcad_replay_reviews_before_the_giveback` looks for an open dollar-king USDCAD position; the canonical book, unchanged for that seat, has USDJPY only.

## Not in this change

True OHLC, ATR, candlesticks, and Kronos remain future work. No new warehouse, cron, database, or vendor feed was added. No Market Watch or Trader Room production run was started. Nothing was merged or deployed. ACP was not edited. `chart-guy` is active on this branch only. His paper results are prospective. The old blind exam was not marked as a pass.
