Run the on-demand Market Watch Trader Room debate. If the user says `go`, that is sufficient.

Read `docs/TRADER_ROOM_PROTOCOL.md`, `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`, `docs/TRADER_RESEARCH_METHOD.md`, and `docs/TRADER_ROOM_ON_DEMAND.md` first. You are not the arbiter. ChatGPT in the Market Watch Trader Room is the sole arbiter.

This workflow runs in Cursor Cloud. Do not require a local checkout, local terminal, or local Cursor session.

The deterministic repository entrypoint is:

```bash
PYTHONPATH=. python scripts/trader_room_go.py go --topic "<user text or go>"
```

## 1. Preflight and freeze

Attempt and status all four required evidence families. Build one packet containing exactly the required sections:
- `temperature_gauges`
- `central_bank_research`
- `news_and_research`
- `market_state`
- `research_method`
- `source_index`
- `known_gaps`

Freeze the packet and SHA-256. Every downstream model receives the exact same frozen common evidence packet. Snapshot each advocate's own learning-memory sidecar separately; do not put another seat's private memory into the common packet. Each sidecar is mandatory private state for that seat and contains its current open positions / durable learning context. No browse/search/new evidence after freeze.

## 2. Round 1

Launch all 14 standing advocates concurrently on exact `grok-4.6`. Keep the standing remits unchanged.

Expression selection is mandatory before submission:
- `dollar-king` and `cross-merchant` remain spot-only;
- `vol-convexity` remains the options specialist and is not forced through a rates tenor scan;
- every other seat is rates-first when it submits a trade: first complete `rates_tenor_scan` across STIR/policy path, 2Y, 5Y, 10Y, curve, and cross-market rates RV (each bucket a concrete candidate or an explicit unavailable/not-compelling reason), then choose the best rates expression and compare it with a spot candidate. The selected bucket’s canonical `instrument`/`asset_class` must equal `expression_comparison.rates_candidate`; free-text cannot prove that linkage. Prefer rates when comparably clean, and select spot only with an explicit reason the selected rates candidate is inferior or unavailable. Do not force a tenor and do not force rates over spot;
- `no-trade-skeptic` may still return no trade without manufacturing the scan.

Each initial advocate must build the idea in this order: context -> what changed -> what is priced -> historical comparison -> discrepancy -> expression -> sizing. A percentile/z-score is a discovery flag, not a thesis. Complete the validated `context_build` before selecting risk. For rates, use `policy_paths` to understand what is priced, then choose the actual expression from `tradable_rate_curves` (SOFR=`SR3`, CORRA=`CRA`, AONIA=`IB`) or from the sovereign bond curve when that is cleaner. Use the packet's historical move analogs and explicitly state both similarities and regime differences.

Paper-action direction is canonical and must never use trader shorthand ambiguously:
- for `asset_class` `rates`, `curve`, or `rates_rv`, `side: "long"` means long duration / receive the canonical mark and profits when that mark falls;
- for those same asset classes, `side: "short"` means short duration / pay the canonical mark and profits when that mark rises;
- every rates/curve/rates_rv `OPEN` must also include `expected_mark_direction: "lower"|"higher"`; trusted validation requires `lower -> side long` and `higher -> side short`;
- never write `side: "long"` merely to mean "long the implied rate." If the thesis is higher implied rates, the book action is `side: "short"`;
- when the primary debate `trade` and an `OPEN` paper action refer to the same rates instrument, `trade.direction` must equal the canonical paper-action `side`. This keeps deterministic conflict routing consistent with the actual risk.

Paper execution is at deterministic packet mid. A broker-executable quote is not required for the paper book. The core tradable rates curves are SOFR via CME `SR3`, CORRA via MX `CRA`, and AONIA via ASX `IB`; sovereign bond curves remain a separate valid expression family. The curve family chosen at OPEN is locked for that position and must be used for every subsequent ADD/REDUCE/CLOSE/re-mark. Do not silently switch a bond trade to SOFR/CORRA/AONIA or vice versa. Direct contracts use the frozen implied-rate/yield mid. Linear spreads/flies and forward windows are valid. For a futures-curve forward/fwd-fwd, prefer `{"type":"futures_strip_average","curve_id":"CORRA","expiries":["2028-03","2028-06","2028-09","2028-12"]}` (with optional explicit weights); the advocate or permitted Composer subagent chooses the exact contracts, and trusted code owns the arithmetic and replay. `official_curves` may still support an explicitly selected government-bond forward expression, but they are supplemental bond curves, not a manufactured swap/OIS curve. Swap-spread trades are out of scope until both legs are deliberately supported.

Each initial advocate:
- may use at most two `composer-2.5` subagents;
- must remain on the frozen packet;
- must read exactly its own immutable sidecar at the path recorded for that seat in the frozen launch plan (normally `trader-room/runs/<run_id>/memory/<seat>.json`) before making any book decision;
- must treat `open_positions` in that sidecar as its current book and use the existing `position_id` for `ADD`, `REDUCE`, or `CLOSE`;
- must return one validated `TRADER_ROOM_CONTRIBUTION`;
- except `no-trade-skeptic`, must return one actionable debate trade;
- must include the complete compact `conflict_synopsis` required by `docs/TRADER_ROOM_ON_DEMAND.md`;
- must include a non-empty final `paper_actions` list for its own competition book. The list may contain zero risk changes via `[{"action":"HOLD"}]`, or any number of independent `OPEN` / `ADD` / `REDUCE` / `CLOSE` / `HEDGE` actions. There is no one-trade limit. The single `trade` field remains the primary debate pitch only;
- must not rely on legacy `paper_capital` for a new live run. That field remains compatibility-only;
- must manage the existing book, not re-open an already-owned position as a new trade merely because it is the primary pitch. Notional is descriptive, not the risk budget. Trusted code caps each $100m-paper-NAV seat at **$10m of standard-shock risk capital** and enforces a **$5m high-water-mark drawdown stop**. Size from path risk and historical adverse excursion; do not mechanically fill the risk-capital limit. Official SOFR ACT/360 is the zero-return benchmark and is charged on shocked risk capital, so a flat book has zero net financing P&L and equal risk capital receives equal financing treatment across asset classes.

