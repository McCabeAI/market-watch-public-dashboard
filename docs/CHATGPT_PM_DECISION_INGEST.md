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

1. Select the newest complete valid Trader Room run.
2. Rebuild/read the current ChatGPT review packet.
3. Validate id/hash/cutoff/freshness.
4. Hydrate OPEN/ADD/REDUCE/HEDGE/CLOSE at packet mids.
5. Enforce supported instruments, $1bn gross cap, curve-family lock, swinger-inapplicable HEDGE rule (N/A here).
6. Mutate only `pms.chatgpt`.
7. Persist provenance, history, refreshed marks, public JSON, and any future data requests.
