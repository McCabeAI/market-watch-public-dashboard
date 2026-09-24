# Launch Market Watch (manual)

Use this when Kevin says **launch market watch**. Do not start a cron, do not open an `[agent-run]` issue, and do not dispatch traders yourself.

Create one human GitHub issue in `McCabeAI/market-watch-public-dashboard`.

Title:

```text
[launch-market-watch] YYYY-MM-DD
```

Use today's date in America/New_York. For a deliberate same-day rerun, append ` rerun` to the title and set `"rerun": true`.

Body:

```json
{
  "session_date": "YYYY-MM-DD",
  "rerun": false,
  "mode": "live",
  "provider": "acp"
}
```

Optional alternative: `workflow_dispatch` on `Launch Market Watch` with the same fields. Full schema, stage table, and the ACP wait state are in `docs/MANUAL_MARKET_WATCH_LAUNCH_RUNBOOK.md`.
