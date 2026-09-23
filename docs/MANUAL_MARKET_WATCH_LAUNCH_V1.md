# Market Watch — manual launch contract (design, not yet implemented)

Status: approved direction, implementation pending. September 23, 2026. Source of truth for future implementation is current `main`, not any earlier Cursor working tree. This document is the implementation contract for the next targeted build, not a claim that a one-command launcher exists.

## Operator intent

The only new trading-day trigger is Kevin saying **"launch market watch"** (or an equivalent authenticated explicit manual GitHub command). Once launched, deterministic and provider stages run in order, on **one** immutable session/review identity, with no independent weekday stage clocks, scheduled provider call, automatic data refresh or timed Pages publishing. PR validation and event-driven output acceptance remain allowed because they are consequences of the operator-triggered run. No model call is authorized merely by the passage of time.

ACP schedule `market-watch-weekday-0205` was disabled in ACP PR #147 without changing ACP's shared provider-control infrastructure. Market Watch PR #110 retires independent collection/overnight/Pages triggers while preserving manual stage dispatch and CI. The new macro-ingestion workflow introduced by PR #109 is already `workflow_dispatch` only.

## Required orchestration DAG

```
EXPLICIT HUMAN "launch market watch"
  |
  v
00 AUTHENTICATE + RESERVE UNIQUE LAUNCH (session_date_NY, launch_id; same-day review_id allocated by trusted code)
  |
  v
01 LIVE PRIMARY-SOURCE INGESTION (US/CA/AU/NZ/EA/JP; preserve all verified vintages;
   run scoped publisher checks, including scored and context sources; persist raw receipts)
  |
  v
02 REFRESH MARKET STATE + NEWS + CURVES/OIL/FX/POSITIONING
  |  Independent acquisition jobs may parallelize, but neither may bypass gate 03.
  v
03 PRE-TRADER QUALITY GATE (reconcile catalog->canonical histories/scores, verified
   release periods, coverage/freshness by country and expression, risk-input markability)
  |  FAILURE: stop before ACP/traders and show actionable BLOCKED data report, not a HOLD signal.
  |  PARTIAL: optional/known proprietary gaps stay explicit; only affected expressions
  |  are unavailable. Do not demand that all 119 catalog rows become ingestible.
  v
04 TRUSTED REVIEW FREEZE (one current-time evidence cutoff, starting trader/PM book
   hashes, review-### scoped identity; commit immutable packet before provider dispatch)
  |
  v
05 DISPATCH ONE BOUNDED ACP CURSOR RUN FROM EXISTING HUMAN AUTHORIZATION
  |  bounded research on frozen base -> final common agent packet -> 14 independent
  |  trader decisions -> 3 independent automated PMs using only private prior memory.
  |  No trader/PM provider call if stage 03 or 04 failed; no duplicate calls on retry.
  v
06 TRUSTED ACCEPTANCE GATE (existing data-only [overnight-output] PR, exact hashes,
   14 seats/3 PMs, invocation policy, canonical deterministic book/P&L application)
  |  Rejected/late provider output must never be displayed as a completed HOLD review.
  v
07 FINAL LIVE DELTA -> ASSEMBLE CURRENT DATASET -> PUBLICATION GATE
  |  Verify same launch_id/session/review, current canonical books, macro score
  |  lineage, required markable market-state inputs and accepted trader+PM outputs.
  v
08 EXPLICIT PAGES DEPLOY + VERIFY PUBLIC HTML/JSON AND EXACT ACCEPTED REVIEW.
```

Every stage must have durable `pending/running/succeeded/blocked/failed` state and a receipt (input/ref SHA, output/ref SHA, started/finished timestamps, structured reason and URL). Do not attempt a later stage merely because a preceding GitHub job finished with exit code 0; verify the domain contract, persisted data and expected session/review. Concurrency is one active Market Watch production launch. A duplicate launch command must return the existing run; a new same-day review requires a deliberate explicit rerun request. Restarts resume after last verified stage, without replacing frozen evidence or applying accepted decisions twice.

