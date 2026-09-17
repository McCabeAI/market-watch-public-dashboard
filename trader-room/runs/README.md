# Trader Room run artifacts

Live and dry-run packets are written under `trader-room/runs/<run_id>/` with an immutable run ID and evidence cutoff.

This directory is the approved project artifact surface. Do not copy run output into the agent-control-plane repository.

`*.json` run folders are gitignored so a local live packet is not committed by accident. Retrieval is by run ID:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent dollar-king
```
