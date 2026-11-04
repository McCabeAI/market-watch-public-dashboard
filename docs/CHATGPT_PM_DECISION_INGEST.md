# ChatGPT PM decision ingest

Git-native contract. ChatGPT authors a decision JSON. Trusted Market Watch code validates it, hydrates deterministic packet mids, and mutates only the ChatGPT book.

## Command

```bash
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py validate --input data/pm/inbox/chatgpt_decision.json
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py apply --input data/pm/inbox/chatgpt_decision.json
```

Inbox path: `data/pm/inbox/chatgpt_decision.json`  
Schema file: `data/pm/schema/chatgpt_decision.v1.json`

The inbox file is the optional pull-request fallback. The daily path is one GitHub issue. It does not open a pull request, and it does not ask a maintainer to approve a workflow or to start Pages by hand.

## GitHub issue

Create one issue in `McCabeAI/market-watch-public-dashboard` with the ChatGPT GitHub connector, signed in as a human who has `admin`, `maintain`, or `write` on the repository.

Title, exact:

```text
[chatgpt-pm-decision]
```

Body: one JSON object, or one fenced `json` block and nothing else. The connector's GitHub user and the issue sender must be that same human `User`. Bots, a sender that is not the author, a failed permission lookup, and any other title are rejected. Fields inside the JSON such as `signature`, `authorization`, `token`, `command`, or `shell` are rejected and are never trusted.

Trusted code on `main` checks the collaborators API, checks the frozen packet and the current ChatGPT book, runs the existing deterministic apply, and commits only generated portfolio state. A second distinct decision on the same day is valid after that commit, and only if its ticket copies the refreshed packet hash and the new `book_sha256.txt`. A replay of the same ticket does not book the trade again. Two different tickets for the same book hash are a conflict: the first commit stands and the other ticket must be re-based. The workflow does not rebase onto a `main` that moved.

Copy these fields from the repository, do not calculate them:

| Field | Source |
| --- | --- |
| `review_packet_id` | `data/pm/review_packets/chatgpt/latest.json` |
| `review_packet_sha256` | same file |
| `evidence_cutoff` | same file |
| `memory_context_sha256` | same file; required by the learning gate for OPEN/ADD/HEDGE |
| `expected_book_sha256` | the single line in `data/pm/review_packets/chatgpt/book_sha256.txt` |

`expected_book_sha256` is required on this path. It is the SHA-256 of the canonical JSON for `data/pm/books/latest.json` → `pms.chatgpt` (sorted keys, indent 2, trailing newline). Trusted code rewrites the text file when it persists books. The pull-request fallback still accepts a decision that omits it.

Example body:

```json
{
  "schema_version": 1,
  "type": "PM_DECISION",
  "pm_id": "chatgpt",
  "review_packet_id": "prp-chatgpt-overnight-YYYYMMDD-review-001",
  "review_packet_sha256": "<64 lowercase hex from latest.json>",
  "evidence_cutoff": "<evidence_cutoff from latest.json>",
  "memory_context_sha256": "<memory_context_sha256 from latest.json>",
  "expected_book_sha256": "<line from book_sha256.txt>",
  "actions": [{"action": "NO_TRADE"}],
  "thesis": "No incremental edge after the freeze.",
  "invalidation": "A clean policy-path surprise.",
  "conviction": 40,
  "rationale": "Wait for the next packet.",
  "synthesis": "Hold dry powder.",
  "alerts": [],
  "future_data_requests": []
}
```

A local check that does not apply a trade:

```bash
PYTHONPATH=. python -m scripts.pm.chatgpt_issue dry-run --input /tmp/chatgpt_ticket.json
```

The issue comment is the result. `status: applied` with `book_committed: true` means the canonical commit landed. `publication_status: published` means the existing `deploy-pages.yml` production run finished and the live `pm-books.json` ChatGPT book matches that commit. Creating the issue, or accepting the dispatch, is not publication. `book_committed: true` with `publication_status: incomplete` and `needs_attention: true` means the book commit stands and Pages still needs attention.

Receipts are immutable. The first decision for a packet id remains at `data/pm/decisions/<review_packet_id>.json`. Every decision is also stored at `data/pm/decisions/chatgpt/<decision_fingerprint>.json`. A later decision adds a new fingerprint file and does not replace the earlier receipt, journal row, or ledger history.

Failure and recovery:

