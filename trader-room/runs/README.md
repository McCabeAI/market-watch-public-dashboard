# Trader Room run artifacts

Live and dry-run packets are written under `trader-room/runs/<run_id>/` with an immutable run ID and evidence cutoff.

This directory is the approved project artifact surface. Do not copy run output into the agent-control-plane repository.

`*.json` run folders are gitignored so a local live packet is not committed by accident. Retrieval is by run ID:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id <run_id> --kind submission --agent dollar-king
```

Latest live Cursor-native run (production Market Watch evidence, not the synthetic fixture):

- run ID: `tr-20260917T222019Z-38c9ed3d`
- evidence cutoff: `2026-09-17T22:20:19Z`
- packet sha256: `797b7f84145d23c8546667174babc46ae49e72bba8a5af1aba00ecf1012b0924`
- PM handoff: `trader-room/runs/tr-20260917T222019Z-38c9ed3d/pm_handoff.json`
- status: `STATUS: AWAITING_CHATGPT_ARBITRATION`

Retrieve that handoff with:

```bash
PYTHONPATH=. python scripts/trader_room_go.py retrieve --run-id tr-20260917T222019Z-38c9ed3d --kind pm_handoff
```
