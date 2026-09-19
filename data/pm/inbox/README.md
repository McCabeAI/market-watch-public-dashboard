# ChatGPT PM decision inbox

Place a single `chatgpt_decision.json` here. Validate and apply with trusted repository code:

```bash
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py validate --input data/pm/inbox/chatgpt_decision.json
PYTHONPATH=. python scripts/pm/chatgpt_ingest.py apply --input data/pm/inbox/chatgpt_decision.json
```

The model may not include canonical books, P&L, NAV, or marks. Stale or wrong review-packet hashes are rejected. See `docs/CHATGPT_PM_DECISION_INGEST.md`.
