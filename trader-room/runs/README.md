# Trader Room run artifacts

Live and dry-run packets are written under `trader-room/runs/<run_id>/` with an immutable run ID and evidence cutoff.

This directory is the approved Git-durable artifact surface. Sanitized analysis artifacts — the frozen public evidence packet, 14 submissions, conflict map, rebuttals, PM handoff JSON, and Markdown arbiter packet — are committed here so ChatGPT can retrieve a complete handoff. Do not copy run output into the agent-control-plane repository. Do not commit private, licensed, or raw paid evidence.

Unsanitized provider-local packets may be written under `trader-room/runs/.local/` and remain gitignored.

A run is valid only when every standing trader, aggregator, and rebuttal payload was returned by an independent `grok-4.6` seat. Parent-authored or simulated briefs are `INVALID`. The prior run `tr-20260917T231827Z-4ca9133b` is marked invalid for that reason and must not be presented as a Trader Room result. `tr-20260917T235817Z-3adf83db` has independent first-pass, conflict, and rebuttal seats on disk but is `INCOMPLETE` until the grok-4.6 final aggregator returns; it is not a valid complete result.

Published-run pointers:

- `trader-room/runs/latest.json`
- `trader-room/runs/INDEX.json`

Retrieval is by run ID:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent dollar-king
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff_markdown
```
