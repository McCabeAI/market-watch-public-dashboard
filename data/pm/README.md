# Four-PM durable state

Canonical Git artifacts for the ChatGPT / Swinger / Pragmatist / Grinder layer.

- `books/latest.json` — trusted $1bn-gross books. Models never author this file.
- `public/latest.json` — dashboard-safe projection
- `review_packets/<pm_id>/latest.json` — deterministic daily review packet for that PM only (overnight 14-seat source; Trader Room is explicit fallback only)
- `data_requests/latest.json` — consolidated future-data-request registry
- `inbox/chatgpt_decision.json` — untrusted ChatGPT decision awaiting `scripts/pm/chatgpt_ingest.py`
- `schema/chatgpt_decision.v1.json` — ingest schema
- `decisions/` — apply receipts / provenance

See `docs/PM_LAYER_V1.md`. Do not put secrets or private research pointers here.
