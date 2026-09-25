# Overnight scheduled provider run (weekday 02:05 ET)

ACP launches this parent on schedule `market-watch-weekday-0205`. This repository file is the **target-repo contract** the parent must follow. Models are launched only by ACP; this command does not start GitHub cron work.

## Run policy marker (required in parent transcript)

Emit exactly once:

```
MW_OVERNIGHT_RUN_POLICY={"version":1,"schedule_id":"market-watch-weekday-0205","total_model_cap":20,"grok_cap":18,"composer_cap":2,"parent_model":"grok-4.6","parent_total":1,"parent_grok":1}
```

ACP must emit a matching policy marker. `.cursor/hooks/enforce-overnight-budget.py` enforces these caps atomically on every child spawn.

## 0. Trusted-freeze preflight — before any child subagent spend

The ACP parent is already running at this point. Before launching the Composer research child or any trader/PM child:

1. Resolve the current New York session ID as `overnight-YYYYMMDD`.
2. Read the **committed starting-ref** files:
   - `data/overnight/runs/<run_id>/run.json`
   - `data/overnight/runs/<run_id>/reviews/index.json`
   - the open review's `data/overnight/runs/<run_id>/reviews/<review_id>/evidence_snapshot.json`
   The open review is the latest `frozen` or `accepting` entry. Do not read a mutable session-level snapshot to invent `review_id`.
3. Require `freeze_evidence.status == "succeeded"`, snapshot `type == "OVERNIGHT_EVIDENCE_SNAPSHOT"`, matching `overnight_run_id`, a `review_id` of the form `review-NNN`, and a valid committed `packet_sha256`. Copy that `review_id` into the scheduled output. Do not mint a new one.
4. Never create, regenerate, or repair the trusted base freeze inside the provider run. Market Watch deterministic automation owns that state.
5. If the committed trusted freeze is absent or invalid, stop **before launching any child** and return:
   `STATUS: BLOCKED_MISSING_TRUSTED_FREEZE`
   Do not open an overnight-output PR.

The runtime budget hook independently enforces this committed-freeze requirement on the first overnight child spawn, so a locally synthesized snapshot cannot substitute for persisted trusted state.

## Approved graph (20 / 18 / 2)

| Role | Count | Model |
| --- | ---: | --- |
| Parent orchestrator | 1 | `grok-4.6` |
| Research (bounded) | 1 | `composer-2.5` |
| Direct trader children | 14 | `grok-4.6` |
| Direct automated PM principals | 3 | `grok-4.6` custom agents |
| Learning-quality examiner | 1 | `composer-2.5` |

**Total model invocations: 20** when the learning examiner is used (18 Grok + 2 Composer). Declared normal usage is 18 Grok + 2 Composer. The examiner runs once after the primary trader and PM decisions and grades causal adequacy of required learning submissions only. It must not produce a second market opinion, trade, lesson, or canonical fact. Skip the examiner only when no identity has a learning obligation; the caps stay 20 / 18 / 2.

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
5. **Learning-quality examiner** — one Composer 2.5 call after all primary trader and PM decisions. It reads only the required learning submissions and returns adequacy grades. It does not see a mandate to trade and its output cannot add actions, theses, or lessons.
6. **Do not** launch ChatGPT PM, on-demand Trader Room aggregators, rebuttals, or continuation flows.
7. **Output** — write only:
   ```
   data/overnight/inbox/<run_id>/scheduled_output.json
   ```
   including `overnight_run_id`, the frozen `review_id`, `decisions` (14 seats), and **`pm_decisions`** (swinger, pragmatist, grinder). The agent packet must carry the same `review_id`. ChatGPT is excluded from automated overnight output.

## Evidence-closed children

`.cursor/hooks/enforce-overnight-runtime.py` blocks all tools when `MW_TRADER_FROZEN=1` or `MW_PM_FROZEN=1` is present in the child transcript.

## What this is not

- Not full Trader Room (no advocates-with-Composer grandchildren, no Sunday clock).
- Not a second provider clock beyond the existing Mon–Fri 02:05 ET ACP schedule.
