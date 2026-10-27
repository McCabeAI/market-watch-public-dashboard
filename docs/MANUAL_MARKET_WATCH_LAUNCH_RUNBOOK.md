# Manual Market Watch launch runbook

This is the operator command for the dependency-gated launcher. It does not start a clock. ACP weekday schedule `market-watch-weekday-0205` stays disabled. Saying the words in chat does nothing until an authenticated GitHub initiating event exists.

Readiness of this repository build: **GATED_WAITING_ACP**. Stages 00–04 run for a human launch. Stage 05 fail-closes with `awaiting_acp_one_shot_authority` until the ACP one-shot contract in `docs/ACP_ONE_SHOT_AUTHORITY.md` is implemented and verified. The stub provider path is for tests only. It does not call traders and it does not publish production Pages.

## Exact initiating events

Only these two events start a launch:

1. A human-created GitHub issue in `McCabeAI/market-watch-public-dashboard`.
2. A human `workflow_dispatch` of `.github/workflows/launch-market-watch.yml`.

Bot-authored issues and bot workflow dispatches are ignored. GitHub Actions must not open an `[agent-run]` issue. The issue author must be the authenticated GitHub user, and that user must have `admin`, `maintain`, or `write` on this repository. A read-only or outside actor is refused at stage 00, before ingestion.

An `acp` launch commits and pushes the stage 04 freeze, rereads that commit on the remote, and only then writes the delegation request. Stage 05 stays `awaiting_remote_freeze` until that attestation exists, and `awaiting_acp_one_shot_authority` after it. A local grant file is not a provider dispatch. After ACP later accepts an `[overnight-output]` pull request, it sends `repository_dispatch` event `market-watch-launch-accepted` with `client_payload` `{launch_id, review_id, base_packet_sha256, provider_run_url}`. That event is handled by `launch-continuation.yml`. Production Pages run only after stages 06 and 07 succeed for that same launch and review.

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
| 08 | `08_pages` | Explicit `deploy-pages.yml` `workflow_dispatch` after 07, confirmed by an Actions run id. The launch stays `running` until that run's deploy succeeds and is reconciled. Stub runs record a dry-run and do not publish |

Accepted `[overnight-output]` merges set `MW_PAGES_REQUIRE_LAUNCH=1`. Production Pages then run only when that payload carries a `launch_id` whose stage 07 succeeded, the provider is `acp`, and `publish_production` is true. A merge with no launch binding skips Pages. Callers that leave `MW_PAGES_REQUIRE_LAUNCH` unset still dispatch Pages, so older handoff tests stay valid. No workflow `push` or `schedule` deploys production Pages.

Durable status values are `pending`, `running`, `succeeded`, `blocked`, and `failed`. Each stage stores input and output hashes. A later stage does not run because an earlier process exited 0.

State directory: `data/market_watch_launches/<launch_id>/`.

## Two editions on one Pages URL

Every production site carries `release.json` with its phase, launch, review, packet, and session. The visible banner under the header repeats the phase, date, and times.

| Edition | Published by | When | Trader Book shows |
| --- | --- | --- | --- |
| `research` | `publish-research-pages.yml` | After a live ACP launch run on `main` completes with Stage 04 verified and remotely attested | Previous accepted books, labeled with their run id, as-of, and acceptance time. Today's cycle is `pending` |
| `final` | `deploy-pages.yml` (Stage 08) | After Stage 07, unchanged dispatch and reconcile path | Today's accepted books and P&L for the same launch, review, and packet |

The research edition has no `workflow_dispatch` and no schedule. It builds in a throwaway overlay from the frozen evidence packet and the launch's staged lineage scores. Source health is that launch's Stage 01 ingest. News is in two labeled parts (see below). It refuses to build when the attestation is missing or does not match, a Stage 00–04 artifact hash drifted, the frozen packet fails `require_snapshot`, staged scores do not match `score_state_sha256`, the quality gate is not `PASS`, or the freeze date is not the session date (`fail`). It skips a stub, fixture, or non-production launch, a launch that is no longer `running`, a session that is no longer today in New York, and a launch whose Stage 06/07 already succeeded or that a newer launch replaced (`skip`).

