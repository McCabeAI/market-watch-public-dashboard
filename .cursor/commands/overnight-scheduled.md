# Overnight scheduled provider run (weekday 02:05 ET)

ACP launches this parent on schedule `market-watch-weekday-0205`. This repository file is the **target-repo contract** the parent must follow. Models are launched only by ACP; this command does not start GitHub cron work.

## Run policy marker (required in parent transcript)

Before any tool call, child, or other transcript text, run this on the pinned trusted SHA and emit its two lines verbatim as the first lines of the parent transcript:

```bash
PYTHONPATH=. python -m scripts.trader_room.agent_config markers --kind daily --snapshot <evidence_snapshot.json>
```

`<evidence_snapshot.json>` is the committed open review snapshot. Do not invent, shorten, or quote an example of that JSON. The hook binds the first marker it sees to that freeze pin. A later copy is ignored. A marker for a different pin, or a version-1 marker on a non-legacy pin, is denied at the first child.

Each child task must contain exactly one `MW_ROLE` tag (`MW_ROLE=synthesis`, `MW_ROLE=trader:<seat>`, `MW_ROLE=pm:<pm_id>`, `MW_ROLE=learning_examiner`) using seats from the pinned roster in `agent_roster_pin` on the evidence snapshot. Put that tag alone on its own line and do not mention `MW_ROLE` again. A trailing period or comma, surrounding parentheses, backticks, or asterisks on that single line are accepted. A glued suffix (`.bad`, `/extra`), a repeated tag, an unknown role, or a mismatched seat is denied. Models and custom agents come from the pin, never Auto: `PYTHONPATH=. python -m scripts.trader_room.agent_config agents --kind daily --snapshot <evidence_snapshot.json>`. Custom-agent frontmatter must equal that exact model id with an empty `[]` suffix.

The marker's current-graph line is the launch ceiling. A 19-call ceiling is the pre-examiner graph and is not valid. On the current 14-seat roster the ceiling is 20 / 18 / 2.

`.cursor/hooks/enforce-overnight-budget.py` enforces these caps atomically on every child spawn. The hook rejects a policy whose `total_model_cap` is 19.

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

## Approved graph (pin budget; 20 / 18 / 2 on the current roster)

| Role | Count | Model |
| --- | ---: | --- |
| Parent orchestrator | 1 | pinned `parent` |
| Research (bounded) | 1 | pinned `synthesis` (`composer-2.5`) |
| Direct trader children | pinned trader count (14 on the current roster) | pinned `trader` |
| Direct automated PM principals | 3 | pinned `pm_principal` custom agents |
| Learning-quality examiner | 1 | pinned `learning_examiner` (`composer-2.5`) |

**Total model invocations follow the pin.** On the current roster that is 20 when the learning examiner is used (18 Grok-family + 2 Composer). The caps stay 20 / 18 / 2 until the roster changes. The examiner runs once after the primary trader and PM decisions. It grades causal adequacy only and must not produce a second market opinion, trade, lesson, canonical fact, or psychology state. Skip the examiner only when the frozen learning-obligation manifest is empty. A non-empty manifest requires declared calls equal to the pin caps (**20 / 18 / 2** on the current roster). Declared **19** is not valid when any prior obligation exists. Omitting learning submissions does not skip the examiner.

Nested subagents are **prohibited** for both traders and PMs on overnight runs (`allow_nested_composer` is false). Do not use Cursor Auto or Other Models.

## Sequence

1. **Research** — bounded Composer research is allowed before the final agent packet is frozen.
2. **Freeze final agent packet** — one common evidence packet + SHA-256 for all downstream children.
3. **Pinned trader children** — launch every pinned seat concurrently (or in bounded waves) as direct children on the pinned trader model, through the custom agent from `agent_config agents`, with:
   - `MW_TRADER_FROZEN=1`
   - the same frozen final packet/hash
   - **only that seat's** prior memory sidecar / `memory_context_sha256`
