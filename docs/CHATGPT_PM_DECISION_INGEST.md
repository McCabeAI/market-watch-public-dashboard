# ChatGPT PM decision ingest

Git-native contract. ChatGPT authors a decision JSON. Trusted Market Watch code validates it, hydrates deterministic packet mids, and mutates only the ChatGPT book.

## Command

```bash
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py validate --input data/pm/inbox/chatgpt_decision.json
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py apply --input data/pm/inbox/chatgpt_decision.json
```

Inbox path: `data/pm/inbox/chatgpt_decision.json`  
Schema file: `data/pm/schema/chatgpt_decision.v1.json`

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

A receipt keyed by `review_packet_id` + `review_packet_sha256` + decision fingerprint makes apply idempotent. Workflow reruns do not double-apply OPEN/ADD or increment a data request. Stale or wrong packet hash fails closed with no state mutation. Model-authored P&L, canonical marks, and book state are rejected.
