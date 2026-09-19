# Round 1 instructions — frozen packet only

TRADER_ROOM_ADVOCATE=1
MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}
ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["composer-2.5","grok-4.6"]}

Run ID: `tr-20260919T214000Z-ondemand`
Evidence cutoff: `2026-09-19T21:40:00Z`
Packet SHA-256: `f8424b8ac50590dd4d26c54f91e2558b648d2dfe97372081e8f0f7479e69183d`

Read only:
- `trader-room/runs/tr-20260919T214000Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260919T214000Z-ondemand/PACKET_FACTS.json`
- `trader-room/runs/tr-20260919T214000Z-ondemand/advocate_card.json`
- `trader-room/runs/tr-20260919T214000Z-ondemand/memory/<your-seat>.json` (your memory only)
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Mandatory idea-building order: context -> what changed -> what is priced -> historical comparison -> discrepancy -> expression -> sizing.
A z-score, percentile, spread extreme, or correlation break may be a discovery signal only, never the thesis.
Complete a validated `context_build` before selecting risk.
For rates, inspect the frozen SOFR/CORRA/AONIA-linked policy path before sovereign curves or RV.
Use packet historical move analogs and explicitly state similarities AND regime differences.

Paper execution is at deterministic packet mid. Prefer markable expressions:
- spot FX pairs present in `market_state.fx.pairs`
- `SOFR_YYYY-MM` / `CORRA_YYYY-MM` / `AONIA_YYYY-MM` or exchange codes from the frozen tradable curves
- `{"type":"futures_strip_average","curve_id":"SOFR|CORRA|AONIA","expiries":["YYYY-MM",...]}`
- sovereign bonds `US_2Y` / `CA_10Y` / `AU_2Y` etc. when that family is cleaner

Official NY Fed SOFR is the realized funding authority (latest published prior-day fixing, ACT/360, no later true-up). SR3 is forward context only. There is no 5% assumption.

Return exactly one JSON object matching `scripts/trader_room/schema.py`.