| Result | What happened | What to do |
| --- | --- | --- |
| `rejected` / stale packet or book | No commit | Read the current packet and `book_sha256.txt`, then open a new issue |
| `conflict` / `main` moved | No commit | Re-base the ticket on the new book and packet |
| `already_applied` | Replay of a stored fingerprint | Do not expect a second fill |
| `incomplete` after a commit | Book is on `main`; Pages did not finish or the live book did not match | Re-run the failed Actions workflow. That replay does not book again. If no Pages run exists for the commit, the replay dispatches `deploy-pages.yml` once |

Rollback: revert the commit that contains both the book state and the new receipt. Reverting the book without the receipt makes a replay look already applied. The pull-request workflow remains available as a fallback. Removing the `issues:` trigger from `.github/workflows/pm-chatgpt-issue.yml` stops new issue submissions. After a revert, dispatch the existing `deploy-pages.yml` workflow on `main` with an empty launch id. Do not edit trader seats, the other three PM mandates, or agent-control-plane as part of this rollback.

## Required fields

| Field | Rule |
| --- | --- |
| `schema_version` | `1` |
| `type` | `PM_DECISION` |
| `pm_id` | `chatgpt` |
| `review_packet_id` | must equal current `data/pm/review_packets/chatgpt/latest.json` |
| `review_packet_sha256` | must equal the current packet hash |
| `evidence_cutoff` | must equal the current packet cutoff |
| `actions` | list; empty is treated as HOLD |
| `thesis` / `invalidation` / `conviction` | optional but recommended |
| `rationale` / `synthesis` | ChatGPT's final write-up |
| `memory_context_sha256` | required for OPEN/ADD/HEDGE; must match this packet's own memory hash |
| `lifecycle` on `OPEN` / `HEDGE` | `framing` tactical, swing, or structural, plus `realization_logic` and `catalyst_logic` |
| `harvest_reviews` | required only when a kept open position has tripped a profit-harvest review. Separate `thesis_still_valid` from `remaining_edge`. Full size needs `remaining_edge: true` and `would_initiate_flat: "yes"`. Not a take-profit order. |
| `postmortems` / `memory_updates` | optional structured reflection; cannot change marks or P&L |
| `alerts` | list |
| `future_data_requests` | optional list |

Each future-data-request object:

```json
{
  "request": "string",
  "reason": "string",
  "decision_impact": "string",
  "priority": "low|medium|high",
  "suggested_source": null
}
```

## Forbidden

The model may **not** author:

- canonical books / positions
- NAV / cash
- realized, unrealized, or total P&L
- gross utilization
- canonical marks / `entry_price` / `mark_price` as book state

Action-level `price` is ignored when a deterministic packet mid exists. Trusted code overwrites it.

Stale packet hash, wrong packet id, malformed JSON, or model-authored canonical state is rejected.

## Apply path

`.github/workflows/pm-chatgpt-decision.yml` is the unattended Git-native path. It runs trusted code from the PR base, downloads only `data/pm/inbox/chatgpt_decision.json`, and never executes model-authored code.

1. Select the current daily PM source (newest successful overnight 14-seat review; explicit Trader Room fallback only when no overnight review exists).
2. Rebuild/read the current ChatGPT review packet.
3. Validate id/hash/cutoff/freshness against that packet.
4. Hydrate OPEN/ADD/REDUCE/HEDGE/CLOSE at packet mids.
5. Enforce supported instruments, $1bn gross cap, curve-family lock, swinger-inapplicable HEDGE rule (N/A here).
6. Mutate only `pms.chatgpt`.
7. Persist canonical PM books, `data/trading/**` ledger/journal/memory updates, decision receipt/history, review packet refresh, public JSON, and any future data requests.
8. Commit those trusted generated files to the decision branch and leave the PR mergeable.

A receipt keyed by decision fingerprint, packet hash, and book hash makes an exact replay idempotent. A later genuine decision is stored beside it after the packet and book hashes move; it does not replace the earlier receipt. Workflow reruns do not double-apply OPEN/ADD or increment a data request. Stale or wrong packet hash, or a book hash that is no longer current, fails closed with no state mutation. Model-authored P&L, canonical marks, and book state are rejected. The issue workflow then dispatches the existing production Pages workflow. That dispatch joins the `pages-production` concurrency group already defined on `deploy-pages.yml`. This repository does not merge Pages publication into the trading engine.
