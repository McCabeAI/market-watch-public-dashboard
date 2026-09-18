# Round 2 rebuttal instructions — frozen packet only

Run ID: `tr-20260918T223926Z-ondemand`
Evidence cutoff: `2026-09-18T22:39:26Z`
Packet SHA-256: `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`

You are one locked standing advocate making exactly one rebuttal pass. Deterministic conflict mapping already selected you because of a **direct** currency-view or same-instrument conflict. Theoretical/context tensions and the no-trade challenge do not require a rebuttal from you.

This is a new run. Do not read, copy, continue, or adapt any file under `trader-room/runs/tr-20260918T182933Z-ondemand/` or any earlier run.

Read only:

- `trader-room/runs/tr-20260918T223926Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260918T223926Z-ondemand/submissions/<your-seat>.json`
- `trader-room/runs/tr-20260918T223926Z-ondemand/rebuttal_briefs/<your-seat>.json`
- `trader-room/runs/tr-20260918T223926Z-ondemand/ROUND2_INSTRUCTIONS.md`
- your standing remit in `.cursor/agents/<your-seat>.md`

After freeze: no web, search, browse, fetch, or new evidence. Do not launch any subagents. `subagent_calls` must be absent or 0.

Return only one validated `TRADER_ROOM_REBUTTAL` JSON object. No extra prose.

## Rebuttal schema

Required keys: `type`, `run_id`, `round`, `agent`, `opponents`, `own_original_ref`, `holes_in_opposing_case`, `trade_change`, `revised_trade`, `attack`, `defense`, `packet_sha256`.

- `type` = `TRADER_ROOM_REBUTTAL`
- `run_id` = `tr-20260918T223926Z-ondemand`
- `round` = `2`
- `agent` = your locked seat name
- `opponents` = a non-empty list drawn only from your brief's `assignment.opponents`
- `own_original_ref` = `trader-room/runs/tr-20260918T223926Z-ondemand/submissions/<your-seat>.json`
- `holes_in_opposing_case` = non-empty list of strings; you must explicitly shoot holes
- `trade_change` = `unchanged` | `amended` | `withdrawn`
- `packet_sha256` = `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`
- `attack` and `defense` = non-empty strings
- Useful optional keys: `strongest_opposing_claim`, `what_would_concede`, `uncertainty`

Trade-change rules:

- `unchanged`: keep the Round 1 trade; set `revised_trade` to that same valid trade object (or null only if your original trade was null).
- `amended`: `revised_trade` must be a complete valid trade object for your seat.
- `withdrawn`: `revised_trade` must be JSON `null`.

## Expression mandate if you amend

- `dollar-king` and `cross-merchant` remain spot-only: `asset_class`=`spot_fx`, `selected`=`spot`, concrete `spot_candidate`.
- `vol-convexity` remains options-focused: `asset_class`=`options`, `selected`=`options`.
- Every other seat that keeps or amends a trade is rates-first: concrete `rates_candidate` and `spot_candidate`; prefer rates when comparably clean; `selected` must match `asset_class`.
- `evidence_refs` must be IDs already in the frozen packet. Do not invent levels.

Identify the strongest opposing claim, attack weaknesses, state your defense, preserve uncertainty, and say what would concede the argument.

MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":58,"grok_cap":30,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}
ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["composer-2.5","grok-4.6"]}
