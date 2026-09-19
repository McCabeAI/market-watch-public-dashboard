# Round 1 instructions — frozen packet only

TRADER_ROOM_ADVOCATE=1
MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}

Run ID: `tr-20260919T123430Z-ondemand`
Evidence cutoff: `2026-09-19T12:34:30Z`
Packet SHA-256: `8903f3edceded5a5d9866d84bd422940ebc0c93106b761fbcb6267449e9504f9`

Read only:
- `trader-room/runs/tr-20260919T123430Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260919T123430Z-ondemand/advocate_card.json`
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Mandatory idea-building order: context -> what changed -> what is priced -> historical comparison -> discrepancy -> expression -> sizing.
A z-score, percentile, spread extreme, or correlation break may be a discovery signal only, never the thesis.
Complete a validated `context_build` before selecting risk.
For rates, inspect the frozen SOFR/CORRA/AONIA-linked policy path before sovereign curves or RV.
Use packet historical move analogs and explicitly state similarities AND regime differences.

Return exactly one JSON object, no prose, matching `scripts/trader_room/schema.py`.

Required contribution keys: `type`, `run_id`, `round`, `agent`, `archetype`, `stance_summary`, `trade`, `confidence`, `remit`, `conflict_synopsis`, `packet_sha256`.

- `type` = `TRADER_ROOM_CONTRIBUTION`
- `run_id` = `tr-20260919T123430Z-ondemand`
- `round` = 1
- `remit` must equal the locked standing remit string exactly
- `confidence` integer 0-100
- `packet_sha256` = `8903f3edceded5a5d9866d84bd422940ebc0c93106b761fbcb6267449e9504f9`

Required trade keys: `instrument`, `asset_class`, `expression_comparison`, `context_build`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs`, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`.

- `why_now`, `evidence_refs`, `catalysts`, `principal_risks` = non-empty string lists
- `evidence_refs` must be IDs from `advocate_card.json` `allowed_evidence_refs`
- `entry`, `target`, `stop`, `invalidation`, `structure` = sourced string or JSON `null`
- Do not invent executable levels
- Every seat except `no-trade-skeptic` must submit one actionable trade
- `no-trade-skeptic` may set `trade` to JSON `null`

`context_build` is a hard gate. It must include:
- causal_mechanism
- path_to_current_price
- known_vs_new_information
- market_implied_assumption
- market_assumption_disagreed_with
- price_decomposition
- historical_reference.distribution
- historical_reference.analogs (at least one comparable episode or an explicit no-analog statement)
- historical_reference.regime_differences
- independent_checks (at least two)
- flow_and_positioning_check
- policy_path_check {status: available|not_applicable, relevant_countries, pricing_summary, rationale}

Expression rules:
- dollar-king and cross-merchant remain spot-only
- vol-convexity remains options-focused
- every other non-null trade seat is rates-first: construct a concrete rates candidate AND a spot candidate, prefer rates when comparably clean, and select spot only with an explicit reason rates is inferior or unavailable
- no-trade-skeptic may return no trade

Also include `paper_capital` on the contribution:
{
  "decision": "OPEN" | "HOLD",
  "notional_usd": 10000000,
  "side": "long" | "short" | null,
  "instrument": "<same as trade or null>",
  "asset_class": "<spot_fx|rates|curve|rates_rv|options or null>",
  "rationale": "why this size clears or fails the 5% ACT/365 hurdle"
}
Do not invent a mark. If the book engine cannot safely represent the expression from the frozen packet, the parent will record execution_blocked and HOLD.

You may launch at most two internal `composer-2.5` subagents. They inherit this frozen packet and may not acquire new evidence. Aggregators/rebuttals are not your job.
