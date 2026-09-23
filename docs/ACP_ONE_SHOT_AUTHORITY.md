# ACP one-shot Market Watch delegation (contract only)

**Status:** Not implemented in ACP or in this repository’s runtime dispatch. Market Watch stage `05_acp_handoff` remains **blocked** with reason `awaiting_acp_one_shot_authority` until an approved ACP change exists **and** this repo sets `MW_LAUNCH_ACP_DISPATCH_IMPLEMENTED=1`.

## Required ACP behavior (future PR)

1. **Reject** bot-created ordinary `[agent-run]` issues (unchanged policy).
2. **Accept** one-shot delegation only after verifying the original human `[launch-market-watch]` issue (`author.type == User`), target repo `McCabeAI/market-watch-public-dashboard`, matching `launch_id`, `review_id`, exact `base_packet_sha256` on the trusted freeze commit, and the budget object below.
3. **Single-use:** each consumed `launch_id` must not authorize a second provider run.
4. **Dispatch timing:** provider dispatch only after `freeze-succeeded` for that launch/review.
5. **Scope:** no change to global scheduler, shared credentials, or other projects; weekday schedule `market-watch-weekday-0205` stays disabled.

## MW runtime (this repo)

- Writes `MW_ACP_ONE_SHOT_DELEGATION_REQUEST` under the launch directory; never writes `MW_ACP_ONE_SHOT_GRANT`.
- With a matching grant file, verifies fields then stays blocked unless dispatch is explicitly implemented.
- Does **not** call live models or open synthetic `[agent-run]` issues.

## Delegation request schema

```json
{
  "type": "MW_ACP_ONE_SHOT_DELEGATION_REQUEST",
  "version": 1,
  "target_repo": "McCabeAI/market-watch-public-dashboard",
  "launch_id": "mwl-YYYYMMDDTHHMMSSZ-xxxxxxxx",
  "session_date": "YYYY-MM-DD",
  "review_id": "review-NNN",
  "overnight_run_id": "overnight-YYYYMMDD",
  "base_packet_sha256": "<sha256>",
  "origin": {
    "source": "github_issue",
    "issue_number": 0,
    "issue_url": "https://github.com/...",
    "actor": "login",
    "actor_type": "User"
  },
  "budget": {
    "launcher_id": "manual-market-watch-launch-v1",
    "legacy_schedule_id_inactive": "market-watch-weekday-0205",
    "total_model_cap": 19,
    "grok_cap": 18,
    "composer_cap": 2,
    "parent_model": "grok-4.6",
    "frozen_command": ".cursor/commands/overnight-scheduled.md"
  },
  "dispatch_when": "freeze-succeeded",
  "single_use": true
}
```

## Grant schema (ACP-owned artifact)

ACP would emit (MW only **reads** `launch_dir/acp_one_shot_grant.json` in tests):

```json
{
  "type": "MW_ACP_ONE_SHOT_GRANT",
  "issuer": "acp",
  "launch_id": "...",
  "review_id": "review-NNN",
  "base_packet_sha256": "...",
  "single_use": true
}
```
