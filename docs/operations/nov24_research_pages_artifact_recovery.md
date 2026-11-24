# Nov 24, 2026 — research Pages artifact recovery (documented only; not executed)

This note records the safe recovery for launch `mwl-20261124T100050Z-f1607c19` after research publication uploaded its Pages artifact and `actions/deploy-pages` did not see that exact name. **Nothing in this document was run against production from the coding lane.** Do not recollect data, refreeze, launch traders, deploy, or merge from this note. A human runs the recovery only after the visibility fix is on `main`, and only with separate authorization to publish.

## Facts

| Item | Value |
|------|--------|
| Launch | `mwl-20261124T100050Z-f1607c19` |
| Session date | `2026-11-24` (America/New_York) |
| Launch status | `running`. Stages `00_authenticate` through `04_freeze` are `succeeded`. Stage `05_acp_handoff` is `pending`. |
| Remote freeze commit | `0bcdb7cc9172d309983f14035e979833aeb0cc6a` |
| Packet SHA-256 | `6a780ad835844268a3333fe2729dddab24fec781bcdfd93772ec0c227df7f625` |
| Review id | `review-001` |
| Failed workflow run | https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/45370439017 |
| Run head SHA (the YAML a rerun would use) | `8cc4f533dfcaa31191e9e53f09317bd2197a9773` |
| Attempt 1 artifact | `github-pages-research-45370439017-1`, id `14910118264` |
| Attempt 2 artifact | `github-pages-research-45370439017-2`, id `14916005309` |

Both uploads finalized. `deploy-pages` lists artifacts once through the Actions results service and then requires an exact name. The runner injects `ACTIONS_RUNTIME_TOKEN` and `ACTIONS_RESULTS_URL` into JavaScript actions (`NodeScriptActionHandler`), not into ordinary `run:` shell steps. Attempt 1's list returned 0 artifacts. Attempt 2's list returned 1 artifact and still did not contain `github-pages-research-45370439017-2`. The action stopped before creating a Pages deployment. The research job does not grant `actions: read`; that permission is not what this list uses, and the list call itself succeeded.

The public REST artifact list is a different index. After the fact it shows both ids under their exact names. It is not the lookup `deploy-pages` uses, so a REST hit is not proof the results list can see the new artifact.

There is no `research_pages.json` receipt. The research edition was not published.

## What not to do

1. **Do not re-run failed jobs on run `45370439017`.** GitHub uses the workflow file from head SHA `8cc4f533dfcaa31191e9e53f09317bd2197a9773` for that rerun. That file has no exact-name visibility wait. Attempt 2 already showed that a second upload can be invisible while the previous attempt's artifact is the one the list returns.

2. **Do not `workflow_dispatch` `launch-market-watch.yml` for this recovery.** The guard refuses `provider=acp` and `mode=live` on `workflow_dispatch` so a live launch stays tied to a human issue. That dispatch does not publish research.

3. **Do not reopen issue 370.** The workflow listens for `issues: [opened]` only. `reopened` does not start it.

4. **Do not put `rerun` in the title or body.** `rerun` allocates a new launch and can collect again. The recovery title is exactly `[launch-market-watch] 2026-11-24` and the body is empty.

5. **Do not `workflow_dispatch` `deploy-pages.yml`.** That path publishes the final edition. This launch is still the research edition.

6. **Do not start `launch-continuation.yml`, trader room, or an ACP dispatch.** Those are separate authorizations.

7. **Do not open the recovery issue after 2026-11-24 in America/New_York.** Research select skips with `session_not_today` and does not deploy. The orchestrate job would still hash-check the freeze, and the handoff job can still record stage 05 as awaiting research publication. That is not this recovery.

## Recovery after the visibility fix is on `main` (human operator)

`issues` workflows run the default-branch file. Open the issue only after `main` contains `wait-for-pages-artifact` in `.github/workflows/launch-market-watch.yml`. The sender must be a human `User` with write access. A bot opening the issue is refused.

Read-only preflight, from a checkout that is not deploying:

```bash
gh api "repos/McCabeAI/market-watch-public-dashboard/contents/.github/workflows/launch-market-watch.yml?ref=main" \
  --jq .content | base64 -d | grep -F wait-for-pages-artifact
```

The command must print the wait step. Then, on 2026-11-24 America/New_York, the human opens:

```bash
gh issue create \
  --repo McCabeAI/market-watch-public-dashboard \
  --title "[launch-market-watch] 2026-11-24" \
  --body ""
```

What that run is designed to do:

- Guard accepts the new issue because the title matches, the author is a human, and `rerun` is false.
- Orchestrate calls the launch CLI with `--through 04_freeze` and without `--rerun`. The session already has `mwl-20261124T100050Z-f1607c19` in status `running` with stages `00`–`04` succeeded. Resume hash-checks those stage artifacts and does not call their handlers, so it does not recollect or refreeze. The packet SHA stays `6a780ad835844268a3333fe2729dddab24fec781bcdfd93772ec0c227df7f625`.
- The research job on the repaired workflow builds the research edition, uploads a new Pages artifact, rechecks publication order, and runs the `wait-for-pages-artifact` JavaScript action until that exact artifact name and id are in the unfiltered results list. Only then does it call `deploy-pages` once. A timed-out or ambiguous listing does not deploy.
- If the public read-back matches, the job commits `research_pages.json` only.
- The handoff job may then write the stage 05 delegation request. That request records `live_provider_dispatched: false` and does not call ACP or start traders. `launch-continuation.yml` does not run on that push.

If the preflight grep does not match, stop. The issue would start the old workflow.