## Hard requirement: one command with correct ACP authority

Today ACP authenticates direct human-created `[agent-run]` issues and refuses bot-manufactured ones. An Actions bot MUST NOT create an ordinary `[agent-run]` issue to evade authorization. A full autonomous handoff after stage 04 requires a **minimal, explicitly approved ACP mechanism** for one-shot deferred authority tied to the original authenticated human launch, target repo, launch_id, latest trusted packet hash and allowed provider/model budget. ACP should dispatch only on receipt of a verified `freeze-succeeded` event. Prefer a small additive ACP handoff contract over changing existing provider runtime, global scheduler, credentials or other projects. If this ACP addition is not authorized, implement a clear stage-04 stop requiring Kevin's separate authorized ACP launch; do not claim one-command operation is complete.

The default user-facing launch path should be available from ChatGPT's connected GitHub action (an authenticated dedicated Market Watch launch issue) and optionally GitHub `workflow_dispatch`. It should create **one** auditable launch receipt/URL. GitHub jobs and GitHub events, not an open ChatGPT session, own continuation.

## Prevent false HOLD from broken inputs

Preserve genuine `OPEN/ADD/HOLD/REDUCE/HEDGE/CLOSE` decisions and existing trade-specific risk gates. A prior-book HOLD can be an intentional choice; do not force trading. Treat `macro_hard` stale/missing due releases and source errors as named upstream data failures, never as 14 automatically generated HOLD decisions. Integrate PR #109's live six-country ingest output into existing `scripts/overnight/collect.py` and `scripts/macro_freshness.py`; currently separate workflows and old source checks are insufficient. Before stage 04, verify that all *required* trade-marking preflight legs are available, that core macro series and source checks have true release-aware status, and that per-country/leg gaps are attached to the frozen evidence. A missing source in one country blocks only dependent new-risk expressions; unaffected markets remain eligible. If no meaningful tradeable universe or current trusted freeze exists, STOP and surface actionable BLOCKED instead of paying for a trader cycle destined to be risk-blocked.

Data gate status `BLOCKED` is an operational outcome outside trader decisions. `HOLD` is a voluntary trader decision within a valid review. Distinguish an existing position retained unchanged from a new-trade refusal. Preserve research/level-analysis expectations: bounded common research and historical levels must precede the final trader packet. Keep the locked roster, independent seat/PM memories, portfolio risk/funding model, scope and accepted historical reviews unchanged.

## Cutoff and publication semantics

A manually triggered session uses its actual trusted freeze timestamp, **not** the old 01:50 ET logical clock, as the decision evidence boundary. Data published after the freeze may enter a separately timestamped delta/current web state but cannot be retroactively represented in that review. Preserve every previously accepted `overnight-YYYYMMDD/review-###` packet and its hashes. Do not let accepted-output PR merges or any unrelated code push independently publish an incomplete run; deployment must be explicitly invoked by the orchestrator **after** stage 07 succeeds. An automated publishing event is valid only as a continuation of the initiating launch_id.

## Definition of done

- No Market Watch cron-driven deterministic stages, Pages clock/push trigger or ACP weekday model dispatch remain enabled.
- One authenticated command creates one unique run; deterministic stages actually run in DAG order and data is persisted/reloaded before freeze; no model is invoked on an upstream failure.
- Exercise real bounded six-economy live ingestion, score bridge, oil/market-state and release-aware source freshness, with explicit partial-series gap matrix and no invented values.
- A stub/mock provider proves the end-to-end accepted 14-trader/3-PM output, book/P&L update, final delta, assembled dataset and explicit Pages dispatch/verification. Real ACP handoff requires the separate approved one-shot authority work.
- Integration tests for missing source, all-critical sources stale, partial-country gap, missing frozen packet, duplicate launch, rejected/late output, same-day distinct review, SHA drift, missing market marks and Pages state mismatch.
- Retain PR validation, immutable accepted review history, budget hooks and deterministic acceptance. No silently manufactured HOLD or automatic provider retries.