4. **After every pinned trader decision exists** — launch **3 concurrent** automated PM principals as **custom agents** (not Task model slugs):
   - `.cursor/agents/swinger.md`
   - `.cursor/agents/pragmatist.md`
   - `.cursor/agents/grinder.md`
   Each PM child receives:
   - `MW_PM_FROZEN=1`
   - the same frozen packet + the accepted trader decisions for every pinned seat
   - **only that PM's** prior book/memory sidecar
   No PM sees another PM's current-cycle decision.
5. **Learning-quality examiner** — after all primary trader and PM decisions, read the private review artifact `learning_obligations.json` (the shared packet only carries its `manifest_sha256` and `obligation_count`). If `obligation_count` is non-zero, launch exactly one Composer 2.5 examiner. Give it that manifest and the learning submissions only, not a mandate to trade and not another identity's sidecar. Do not paste `learning_obligations.json`, examiner notes, or another identity's sidecar into a trader or PM child. Each assessment's `submission_ref` is the frozen `obligation_id`, `submission_kind` is `postmortem` or `performance_reflection`, and `submission_state` is `adequate`, `inadequate`, or `missing`. Missing is explicit when the identity omitted the row. One assessment per manifest obligation, exactly once. It cannot add actions, theses, lessons, or canonical facts, and it cannot change the trading decision. Do not force a lesson: an adequate substantive `no_new_lesson` may clear that obligation. Each identity must already have addressed its own sidecar `learning_obligations` before its trading decision, including `HOLD` / `NO_TRADE`. The examiner does not grade psychology and does not change the 20 / 18 / 2 contract.
6. Each seat sidecar includes a private `psychology` block. When an active required flag intersects `OPEN`/`ADD`/`HEDGE`, return `psychology_check` echoing `state_sha256`. `HOLD`/`NO_TRADE`/`REDUCE`/`CLOSE` never require it and always remain executable. Do not quote axes, flags, Learning Default, or psychology in public prose. Psychology never sizes or forces a trade.
7. **Do not** launch ChatGPT PM, on-demand Trader Room aggregators, rebuttals, or continuation flows.
8. **Output** — write only:
   ```
   data/overnight/inbox/<run_id>/scheduled_output.json
   ```
   including `overnight_run_id`, the frozen `review_id`, `decisions` (14 seats), and **`pm_decisions`** (swinger, pragmatist, grinder). The agent packet must carry the same `review_id`. ChatGPT is excluded from automated overnight output.

## Expanding-action setup fingerprint

Each `OPEN`, `ADD`, or `HEDGE` action must include `setup_fingerprint` as an object when that seat or PM has at least one **active** lesson with populated scope. Keys must be drawn from the real strategy scope only: `instruments`, `instrument_family`, `asset_class`, `countries`, `currencies`, `setup_type`, `market_drivers`, `catalyst_type`, `failure_mode`, `decision_dimension`, `technical_setup`. Values must describe that trade (`setup_type`, drivers, catalyst) — not an empty placeholder and not another seat's fingerprint. `HOLD`, `REDUCE`, `CLOSE`, and `NO_TRADE` omit `setup_fingerprint`. If a decision also contains `HOLD`, `NO_TRADE`, `REDUCE`, or `CLOSE`, those actions still apply when an expansion is missing the field. An empty `setup_fingerprint` object is not strategy metadata and does not satisfy the check. A decision whose **only** actions are expanding and missing a populated `setup_fingerprint` is rejected before book simulation.

## Evidence-closed children

`.cursor/hooks/enforce-overnight-runtime.py` blocks all tools when `MW_TRADER_FROZEN=1` or `MW_PM_FROZEN=1` is present in the child transcript.

## What this is not

- Not full Trader Room (no advocates-with-Composer grandchildren, no Sunday clock).
- Not a second provider clock beyond the existing Mon–Fri 02:05 ET ACP schedule.
