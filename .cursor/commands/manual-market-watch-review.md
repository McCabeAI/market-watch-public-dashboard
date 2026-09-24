# Manual Market Watch one-shot provider review

This command is used only after an authenticated human `[launch-market-watch]` request has completed the deterministic live-data quality gate and committed a trusted stage-04 freeze. ACP's weekday schedule remains disabled. ACP may invoke this provider graph only through its verified one-use manual-launch authority.

## Run policy marker

Emit exactly once:

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":19,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
```

The legacy schedule id is an inactive compatibility identifier for existing hooks and validators. It is not launch authority and it does not imply a 02:05 clock.

## 0. Immutable manual-freeze preflight — before any child spend

ACP supplies `MW_MANUAL_ONE_SHOT_BOUND_CONTEXT` containing the exact `launch_id`, `overnight_run_id`, `review_id`, `base_packet_sha256`, original human issue and pinned trusted-main SHA.

Before any Composer, trader or PM child:

1. Checkout/read only the pinned trusted-main SHA supplied by ACP.
2. Read `data/market_watch_launches/<launch_id>/launch.json`, the bound stage-04 artifact, `freeze_binding.json`, and `data/overnight/runs/<run_id>/reviews/<review_id>/evidence_snapshot.json`.
3. Require exact launch/run/review/hash agreement with `MW_MANUAL_ONE_SHOT_BOUND_CONTEXT`; require stage 03 and stage 04 succeeded; require the evidence snapshot to hash to `base_packet_sha256`.
4. Do not regenerate, repair, advance, or replace the trusted freeze. Do not change its `as_of` timestamp.
5. If any binding is absent or mismatched, stop before launching any child and do not open an output PR.

## Evidence-closed graph

The manual stage-04 packet is the evidence boundary for every model in this provider call. **No model may fetch or introduce evidence published after that freeze.**

Approved graph:

| Role | Count | Model |
| --- | ---: | --- |
| Parent orchestrator | 1 | `grok-4.6` |
| Frozen-packet synthesis child | 1 | `composer-2.5` |
| Direct trader children | 14 | `grok-4.6` |
| Direct automated PM principals | 3 | `grok-4.6` |

Total: 19 invocations (18 Grok + 1 Composer). Cursor Auto and all other models are prohibited. Nested children are prohibited.

### Frozen-packet synthesis

The Composer child may organize, compare, calculate from, and summarize only the already-frozen evidence packet and explicitly bound historical/prior context contained in that packet. It must not browse, call external data tools, refresh prices, or add a later release. Its output is analysis/synthesis, not new evidence.

The parent may create a common **agent packet** from the trusted evidence plus that evidence-closed synthesis. The agent packet may have its own content SHA, but:
- its evidence cutoff remains exactly the stage-04 `as_of`;
- it must cite the same `base_packet_sha256`;
- it cannot contain a source/value/vintage not already present in the trusted freeze.

### Traders

Launch exactly the locked 14 trader seats as direct Grok children. Each gets:
- `MW_TRADER_FROZEN=1`;
- the same agent packet and exact base packet/review identity;
- only that seat's prior memory sidecar.

Trader children cannot use tools or fetch evidence. A valid `HOLD` is a deliberate trading decision. An operational data failure must already have stopped the deterministic launch before ACP and must never be represented as 14 synthetic HOLDs.

### Automated PMs

After all 14 trader decisions exist, launch exactly three direct Grok custom-agent principals: `swinger`, `pragmatist`, and `grinder`. Each gets:
- `MW_PM_FROZEN=1`;
- the same frozen agent packet and accepted 14 trader decisions;
- only its own prior book/memory.

No PM sees another PM's current-cycle decision. Do not launch ChatGPT PM.

## Output

Write exactly one provider-authored file:

```
data/overnight/inbox/<overnight_run_id>/scheduled_output.json
```

It must pass the existing trusted validator and include at root:
- `launch_id` equal to the ACP-bound manual launch;
- `overnight_run_id`;
- `review_id`;
- `base_packet_sha256`;
- unchanged legacy `schedule_id` required by the existing validator;
- decisions for exactly 14 traders;
- `pm_decisions` for exactly swinger, pragmatist and grinder;
- actual invocation counts, with no Auto or other-model use.

Do not author canonical books, NAV, cash, funding, realized/unrealized P&L, launch stage state, deterministic data, or Pages output. Market Watch trusted code validates and applies the output after the PR arrives.
