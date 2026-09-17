# On-demand Trader Room execution contract

This is the user-approved on-demand workflow. It supplements `docs/TRADER_ROOM_PROTOCOL.md` and `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`. Where they differ on orchestration, model routing, evidence acquisition, rebuttal scope, or artifact storage, this contract wins.

The user only needs to say `go` in the Trader Room chat. The repository entrypoint is:

```bash
PYTHONPATH=. python scripts/trader_room_go.py go
```

That command prepares and freeze-validates one evidence packet, then runs the complete debate. Default `go` is a dry-run that does not consume the production Grok/Composer budget.

A live 14-trader research run is armed with `TRADER_ROOM_LIVE=1` and `--live`. It uses Cursor native parent-agent orchestration: one Grok 4.6 parent invokes the 14 standing `grok-4.6` seats against the identical frozen production packet, then `conflict-aggregator`, one rebuttal pass for each conflicted seat, and `final-aggregator`. `LiveRunner` does not synthesize model output. CI remains refused. Unarmed `--live` remains refused.

```bash
TRADER_ROOM_LIVE=1 PYTHONPATH=. python scripts/trader_room_go.py go --live --repo-evidence --market-state <production-market-state.json>
TRADER_ROOM_LIVE=1 PYTHONPATH=. python scripts/trader_room_go.py go --live --resume --run-id <run_id>
```

The first live call freeze-validates four-family evidence and writes dispatch prompts under `trader-room/runs/<run_id>/dispatch/`. Exit code 4 means `AWAITING_PARENT_DISPATCH`: the parent must invoke the named seats and write JSON results, then resume. Do not simulate those results.

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

- Baseline main Grok invocations = 16 (14 advocates + 2 aggregators)
- Plus only conflict-rebuttal Grok calls, max 14
- Total Grok ceiling = 30
- Composer ceiling = 28 (2 per initial advocate only)
- No retries or model reroutes may silently exceed these ceilings

## Required trade schema

`instrument`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs` into the frozen packet, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`. Unsupported levels must be JSON `null`, not invented.

## ChatGPT retrieval

The PM handoff `artifact_index` stores durable relative paths for the packet, every original submission, the conflict map, and every rebuttal. ChatGPT retrieves any artifact with:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent <name>
```
