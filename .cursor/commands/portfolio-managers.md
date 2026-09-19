Run the automated Portfolio Manager review for **Swinger**, **Pragmatist**, and **Grinder** after review packets exist. ChatGPT PM decisions use Git ingest only — do **not** launch ChatGPT here.

Read `docs/PM_LAYER_V1.md` first. Each automated PM is independent: own packet, own prior book, own memory; no mutual current-cycle visibility. ChatGPT may still see committed PM outputs per the existing hierarchy — do not change that.

Deterministic packet refresh (when needed):

```bash
PYTHONPATH=. python scripts/pm_layer.py refresh-packets --allow-trader-room-fallback
```

Emit the launch plan (orchestration must follow it):

```bash
PYTHONPATH=. python scripts/pm_layer.py launch-plan --run-id <trader_room_run_id>
```

## Principal routing (required)

Launch each automated PM by invoking its **Cursor custom agent** (same mechanism as the 14 Trader Room advocates):

| PM | Custom agent |
| --- | --- |
| `swinger` | `.cursor/agents/swinger.md` |
| `pragmatist` | `.cursor/agents/pragmatist.md` |
| `grinder` | `.cursor/agents/grinder.md` |

Each custom agent frontmatter pins exact **`grok-4.6[]`**, which routes to runtime model **`grok-4.6`** and passes `enforce-subagent-models.sh`.

**Do not** launch PM principals with Task / `subagent_type` and `model: grok-4.6`, `inherit`, or any `cursor-grok-4.6-*` slug. That path emits forbidden runtime slugs (`cursor-grok-4.6-high-fast`, etc.) and will fail closed or fall back incorrectly.

Run all three automated PM principals concurrently when packets are ready.

## Subagents

Each PM principal may use **0–3** children total. Allowed child models: **`composer-2.5`** and **`grok-4.6`** only.

- Prefer **`composer-2.5`** Task subagents for internal research passes.
- If a **`grok-4.6`** child is truly required, launch another locked custom agent with `grok-4.6[]` frontmatter — never a Task `model` slug.

No grandchildren. No web/search/new evidence after freeze.

## Apply path

Trusted code applies decisions — models do not write canonical books:

```bash
PYTHONPATH=. python scripts/pm/automated.py  # ingestion helpers only in repo tests/overnight
```

Persist provenance under `data/pm/decisions/` and refresh public state via trusted CLIs.

## Policy line

Include in the parent transcript for hook enforcement:

`PM_MODEL_POLICY={"version":1,"principal_model":"grok-4.6","principal_launch":"cursor_custom_agent","subagent_models":["grok-4.6", "composer-2.5"],"max_subagents_per_pm":3}`

Auto, Other Models, and Fast/high/low Grok aliases remain prohibited.
