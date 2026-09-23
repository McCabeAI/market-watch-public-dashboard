# Manual Market Watch launch runbook

This is the operator command for the dependency-gated launcher. It does not start a clock. ACP weekday schedule `market-watch-weekday-0205` stays disabled. Saying the words in chat does nothing until an authenticated GitHub initiating event exists.

Readiness of this repository build: **GATED_WAITING_ACP**. Stages 00–04 run for a human launch. Stage 05 fail-closes with `awaiting_acp_one_shot_authority` until the ACP one-shot contract in `docs/ACP_ONE_SHOT_AUTHORITY.md` is implemented and verified. The stub provider path is for tests only. It does not call traders and it does not publish production Pages.

## Exact initiating events

Only these two events start a launch:

1. A human-created GitHub issue in `McCabeAI/market-watch-public-dashboard`.
2. A human `workflow_dispatch` of `.github/workflows/launch-market-watch.yml`.

Bot-authored issues and bot workflow dispatches are ignored. GitHub Actions must not open an `[agent-run]` issue.

### Issue created from ChatGPT

Repository: `McCabeAI/market-watch-public-dashboard`

Title (exact):

```text
[launch-market-watch] YYYY-MM-DD
```

`YYYY-MM-DD` is the America/New_York session date. A deliberate same-day rerun uses a different title:

```text
[launch-market-watch] YYYY-MM-DD rerun
```

Body (raw JSON, or one fenced `json` block). Omitted fields use the defaults.

```json
{
  "session_date": "YYYY-MM-DD",
  "rerun": false,
  "mode": "live",
  "provider": "acp"
}
```

| Field | Values | Default |
| --- | --- | --- |
| `session_date` | `YYYY-MM-DD` in America/New_York | Title date, else today |
| `rerun` | `false` or `true` | `false`. `true` allocates a new `launch_id` and a new `review-###` |
| `mode` | `live` or `fixture` | `live` |
| `provider` | `acp` or `stub` | `acp` |

`provider: acp` is the production path. It freezes trusted evidence, then stops at stage 05 until ACP grants one-shot authority. `provider: stub` is a zero-model rehearsal. It must not be used to publish production Pages.

A second issue or dispatch for the same session with `rerun: false` returns the current launch instead of starting another provider cycle.

### workflow_dispatch

Workflow: `Launch Market Watch` (`launch-market-watch.yml`), ref `main`.

| Input | Type | Default |
| --- | --- | --- |
| `session_date` | string `YYYY-MM-DD`, optional | today in America/New_York |
| `rerun` | boolean | `false` |
| `mode` | `live` or `fixture` | `live` |
| `provider` | `acp` or `stub` | `acp` |

## What the command reserves

| Identity | Meaning |
| --- | --- |
| `launch_id` | Immutable `mwl-YYYYMMDDTHHMMSSZ-<8 hex>` |
| `session_date` | America/New_York calendar date |
| `overnight_run_id` | Existing `overnight-YYYYMMDD` session id. Not a clock |
| `review_id` | Trusted `review-###`, allocated at freeze. Explicit rerun gets the next id |

Legacy `schedule_id` `market-watch-weekday-0205` remains only so previously accepted scheduled-output packets still validate. It is not an active schedule. Launcher id is `manual-market-watch-launch-v1`.

## Stage table

| Stage | Name | Continues only when |
| --- | --- | --- |
| 00 | `00_authenticate` | Human issue or human `workflow_dispatch`; unique launch reserved |
| 01 | `01_ingest` | Six-country primary ingestion receipt stored. No invented values |
| 02 | `02_acquire` | Market-state, news, curves, oil, FX, positioning refresh stored |
| 03 | `03_quality_gate` | `PASS`. Due scored gaps are `BLOCKED` with series ids. Optional PMI gaps are `PARTIAL` and do not become HOLDs |
| 04 | `04_freeze` | Evidence reread; packet SHA matches. Cutoff is the actual freeze time, not 01:50 ET |
| 05 | `05_acp_handoff` | Stub rehearsal, or a verified ACP grant once that side exists. Otherwise `awaiting_acp_one_shot_authority` |
| 06 | `06_acceptance` | Existing `[overnight-output]` validate/apply for this launch's packet, 14 traders, and 3 PMs |
| 07 | `07_finalize` | Same launch, session, and review; publication gate `may_publish` |
| 08 | `08_pages` | Explicit `deploy-pages.yml` `workflow_dispatch` after 07. Stub runs record a dry-run and do not publish |

Accepted `[overnight-output]` merges set `MW_PAGES_REQUIRE_LAUNCH=1`. Production Pages then run only when that payload carries a `launch_id` whose stage 07 succeeded, the provider is `acp`, and `publish_production` is true. A merge with no launch binding skips Pages. Callers that leave `MW_PAGES_REQUIRE_LAUNCH` unset still dispatch Pages, so older handoff tests stay valid. No workflow `push` or `schedule` deploys production Pages.

Durable status values are `pending`, `running`, `succeeded`, `blocked`, and `failed`. Each stage stores input and output hashes. A later stage does not run because an earlier process exited 0.

State directory: `data/market_watch_launches/<launch_id>/`.

## Local rehearsal (no production publish)

```bash
PYTHONPATH=. python3 -m scripts.market_watch_launch.cli launch \
  --state-root /tmp/mw-launch \
  --session-date 2026-09-18 \
  --mode fixture \
  --provider stub \
  --actor-type User \
  --actor kevin
```

## Live source smoke (no traders, disposable workspace)

```bash
PYTHONPATH=. python3 -m scripts.market_watch_launch.live_smoke
```

The report lists each series status. HTTP 403 is recorded only when the primary source returns it.
