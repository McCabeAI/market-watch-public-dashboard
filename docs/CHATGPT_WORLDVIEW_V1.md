# ChatGPT PM worldview (v1)

Ever-present, revisable macro opinion for the ChatGPT PM. It is independent of the book. A trade hypothesis is one expression of this view, not the filter for what is remembered.

Storage is the existing research tree, `data/trading/pm/chatgpt/research/worldview/`. The native `[chatgpt-research-memory]` issue and `scripts/pm/commit_chatgpt_research.sh` already commit that directory and nothing else. This layer does not add a writer, a schedule, or a Pages dispatch.

## No automatic recall

`boundaries.runtime_autoload` is false. A new ChatGPT session starts blank. Rehydration means someone runs the CLI, or reads the files, at the start of the session. Do not claim a runtime hook or human-like memory.

Entrypoint:

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research retrieve
```

The JSON field `worldview` is the compact startup bundle: global tension, six core-country score lines, the wider watchlist, recent change records, unresolved contradictions, signposts, and research questions. Order is deterministic. Open a deeper file only when the bundle is not enough.

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --country CA
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --theme inflation
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --watch wv-watch-iran
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --history wv-global-tension
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --revision rev-worldview-0001
PYTHONPATH=. python -m scripts.pm.chatgpt_research show-worldview --markdown
```

Core countries are Australia, Canada, the euro area, Japan, New Zealand, and the United States. The watchlist is a list. It is not fixed at three topics.

## What is stored

| Path | Role |
| --- | --- |
| `worldview/state.json` | Current global view, six country records, watchlist, beliefs |
| `worldview/archive/<revision_id>.json` | Append-only snapshot. Later text does not rewrite it |
| `worldview/changes/<change_id>.json` | What changed, what did not, why, contrary evidence, implications |
| `index.json` `worldview` | Revision id and summary covered by `research_sha256` |

Each substantive belief has an id, an epistemic label (`fact`, `inference`, or `assumption`), support (`sourced`, `unsupported`, `outdated`, or `insufficient_authorized_current_evidence`), evidence refs with observation, collection, and freeze clocks, `first_stated_at`, `revised_at`, `last_reviewed_at`, confidence and a reason, alternatives, and falsifiers or review triggers. Quantitative probability is optional and is left null unless a person supplies one.

Structural facts keep review triggers and are expected to change slowly. Cyclical readings and market implications can change quickly. An unsupported belief stays visibly unsupported. A missing print does not delete a retained observation.

The seed is `acceptance: awaiting_pm`. `claims.learned_edge` and `claims.validated_edge` are false. It is not a validated trading edge.

Market Watch temperature levels, impulses, classes, component vintages, and the score lineage are reused. They are not a new score model. Country prose is a reading of those stored components. Policy reaction, transmission, and financial conditions are unsupported where the frozen packet does not contain them. Derived meeting-price levels are excluded because Kevin flagged the frozen front Fed estimate as wrong by about 8bp. Calendar dates are kept. An empty date list means unverified timing, not the absence of events.

The sixteen numbered foundation lessons (1–16) are stored on the edge profile at `data/trading/pm/chatgpt/research/edge/profile.json` under `methods[0].scope.approved_foundation_and_tail_lessons`. The seed cites `edge.current_revision_id` from `index.json` (currently `rev-edge-portfolio-pass-20260920-05`) plus that lesson list; it does not replace or retire them.

Clocks are split on purpose: belief `effective_at` stays on the **freeze label** from the November 6 evidence packet (`2026-11-06T06:25:49.281876-05:00`). Packet component `as_of` / `retrieved_at` and internal market generation `2026-11-06T11:42:41Z` stay on the evidence rows. Direct-input `observation_as_of` stays the input calendar day (`2026-11-06`); `collection_as_of` is the **persisted_at** clock when the seed recorded that input. `seeded_at`, `updated_at`, `persisted_at`, and `first_stated_at` / `last_reviewed_at` on beliefs use the same **generation** timestamp (UTC ISO) when the seed is written—not the freeze label.

Canada transmission in the seed is a **qualitative hypothesis** from Kevin’s direct input (not a calibrated strength). The tail on deleveraging is explicitly **not** a bot verdict on credibility or trade selection; mechanism and practical evaluation remain open.

There is **no** runtime autoload. A **new session must run** `retrieve` (or read the files) to load the worldview; do not claim automatic recall.

## Daily order

1. `retrieve` standing context, including the worldview, before the book review.
2. Mark and evaluate the owned book.
3. Read the whole market and the regime. Keep watchlist topics when the day's headlines drop them.
4. Reconcile the book with that context.
5. Rank scenarios, research questions, and opportunities.
6. Discuss any research launch with Kevin. Data-complete and traders-complete remain his two separate calls.
7. Save only an explicitly accepted worldview or hypothesis update.

