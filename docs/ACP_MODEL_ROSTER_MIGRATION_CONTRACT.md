# ACP one-shot migration contract (model/roster decoupling)

**Status:** PROPOSED. This is a specification for a later protected-repository
PR in `McCabeAI/agent-control-plane`, which needs its own authorization. This
Market Watch PR does not change ACP, ACP schedules, or ACP configuration, and
does not dispatch anything to ACP.

## Evidence status

The ACP source was **not readable** from the environments that wrote this
contract. On 2026-11-03 `gh api` returned 404 for
`repos/McCabeAI/agent-control-plane` and for `src/acp/mw_one_shot.py`, and the
GitHub MCP connector was unavailable. Nothing below is verified against ACP
code.

| Statement about ACP today | Source | Status |
| --- | --- | --- |
| `src/acp/mw_one_shot.py` builds the Market Watch one-shot by cloning the disabled `market-watch-weekday-0205` entry in `config/schedules.v1.json` | operator brief | unverified |
| ACP has **no** known dedicated armed/unarmed toggle for the Market Watch one-shot | operator brief | unverified; this contract does not rely on one |
| ACP launches a provider job only for a verified human `[launch-market-watch]` request, one provider call per grant, no overlap, no retry without fresh approval | `docs/ACP_ONE_SHOT_AUTHORITY.md`, `scripts/market_watch_launch/acp_handshake.py` (Market Watch side) | Market Watch side verified; ACP enforcement unverified |
| ACP's provider prompt includes the literal v1 `MW_OVERNIGHT_RUN_POLICY` marker and an `ACP_SUBAGENT_POLICY` allowlist | Market Watch commands and hook expectations | unverified |
| ACP's parent model for Market Watch is `grok-4.6` | Market Watch v1 marker and validators | unverified |

ACP reviewers must confirm or correct each row before implementing. If a row
is wrong, the corresponding item below must be re-specified, not assumed.

## Goal

After this migration, a change to trader count, trader models, PM models,
debate/rebuttal models or Composer roles is a **Market Watch config-only
change** (`scripts/trader_room/model_registry.json`, see
`docs/AGENT_ROSTER_MODEL_PROFILES.md` §1.1). ACP keeps only:

- the **parent model**, as a single field in one ACP config file (target
  `grok-4.7`); changing the parent later is a one-field ACP change plus the
  mirrored Market Watch profile value, landed in one coordinated cutover;
- the stable **provider/authority contract**: verified human origin,
  single-use grant, one provider job, pinned trusted-main SHA, freeze/packet
  and book hash binding, no overlap, one data-only output delivery, and no
  retry without a fresh human approval.

## Required ACP changes (bounded)

1. **Dedicated one-shot config.** Add one explicit Market Watch one-shot entry
   (for example `config/market_watch_one_shot.v1.json`). It holds the target
   repo, launch command path, provider, authority rules and exactly one
   `parent_model` field. It is not a schedule: no cron and no `enabled` flag
   that could start a clock.
2. **Narrow loader swap in `src/acp/mw_one_shot.py`** (location unverified).
   Replace "clone the disabled schedule entry" with "load the dedicated
   one-shot config". Change nothing else in the dispatch path.
3. **Remove the disabled schedule** only after item 2 no longer reads it:
   delete `market-watch-weekday-0205` from `config/schedules.v1.json`. Market
   Watch keeps that string only as an inactive compatibility identifier in its
   own run-policy marker and validator; ACP must not depend on it.
4. **Parent equality gate (the required cutover gate).** Before any provider
   call, ACP refuses the delegation request when
   `budget.parent_model != one_shot_config.parent_model`. The refusal happens
   before the provider job, is recorded, and ends that grant; a later attempt
   needs a fresh human launch request. ACP launches the parent with that exact
   id: no Auto, no alias, no `-fast`/`-high` runtime slug. Because no
   armed/unarmed toggle is known to exist, this check is what pauses launches
   during the cutover window: once ACP is configured for `grok-4.7`, every
   request built by a Market Watch build still on the `grok-4.6` profile is
   refused without spend.
5. **No Market Watch subagent allowlist, trader count or child models in
   ACP.** For Market Watch one-shot runs, stop emitting `ACP_SUBAGENT_POLICY`
   or emit `"allowed_models": null`. Do not encode 14/15 seats, 20/18/2 caps
   or child model ids in ACP. Child models are enforced by the Market Watch
   hooks from the pin inside the frozen snapshot.
6. **Truthful run-policy marker, no hard-coded literal.** Stop putting the
   literal version-1 `MW_OVERNIGHT_RUN_POLICY` line in the provider prompt.
   (This document deliberately never writes a marker with its JSON body: the
   hook parses the first marker in a transcript, and a quoted example would
   be parsed.) Either copy verbatim the lines printed by
   `PYTHONPATH=. python -m scripts.trader_room.agent_config markers --kind daily --snapshot <bound evidence_snapshot.json>`
   at the pinned trusted-main SHA, or let the parent emit them per
   `.cursor/commands/manual-market-watch-review.md`. The Market Watch hook uses
   the **first** run-policy marker in the parent transcript and cannot observe
   the parent's runtime model, so the marker's `parent_model` must be the
   parent ACP actually launched. With item 4 in place, the pin-derived marker
   is truthful by construction.
