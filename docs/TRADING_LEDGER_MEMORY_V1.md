# Market Watch — Trading Ledger and Learning Memory V1

Status: LIVE · GIT-BACKED · NO NEW SERVICE

This is the operating contract for durable executed-trade history, decision journals, and compact identity-specific learning memory. Canonical positions, marks, P&L, and persistence stay in trusted repository code. Model output is untrusted structured decision and reflection data only.

This document does not change the ACP 02:05 schedule, the locked 14-seat roster, or the four PM mandates.

## 1. Source-of-truth hierarchy

| Layer | Owner | Mutable by models? |
| --- | --- | --- |
| Paper books, marks, realized/unrealized P&L, funding/cash yield | Trusted `scripts/overnight/books.py` and `scripts/pm/books.py` | No |
| Canonical trade lifecycle ledger | Trusted `scripts/trading/ledger.py` | No |
| Decision journal (accepted decisions, proposals, rebuttals, postmortems) | Trusted `scripts/trading/journal.py` | Models supply structured fields only |
| Compact learning-memory context | Trusted `scripts/trading/memory.py` | Lessons/postmortems are untrusted structured input; calibration is deterministic |
| Dashboard / publication | Existing overnight and PM public projections | No new UI in this version |

Account-level 5% Trader Room funding remains account-level. Trade P&L is instrument trading P&L only.

## 2. Identities

Exactly 18 identities:

- Traders: `perma-bull`, `perma-bear`, `dollar-king`, `cross-merchant`, `carry-is-king`, `rate-hawk`, `rate-dove`, `value-guy`, `trend-follower`, `mean-reverter`, `positioning-cynic`, `catalyst-junkie`, `vol-convexity`, `no-trade-skeptic`
- PMs: `chatgpt`, `swinger`, `pragmatist`, `grinder`

A trader never receives another seat's private memory. A PM never receives another PM's private memory. Common macro evidence stays identical.

## 3. File layout

```
data/trading/index.json
data/trading/trades/<trade_id>.json
data/trading/<owner_type>/<owner_id>/journal.json
data/trading/<owner_type>/<owner_id>/lessons.json
data/trading/<owner_type>/<owner_id>/postmortems.json
data/trading/<owner_type>/<owner_id>/postmortems_due.json
data/trading/<owner_type>/<owner_id>/context.json
```

Overnight freeze also writes per-seat sidecars at `data/overnight/runs/<run_id>/memory/<seat>.json`. Full Trader Room freeze writes `trader-room/runs/<run_id>/memory/<seat>.json`. Those sidecars are not part of the common evidence packet.

`trade_id` is stable and linked to `position_id`:

```
trd-<owner_type>-<owner_id>-<position_id>
```

A closed ledger record never disappears because the live book position was removed.

## 4. Lifecycle

`OPEN` creates a ledger trade. `ADD` / `REDUCE` / `CLOSE` update that same lifecycle. `HEDGE` opens a new linked lifecycle for the hedge position and records a hedge event on the original trade.

Each risk-changing event stores date/time, run id, deterministic mark/source, notional change, realized P&L increment where applicable, and supplied rationale. Close stores exit mark, exit rationale, structured exit-reason category when supplied, full realized trading P&L, and holding duration.

MFE/MAE are derived only from canonical marks observed while open. If those marks are missing, MFE/MAE stay null.

## 5. Decision journal

Journal events are concise structured artifacts. They are not chain-of-thought.

Recorded:

- every accepted overnight 14-seat decision, including `HOLD`
- every applied automated PM decision
- every applied ChatGPT PM decision
- full on-demand Trader Room original pitches and rebuttals as `TRADER_ROOM_PROPOSAL` / `TRADER_ROOM_REBUTTAL`

On-demand pitches and rebuttals do not become executed ledger trades.

## 6. Rationale contract

