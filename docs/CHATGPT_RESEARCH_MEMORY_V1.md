# ChatGPT research memory (v1)

Git-backed research memory for the ChatGPT PM only. Hypotheses and the trading-edge profile are **not** canonical books, marks, P&L, or trades. They sit outside frozen Trader Room evidence and outside other traders' private memory. A research update must not be pasted back into an accepted frozen trade packet to change what was knowable at the freeze.

Trusted code: `scripts/pm/chatgpt_research.py`. Storage root: `data/trading/pm/chatgpt/research/`.

## No automatic runtime memory

There is **no** runtime hook that loads these files into a ChatGPT conversation. In `data/trading/pm/chatgpt/research/index.json`, `boundaries.runtime_autoload` is `false`. A new chat starts blank. **Rehydration** means the human or ChatGPT reads the files through the GitHub connector or the local CLI at the start of the conversation. Do not claim automatic memory.

## Cold-start retrieval (order)

1. Read this document: `docs/CHATGPT_RESEARCH_MEMORY_V1.md`.
2. Read `data/trading/pm/chatgpt/research/index.json` — compact current hypotheses, edge revision id, `research_sha256`, and (via CLI) due reviews.
3. Read `data/trading/pm/chatgpt/research/edge/profile.json` for the trading-edge profile.
4. Only if a summary is not enough, open one current hypothesis file or one archive revision:

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research retrieve
PYTHONPATH=. python -m scripts.pm.chatgpt_research retrieve --today 2026-11-13
PYTHONPATH=. python -m scripts.pm.chatgpt_research show --hypothesis HYP_ID
PYTHONPATH=. python -m scripts.pm.chatgpt_research show --hypothesis HYP_ID --revision REV_ID
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-edge
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-edge --revision REV_ID
```

Archive files under `archive/` and `edge/archive/` are historical judgments. Do not treat a later revision as what was believed on an earlier date.

### Due reviews (`retrieve`)

`retrieve` compares each open hypothesis `review_due` (YYYY-MM-DD) to a **review date**, not to `index.as_of`. By default the review date is the current calendar day in `America/New_York`. Override with `--today YYYY-MM-DD`. The response includes `review_date`, `historical_as_of` (the stored index `as_of`), and `due_reviews` rows with `overdue` when `review_due` is strictly before the review date. `retrieve` is read-only and does not rewrite `index.json`.

### `research_sha256`

Every applied ticket advances `research_sha256` in `index.json`. Copy `expected_research_sha256` from the **current** `index.json` when authoring a ticket — not from memory or from this document. The seed commit at the time this doc was written used:

`f5a3ad3eaef5c67edda962afa4e27d531dfe66131529ed07ffc835af369670ea`

That value is obsolete after the first applied update.

## Seeded records (migration, not new forecasts)

One-time seed from journal and lessons (`migration.json`). These are migrated journal facts, not new market forecasts. Seeded hypothesis forecasts use `forecast_kind`: `migrated_historical_observation`, `persistence`: `journal_migration`, journal-cited `stated_at`, and `persisted_at`: null on the revision. New tickets use `forecast_kind`: `prospective` with trusted `stated_at` and `persisted_at` equal to apply time.

| Record | Description |
| --- | --- |
| `hyp-chatgpt-corra-2027hz-20260919` | Open hypothesis **CORRA_2027H-Z receive**. Revisions `rev-hyp-chatgpt-corra-2027hz-20260919-01` through `-04` tied to journal events `jde-bae95770371d4083`, `jde-69e33ef1bd1e4bcf`, `jde-f8d178e55a6644dd`, `jde-2c433e94a5934e8c`. Quantitative forecast field is null. |
| `hyp-chatgpt-rejected-cad-fx-20261002` | Rejected 2026-10-02 from the portfolio pass in journal event `jde-f8d178e55a6644dd`. Not executed. |
| `hyp-chatgpt-rejected-duration-beta-20261002` | Same rejection pass and event. Not executed. |
| `edge-portfolio-pass-20260920` | Seeded from lesson `les-portfolio-pass-20260920`. `provenance_label`: `seeded_from_existing_lesson`. `conditions_worked` is empty. Not promoted from P&L. Confidence `not_assessed`. Maturity `candidate`. Current edge revision: `rev-edge-portfolio-pass-20260920-01`. |

## Saving updates

### Until the workflow is on `main`

The GitHub issue path in `.github/workflows/pm-chatgpt-issue.yml` for title `[chatgpt-research-memory]` is present in the repo but **does not run on `main` until that workflow change is merged**. Until then, use trusted local apply:

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research dry-run --input TICKET.json
PYTHONPATH=. python -m scripts.pm.chatgpt_research apply --input TICKET.json --author LOGIN
```

