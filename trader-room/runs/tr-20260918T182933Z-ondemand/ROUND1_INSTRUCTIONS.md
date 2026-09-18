# Round 1 instructions — frozen packet only

Run ID: `tr-20260918T182933Z-ondemand`
Evidence cutoff: `2026-09-18T18:29:33Z`
Packet SHA-256: `63f781354ed4048cf1091125e35854ed64db800467e7a98c336cf72032a33956`

Read only:

- `trader-room/runs/tr-20260918T182933Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260918T182933Z-ondemand/advocate_card.json`
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Return exactly one JSON object, no prose, matching `scripts/trader_room/schema.py`.

Required contribution keys: `type`, `run_id`, `round`, `agent`, `archetype`, `stance_summary`, `trade`, `confidence`, `remit`, `packet_sha256`.

- `type` = `TRADER_ROOM_CONTRIBUTION`
- `run_id` = `tr-20260918T182933Z-ondemand`
- `round` = `1`
- `remit` must equal the locked standing remit string exactly
- `confidence` integer 0-100
- `packet_sha256` = `63f781354ed4048cf1091125e35854ed64db800467e7a98c336cf72032a33956`

Required trade keys: `instrument`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs`, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`.

- `why_now`, `evidence_refs`, `catalysts`, `principal_risks` = non-empty string lists
- `evidence_refs` must be IDs from `advocate_card.json` `allowed_evidence_refs`
- `entry`, `target`, `stop`, `invalidation`, `structure` = sourced string or JSON `null`
- Do not invent executable levels
- Every seat except `no-trade-skeptic` must submit one actionable trade
- `no-trade-skeptic` may set `trade` to JSON `null`

Optional useful keys: `macro_assumptions` object using keys `growth` (`above_trend`|`below_trend`), `risk` (`risk_on`|`risk_off`), `rates` (`higher_for_longer`|`easing_cycle`), `policy` (`hawkish`|`dovish`); `subagent_calls` integer 0-2; `subagent_model` `composer-2.5` or null.

You may launch at most two internal `composer-2.5` subagents. They inherit this frozen packet and may not acquire new evidence. Aggregators/rebuttals are not your job.
