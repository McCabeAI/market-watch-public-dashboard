# Round 1 instructions — frozen packet only

Run ID: `tr-20260918T223926Z-ondemand`
Evidence cutoff: `2026-09-18T22:39:26Z`
Packet SHA-256: `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`

This is a fresh Round 1. Do not read, copy, continue, or adapt any file under `trader-room/runs/tr-20260918T182933Z-ondemand/` or any earlier run.

Read only:

- `trader-room/runs/tr-20260918T223926Z-ondemand/evidence_packet.json`
- `trader-room/runs/tr-20260918T223926Z-ondemand/advocate_card.json`
- `docs/TRADER_RESEARCH_METHOD.md` (already copied into the packet as `research_method`)
- your standing remit in `.cursor/agents/<seat>.md`

After freeze: no web, search, browse, or new evidence. Apply `research_method` before archetypal bias.

Write exactly one validated JSON object to:

`trader-room/runs/tr-20260918T223926Z-ondemand/submissions/<your-seat>.json`

Then return that same JSON. No extra prose.

## Contribution schema

Required keys: `type`, `run_id`, `round`, `agent`, `archetype`, `stance_summary`, `trade`, `confidence`, `remit`, `conflict_synopsis`, `packet_sha256`.

- `type` = `TRADER_ROOM_CONTRIBUTION`
- `run_id` = `tr-20260918T223926Z-ondemand`
- `round` = `1`
- `agent` / `archetype` = your locked seat name
- `remit` must equal the locked standing remit string in `advocate_card.json` exactly
- `confidence` integer 0-100; must match `conflict_synopsis.confidence` and `trade.confidence` when a trade exists
- `packet_sha256` = `b4c642412ddcc969d6fd135638baede8f3e9f987015684f2085c8460c3af466a`

## Trade schema

Every seat except `no-trade-skeptic` must submit one actionable trade. `no-trade-skeptic` may set `trade` to JSON `null`.

Required trade keys: `instrument`, `asset_class`, `expression_comparison`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs`, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`.

- `asset_class` one of: `spot_fx` | `rates` | `curve` | `rates_rv` | `options`
- `expression_comparison` object with `rates_candidate`, `spot_candidate`, `selected`, `rationale`
- `selected` one of: `rates` | `spot` | `options`
- `why_now`, `evidence_refs`, `catalysts`, `principal_risks` = non-empty string lists
- `evidence_refs` must be IDs from `advocate_card.json` `allowed_evidence_refs`
- `entry`, `target`, `stop`, `invalidation`, `structure` = sourced string or JSON `null`
- Do not invent executable levels

## Expression mandate (mechanical)

- `dollar-king` and `cross-merchant` remain spot-only: `asset_class` = `spot_fx`, `selected` = `spot`. They need a concrete `spot_candidate`. `rates_candidate` may be null.
- `vol-convexity` remains options-focused: `asset_class` = `options`, `selected` = `options`.
- Every other seat that submits a trade is rates-first: construct a **concrete** rates candidate (outright duration, curve, or cross-market rates RV) and a **concrete** spot candidate. Prefer rates when comparably clean. Select spot only with an explicit rationale that the rates candidate is inferior or unavailable from this packet. `rates_candidate` and `spot_candidate` must be non-empty strings. If `selected` is `rates`, `asset_class` must be `rates`, `curve`, or `rates_rv`. If `selected` is `spot`, `asset_class` must be `spot_fx`.
- `no-trade-skeptic` may return no trade. If it endorses a trade, the same rates-first comparison applies.

## conflict_synopsis

Required object fields: `seat`, `primary_trade`, `core_view`, `usd_view`, `cad_view`, `aud_view`, `nzd_view`, `us_rates_view`, `ca_rates_view`, `au_rates_view`, `nz_rates_view`, `risk_view`, `carry_view`, `time_horizon`, `key_catalyst`, `key_invalidation`, `confidence`, `conflict_tags`.

- currency/rates views: `higher` | `lower` | `neutral` | `not_relevant`
- `risk_view`: `risk_on` | `risk_off` | `neutral` | `not_relevant`
- `carry_view`: `supports_trade` | `opposes_trade` | `neutral` | `not_relevant`
- `conflict_tags`: non-empty list of strings
- This is a compression of the completed pitch, not a second opinion

Optional useful keys: `macro_assumptions` object using keys `growth` (`above_trend`|`below_trend`), `risk` (`risk_on`|`risk_off`), `rates` (`higher_for_longer`|`easing_cycle`), `policy` (`hawkish`|`dovish`); `subagent_calls` integer 0-2; `subagent_model` `composer-2.5` or null.

You may launch at most two internal `composer-2.5` subagents. They inherit this frozen packet and may not acquire new evidence. Aggregators/rebuttals are not your job.

Validate before writing:

```bash
PYTHONPATH=/workspace python3 - <<'PY'
from pathlib import Path
import json
from scripts.trader_room.schema import validate_contribution
packet = json.loads(Path("trader-room/runs/tr-20260918T223926Z-ondemand/evidence_packet.json").read_text())
item = json.loads(Path("YOUR_SUBMISSION_PATH").read_text())
validate_contribution(item, packet=packet, expected_agent="YOUR_SEAT")
print("OK")
PY
```

TRADER_ROOM_ADVOCATE=1
MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":58,"grok_cap":30,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
TRADER_ROOM_MODEL_POLICY={"version":1,"advocate_model":"grok-4.6","aggregator_model":"grok-4.6","subagent_models":["composer-2.5"]}
ACP_SUBAGENT_POLICY={"version":1,"allowed_models":["composer-2.5","grok-4.6"]}
