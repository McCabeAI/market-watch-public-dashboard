# Round 2 rebuttal — frozen packet only, no subagents

TRADER_ROOM_ADVOCATE=1
MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}

Run ID: `tr-20260920T020818Z-ondemand`
Evidence cutoff: `2026-09-20T02:08:18Z`
Packet SHA-256: `349a16aeeda7f4a89e10ba16c22c90311da76536984e943cf04249588d954e1e`

This is a **rebuttal pass**. You are only this seat. You may defend, amend, or withdraw.

## Allowed reads

- `trader-room/runs/tr-20260920T020818Z-ondemand/ROUND2_INSTRUCTIONS.md`
- `trader-room/runs/tr-20260920T020818Z-ondemand/round2/<YOUR_SEAT>.assignment.json`
- `trader-room/runs/tr-20260920T020818Z-ondemand/submissions/<YOUR_SEAT>.json` (your Round-1 original, including `paper_actions`)
- `trader-room/runs/tr-20260920T020818Z-ondemand/memory/<YOUR_SEAT>.json` (your private sidecar / current book only)
- `trader-room/runs/tr-20260920T020818Z-ondemand/PACKET_FACTS.json`
- `trader-room/runs/tr-20260920T020818Z-ondemand/evidence_packet.json` (frozen; no new evidence)
- `trader-room/runs/tr-20260920T020818Z-ondemand/advocate_card.json`
- `docs/TRADER_RESEARCH_METHOD.md` and your standing remit in `.cursor/agents/<YOUR_SEAT>.md`

Do **not** read another seat's `memory/` sidecar. Do **not** read PM books, other PM packets, or another seat's private state. Compact opposing Round-1 trades in your assignment file are the only opponent material you may use.

No web, search, browse, or new evidence. No subagent calls of any kind (including composer-2.5). `subagent_calls` must be 0.

## Required output

Return exactly one JSON object, no prose.

```json
{
  "type": "TRADER_ROOM_REBUTTAL",
  "run_id": "tr-20260920T020818Z-ondemand",
  "round": 2,
  "agent": "<YOUR_SEAT>",
  "opponents": ["...exactly the opponents listed in your assignment..."],
  "own_original_ref": "submissions/<YOUR_SEAT>.json",
  "holes_in_opposing_case": ["non-empty list of attacks on the opposing case"],
  "attack": ["..."],
  "defense": ["..."],
  "trade_change": "unchanged | amended | withdrawn",
  "revised_trade": {},
  "paper_actions": [],
  "packet_sha256": "349a16aeeda7f4a89e10ba16c22c90311da76536984e943cf04249588d954e1e",
  "subagent_calls": 0
}
```

Rules:
- `opponents` must be the assignment list (no extras).
- `holes_in_opposing_case` is mandatory and must actually shoot holes in the opposing case.
- If `trade_change` is `unchanged`, `revised_trade` may repeat the Round-1 trade (or be that same object) and `paper_actions` may repeat the Round-1 actions.
- If `trade_change` is `amended`, `revised_trade` must be a complete valid trade and `paper_actions` must **replace** Round-1 expansion intent with the amended final book actions.
- If `trade_change` is `withdrawn`, `revised_trade` must be JSON `null` and `paper_actions` must contain **no** `OPEN`, `ADD`, or `HEDGE` for the withdrawn idea. Use `HOLD` and/or valid de-risk actions for existing sidecar positions.
- `paper_actions` is mandatory, non-empty. `[{"action":"HOLD"}]` is the explicit no-change book. OPEN/ADD/HEDGE need instrument, side, notional_usd, asset_class, rationale/thesis. Manage existing positions by `position_id`. Sidecar books are currently empty.
- Do not invent marks. Trusted code owns the $100m gross cap, fills, and P&L.
- Never invent levels; use explicit nulls. Evidence refs must remain inside the frozen packet.
- Do not rank, pick a winner, or produce a house view.

Shoot holes first, then state the final book explicitly.