A human commits **only** `data/trading/pm/chatgpt/research/`. Do not commit books or journal from a research ticket.

### After the workflow is on `main`

ChatGPT (or the human) opens **one new** GitHub issue in `McCabeAI/market-watch-public-dashboard`.

**Title (exact):**

```text
[chatgpt-research-memory]
```

**Body:** one JSON object, or one fenced `json` block and nothing else.

The GitHub user and the issue sender must be the same human with `admin`, `maintain`, or `write`. Bots are rejected. Fields `authorization`, `signature`, `token`, `command`, `shell`, and book/P&L/mark fields are rejected. The issue body is not executed as a trade or a shell command.

Trusted workflow on `main`:

- Checks permission and validates the schema.
- Refuses a stale `expected_research_sha256` or a stale revision id.
- Refuses a replay (same ticket fingerprint already in `receipts/`).
- Commits only the research directory.
- Does **not** dispatch Pages.

The issue comment is the receipt. Interpret status as research persistence only — not booking:

| status | Meaning |
| --- | --- |
| `applied` | Research commit landed. Not a trade. |
| `already_applied` | Same ticket was already stored. |
| `stale` or `conflict` | Re-read `index.json` and open a **new** issue with fresh hashes and revision ids. |
| `rejected` | Schema, auth, or policy failure. |

Editing an old issue does nothing: the workflow listens to `issues` **`opened`** only.

## Ticket shape

| Field | Value |
| --- | --- |
| `schema_version` | `1` |
| `type` | `RESEARCH_MEMORY` |
| `pm_id` | `chatgpt` |
| `action` | One of `create`, `revise`, `close`, `invalidate`, `reject`, `edge_update` |
| `expected_research_sha256` | Copied from current `index.json` |

### `create` / `reject`

Require a `hypothesis` object:

- `title`, `claim`, `as_of`
- `forecast`: `expectation`, optional `horizon`, `metric`, `quantitative`. Omit `stated_at` on new predictions — trusted apply sets it to the apply timestamp. Do not backdate `stated_at`; it must match apply time when supplied. `forecast_kind` is assigned by trusted code (`prospective` for new tickets), not by the ticket.
- `evidence`: list of `{ ref, as_of, note, kind }` with `kind` one of `git`, `drive`, `notion`, `journal`, `packet`, `url`
- `falsifiers`, `competing_explanations`
- `calculations`: `{ description, reproducible_ref, as_of, optional quote }`

`reject` also requires `disposition` (`rejected` or `missed`) and `rejected_reason`.

### `revise` / `close` / `invalidate`

Require `hypothesis_id` and `expected_revision_id` of the **current** revision. `revise` should include the new `hypothesis` body. Optional `evidence_assessment`: `supports`, `contradicts`, `mixed`, or `inconclusive`. Optional `contradicts_revision_id` pointing to an earlier revision of the same hypothesis. `close` and `invalidate` preserve prior archive files. On `revise`, the prior current forecast is copied to `previous_forecast`. If the forecast expectation, horizon, metric, and quantitative are unchanged (or the action is `close` / `invalidate`), the stored forecast is kept unchanged — do not redate it. A changed forecast is a new prospective prediction with `stated_at` at apply time.

### `edge_update`

Require `expected_revision_id` of the edge profile, `accept_as_method`: `true`, `promotion_basis` with `basis_kind` (`lesson`, `postmortem`, `reflection`, or `hypothesis` — **not** `profitable_outcome`), `source_id`, and `rationale` (at least 40 characters), plus `edge_method`. The `source_id` must exist for this PM: a `lesson_id` in `lessons.json`, a `postmortem_id` in `postmortems.json`, a `reflection_id` in `reflections.json`, or a hypothesis file under `research/hypotheses/`. Unknown ids are rejected with no edge archive write. A profitable outcome is not automatically a lesson or an edge. `edge_method.method_status`: `candidate`, `active`, or `retired`. Omit `method_status` on a new method and it stays `candidate`.

