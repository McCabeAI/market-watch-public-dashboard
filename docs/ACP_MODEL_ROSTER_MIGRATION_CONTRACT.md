# ACP one-shot migration contract (model/roster decoupling)

**Status:** PROPOSED. This is a specification for a later protected-repository
PR in `McCabeAI/agent-control-plane`, which needs its own authorization. This
Market Watch PR does not change ACP, ACP schedules, or ACP configuration, and
does not dispatch anything to ACP.

**Evidence limitation:** the ACP source was not readable from the environment
that wrote this contract (GitHub returned 404 for `src/acp/mw_one_shot.py`,
`config/schedules.v1.json` and the README). File and function names below come
from the Market Watch side of the contract (`docs/ACP_ONE_SHOT_AUTHORITY.md`,
`scripts/market_watch_launch/acp_handshake.py`, `.cursor/commands/*`) and from
the operator brief. ACP reviewers must confirm each named location before
implementing.

## Goal

After this migration, a change to trader count, trader models, PM models,
debate/rebuttal models or Composer roles is a **Market Watch config-only
change** (`scripts/trader_room/model_registry.json`). ACP keeps only the
following:

- the **parent model** (target `grok-4.7`);
- the stable **provider/authority contract**: verified human origin,
  single-use grant, freeze/packet/book hash binding, one-shot, no overlap,
  output delivery, and no retry without fresh approval.

## Required ACP changes (bounded)

1. **Dedicated one-shot config.** Add one explicit Market Watch one-shot entry
   (for example `config/market_watch_one_shot.v1.json`). It holds the target
   repo, launch command path, parent model, provider, and authority rules. It
   is not a schedule. It has no cron and no `enabled` flag that could start a
   clock.
2. **Remove the disabled schedule.** Delete the disabled
   `market-watch-weekday-0205` entry from `config/schedules.v1.json`. Market
   Watch keeps the string `market-watch-weekday-0205` only as an inactive
   compatibility identifier inside its own run-policy marker and validator.
   ACP must not depend on it.
3. **Narrow loader swap in `src/acp/mw_one_shot.py`.** Replace "clone the
   disabled schedule entry" with "load the dedicated one-shot config". Do not
   change anything else in the dispatch path.
4. **Parent pinned to `grok-4.7`.** ACP launches the parent with exact
   `grok-4.7`: no Auto, no alias, no `-fast`/`-high` slug. ACP refuses to
   dispatch when the delegation request's `budget.parent_model` differs from
   the ACP-configured parent.
5. **No Market Watch subagent allowlist, trader count or child models in
   ACP.** Stop emitting `ACP_SUBAGENT_POLICY` for Market Watch one-shot runs,
   or emit `"allowed_models": null`. Do not encode 14/15 seats, 20/18/2 caps or
   child model IDs in ACP. Child models are enforced by Market Watch hooks
   (`.cursor/hooks/enforce-overnight-budget.py`) from the pin inside the frozen
   snapshot.
6. **No hard-coded run-policy marker.** Stop putting a literal
   `MW_OVERNIGHT_RUN_POLICY={"version":1,...,"total_model_cap":20,...}` line
   in the provider prompt. The Market Watch hook reads the first marker in the
   parent transcript. A v1 marker is accepted only for a legacy-equivalent pin:
   14 seats, `grok-4.6` parent, 20/18/2. For any other pin, the run-policy and
   graph markers must be the exact lines printed by
   `PYTHONPATH=. python -m scripts.trader_room.agent_config markers --kind daily --snapshot <bound evidence_snapshot.json>`.
   ACP either copies those lines verbatim from Market Watch at the pinned
   trusted-main SHA, or lets the parent emit them per
   `.cursor/commands/manual-market-watch-review.md`.
7. **Caps travel with the request.** ACP treats
   `budget.total_model_cap / grok_cap / composer_cap / current_graph` in the
   delegation request as opaque values bound to the launch. ACP may enforce
   them as its own outer ceiling. It must not hard-code 20/18/2.

## Invariants ACP must preserve (unchanged)

- Exact human origin: a `[launch-market-watch]` issue, `author.type == User`,
  permission `admin`, `maintain` or `write`.
- `launch_id`, `review_id`, `base_packet_sha256`, `score_state_sha256` and the
  starting trader/PM book hashes match across the issue, `freeze_binding.json`,
  `remote_freeze.json` and the delegation request.
- One-shot: one provider call per grant, no overlap with an in-flight launch,
  and a superseded launch is refused.
- Delivery: one data-only `[overnight-output]` PR plus one
  `market-watch-launch-accepted` `repository_dispatch`.
- No retries, reroutes or second provider call without a fresh authenticated
  human approval.
- The weekday clock stays off. There is no schedule-based launch.

## What Market Watch guarantees to ACP

- The delegation request **shape is unchanged** (same keys).
  `budget.parent_model` and the caps are derived from the frozen
  `agent_roster_pin`.
- The pin lives inside the evidence snapshot whose `packet_sha256` ACP already
  binds. A roster or model change therefore always changes the bound hash.
  ACP needs no new hash field.
- Market Watch hooks deny the first child, before any model spend, if:
  - the ACP parent model and the pinned profile parent differ;
  - a child's model is not the exact pinned role model;
  - a child lacks a verified `MW_ROLE` tag;
  - the pin is a candidate or fixture pin.
- Historical launches validate against their own pin, or the legacy 14-seat
  `grok-4.6` pin. ACP never needs to re-validate old launches.

## Cutover sequencing (must not be reordered)

1. The ACP PR lands with the parent model **configured but not armed**, using
   ACP's own dispatch gate.
2. The Market Watch stage-2 cutover PR is merged. It activates
   `candidate-grok-4.7` and re-renders the agent frontmatter.
3. ACP is armed for the next human-authorized launch.

If ACP runs a `grok-4.7` parent while Market Watch is still on
`current-production-grok-4.6`, the Market Watch hook denies the first child.
The run fails closed without spending child calls. The grant is still
consumed, so do not arm ACP early.

## ACP acceptance tests (for the ACP PR)

- Loading the one-shot config does not read `schedules.v1.json`.
- `schedules.v1.json` no longer contains `market-watch-weekday-0205`.
- Dispatch is refused when `budget.parent_model != "grok-4.7"`.
- No `ACP_SUBAGENT_POLICY` allowlist is emitted, or it is emitted with
  `allowed_models: null`, for Market Watch one-shot runs.
- The existing human-origin, hash-binding, single-use, no-overlap and
  no-retry tests pass unchanged.

## Rollback

Revert the ACP PR. Revert Market Watch stage 2 if it was applied. A Market
Watch stage-0 build accepts the legacy `grok-4.6` parent with v1 markers
indefinitely.
