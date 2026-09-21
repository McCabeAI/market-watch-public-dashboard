# Overnight scheduled provider run (weekday 02:05 ET)

ACP launches this parent on schedule `market-watch-weekday-0205`. This repository file is the **target-repo contract** the parent must follow. Models are launched only by ACP; this command does not start GitHub cron work.

## Run policy marker (required in parent transcript)

Emit exactly once:

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":19,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
```

ACP must emit a matching policy marker. `.cursor/hooks/enforce-overnight-budget.py` enforces these caps atomically on every child spawn.

## 0. Trusted-freeze preflight — before any child/model spend

Before launching the Composer research child or any trader/PM child:

1. Resolve the current New York run ID as `overnight-YYYYMMDD`.
2. Read the **committed starting-ref** files:
   - `data/overnight/runs/<run_id>/run.json`
   - `data/overnight/runs/<run_id>/evidence_snapshot.json`
3. Require `freeze_evidence.status == "succeeded"`, snapshot `type == "OVERNIGHT_EVIDENCE_SNAPSHOT"`, matching `overnight_run_id`, and a valid committed `packet_sha256`.
4. Never create, regenerate, or repair the trusted base freeze inside the provider run. Market Watch deterministic automation owns that state.
5. If the committed trusted freeze is absent or invalid, stop **before launching any child** and return:
   `STATUS: BLOCKED_MISSING_TRUSTED_FREEZE`
   Do not open an overnight-output PR.

The runtime budget hook independently enforces this committed-freeze requirement on the first overnight child spawn, so a locally synthesized snapshot cannot substitute for persisted trusted state.

## Approved graph (19 / 18 / 2)

| Role | Count | Model |
| --- | ---: | --- |
| Parent orchestrator | 1 | `grok-4.6` |
| Research (bounded) | 1 | `composer-2.5` |
| Direct trader children | 14 | `grok-4.6` |
| Direct automated PM principals | 3 | `grok-4.6` custom agents |

**Total model invocations: 19** (1 Grok parent + 14 Grok traders + 3 Grok PM principals + 1 Composer research). Composer cap remains 2; only one Composer research child is used in the approved graph.

Nested subagents are **prohibited** for both traders and PMs on overnight runs (`allow_nested_composer` is false). Do not use Cursor Auto or Other Models.

## Sequence

1. **Research** — bounded Composer research is allowed before the final agent packet is frozen.
2. **Freeze final agent packet** — one common evidence packet + SHA-256 for all downstream children.
3. **14 trader children** — launch concurrently (or in bounded waves) as direct Grok children with:
   - `MW_TRADER_FROZEN=1`
   - the same frozen final packet/hash
   - **only that seat's** prior memory sidecar / `memory_context_sha256`
4. **After all 14 trader decisions exist** — launch **3 concurrent** automated PM principals as **custom agents** (not Task grok slugs):
   - `.cursor/agents/swinger.md`
   - `.cursor/agents/pragmatist.md`
   - `.cursor/agents/grinder.md`
   Each PM child receives:
   - `MW_PM_FROZEN=1`
   - the same frozen packet + the same accepted 14 trader decisions
   - **only that PM's** prior book/memory sidecar
   No PM sees another PM's current-cycle decision.
5. **Do not** launch ChatGPT PM, on-demand Trader Room aggregators, rebuttals, or continuation flows.
6. **Output** — write only:
   ```
   data/overnight/inbox/<run_id>/scheduled_output.json
   ```
   including `decisions` (14 seats) and **`pm_decisions`** (swinger, pragmatist, grinder). ChatGPT is excluded from automated overnight output.

## Evidence-closed children

`.cursor/hooks/enforce-overnight-runtime.py` blocks all tools when `MW_TRADER_FROZEN=1` or `MW_PM_FROZEN=1` is present in the child transcript.

## What this is not

- Not full Trader Room (no advocates-with-Composer grandchildren, no Sunday clock).
- Not a second provider clock beyond the existing Mon–Fri 02:05 ET ACP schedule.
