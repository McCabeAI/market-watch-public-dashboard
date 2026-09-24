# ACP one-shot Market Watch delegation

**Status:** **GATED_WAITING_ACP**. Market Watch stage `05_acp_handoff` stays **blocked** with reason `awaiting_acp_one_shot_authority` until ACP performs a real one-shot provider run and returns trusted output through the continuation contract below. A local grant file, environment feature flag, or forged dispatch receipt does **not** count as live provider dispatch and does **not** mark stage 05 succeeded.

## MW runtime (this repository)

- Writes `MW_ACP_ONE_SHOT_DELEGATION_REQUEST` under the launch directory; never writes `MW_ACP_ONE_SHOT_GRANT`.
- Requires a verified `remote_freeze.json` on the trusted freeze commit before stage 05 can reach `handoff_status: request_ready`.
- With a matching grant or receipt file, logs verification only; stages remain blocked until continuation applies provider output from ACP.
- Does **not** call live models, does **not** open `[agent-run]` issues, and does **not** treat `MW_LAUNCH_ACP_DISPATCH_IMPLEMENTED` as dispatch authority.

## ACP contract (single-use)

ACP must, **without a shared secret**, read:

1. The human `[launch-market-watch]` GitHub issue (`author.type == User`, permission `admin`, `maintain`, or `write`).
2. The commit on `main` that contains both:
   - `data/market_watch_launches/<launch_id>/freeze_binding.json`
   - `data/market_watch_launches/<launch_id>/remote_freeze.json`
3. Matching `launch_id`, `review_id`, `base_packet_sha256`, `score_state_sha256`, and starting trader/PM book hashes across the issue, binding, remote freeze, and delegation request.

ACP then:

1. Runs the existing **14 traders + 3 PMs** for that frozen packet.
2. Opens a **data-only** `[overnight-output]` pull request bound to the same `launch_id`, `review_id`, and `base_packet_sha256`.
3. Sends a **single-use** `repository_dispatch` event:

```json
{
  "event_type": "market-watch-launch-accepted",
  "client_payload": {
    "launch_id": "mwl-YYYYMMDDTHHMMSSZ-xxxxxxxx",
    "review_id": "review-NNN",
    "base_packet_sha256": "<sha256>",
    "provider_run_url": "https://example.test/acp/run/..."
  }
}
```

The `.github/workflows/launch-continuation.yml` workflow loads the launch record and runs `continue_accepted_launch` (stages 06–08). It exits **0** while blocked on ACP authority; it exits **non-zero** on hash/review mismatch or unexpected exceptions. It does **not** invoke `deploy-pages.yml` directly.

Weekday schedule `market-watch-weekday-0205` remains disabled. No bot `[agent-run]` issue.

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
  "freeze_commit_sha": "<git sha>",
  "score_state_sha256": "<sha256>",
  "starting_trader_books_sha256": "<sha256>",
  "starting_pm_books_sha256": "<sha256>",
  "binding_relpath": "data/market_watch_launches/<launch_id>/freeze_binding.json",
  "public_verification": {
    "repo": "McCabeAI/market-watch-public-dashboard",
    "ref": "main",
    "readable_without_secrets": true
  },
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

## Grant schema (ACP-owned artifact; MW read-only)

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

## Dispatch receipt schema (ACP-owned; never accepted as dispatch in MW)

```json
{
  "type": "MW_ACP_ONE_SHOT_DISPATCH_RECEIPT",
  "issuer": "acp",
  "launch_id": "...",
  "review_id": "review-NNN",
  "base_packet_sha256": "...",
  "single_use": true
}
```
