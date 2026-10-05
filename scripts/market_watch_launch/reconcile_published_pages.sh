#!/usr/bin/env bash
# Record a successful deploy-pages.yml workflow_dispatch into canonical launch
# state. Does not rerun traders, PMs, learning, ingestion, market evidence,
# score calibration, books, or P&L, and does not dispatch Pages again.
# A second run is a no-op once this deploy is already reconciled on the branch.
# The commit contains only that launch's launch.json, artifacts/08_pages.json,
# and data/market_watch_launches/index.json. Any other dirty path fails.
set -euo pipefail

LAUNCH_ID="${LAUNCH_ID:?LAUNCH_ID is required}"
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

PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery preflight \
  --launch-id "$LAUNCH_ID" \
  --repo-root "$git_root" \
  --remote "$REMOTE" \
  --branch "$BRANCH"

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

PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery apply \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --run-json "$run_json" \
  --repository "$REPO" \
  --repo-root "$git_root" \
  --decision-out "$decision_file"
cat "$decision_file"

if ! PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery stage \
  --launch-id "$LAUNCH_ID" \
  --repo-root "$git_root"
then
  echo "::error::Pages reconciliation refused to stage because unexpected paths are dirty." >&2
  exit 1
fi

if git diff --cached --quiet; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "::error::Unexpected dirty paths remain and there is no reconciliation commit." >&2
    git status --porcelain >&2
    exit 1
  fi
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery assert-reconciled \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --run-json "$run_json" \
    --repository "$REPO" \
    --repo-root "$git_root" \
    --ref HEAD >/dev/null
  echo "Launch $LAUNCH_ID pages publication already reconciled; no additional commit."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "chore: reconcile market watch launch ${LAUNCH_ID} pages publication"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Unexpected dirty paths remain after the pages reconciliation commit." >&2
  git status --porcelain >&2
  exit 1
fi

PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery assert-reconciled \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --run-json "$run_json" \
  --repository "$REPO" \
  --repo-root "$git_root" \
  --ref HEAD >/dev/null

git pull --rebase "$REMOTE" "$BRANCH"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Rebase left a dirty worktree after the pages reconciliation commit." >&2
  git status --porcelain >&2
  exit 1
fi

if [ "$PUSH" = "1" ]; then
  git push "$REMOTE" "HEAD:$BRANCH"
  git fetch "$REMOTE" "$BRANCH"
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.pages_recovery assert-reconciled \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --run-json "$run_json" \
    --repository "$REPO" \
    --repo-root "$git_root" \
    --ref "$REMOTE/$BRANCH" >/dev/null
fi