### Examples (placeholders — copy live values from the repo)

**Minimal `create`:**

```json
{
  "schema_version": 1,
  "type": "RESEARCH_MEMORY",
  "pm_id": "chatgpt",
  "action": "create",
  "expected_research_sha256": "<COPY_FROM_index.json>",
  "hypothesis": {
    "title": "Fixture hypothesis for save procedure",
    "claim": "Fixture claim for the save procedure.",
    "as_of": "2026-11-04T12:00:00-05:00",
    "forecast": {
      "expectation": "Fixture expectation for documentation only.",
      "horizon": null,
      "metric": null,
      "quantitative": null
    },
    "evidence": [
      {
        "ref": "docs/CHATGPT_RESEARCH_MEMORY_V1.md",
        "as_of": "2026-11-04",
        "note": "Procedure fixture",
        "kind": "git"
      }
    ],
    "falsifiers": [{ "statement": "Fixture falsifier." }],
    "competing_explanations": [{ "statement": "Fixture alternative." }],
    "calculations": [
      {
        "description": "Fixture calculation row.",
        "reproducible_ref": "docs/CHATGPT_RESEARCH_MEMORY_V1.md",
        "as_of": "2026-11-04"
      }
    ]
  }
}
```

**Minimal `revise`:**

```json
{
  "schema_version": 1,
  "type": "RESEARCH_MEMORY",
  "pm_id": "chatgpt",
  "action": "revise",
  "expected_research_sha256": "<COPY_FROM_index.json>",
  "hypothesis_id": "hyp-chatgpt-corra-2027hz-20260919",
  "expected_revision_id": "<COPY_current_revision_id_FROM_index.json_OR_hypothesis_file>",
  "evidence_assessment": "mixed",
  "hypothesis": {
    "title": "CORRA_2027H-Z receive",
    "claim": "Fixture claim for the save procedure.",
    "as_of": "2026-11-04T12:00:00-05:00",
    "forecast": {
      "expectation": "Fixture expectation; score evidence against stored forecast.",
      "horizon": null,
      "metric": null,
      "quantitative": null
    },
    "evidence": [],
    "falsifiers": [],
    "competing_explanations": [],
    "calculations": []
  }
}
```

## Daily procedure (order)

1. **Rehydrate** from the compact index, edge profile, and any due review (from `retrieve` → `due_reviews`) before the Trader Room decision is completed. This is a read. It does not change the frozen packet.
2. **Research and record** new or revised hypotheses, rejected ideas, and evidence assessments through the research issue or the local `apply` command.
3. **Score evidence** against the forecast that was stored, including contradictory evidence. Do not delete the earlier revision.
4. **Trade, hold, or reduce** only through the existing `[chatgpt-pm-decision]` path in [`docs/CHATGPT_PM_DECISION_INGEST.md`](CHATGPT_PM_DECISION_INGEST.md), bound to the current review packet and book hash. Research memory does **not** authorize a trade. Learning lessons still go through the existing `postmortems` and `memory_updates` fields on that decision path. Do not promote a research outcome into a lesson from P&L alone.

## Provenance

| Field | Meaning |
| --- | --- |
| `forecast.stated_at` | When the prediction was stated. Trusted apply sets this for new `prospective` forecasts; seeded rows keep the cited journal timestamp. |
| `forecast.forecast_kind` | `migrated_historical_observation` (seed) or `prospective` (ticket create/revise with a new forecast). |
| `persisted_at` | When the revision was written to research memory (`null` on seeded hypothesis/edge revisions). |
| `previous_forecast` | On revise/close/invalidate, the forecast that was current before this revision. |

| Path | Role |
| --- | --- |
| `index.json`, `hypotheses/*.json`, `edge/profile.json` | Current retrieval view |
| `archive/<hypothesis_id>/<revision_id>.json`, `edge/archive/<revision_id>.json` | Append-only history |
| `receipts/<fingerprint>.json` | Replay prevention |
| `migration.json` | One-time seed record |
