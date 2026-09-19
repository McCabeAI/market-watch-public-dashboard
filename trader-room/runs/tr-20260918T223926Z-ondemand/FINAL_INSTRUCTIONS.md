# Final aggregator instructions — frozen packet only

Run ID: `tr-20260918T223926Z-ondemand`
Evidence cutoff: `2026-09-18T22:39:26Z`
Packet SHA-256: `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`

You are the Trader Room `final-aggregator`. Organize a PM handoff. You are not the arbiter.

Do not select a winner, produce a house view, rank, average into consensus, call a trade approved, or create a surrogate PM/chair. Forbidden keys anywhere in the payload: `winner`, `winners`, `house_view`, `ranking`, `rank`, `leaderboard`, `approved_trade`, `recommended_trade`.

Do not browse, search, fetch, or acquire new evidence. Do not launch subagents. Do not read `trader-room/runs/tr-20260918T182933Z-ondemand/` or any earlier run.

Read only:

- `trader-room/runs/tr-20260918T223926Z-ondemand/FINAL_INSTRUCTIONS.md`
- `trader-room/runs/tr-20260918T223926Z-ondemand/FINAL_INPUT.json`
- `trader-room/runs/tr-20260918T223926Z-ondemand/evidence_packet.json` (known gaps / family status if needed)
- `.cursor/agents/final-aggregator.md`

Return ONLY one `TRADER_ROOM_PM_HANDOFF` JSON object. No extra prose.

## Required keys

`type`, `run_id`, `evidence_cutoff`, `proposed_trades`, `agreement_clusters`, `conflicts`, `strongest_evidence_by_side`, `rebuttals`, `amendments_and_withdrawals`, `shared_assumptions`, `unresolved_questions_and_gaps`, `artifact_index`, `status`

Optional useful keys: `theoretical_tensions`, `context_tensions`, `challenges`, `packet_sha256`

## Exact values

- `type` = `TRADER_ROOM_PM_HANDOFF`
- `run_id` = `tr-20260918T223926Z-ondemand`
- `evidence_cutoff` = `2026-09-18T22:39:26Z`
- `status` = exactly `STATUS: AWAITING_CHATGPT_ARBITRATION`
- `packet_sha256` = `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`
- `artifact_index` = copy `required_artifact_index` from FINAL_INPUT.json unchanged

## proposed_trades

Array of 14 objects, one per original seat. Each item: `{"agent": "<seat>", "ref": "trader-room/runs/tr-20260918T223926Z-ondemand/submissions/<seat>.json", "trade": <original trade or null>}`.
Preserve every original proposed trade. Do not replace with rebuttal revisions unless you also record the revision under amendments.

## rebuttals

Object keyed by the 12 routed seats only (not `no-trade-skeptic` or `positioning-cynic`). Each value: `{"ref": "trader-room/runs/tr-20260918T223926Z-ondemand/rebuttals/<seat>.json", "trade_change": "unchanged", "strongest_opponent_point": "<short string>"}`.

## conflicts

Array whose length equals the 3 direct conflicts in FINAL_INPUT. Include `id`, `kind`, `agents`, `description`. No ranking.

## Other sections

- `agreement_clusters`: thematic clusters of seats that proposed similar expressions (instrument/direction), not a ranking.
- `strongest_evidence_by_side`: map or list of sides with cited packet evidence refs already in the freeze.
- `amendments_and_withdrawals`: all 12 routed seats defended unchanged; record that explicitly. No amendments or withdrawals.
- `shared_assumptions`: facts both sides used from the freeze.
- `unresolved_questions_and_gaps`: include packet `known_gaps` plus debate leftovers (NZ yields unavailable, no positioning, no executable levels, market_state stale).
- Copy theoretical_tensions, context_tensions, and the no-trade challenge so ChatGPT can see them without treating them as routed rebuttals.

MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":58,"grok_cap":30,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["composer-2.5","grok-4.6"]}