Trusted apply time is the clock for a new statement. Evidence dates stay on the evidence refs. A no-change review updates `last_reviewed_at` only. It does not reset `first_stated_at` or invent a revised opinion. A review may lower confidence without reversing the statement. The same ticket, or the same patch body replayed under a fresh hash, does not write a second revision. A stale `expected_research_sha256` or a stale `expected_worldview_revision_id` writes nothing.

`suggest-worldview` compares the authorized evidence snapshot’s `temperature_scores` with the stored score foundation and prints diffs. It does not author a belief and it does not write.

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research suggest-worldview
```

To compare against an explicit file (no automatic “newest file” discovery), pass `--snapshot`, `--file-sha256`, and `--packet-sha256`. Optionally pass `--freeze-label` when the file is not the canonical November 6 path.

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research suggest-worldview \\
  --snapshot tests/fixtures/worldview_synthetic_future.json \\
  --file-sha256 <sha256 of that file’s bytes> \\
  --packet-sha256 <packet_sha256 field inside the JSON> \\
  --freeze-label 2099-01-01T00:00:00Z
```

## Save an accepted update

Copy `research_sha256` and `worldview.current_revision_id` from the current `index.json`. `pm_authored` must be true. Local preview:

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_research dry-run --input TICKET.json
PYTHONPATH=. python -m scripts.pm.chatgpt_research apply --input TICKET.json --author LOGIN
```

On `main`, the same JSON is the body of one new issue titled `[chatgpt-research-memory]`. The workflow commits only `data/trading/pm/chatgpt/research/`. It does not book a trade, change canonical scores, or dispatch Pages.

Minimal patch (belief-only):

```json
{
  "schema_version": 1,
  "type": "RESEARCH_MEMORY",
  "pm_id": "chatgpt",
  "action": "worldview_patch",
  "pm_authored": true,
  "expected_research_sha256": "<COPY_FROM_index.json>",
  "expected_worldview_revision_id": "<COPY_worldview.current_revision_id>",
  "worldview_patch": {
    "why": "PM accepts a narrower reading of the stored US activity score after review.",
    "contrary_evidence": "The services survey impulse is slightly negative while manufacturing is positive.",
    "implications": "No trade follows from this reading.",
    "acceptance": "pm_accepted",
    "beliefs": [
      {
        "belief_id": "wv-us-activity",
        "statement": "US activity remains near the structural anchor. The October surveys disagree in sign. This is still not a policy conclusion.",
        "evidence_comparison": "mixed",
        "confidence": {
          "level": "low",
          "reason": "Component signs disagree and the GDP vintage is older."
        }
      }
    ]
  }
}
```

Copyable example that updates a **country score foundation** (merge into `countries.CA.score_foundation.Activity`; supply the scalar fields your change touches—`level`, `impulse`, `temperature_class`, `direction`, `as_of`, `coverage`—so the patch is substantive):

```json
{
  "schema_version": 1,
  "type": "RESEARCH_MEMORY",
  "pm_id": "chatgpt",
  "action": "worldview_patch",
  "pm_authored": true,
  "expected_research_sha256": "<COPY_FROM_index.json>",
  "expected_worldview_revision_id": "<COPY_worldview.current_revision_id>",
  "worldview_patch": {
    "why": "PM adjusts the retained Canada Activity level after reconciling with the latest authorized packet.",
    "contrary_evidence": "Prior retained level disagrees with the incoming structural level.",
    "implications": "Tension belief may need review if pillars diverge from the stored narrative.",
    "countries": [
      {
        "country": "CA",
        "score_foundation": {
          "Activity": {
            "level": 41.25,
            "impulse": 0.5,
            "temperature_class": "neutral",
            "direction": "neutral",
            "as_of": "2026-08",
            "coverage": 1.0
          }
        }
      }
    ]
  }
}
```

No-change review:

```json
{
  "schema_version": 1,
  "type": "RESEARCH_MEMORY",
  "pm_id": "chatgpt",
  "action": "worldview_review",
  "pm_authored": true,
  "expected_research_sha256": "<COPY_FROM_index.json>",
  "expected_worldview_revision_id": "<COPY_worldview.current_revision_id>",
  "worldview_review": {
    "note": "Reviewed the US activity belief. The statement still matches the stored components.",
    "belief_ids": ["wv-us-activity"]
  }
}
```

Confidence can be lowered in `worldview_review.confidence_updates` without a new statement. Receipts use the same status words as hypothesis tickets: `applied`, `already_applied`, `stale`, `conflict`, `rejected`.

## Seed boundary

The committed seed uses frozen `evidence_snapshot.json` for overnight `20261106` review `001`: packet `57cbe09b78e90e4d87a1fc08764ce3f0983ef627fa58c168f36bd2db09081ac8`, git blob `d875ddc64fab7258cbcf72c6b4a7df0a4ec64d33`, freeze `2026-11-06T06:25:49.281876-05:00`, market generation `2026-11-06T11:42:41Z`. Iran, Ukraine, and Brazil are retained with insufficient authorized current evidence. No article URLs are opened and no new collection is run.