The only durable write is `data/market_watch_launches/<launch_id>/research_pages.json`, with one row per deploy run. `launch.json`, `index.json`, and Stage 08 are not touched, so the launch stays `running` and the one-live-launch guard stays closed until the final edition is reconciled. A research build or deploy failure does not affect the ACP handoff, acceptance, or Stage 08.

Publication order is the rank `(session_date, launch stamp, phase)` with research < final. Before deploying, both workflows compare against committed research receipts, finalized launches, and the live `release.json`. They refuse anything that is outranked. Equal rank with a different identity also fails closed. Consequences:

* A late or replayed research deploy never replaces the final edition of the same or a newer launch.
* `gh workflow run deploy-pages.yml --ref main` without `launch_id` (manual refresh) is refused while a newer research edition is live or committed. Wait for the final edition, or dispatch with the finalized `launch_id`.
* Recovery is a re-run of the same `publish-research-pages.yml` run ("Re-run all jobs"). It re-derives eligibility from `main` and is idempotent.

### Deploy ordering between the two workflows

The research deploy job is not in the `pages-production` concurrency group. GitHub keeps one pending run per group and a new entrant replaces it, so sharing the group would let research cancel a pending final. `scripts/market_watch_launch/publication_coordinator.py` orders the two through Actions API state instead:

1. Research `Record deploy job start` stores the job start time before checking out `main`. A finalized launch commits Stage 07 to `main` before its `deploy-pages.yml` dispatch, so a final created before that time makes the research guard skip.
2. Research `Yield to production Pages deploys` runs right before `actions/deploy-pages`. It skips (fail closed) if any production `deploy-pages.yml` run (`workflow_dispatch`, `main`) is not completed, or was created or re-run since the job started, or has unreadable times. Runs are listed newest-first and by every active status, so re-runs of old runs are seen. Research never waits.
3. Final `Wait for in-flight research deploy` runs right before `actions/deploy-pages` in `deploy-pages.yml`. It polls every 15 s, up to 25 min, while any `Deploy research edition` job is unfinished and its `Deploy to GitHub Pages` step is not completed. The research deploy job has a 12 min timeout, and its Pages step a 5 min timeout. Then it refuses a release whose session is older than the New York date of any successful research deploy step. That covers the gap before the research receipt is committed.
4. Final `Recheck publication order before deploy` repeats the publication guard against a fresh `main` checkout and the live `release.json`.

If the final is not visible to step 2, it was created after the research job started. The final reaches step 3 only after its multi-minute build, when the research deploy job is long visible. Stale API data only shows earlier states, which makes the final wait. `InterleavingModelTests` in `tests/test_mw_publication_coordinator.py` checks this over a grid of arrival times, API lag, deploy durations, and CDN lag. A negative control drops the wait and finds violations.

The proof assumes four things:

* The API never reports a step completed before it is.
* `actions/deploy-pages` returns only after the Pages deployment is terminal.
* Runner and API clocks agree within 120 s.
* Pages serves the most recently created successful deployment.

Operator notes:

* A research edition skipped because a final was queued is not retried; the final replaces it.
* A final that times out in step 3 fails without deploying. Use "Re-run all jobs". Artifact names include the run attempt, so "Re-run failed jobs" cannot find the build artifacts.
* API errors fail closed: research skips, the final fails.
* Rollback: revert the coordinator steps in both workflows. Restoring the old shared group brings back the pending-replacement race.

### News on the research edition

