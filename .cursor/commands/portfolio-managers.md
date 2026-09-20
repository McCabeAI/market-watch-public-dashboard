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

## Risk sizing and hard loss limits

Notional is descriptive, not the risk budget. Each PM has $1bn paper NAV, a trusted **$10m 1%-shock risk-capital limit**, and a trusted **$50m high-water-mark drawdown stop**. Official SOFR ACT/360 is charged on shocked risk capital; equal risk capital receives equal financing treatment across asset classes. Size from plausible adverse paths and historical drawdowns, not as a percentage of a gross-notional cap and never merely to fill available capacity. If trusted state is `risk_stopped`, do not submit OPEN/ADD/HEDGE; the book remains flat until the stop is explicitly reset by trusted policy.

For every PM rates/curve/rates-RV action, use the same canonical book-side convention as Trader Room: `side: "long"` = long duration / receive / profits when the canonical mark falls; `side: "short"` = short duration / pay / profits when the canonical mark rises. Never use `long` to mean "long implied rate." For a new rates `OPEN`, include `expected_mark_direction: "lower"|"higher"` and keep it consistent with the side (`lower -> long`, `higher -> short`).

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