Do not show Round 1 outputs or another seat's private sidecar to other advocates.

## 3. Validate

Validate roster/remit, schema, evidence refs, packet hash, null levels, confidence, `asset_class`, `expression_comparison`, `context_build`, `conflict_synopsis`, and the explicit non-empty `paper_actions` book decision. Reject malformed work; do not silently guess missing fields or substitute an implicit HOLD.

## 4. Deterministic conflict stage

Do NOT launch `conflict-aggregator`.

Run deterministic synopsis mapping:

```bash
PYTHONPATH=. python scripts/trader_room_conflict_map.py --run-dir trader-room/runs/<run_id>
```

This produces `conflict_map.json` and `rebuttal_assignments.json` with zero model calls.

Direct conflicts route rebuttals:
- opposite same-instrument direction;
- opposite USD/CAD/AUD/NZD directional view.

Theoretical/context tensions are visible but do not automatically trigger model calls:
- currency higher vs same-country rates lower;
- currency lower vs same-country rates higher;
- risk-on vs risk-off;
- carry supports vs opposes.

The no-trade challenge is preserved without forcing all traders into rebuttal calls.

## 5. Round 2

Each directly conflicted advocate gets exactly one `grok-4.6` rebuttal pass. No subagents. No new evidence.

Give each advocate only:
- frozen packet;
- its own original, including its Round-1 `paper_actions`;
- its own private memory sidecar/current positions;
- its deterministic assignment;
- the relevant opposing original trades.

The advocate may defend, amend, or withdraw and must shoot holes in the opposing case. Every rebuttal must state the final book action set explicitly in `paper_actions`. If the trade is unchanged, it may repeat the Round-1 actions. If the trade is amended, the list must replace the Round-1 intent with the amended final actions. If the trade is withdrawn, the final actions must contain no `OPEN`, `ADD`, or `HEDGE` for that withdrawn idea; use `HOLD` and/or valid de-risk actions for existing positions. Deterministic validation must reject an amended/withdrawn rebuttal that leaves the Round-1 book intent ambiguous.

## 6. Deterministic final handoff

Do **not** launch `final-aggregator`. After all routed rebuttals validate, build the PM handoff directly from the saved structured artifacts:

```bash
PYTHONPATH=. python scripts/trader_room_finalize.py --run-dir trader-room/runs/<run_id>
```

This finalizer reads the already-validated 14 originals, deterministic conflict map and routed rebuttals, then writes `pm_handoff.json`, `artifact_index.json`, and the final receipt. It consumes zero model calls and must not reread or summarize the full evidence packet beyond its frozen metadata/known gaps.

Do not create `FINAL_INPUT.json`, `FINAL_INPUT.compact.json`, or `FINAL_INSTRUCTIONS.md`; those were recovery artifacts from the old model-based final aggregator and are no longer part of production.

No winner, ranking, house view, or official decision.

Persist the complete run under `trader-room/runs/<run_id>/` and end with exactly:

`STATUS: AWAITING_CHATGPT_ARBITRATION`

Optional private Markdown copy may use Google Drive folder `1NS6Qb6vNGKM18_PW0zPl4NOIJZOLyfUD`. Repository artifacts are authoritative.

## Learning memory, consequence, and reflections

Before any book decision, read your own frozen sidecar (`memory/<seat>.json`). It includes **consequence** (your rank among 14, own P&L/NAV/drawdown/risk utilization — never other seats' P&L or spread-to-winner), **active_lessons**, **postmortems_due**, and **reflections_due** from prior runs.

- Prior-run **postmortems_due** or **reflections_due** are mandatory on this invocation, including when you choose `HOLD` or `NO_TRADE`. A causal `causal` block is required. P&L summaries and platitudes do not clear debt. `NO_NEW_LESSON` is valid only when you explain ordinary bounded variance or why the prior process remains sound.
- `OPEN`/`ADD`/`HEDGE` stay blocked until that debt is cleared. Unresolved debt is learning default: competitive eligibility is removed while raw P&L rank stays auditable. `HOLD`/`REDUCE`/`CLOSE` remain executable.
- On expansion, supply `setup_fingerprint` and address every materially matching own lesson with `lesson_considerations` (`APPLIES`, `DOES_NOT_APPLY`, or `OVERRIDE`) and a substantive rationale. You do not see peer lessons.
- A same-run `CLOSE` creates a future postmortem due; it does not block sibling actions in that decision.
- Material drawdown/win triggers require a structured **performance_reflection** (not prose acknowledgement alone). You may answer with a durable lesson or explicit `no_new_lesson` plus reason.
- Do not invent canonical P&L, rank, or marks; trusted code owns books.

## Hard limits

Full run policy:

`MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}`

- total Grok ceiling 29 including ACP parent;
- Composer ceiling 28;
- total model ceiling 57;
- Auto and Other Models prohibited;
- no silent retries or reroutes.

Return only the run receipt/artifact handoff. ChatGPT performs arbitration.