* **Current verified headlines (as of the Stage 04 news cutoff).** Selected by `scripts/market_watch_launch/research_headlines.py` from `families.news` in the hash-verified `evidence_snapshot.json`. Shown on the Front Page (top 4) and under News & Research (up to 8). Headline, source, time, and link only. There are no summaries or model text, and nothing implies trader acceptance.
  * An item needs a verification status of `official`, `corroborated`, or `single_source`, and its `id` must match its source edges.
  * Its frozen and recomputed `score_transmission` disposition must be `show` or `assess`.
  * One source edge must have an `https` link on the publisher's own host. That edge must come from a known discovery surface with an `ok` acquisition receipt in this run.
  * Its timestamp must carry a timezone and fall after the later of the previous acceptance and the cutoff minus 24 h, and not after the cutoff.
  * Items already in the accepted digest, and duplicates, are dropped.
  * Any other item is rejected and counted by reason in `release.json` under `headlines.counts.rejected`.
  * With no eligible item, the panel says so and gives the reason and the previous analysis age. When the news family itself fails verification (stale, not live, cutoff outside the freeze, malformed), the panel says it is unavailable.
* **Previous accepted analysis (as of the last accepted cutoff).** The accepted digest, desk summary, Market News, central-bank research, and analyst text. These stay bound to acceptance and change only with the final edition.

The feed reads only the frozen packet. It does not change `accepted_public_news.json`, the overnight dataset, or the news approval path.

Local, never production:

```bash
PYTHONPATH=. python3 -m scripts.market_watch_launch.research_pages select
PYTHONPATH=. python3 -m scripts.market_watch_launch.research_pages build \
  --launch-id <launch_id> --review-id <review_id> --packet-sha256 <sha> --site-dir /tmp/research-site
```

`--channel production` is refused outside a GitHub Actions run on `main` of this repository.

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

## Deterministic finalization recovery

Use this when Stage 07 has already succeeded on the runner but the finalization commit never reached `main`. The October 2 failure was launch `mwl-20261002T094056Z-1d0ebea5`: acceptance committed `overnight-20261002`, then `git pull --rebase` stopped on unstaged canonical temperature history and scores. `data/overnight/latest.json` stayed on `overnight-20261001`, so Pages kept that previous dataset.

The recovery replays stages 06 and 07 from the accepted inbox output. It does not call traders, PMs, learning models, or ACP. It does not rewrite `scheduled_output.json`. A second run is a no-op once `main` has stages 06 and 07 succeeded, `publication.may_publish` true, and `data/overnight/latest.json` pointing at the same run. The commit stages the launch record, overnight assembly, PM state, trading state, canonical temperature histories, `data/temperature_scores.json`, and the derived `data/temperature_history/score_paths.json`. Any other dirty path fails the commit. Pages stays a separate explicit dispatch.

After this change is on `main`:

```bash
gh workflow run recover-accepted-finalization.yml --ref main \
  -f launch_id=mwl-20261002T094056Z-1d0ebea5 \
  -f run_id=overnight-20261002
```

Equivalent local command, from a clean checkout of that `main`, with permission to push:

```bash
git fetch origin main
git checkout main
git reset --hard origin/main
LAUNCH_ID=mwl-20261002T094056Z-1d0ebea5 \
RUN_ID=overnight-20261002 \
  bash scripts/market_watch_launch/recover_accepted_finalization.sh
git fetch origin main
git show origin/main:data/overnight/latest.json
```

`latest.json` must name `overnight-20261002` and its `assembled_dataset` must exist on that commit. Then dispatch Pages once, still without rerunning models:

```bash
gh workflow run deploy-pages.yml --ref main
```

A successful `gh workflow run` exits 0 on HTTP 204 and does not include a run id. That is not a deploy and does not terminal the launch. The acceptance job records stage 08 only after it observes the Actions run. `reconcile-published-pages.yml` then starts from that run's `workflow_run` completion. It marks stage 08 succeeded only when `publication_evidence_proven()` matches the successful `workflow_dispatch` on `main` to the finalized launch. Until then the launch stays `running` and the one-live-launch guard stays closed. A missing run, a failed or cancelled deploy, or a mismatched launch, review, packet, or ref does not release the guard. Pull-request Pages builds are not production.

