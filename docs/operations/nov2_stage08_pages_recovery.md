# Nov 2, 2026 — Stage 08 Pages recovery (documented only; not executed)

This note records the safe recovery path for launch `mwl-20261102T102838Z-f747870a` after the deploy-pages reconcile job failed on a CLI bug. **Nothing in this document was run against production launch state from the coding lane.**

## Facts

| Item | Value |
|------|--------|
| Launch | `mwl-20261102T102838Z-f747870a` |
| Launch status | `running`; stage `08_pages` **pending** |
| Dispatch receipt `run_id` | `41438960943` |
| Deploy / workflow head SHA | `3aaf22a786bf21fb17f0917f71e2377ba8412e87` |
| Actions run | https://github.com/McCabeAI/market-watch-public-dashboard/actions/runs/41438960943 |
| Failed reconcile job | `125263841538` (AttributeError: `in-run-evidence` accessed `args.repo_root`) |

The **deploy job on that run succeeded** — GitHub Pages was published for the deploy commit. The **reconcile job crashed** before writing in-run evidence or updating launch state. The workflow run’s API **conclusion is therefore `failure`**, even though production Pages already reflect a successful deploy.

## What not to do

1. **Do not “Re-run failed jobs” on job `125263841538` as the recovery.** GitHub reuses the workflow file from the run’s SHA for that retry. The reconcile step checks out `ref: main` and runs the same `in-run-evidence` command. Until the `pages_recovery` CLI fix is **merged to `main`**, that checkout still hits the `repo_root` AttributeError and the retry fails again.

2. **Do not feed the Actions API run JSON (conclusion `failure`) into `apply` or `workflow-run` as if it were a successful deploy.** `normalize_actions_run` rejects non-success conclusions when reconciliation is required. `workflow_run_decision` would treat an incomplete deploy and leave `production_published` false — Pages are already live; that path does not match reality.

## Recovery after the CLI fix is on `main` (human operator)

A human **may** reconstruct in-run evidence and reconcile launch state locally for review (no push until reviewed).

### 1. Build in-run evidence (fixed CLI)

Run from a checkout that includes the `in-run-evidence` fix, with the **original reconcile job environment**:

```bash
export GITHUB_RUN_ID=41438960943
export GITHUB_SERVER_URL=https://github.com
export GITHUB_REPOSITORY=McCabeAI/market-watch-public-dashboard
export GITHUB_SHA=3aaf22a786bf21fb17f0917f71e2377ba8412e87
export GITHUB_EVENT_NAME=workflow_dispatch
export GITHUB_REF=refs/heads/main
export GITHUB_WORKFLOW_REF=McCabeAI/market-watch-public-dashboard/.github/workflows/deploy-pages.yml@refs/heads/main

python3 -m scripts.market_watch_launch.pages_recovery in-run-evidence \
  --deploy-result success \
  --out /path/to/pages_run.json
```

The written JSON must include `"evidence_source": "in_run_deploy_job"` (from `in_run_actions_run`).

### 2. Reconcile via shell wrapper (review only)

Then run `scripts/market_watch_launch/reconcile_published_pages.sh` with:

- `LAUNCH_ID=mwl-20261102T102838Z-f747870a`
- `RUN_ID=41438960943`
- `PAGES_RUN_JSON` pointing at the file from step 1
- **`PUSH=0`** — still creates a **local** commit for review; a human reviews before any push.

**Do not** run this shell script or push launch state from an automated coding lane.

## Validation in tests

Hermetic tests in `tests/test_mw_pages_in_run_reconcile.py` (class `Nov2Stage08RecoveryPlanTests`) validate:

- Evidence built with the env above and `deploy_result=success`.
- `apply_published_pages` on a **temporary** copy of the launch record (worktree git read-only; temp `state_root`) succeeds with run id `41438960943`, head SHA `3aaf22a…`, `production_published` true, and does **not** modify the worktree launch file under `data/market_watch_launches/`.
- A synthetic API payload with the same ids but `conclusion: failure` does **not** successfully reconcile (apply raises `non-success conclusion`; `workflow_run_decision` fails closed with `ambiguous pending finalized launches` at deploy commit `3aaf22a…` because multiple historical launches still await stage 08 in that tree — production is not marked published).

Identity at deploy commit `3aaf22a786bf21fb17f0917f71e2377ba8412e87` matches the finalized launch packet/review fields; stage `08_pages` remains pending at that commit until reconciliation is applied.
