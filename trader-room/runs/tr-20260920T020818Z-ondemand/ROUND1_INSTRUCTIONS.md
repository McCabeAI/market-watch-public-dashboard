# Round 1 instructions — frozen packet only

TRADER_ROOM_ADVOCATE=1
MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":57,"grok_cap":29,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}

Run ID: `tr-20260920T020818Z-ondemand`
Evidence cutoff: `2026-09-20T02:08:18Z`
Packet SHA-256: `349a16aeeda7f4a89e10ba16c22c90311da76536984e943cf04249588d954e1e`

Read only:
- `trader-room/runs/tr-20260920T020818Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260920T020818Z-ondemand/advocate_card.json`
- your own private memory sidecar at the path in the launch plan / advocate_card `seat_memory.paths`
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Mandatory idea-building order: context -> what changed -> what is priced -> historical comparison -> discrepancy -> expression -> sizing.
A z-score, percentile, spread extreme, or correlation break may be a discovery signal only, never the thesis.
Complete a validated `context_build` before selecting risk.
For rates, inspect the frozen SOFR/CORRA/AONIA-linked policy path (`policy_paths`) then choose the actual expression from `tradable_rate_curves` (SOFR=`SR3`, CORRA=`CRA`, AONIA=`IB`) or the sovereign bond curve when that is cleaner.
Use packet historical move analogs and explicitly state similarities AND regime differences.

You MUST read your own sidecar `open_positions` before any book decision. Manage existing positions by `position_id`. Do not re-open an already-owned expression as a new OPEN merely because it remains the debate pitch.

Return exactly one JSON object, no prose, matching `scripts/trader_room/schema.py`.

Required contribution keys: `type`, `run_id`, `round`, `agent`, `archetype`, `stance_summary`, `trade`, `confidence`, `remit`, `conflict_synopsis`, `packet_sha256`, `paper_actions`.

- `type` = `TRADER_ROOM_CONTRIBUTION`
- `run_id` = `tr-20260920T020818Z-ondemand`
- `round` = 1
- `remit` must equal the locked standing remit string exactly
- `confidence` integer 0-100
- `packet_sha256` = `349a16aeeda7f4a89e10ba16c22c90311da76536984e943cf04249588d954e1e`

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
- no-trade-skeptic may return no trade; a no-trade decision must include structured `funding_view` using frozen `funding_context`

`paper_actions` is the full book decision (not the debate pitch). Non-empty list required:
- `[{"action":"HOLD"}]` is the explicit no-change decision
- any number of independent OPEN / ADD / REDUCE / CLOSE / HEDGE actions is allowed
- OPEN/ADD/HEDGE must include instrument, side, notional_usd, asset_class, and a rationale/thesis
- ADD/REDUCE/CLOSE must target the existing `position_id` from your sidecar
- size the complete action set against the $100m gross deployed-notional cap
- do not rely on legacy `paper_capital` for this live run

Do not invent a mark. Trusted code transacts at deterministic packet mid.

Prefer 0 internal subagents. You may launch at most two internal `composer-2.5` subagents if truly needed to construct this JSON. They inherit this frozen packet and may not acquire new evidence. Aggregators/rebuttals are not your job.
