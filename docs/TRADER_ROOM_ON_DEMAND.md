# On-demand Trader Room execution contract

This is the user-approved on-demand workflow. It supplements `docs/TRADER_ROOM_PROTOCOL.md` and `docs/TRADER_ROOM_EVIDENCE_CONTRACT.md`. Where they differ on orchestration, model routing, evidence acquisition, rebuttal scope, or artifact storage, this contract wins.

The user only needs to say `go` in the Trader Room chat. The repository entrypoint is:

```bash
PYTHONPATH=. python scripts/trader_room_go.py go
```

That command prepares and freeze-validates one evidence packet, then runs the complete debate. Default `go` is a dry-run that does not consume the production Grok/Composer budget. The live 14-trader research run is refused unless a later authenticated human arms `TRADER_ROOM_LIVE=1`. Even when armed, the Python entrypoint must not dispatch, author, ghostwrite, or simulate standing-seat output. The parent launches the independent `grok-4.6` seats and persists only those returned payloads. If a required Grok seat fails to launch, fail loudly.

## Architecture

1. Four-family evidence preflight. Fail before the 14-agent run if an essential family is missing.
2. Freeze one common packet. Immutable SHA-256. No advocate may acquire new evidence.
3. Fourteen independent standing advocates, each exact model `grok-4.6`, each bound to its existing remit.
4. Each advocate may make at most two internal subagent calls. Those subagents may use only `composer-2.5` and inherit the same frozen packet.
5. Every advocate except `no-trade-skeptic` must end with one cogent actionable trade. The skeptic may submit no-trade.
6. Spot-specialist seats (`dollar-king`, `cross-merchant`) stay spot-dedicated. Every other macro/rates-capable seat must compare outright duration, curve, and cross-market rates RV against spot FX, then choose the cleaner expression. The `vol-convexity` remit is unchanged; other seats must not default to vol.
7. First aggregator is a separate `grok-4.6` invocation. It receives all 14 originals. It must not rank or choose winners. It only maps substantive conflicts.
8. Each conflicted advocate gets exactly one rebuttal pass: own original + opposing original trade(s) + unchanged frozen packet. No additional subagent calls. No new evidence. Defend, amend, or withdraw, and explicitly shoot holes in the opposing case.
9. Final aggregator is a separate `grok-4.6` invocation. It receives all originals, the conflict map, and every rebuttal. It must not select a winner or house view. It emits the structured PM handoff with thesis/evidence/expression/catalyst/invalidation detail.
10. Persist complete sanitized run artifacts under `trader-room/runs/<run_id>/` with immutable run ID and evidence cutoff. That folder is the Git-durable ChatGPT retrieval surface. Unsanitized local packets may use `trader-room/runs/.local/`. Do not put project output in ACP.

## Model routing

Validated against `scripts/trader_room/model_registry.json`, which is sourced from the current repository hook and agent-frontmatter catalog:

| Seat | Exact model |
| --- | --- |
| 14 standing advocates | `grok-4.6` (frontmatter `grok-4.6[]`) |
| conflict aggregator | `grok-4.6` |
| final aggregator | `grok-4.6` |
| advocate-internal subagents only | `composer-2.5` |

No other model is allowed on this workflow. `grok-4.5`, Composer fast variants, and Cursor Grok thinking-tier slugs are forbidden.

`TRADER_ROOM_MODEL_POLICY` is written into the run context and enforced by `.cursor/hooks/enforce-subagent-models.sh` plus `scripts/trader_room/hook_enforce.py`.

Role rules:

- Standing trader, rebuttal, and aggregator invocations are exact `grok-4.6` only.
- `composer-2.5` is allowed only for first-pass trader internal research (`TRADER_ROOM_SEAT_ROLE=advocate-research`), max two per trader.
- Rebuttals and both aggregators get no internal subagents.
- ACP `allowed_models` is an allowlist, not an immediate grant. Parent-authored or simulated standing-seat output is rejected.

The prior run `tr-20260917T231827Z-4ca9133b` is `INVALID` because the parent authored the seat briefs. Do not present it as a valid Trader Room result.

## Finite ceilings

- Baseline main Grok invocations = 16 (14 advocates + 2 aggregators)
- Plus only conflict-rebuttal Grok calls, max 14
- Total Grok ceiling = 30
- Composer ceiling = 28 (2 per initial advocate only)
- No retries or model reroutes may silently exceed these ceilings

## Required trade schema

`instrument`, `structure`, `direction`, `thesis`, `mispricing`, `why_now`, `evidence_refs` into the frozen packet, `horizon`, `entry`, `target`, `stop`, `invalidation`, `catalysts`, `principal_risks`, `confidence`. Unsupported levels must be JSON `null`, not invented.

## ChatGPT retrieval

Sanitized run folders are committed under `trader-room/runs/<run_id>/`. `trader-room/runs/latest.json` and `trader-room/runs/INDEX.json` identify the latest published run. The PM handoff `artifact_index` stores durable relative paths for the packet, every original submission, the conflict map, every rebuttal, and the Markdown arbiter packet. ChatGPT retrieves any artifact with:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent <name>
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff_markdown
```
