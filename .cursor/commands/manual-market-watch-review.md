# Manual Market Watch one-shot provider review

This command is used only after an authenticated human `[launch-market-watch]` request has completed the deterministic live-data quality gate and committed a trusted stage-04 freeze. ACP's weekday schedule remains disabled. ACP may invoke this provider graph only through its verified one-use manual-launch authority.

## Run policy marker

Emit exactly once:

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":20,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
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
| Learning-quality examiner | 1 | `composer-2.5` |

Total: 20 invocations when the learning examiner is used (18 Grok + 2 Composer). The examiner grades causal adequacy of required learning submissions after the primary decisions and cannot create a second trading opinion. Cursor Auto and all other models are prohibited. Nested children are prohibited.

### Frozen-packet synthesis

The Composer child may organize, compare, calculate from, and summarize only the already-frozen evidence packet and explicitly bound historical/prior context contained in that packet. It must not browse, call external data tools, refresh prices, or add a later release. Its output is analysis/synthesis, not new evidence.

The parent may create a common **agent packet** from the trusted evidence plus that evidence-closed synthesis. The agent packet may have its own content SHA, but:
- its evidence cutoff remains exactly the stage-04 `as_of`;
- it must cite the same `base_packet_sha256`;
- it cannot contain a source/value/vintage not already present in the trusted freeze;
- it must preserve the deterministic `trade_permissions` block from the trusted stage-04 evidence snapshot unchanged.

### Trade-permission contract

The deterministic `trade_permissions` block is authoritative for country-level new-risk eligibility. The aggregate `families.macro_hard.status` is diagnostic only and MUST NOT be treated as a global veto when `trade_permissions` marks the required country/countries eligible.

- `OPEN` / `ADD`: allowed only when every country needed by the selected expression is eligible and the required market/rate legs are usable.
- `HOLD` / `REDUCE` / `CLOSE`: remain valid management actions for existing positions.
- `HEDGE`: a risk-management action, not proof that the book must be frozen. Propose it only when the frozen packet contains a markable hedge leg.
- Never convert a US or AU data problem into a ban on an unrelated CA/NZ/EA/JP expression.
- A not-due scored series that already has a verified vintage and failed only because of a timeout, HTTP error, source outage, or `budget_deferred` is a source-health carry-forward. It does not make that country ineligible and must not be described as hard data that could not be verified.
- Block new risk only when a relevant due release cannot be verified, or the required historical observation itself is absent or invalid. Unknown country attribution stays fail-closed.
- If a country is restricted, state the actual human-readable reason (for example, "August Australian labor could not be verified") rather than internal status enums. Put that caveat once in the research summary. Repeat it in a seat thesis only when it directly constrains that seat's selected expression.

### Public narrative contract

The research summary and every trader/PM thesis and invalidation are displayed to a human. Write them as concise desk notes, not execution telemetry.

- Research summary: 80–180 words. Lead with the overnight market conclusion, then the 2–4 developments that matter and what to watch next. Numbers appear only when they support the point.
- Trader/PM thesis: 2–4 sentences covering the position or opportunity, why it matters now, and the principal risk. Invalidation should describe the market condition that changes the view.
- Never put hashes, run IDs, review IDs, internal family names/status enums, pipeline stages, model-control terms, postmortem IDs, or provenance mechanics in public prose.
- Never use labels such as `FACT:`, `INFERENCE:`, or `UNKNOWN:`.
- Do not narrate `PASS/PARTIAL`, "fail closed", `macro_hard`, `market_state`, `source_failed`, `budget_deferred`, `MW_...`, or packet metadata. Those facts remain in structured machine fields.
- If the evidence is insufficient for a useful public note, say so plainly in one sentence instead of dumping telemetry.
- Current oil, gold, and equity levels come from the frozen `cross_assets` marks (WTI `CL=F`, Brent `BZ=F`, and the other compact marks), not from an older news story. A Sep 23 story that says oil is near two-week lows must not describe a later freeze if the frozen Brent or WTI mark is newer.

### Traders

Launch exactly the locked 14 trader seats as direct Grok children. Each gets:
- `MW_TRADER_FROZEN=1`;
- the same agent packet and exact base packet/review identity;
- only that seat's prior memory sidecar.

Trader children cannot use tools or fetch evidence. A valid `HOLD` is a deliberate trading decision, but each seat must independently consider the full allowed action set for its book and remit. Do not default to HOLD because an unrelated country is restricted. An operational data failure must already have stopped the deterministic launch before ACP and must never be represented as 14 synthetic HOLDs.

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
