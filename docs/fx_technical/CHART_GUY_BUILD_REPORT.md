# Chart Guy build report

Close-only G10 FX technical research, a shared pre-freeze evidence block, an original playbook, a real ECB case bank, a scored blind qualification, and the 15th paper seat. No production Market Watch or Trader Room run was launched. The accepted 2026-11-06 snapshot was not rewritten.

## What landed

- Close-only indicators in `scripts/fx_technical/indicators.py`: SMA 20/50/200, Wilder RSI(14), SMA-seeded MACD(12,26,9), Bollinger(20,2) with population standard deviation, close-to-close realized vol, 20/60 closing-price range levels, breakout and failed-breakout, and Dow-style swings confirmed only after two later closes. Insufficient samples stay null. FX is stale after 4 calendar days and unavailable after 21, matching the existing source clock. No OHLC, ATR, or candlestick fields are computed.
- `scripts/fx_technical/research.py` builds one `FX_TECHNICAL_RESEARCH` block during `build_snapshot` while the ECB series are still in memory. `scripts/fx_technical/packet.py` copies that block into the overnight freeze and the on-demand packet. `vetoes_unrelated_trades` is forced false, including when the feed is missing. `trade_recommendation` stays null.
- `docs/fx_technical/CHART_GUY_PLAYBOOK.md` is the original close-only curriculum. RSI above 70 is not treated as automatically bearish. Candlestick and ATR methods are excluded until real OHLC exists.
- `data/fx_technical/case_bank.json` holds 40 authentic ECB episodes. `data/fx_technical/blind_holdout.json` is the same eight holdout cases with subsequent paths removed.
- `chart-guy` is an active Grok 4.7 seat from 2026-11-07, spot G10 only, `may_no_trade`, with a new $100m empty paper book and an empty identity-scoped journal. Pins on or before 2026-11-06 stay at 14 seats.
- Learning records an optional `technical_setup` on the existing journal and scope path (`scripts/fx_technical/learning_ext.py`, `scripts/trading/learning.py`, `scripts/trading/journal.py`). Absent keys leave old lessons unchanged.

## Indicators and provenance

ECB Data Portal SDMX `EXR/D.{currency}.EUR.SP00.A` was retrieved on 2026-11-07. Each of USD, GBP, JPY, CHF, AUD, NZD, CAD, NOK, and SEK had 2011 observations from 2019-01-02 through 2026-11-06. Crosses are same-date ratios of those EUR legs, the same construction as `scripts/market_state.py`. The raw series was not committed.

Rounding is applied at the research boundary: prices and MACD to 6 decimals, RSI to 2, volatility and percent measures to 4. Realized vol is the population standard deviation of close-to-close log returns, annualized with `sqrt(252)` and expressed in percent, consistent with existing FX metrics. US 10Y context, when present, is a 20-observation change in basis points with a publication-lag note. Futures series used only as context carry a roll caveat. A missing or failed technical calculation does not fail the snapshot and does not change trade permissions.

## Case bank and qualification

The bank has 40 cases, one per pair, drawn from 5084 candidates. Classes are 8 each of disagreement, breakout, failed breakout, trend continuation, and range. The `no_trade` class did not occur under the expanded-volatility-without-structure rule in this diversity sample. Disagreement episodes are the stand-aside cases. Decision dates in the selected set run from 2019-10-11 through 2020-03-17 because selection prefers the least-used pair and then the earlier date. Each case has a real subsequent 5-session and 20-session close in the answer key only.

Holdout, withheld from the exam prompt: NOKJPY-2019-10-11 (failed breakout), GBPNZD-2019-11-05 (disagreement), GBPSEK-2019-11-22 (range), USDNOK-2019-11-27 (trend continuation), NZDUSD-2019-11-29 (range), EURJPY-2019-12-04 (range), EURNZD-2020-02-18 (range), NZDNOK-2020-03-17 (range).

Composer 2.5 sat the exam from the playbook and `blind_holdout.json` only. The deterministic scorer in `scripts/fx_technical/qualification.py` was re-run against `data/fx_technical/case_bank.json`: 8/8 passed, pass rate 1.0, gate `pass`, conflict failures empty. One trade was accepted (USDNOK long base, 20D, entry at the decision close, invalidation and target inside the close-range levels, reward above risk). The other seven were no-trade, including the disagreement and failed-breakout cases. Result: `data/fx_technical/qualification_result.json`.

Because the gate passed, the seat was activated. It is in the roster for the next freeze on or after 2026-11-07. It is not part of the 2026-11-06 accepted snapshot.

## Seat, books, and budgets

Trusted onboarding (`scripts/trader_room/onboard_trader.py --technical-only --activate`) wrote the registry row, `.cursor/agents/chart-guy.md` (`model: grok-4.7[]`), `data/overnight/books/latest.json` seat `chart-guy` at NAV and cash 100,000,000 with no positions, and `data/trading/trader/chart-guy/` with an empty journal and no lessons. Incumbent seat hashes were unchanged. Expression rule is `spot_only`.

| Pin | Traders | Daily calls | On-demand calls |
| --- | ---: | --- | --- |
| as of 2026-11-06 | 14 | 20 total, 18 Grok, 2 Composer | 57 / 29 / 28 |
| as of 2026-11-07 | 15, including chart-guy | 21 / 19 / 2 | 61 / 31 / 30 |
| legacy grok-4.6 pin | 14, chart-guy excluded | 20 / 18 / 2 | unchanged legacy shape |

A historical freeze dated before activation drops a not-yet-live cold seat from that run's working book copy. It does not delete the seat from `latest.json`. Review, rank, and public-book reads follow the seats in the book being replayed, so the accepted 14-seat snapshot still validates against its own pin.

## Validation

Commands were run from the repo root with `PYTHONPATH=.`.

- `python3 -m unittest tests.test_fx_technical_indicators tests.test_fx_technical_qualification tests.test_fx_technical_learning tests.test_fx_technical_packet tests.test_agent_config tests.test_mw_current_call_graph tests.test_roster_onboarding tests.test_trader_room_executable_catalog tests.test_trader_room_ondemand tests.test_learning_obligations` — 136 tests, OK. A repo hook prints a deny when a test emits a legacy 14-seat policy marker; the test process still exited 0.
- The same qualification module re-scored the stored exam: gate `pass`, 8/8.
- `python3 -m scripts.trader_room.agent_config check-agents` — exit 0.
- Frozen `data/overnight/runs/overnight-20261106/reviews/review-001/evidence_snapshot.json` still has 14 traders, budget 20, no `chart-guy`, and no `fx_technical`. Its prior books validate against that pin.
- A dry-run freeze on the fixture market state (`tests.test_roster_onboarding.RosterOnboardingTests.test_freeze_embeds_pin`, as of 2026-09-18) embeds a 14-seat pin and an `fx_technical` block with `vetoes_unrelated_trades` false. Packet hash matches the digest.

Composer 2.5 workers, before integration, reported indicator tests 10/10, qualification tests 11/11, and learning tests 11/11 on their disjoint files. Integration then fixed failed-breakout side, the US 10Y 20-observation window, case diversity across pairs, holdout reservation, and the 15-seat replay path above. Two pre-existing market-state tests still error on a missing `openpyxl` import (`test_rbnz_workbook_ignores_collapsed_dimension`, `test_rbnz_workbook_parser`). They do not import this feature.

## Not in this change

True OHLC, ATR, candlesticks, and Kronos remain future work. No new warehouse, cron, database, or vendor feed was added. No Market Watch or Trader Room production run was started. Nothing was merged or deployed. ACP and Notion were not edited.
