# Market Watch — Portfolio Manager Layer V1

Status: LIVE · IMPLEMENTATION ONLY (no PM model spend)

This is the four-PM layer above the locked 14-seat Trader Room. It does not change the 14 seats, the overnight ACP schedule, or agent-control-plane.

## Roster

| PM | Mandate | Risk-capital limit | HEDGE |
| --- | --- | --- | --- |
| `chatgpt` | No forced style. Final synthesis. May trade or choose no-trade. | $1bn gross notional | allowed |
| `swinger` | Very aggressive/concentrated when the thesis is valid. Reduce/close instead of hedging. | $1bn gross notional | **prohibited** |
| `pragmatist` | Opportunistic macro. Can swing big or grind singles/doubles. | $1bn gross notional | allowed |
| `grinder` | Preservation/consistency first. Smaller sizes, high hurdles, quick de-risking. No-trade is valid. | $1bn gross notional | allowed |

Each PM has **$1bn paper NAV**, but notional is descriptive rather than the binding risk limit. Trusted code caps each book at **$10m of 1%-shock risk capital** and enforces a **$50m drawdown from high-water NAV**. Risk capital is the absolute MTM loss from a 1% adverse move in the quoted risk factor, with a 1bp minimum shock for rates/spreads. PMs earn official NY Fed SOFR ACT/360 on the full paper cash hurdle and pay the same SOFR on shocked risk capital; equal risk capital receives equal financing treatment across asset classes. If deterministic marks are insufficient to compute risk capital, expansion fails closed. Official NY Fed SOFR is the realized funding authority; SR3 is forward context; a model funding forecast cannot mutate realized accounting. After every action:

```
sum(abs(open position notional)) <= 1_000_000_000
```

Cap breach or a missing required paper mark fails closed. Options remain unavailable when premium/IV/strike marks are insufficient.

## Independence

All four PMs receive the same frozen/current Market Watch evidence and the same finalized 14-seat Trader Room output. Each PM sees only its own prior book. No PM sees another PM's current-cycle decision before commit. Comparison is allowed only after decisions are committed.

## Canonical state

`data/pm/books/latest.json` is trusted-code state. Models may not author it.

Each book stores positions, descriptive gross notional, shocked risk-capital utilization/remaining capacity, high-water NAV/drawdown/risk-stop state, realized/unrealized/total paper P&L, mark provenance, locked expression/curve family, thesis, invalidation, conviction, action history, review status/freshness, and alerts.

Paper marks reuse `scripts/overnight/paper_marks.py`. Packet mids override model-authored prices. SOFR/CORRA/AONIA/bond expression family is locked from OPEN through CLOSE.

Actions: `OPEN / ADD / HOLD / REDUCE / HEDGE / CLOSE` plus explicit `NO_TRADE`.

## Review packets

Deterministic per-PM artifact:

```
data/pm/review_packets/<pm_id>/latest.json
```

Daily packets are generated from the latest **successful overnight 14-seat scheduled review**, not from the newest on-demand Trader Room run. Each packet records `source=overnight_scheduled_review`, the overnight run id, the final agent-packet cutoff/hash, compact frozen evidence and market state, the same deterministic `funding_context` traders receive, SOFR/CORRA/AONIA and sovereign-curve availability, the accepted 14 trader decisions, overnight research supplement/canonical books when present, **only that PM's prior book**, that PM's compact learning-memory context / calibration / `postmortems_due`, allowable actions, descriptive notional plus risk-capital utilization/drawdown state, and unresolved future data requests. See `docs/TRADING_LEDGER_MEMORY_V1.md`.

All four PMs share the same overnight evidence boundary and 14-seat output. On-demand Trader Room publication stays independent. If no overnight review exists yet, `init` / `refresh-packets --allow-trader-room-fallback` may use `source=on_demand_trader_room_fallback`. That fallback is labeled and never treated as a fresher overnight packet.

Refresh is wired into overnight scheduled-output apply (and assemble catch-up). No new model/provider clock:

```bash
PYTHONPATH=. python scripts/pm_layer.py refresh-packets
PYTHONPATH=. python scripts/pm_layer.py refresh-packets --allow-trader-room-fallback
```

## ChatGPT ingest

Documented schema: [`docs/CHATGPT_PM_DECISION_INGEST.md`](CHATGPT_PM_DECISION_INGEST.md).

```bash
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py validate --input data/pm/inbox/chatgpt_decision.json
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py apply --input data/pm/inbox/chatgpt_decision.json
```

Trusted code hydrates marks, checks packet id/hash/freshness, enforces instruments/cap/curve lock and the learning/rationale gate, mutates only the ChatGPT book, applies ledger/journal/memory updates, persists provenance/history, refreshes marks, and updates public state.

## Future data requests

`data/pm/data_requests/latest.json` is the consolidated Git artifact. Entries carry originating PM, request, reason, decision impact, priority `low|medium|high`, suggested source, first/last requested, repeat count, and `status=requested`. Repeated text is deduped with attribution preserved. Requests are for future runs only; they never break the current evidence freeze and never launch collectors. The Trader Book tab surfaces them to Kevin.

## Optional automated PM decisions

Overnight `scheduled_output.json` may include `pm_decisions` for exactly `swinger`, `pragmatist`, and `grinder`. Absence remains valid; automated PM state stays awaiting/stale rather than fabricated. If present, each decision is applied independently and must declare `principal_model`, `subagent_count` (0–3), and `subagent_models` in `{grok-4.6, composer-2.5}`. This repository does not invoke those models.

## Public dashboard

- Trader Room tab auto-selects the newest complete valid run under `trader-room/runs/`. Pages no longer depends on a manually maintained `data/trader-room/public/latest.json`.
- Trader Book tab keeps the 14-seat competition and adds a Portfolio Managers section, four-PM P&L comparison, and compact PM Data Requests area.
- Public PM JSON: `data/pm/public/latest.json` → `_site/pm-books.json`.

## Initial state

All four books start with $1bn paper NAV, $10m shocked-risk capacity, a $50m hard drawdown limit, and zero positions. ChatGPT is `awaiting_chatgpt_decision`. Swinger/Pragmatist/Grinder are `awaiting_automated_pm_review`. Review packets and the data-request registry exist. No PM trades are invented.
