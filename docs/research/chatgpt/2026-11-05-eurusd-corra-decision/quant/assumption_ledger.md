# Assumption ledger

No external data were retrieved; all series from pinned evidence_snapshot.json, book at data/pm/books/latest.json (pms.chatgpt only), optional trader_review.json opinion strings.

## Clocks (not conflated)
- snapshot as_of: 2026-11-05T04:53:53.458055-05:00
- market_state as_of / generated_at: 2026-11-05T10:17:36Z / 2026-11-05T10:17:36Z
- macro_hard as_of: 2026-11-04T05:35:22-05:00

## EURUSD
- Series: `families.market_state.data.opportunities.series[id=EURUSD].history` (126 closes); stats `families.market_state.data.fx.pairs.EURUSD`
- Last: 2026-11-04 close 1.1267; formula daily log return ln(p_t/p_{t-1}); sample std N-1 on last 20/60/full returns
- Horizon yardsticks: sigma_h = daily_sigma_* * sqrt(h); approx % = 100*(exp(sigma_h)-1); label YARDSTICK
- Excursions: overlapping sums in stored sample; label overlapping_descriptive
- Weak rank: 100*count(closes<=last)/126 = 18.253968

## CORRA strip
- Snapshot legs 2027 H/M/U/Z; strip_history_status=ABSENT
- DV01 P&L: receive, yield up = loss; label book identity / illustration

## Carry (long EURUSD)
- Financing drag N*gap*(days/360); gap from 2y sovereign (2026-11-04) and SOFR−ESTR; label INDICATIVE_BENCHMARK_NOT_FORWARD
- Executable forward points: ABSENT

## Oil
- Vol excluded (futures roll-contamination); Dec 2026 Brent leg STALE if observation on/before 2026-10-30

## Real / breakeven
- US real 10y vs breakeven end dates differ; do not same-day combine