- `OPEN` / `ADD` / `HEDGE`: fail closed if expansion rationale is missing (`thesis`, `rationale`, `note`, or `expression_memo.rationale`).
- `REDUCE` / `CLOSE`: never block de-risk because prose is missing. Execute the deterministic action, store `rationale_status=missing_required`, raise an alert, and create `postmortem_due` on close.
- `HOLD` / `NO_TRADE`: always allowed.

## 7. Learning gate

Memory mechanics must not block `HOLD` / `NO_TRADE` / `REDUCE` / `CLOSE`.

Risk-expanding `OPEN` / `ADD` / `HEDGE` fail closed when:

- `memory_context_sha256` is missing or does not match the frozen own-identity snapshot for that seat/run; or
- the identity has outstanding `postmortems_due` created on a prior run.

A trade closed in the current run becomes `postmortem_due` for a later decision opportunity. Same-run hindsight is not required.

Trusted code accepts a postmortem only for a closed trade owned by that identity. Reflection cannot change entry/exit marks or P&L. Durable lessons must cite owned `trade_id`s or `postmortem_id`s. Active lessons are capped at 12.

## 8. Overnight consumption

The 01:50 freeze snapshots each trader's own memory sidecar and stores the hashes on the evidence snapshot as `seat_memory.hashes` without placing another seat's private context in the common packet.

The Grok overnight parent must pass each trader child only:

- the common frozen agent packet; and
- that trader's own frozen memory sidecar / `memory_context_sha256`.

Each accepted expanding decision must reference the memory hash it used. Trusted validation checks that the hash belongs to that seat and run. De-risk and HOLD remain possible on memory failure.

Do not edit the ACP schedule to implement this. `docs/OVERNIGHT_PIPELINE_V1.md` is the provider-facing contract.

## 9. Full Trader Room consumption

At run freeze, each of the 14 advocates gets an own-memory sidecar. The common evidence hash remains identical. `launch_plan.json` carries per-advocate `memory_sidecar_path` and `memory_context_sha256`. After validation/finalization, pitches and rebuttals are journaled. Locked remits, context-first gate, conflict flow, and the ChatGPT-arbiter boundary are unchanged.

## 10. PM consumption

Every PM review packet includes only that PM's compact memory context, calibration, and `postmortems_due` plus its own prior book. Automated PM and ChatGPT decision schemas accept `memory_context_sha256`, `postmortems`, and `memory_updates`. Trusted apply code validates those after deterministic book actions. ChatGPT ingest keeps stale-packet and idempotency protections. This prepares all four PMs; it does not enable a new automation.

## 11. Deterministic vs model-authored

Trusted code owns:

- trade_id / position_id linkage
- marks, notional, realized increments, holding period, MFE/MAE
- calibration stats
- persistence of ledger/journal/memory files

Models may supply:

- actions, thesis, rationale, invalidation, conviction
- structured postmortems and lesson add/reinforce/retire
- the memory-context hash they were given

Models may not author books, NAV, cash, P&L, canonical marks, or ledger facts.

## 12. Workflow persistence

Trusted overnight scheduled-output and ChatGPT ingest workflows persist generated `data/trading/**` together with canonical book changes. `pull_request_target` still runs trusted base code. A decision/output PR cannot smuggle model-authored ledger or memory facts: generated trading-memory state is rebuilt from trusted code and then copied onto the branch.

## 13. Migration

Initialize from current canonical books. Reconstruct only fields proven by live positions and matching open-position history. Preserve null for missing historical rationale or exit detail. Do not convert old Trader Room proposals into executed trades. Do not fabricate closed trades. Legacy empty books initialize to empty ledgers, empty journals, and empty calibration.

## 14. Prompt discipline

The lifetime ledger and journal may grow in Git. The memory prompt surface stays bounded: deterministic calibration, up to 8 recent closed trades, up to 12 active lessons, outstanding postmortems, and current open-position context. Do not stuff the complete journal into a prompt. No vector database, embeddings, or new external state service.
