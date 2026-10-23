#!/usr/bin/env bash
# Record a successful deploy-pages.yml workflow_dispatch into canonical launch
# state. Does not rerun traders, PMs, learning, ingestion, market evidence,
# score calibration, books, or P&L, and does not dispatch Pages again.
# A second run is a no-op once this deploy is already reconciled on the branch.
# The commit contains only that launch's launch.json, artifacts/08_pages.json,
# and data/market_watch_launches/index.json. Any other dirty path fails.
set -euo pipefail

if [ "${PAGES_WORKFLOW_RUN:-}" != "1" ]; then
  LAUNCH_ID="${LAUNCH_ID:?LAUNCH_ID is required}"
fi
RUN_ID="${RUN_ID:?RUN_ID is required}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
PUSH="${PUSH:-1}"
REPO="${GH_REPO:-McCabeAI/market-watch-public-dashboard}"

if ! [[ "$RUN_ID" =~ ^[0-9]{1,20}$ ]]; then
  echo "::error::RUN_ID must be a numeric Actions run id" >&2
  exit 1
fi

SOURCE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${SOURCE_REPO}${PYTHONPATH:+:${PYTHONPATH}}"

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"

run_tmp=""
decision_file="$(mktemp)"
cleanup() {
  rm -f "$decision_file"
  if [ -n "$run_tmp" ]; then
    rm -f "$run_tmp"
  fi
}
trap cleanup EXIT

git fetch "$REMOTE" "$BRANCH"

if [ "$(git rev-parse HEAD)" != "$(git rev-parse "$REMOTE/$BRANCH")" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "::error::HEAD is not $REMOTE/$BRANCH and the worktree is dirty." >&2
    git status --porcelain >&2
    exit 1
  fi
  git merge --ff-only "$REMOTE/$BRANCH"
fi

if [ "${PAGES_WORKFLOW_RUN:-}" != "1" ]; then
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery preflight \
    --launch-id "$LAUNCH_ID" \
    --repo-root "$git_root" \
    --remote "$REMOTE" \
    --branch "$BRANCH"
fi

if [ -n "${PAGES_RUN_JSON:-}" ]; then
  if [ ! -f "$PAGES_RUN_JSON" ]; then
    echo "::error::PAGES_RUN_JSON does not exist" >&2
    exit 1
  fi
  run_json="$PAGES_RUN_JSON"
else
  run_tmp="$(mktemp)"
  gh api "repos/${REPO}/actions/runs/${RUN_ID}" > "$run_tmp"
  run_json="$run_tmp"
fi

COMMIT_MESSAGE=""
if [ "${PAGES_WORKFLOW_RUN:-}" = "1" ]; then
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery workflow-run \
    --run-id "$RUN_ID" \
    --run-json "$run_json" \
    --repository "$REPO" \
    --repo-root "$git_root" \
    --decision-out "$decision_file"
  cat "$decision_file"
  LAUNCH_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("launch_id") or "")' "$decision_file")"
  CHANGED="$(python3 -c 'import json,sys; print("1" if json.load(open(sys.argv[1])).get("changed") else "0")' "$decision_file")"
  ACTION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("action") or "")' "$decision_file")"
  if [ "$CHANGED" != "1" ]; then
    if [ -n "$(git status --porcelain)" ]; then
      echo "::error::Pages workflow_run left a dirty worktree without a reconciliation change." >&2
      git status --porcelain >&2
      exit 1
    fi
    echo "Pages workflow run ${RUN_ID} required no launch-state commit (${ACTION:-skipped})."
    exit 0
  fi
  if [ -z "$LAUNCH_ID" ]; then
    echo "::error::Pages workflow_run changed state without a launch_id." >&2
    exit 1
  fi
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery preflight \
    --launch-id "$LAUNCH_ID" \
    --repo-root "$git_root" \
    --remote "$REMOTE" \
    --branch "$BRANCH"
  if [ "$ACTION" = "noted_incomplete" ]; then
    COMMIT_MESSAGE="chore: record market watch launch ${LAUNCH_ID} pages deploy failure"
  else
    COMMIT_MESSAGE="chore: reconcile market watch launch ${LAUNCH_ID} pages publication"
  fi
else
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery apply \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --run-json "$run_json" \
    --repository "$REPO" \
    --repo-root "$git_root" \
    --decision-out "$decision_file"
  cat "$decision_file"
  COMMIT_MESSAGE="chore: reconcile market watch launch ${LAUNCH_ID} pages publication"
fi

if ! PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery stage \
  --launch-id "$LAUNCH_ID" \
  --repo-root "$git_root"
then
  echo "::error::Pages reconciliation refused to stage because unexpected paths are dirty." >&2
  exit 1
fi

assert_launch_state() {
  local ref="$1"
  if [ "${ACTION:-}" = "noted_incomplete" ]; then
    REF="$ref" LAUNCH_ID="$LAUNCH_ID" PYTHONPATH="$SOURCE_REPO" python3 - <<'PY'
import json, os, subprocess, sys
ref = os.environ["REF"]
launch_id = os.environ["LAUNCH_ID"]
raw = subprocess.check_output(["git", "show", f"{ref}:data/market_watch_launches/{launch_id}/launch.json"], text=True)
launch = json.loads(raw)
stage = launch["stages"]["08_pages"]
details = stage.get("details") or {}
if launch.get("status") != "running" or stage.get("status") != "pending":
    sys.exit("incomplete Pages deploy was recorded as terminal")
if stage.get("reason") != "pages_deploy_failed" or details.get("production_published") is not False:
    sys.exit("incomplete Pages deploy lost its failure receipt")
PY
    return
  fi
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery assert-reconciled \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --run-json "$run_json" \
    --repository "$REPO" \
    --repo-root "$git_root" \
    --ref "$ref" >/dev/null
}

if git diff --cached --quiet; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "::error::Unexpected dirty paths remain and there is no reconciliation commit." >&2
    git status --porcelain >&2
    exit 1
  fi
  assert_launch_state HEAD
  echo "Launch $LAUNCH_ID pages publication already reconciled; no additional commit."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "$COMMIT_MESSAGE"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Unexpected dirty paths remain after the pages reconciliation commit." >&2
  git status --porcelain >&2
  exit 1
fi

assert_launch_state HEAD

git pull --rebase "$REMOTE" "$BRANCH"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Rebase left a dirty worktree after the pages reconciliation commit." >&2
  git status --porcelain >&2
  exit 1
fi

if [ "$PUSH" = "1" ]; then
  git push "$REMOTE" "HEAD:$BRANCH"
  git fetch "$REMOTE" "$BRANCH"
  assert_launch_state "$REMOTE/$BRANCH"
fi
