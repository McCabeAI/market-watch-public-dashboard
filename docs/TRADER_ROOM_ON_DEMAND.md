# On-demand Trader Room execution contract

This is the user-approved on-demand workflow. It supplements `docs/TRADER_ROOM_PROTOCOL.md` and `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`. Where they differ on orchestration, model routing, evidence acquisition, rebuttal scope, or artifact storage, this contract wins.

The user only needs to say `go` in the Trader Room chat. The repository entrypoint is:

```bash
PYTHONPATH=. python scripts/trader_room_go.py go
```

That command prepares and freeze-validates one evidence packet, then runs the complete debate. Default `go` is a dry-run that does not consume the production Grok/Composer budget. The live 14-trader research run is refused unless a later authenticated human arms `TRADER_ROOM_LIVE=1`; this entrypoint still does not dispatch production models.

## Architecture

1. Four-family evidence preflight. Fail before the 14-agent run if an essential family is missing.
2. Freeze one common packet. Immutable SHA-256. No advocate may acquire new evidence.
3. Fourteen independent standing advocates, each exact model `grok-4.6`, each bound to its existing remit.
4. Each advocate may make at most two internal subagent calls. Those subagents may use only `composer-2.5` and inherit the same frozen packet.
5. Every advocate except `no-trade-skeptic` must end with one cogent actionable trade. The skeptic may submit no-trade.
6. First aggregator is a separate `grok-4.6` invocation. It receives all 14 originals. It must not rank or choose winners. It only maps substantive conflicts.
7. Each conflicted advocate gets exactly one rebuttal pass: own original + opposing original trade(s) + unchanged frozen packet. No additional subagent calls. No new evidence. Defend, amend, or withdraw, and explicitly shoot holes in the opposing case.
8. Final aggregator is a separate `grok-4.6` invocation. It receives all originals, the conflict map, and every rebuttal. It must not select a winner or house view. It emits the structured PM handoff.
9. Persist complete run artifacts under `trader-room/runs/<run_id>/` with immutable run ID and evidence cutoff. Do not put project output in ACP.

## Model routing

Validated against `scripts/trader_room/model_registry.json`, which is sourced from the current repository hook and agent-frontmatter catalog:

| Seat | Exact model |
| --- | --- |
| 14 standing advocates | `grok-4.6` (frontmatter `grok-4.6[]`) |
| conflict aggregator | `grok-4.6` |
| final aggregator | `grok-4.6` |
| advocate-internal subagents only | `composer-2.5` |

No other model is allowed on this workflow. `grok-4.5`, Composer fast variants, and Cursor Grok thinking-tier slugs are forbidden.

`TRADER_ROOM_MODEL_POLICY` is written into the run context and enforced by `.cursor/hooks/enforce-subagent-models.sh`.

## Finite ceilings

The ACP parent is now counted explicitly in the autonomous run budget.

- ACP parent/orchestrator = 1 Grok 4.6 invocation
- Baseline debate Grok invocations = 16 (14 advocates + 2 aggregators)
- Plus only conflict-rebuttal Grok calls, max 14
- Total Grok ceiling including parent = 31
- Composer ceiling = 28 (2 per initial advocate only)
- Total model-invocation ceiling = 59
- No retries or model reroutes may silently exceed these ceilings

Every full live run must carry this exact marker:

`MW_TRADER_ROOM_RUN_POLICY={"version":1,"run_type":"trader-room-ondemand","total_model_cap":59,"grok_cap":31,"composer_cap":28,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}`

The repository `subagentStart` budget hook enforces the caps. The root parent may launch only direct `grok-4.6` children. Initial advocate tasks must include `TRADER_ROOM_ADVOCATE=1`; only those advocate children may launch `composer-2.5` subagents, with a hard maximum of two each. Aggregators and rebuttal children may not launch subagents, and no deeper nesting is allowed.

## Required trade schema

`instrument`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs` into the frozen packet, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`. Unsupported levels must be JSON `null`, not invented.

## ChatGPT retrieval

The PM handoff `artifact_index` stores durable relative paths for the packet, every original submission, the conflict map, and every rebuttal. ChatGPT retrieves any artifact with:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent <name>
```