7. **Caps travel with the request.** ACP treats
   `budget.total_model_cap / grok_cap / composer_cap / current_graph` in the
   delegation request as opaque values bound to the launch. ACP may enforce
   them as its own outer ceiling. It must not hard-code 20/18/2.

## Invariants ACP must preserve (unchanged)

- Exact human origin: a `[launch-market-watch]` issue, `author.type == User`,
  permission `admin`, `maintain` or `write`. The original human authority is
  not re-derived or widened by any change above.
- `launch_id`, `review_id`, `base_packet_sha256`, `score_state_sha256`, the
  pinned trusted-main SHA and the starting trader/PM book hashes match across
  the issue, `freeze_binding.json`, `remote_freeze.json` and the delegation
  request.
- One-shot: one provider job per grant, no overlap with an in-flight launch,
  and a superseded launch is refused.
- Delivery: one data-only `[overnight-output]` PR plus one
  `market-watch-launch-accepted` `repository_dispatch`.
- No retries, reroutes or second provider call without a fresh authenticated
  human approval. A gate refusal (item 4) is not retried automatically.
- No schedule-based launch; the weekday clock stays off.

## What Market Watch guarantees to ACP

- The delegation request **shape is unchanged** (same keys).
  `budget.parent_model` and the caps are derived from the frozen
  `agent_roster_pin`.
- The pin lives inside the evidence snapshot whose `packet_sha256` ACP already
  binds. A roster or model change therefore always changes the bound hash.
  ACP needs no new hash field.
- The pin contains only seats whose activation date has been reached on the
  freeze date; a scheduled seat cannot enter a launch early.
- Market Watch hooks deny the first child, before any child spend, if:
  - the run-policy marker disagrees with the pin (including `parent_model`);
  - a v1 marker is used with a non-legacy pin;
  - a child's model is not the exact pinned role model, or its custom agent
    is not the expected one;
  - a child lacks exactly one valid `MW_ROLE` tag;
  - the pin is a candidate or fixture pin.
- Historical launches validate against their own pin, or the legacy 14-seat
  `grok-4.6` pin. ACP never needs to re-validate old launches.

## Cutover sequencing (manual launch; must not be reordered)

There is no schedule to disable and no known arm switch. The sequence relies
on the fact that ACP dispatches only for a fresh human launch request, plus
the item 4 gate.

1. **Launch freeze.** The operator records that no `[launch-market-watch]`
   request will be filed until step 5, and confirms through ACP's existing
   no-overlap state that no launch is in flight.
2. **Verify the evidence table** above against ACP source, and correct this
   contract where it differs.
3. **Land the ACP PR** (items 1–7, separately authorized) with
   `parent_model: grok-4.7`. Any launch attempted now is refused by item 4
   before the provider job (no spend; the grant ends).
4. **Land the Market Watch stage-2 cutover PR.** It activates
   `candidate-grok-4.7`, removes the v1 literal markers from
   `.cursor/commands/*`, and re-renders the agent frontmatter; `check-agents`
   must pass.
5. **Lift the freeze.** The next launch is a new human request with a new
   grant; its delegation request carries `parent_model: grok-4.7` and passes
   the gate.

If step 4 lands before step 3, an old ACP still launches `grok-4.6` with the
v1 literal; the Market Watch hook then denies the first child (v1 marker with
a non-legacy pin). The run fails closed without child spend, but the grant is
consumed. Keep the freeze until both PRs are live.

## ACP acceptance tests (for the ACP PR)

- Loading the one-shot config does not read `schedules.v1.json`, and the
  config has exactly one `parent_model` field and no schedule fields.
- `schedules.v1.json` no longer contains `market-watch-weekday-0205`.
- Dispatch is refused before any provider call when
  `budget.parent_model != parent_model`; the refusal ends the grant and no
  automatic retry occurs.
- The parent is launched with the exact configured id (no runtime slug).
- No `ACP_SUBAGENT_POLICY` allowlist is emitted, or it is emitted with
  `allowed_models: null`, for Market Watch one-shot runs.
- The provider prompt contains no hard-coded `MW_OVERNIGHT_RUN_POLICY` literal;
  any marker it contains equals the Market Watch `markers` output for the
  bound snapshot.
- The existing human-origin, hash-binding, same-SHA, single-use, no-overlap,
  single-delivery and no-retry tests pass unchanged.

## Rollback

Within a launch freeze: revert Market Watch stage 2 (if applied) and set ACP's
`parent_model` back to `grok-4.6` (or revert the ACP PR). With the gate in
place, the order inside the freeze does not matter, because a mismatched
request is refused before spend. A Market Watch stage-0 build accepts the
legacy `grok-4.6` parent with v1 markers indefinitely.