## Reconcile a successful Pages deploy

Use this when `deploy-pages.yml` has already succeeded as a `workflow_dispatch` on `main`, but the bound launch is still `status=running` with stage `08_pages` pending. The October 2 case is launch `mwl-20261002T094056Z-1d0ebea5` and Actions run `37036473785` (`Deploy Market Watch Dashboard`, head `ffec0735582a357277e2ffa6cfe571b29608c6dc`). The launch record at that deployed commit is finalized through stage 07, and stage 08 is still pending there.

The recovery records that deploy into canonical launch state through `publication_evidence_proven()` and `reconcile_published_pages()`. It does not rerun traders, PMs, learning, ingestion, market-state acquisition, score calibration, books, or P&L. It does not dispatch Pages again. It refuses a mismatched launch id, review id, or packet SHA, a deploy head SHA that is not that commit on the current branch, a non-success conclusion, a non-main ref, a non-`workflow_dispatch` event, any other workflow, or stages 00–07 that are not all succeeded. A second run is a no-op once `main` has stage 08 succeeded with reason `pages_publication_reconciled` for the same run. The commit stages only that launch's `launch.json`, `artifacts/08_pages.json`, and `data/market_watch_launches/index.json`. Any other dirty path fails the run.

This does not resume a later launch that already blocked on the guard. The October 5 attempt stays blocked in history. After the October 2 launch is terminal, a new human launch can authenticate.

After this change is on `main`:

```bash
gh workflow run reconcile-published-pages.yml --ref main \
  -f launch_id=mwl-20261002T094056Z-1d0ebea5 \
  -f run_id=37036473785
```

Equivalent local command, from a clean checkout of `main`, with permission to push:

```bash
git fetch origin main
git checkout main
git reset --hard origin/main
LAUNCH_ID=mwl-20261002T094056Z-1d0ebea5 \
RUN_ID=37036473785 \
  bash scripts/market_watch_launch/reconcile_published_pages.sh

## October 22 launch left the guard closed

Launch `mwl-20261022T110951Z-9a049b03` finalized on `65c5600877d234d483820a3957bed1c11bf2de96` at 2026-10-22 12:33:06 UTC. Acceptance run `39776675010` step "Explicitly dispatch Pages for the finalized launch" succeeded from 12:33:09 to 12:33:12. That step's `gh workflow run` returned 0 and GitHub created Actions run [`39779281989`](https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/39779281989) at 12:33:10 (`workflow_dispatch`, `main`, actor `github-actions[bot]`, head `65c5600877d234d483820a3957bed1c11bf2de96`, build and deploy jobs success). The same step then pushed `561135973f32fab2fdb105bf0590bd12163c52e9`, which stored stage 08 as `pending` / `pages_dispatch_requested` and did not store the run id. The workflow token did have `actions: write`; the gap was that exit 0 was recorded without a run receipt, and nothing reconciled the deploy after it finished. The deployed tree is the finalize commit, where stage 08 was already `pending`, so that run is valid publication evidence. Later October 22 Pages runs were pull-request builds and are not this deploy.

October 23 launch `mwl-20261023T130116Z-14063697` (Actions run `39957699286`) blocked at `00_authenticate` with `concurrency_one_live_launch`. That attempt stays blocked. It is not resumed. After the October 22 record on `main` is terminal, the next session needs a new human launch.

The idempotent recovery, once this run is the verified deploy, is the same reconcile command. A second run is a no-op. It does not reset status by hand and it does not republish.

```bash
gh workflow run reconcile-published-pages.yml --ref main \
  -f launch_id=mwl-20261022T110951Z-9a049b03 \
  -f run_id=39779281989
```
```
