# Trader Room run artifacts

Live and dry-run packets are written under `trader-room/runs/<run_id>/` with an immutable run ID and evidence cutoff.

This directory is the approved Git-durable artifact surface. Sanitized analysis artifacts — the frozen public evidence packet, 14 submissions, conflict map, rebuttals, PM handoff JSON, and Markdown arbiter packet — are committed here so ChatGPT can retrieve a complete handoff. Do not copy run output into the agent-control-plane repository. Do not commit private, licensed, or raw paid evidence.

Unsanitized provider-local packets may be written under `trader-room/runs/.local/` and remain gitignored.

Published-run pointers:

- `trader-room/runs/latest.json`
- `trader-room/runs/INDEX.json`

Retrieval is by run ID:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent dollar-king
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind pm_handoff_markdown
```
