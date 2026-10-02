#!/usr/bin/env bash
# Commit the Stage 07 finalization write set and fail closed on anything else.
# Retries are idempotent once origin already has stages 06 and 07 for this launch
# and latest.json points at the same overnight run. This script does not call
# traders, PMs, learning models, or a provider, and it does not dispatch Pages.
set -euo pipefail

LAUNCH_ID="${LAUNCH_ID:?LAUNCH_ID is required}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
PUSH="${PUSH:-1}"
REFRESH_SCORE_PATHS="${REFRESH_SCORE_PATHS:-1}"

SOURCE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${SOURCE_REPO}${PYTHONPATH:+:${PYTHONPATH}}"

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"

git fetch "$REMOTE" "$BRANCH"

if PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery check-finalized \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --repo-root "$git_root" \
  --remote "$REMOTE" \
  --branch "$BRANCH"
then
  if [ -n "$(git status --porcelain)" ]; then
    echo "::error::Launch $LAUNCH_ID is already finalized on $REMOTE/$BRANCH but the worktree is dirty." >&2
    git status --porcelain >&2
    exit 1
  fi
  echo "Launch $LAUNCH_ID already finalized on $REMOTE/$BRANCH; no additional commit."
  exit 0
fi

refresh_args=()
if [ "$REFRESH_SCORE_PATHS" = "1" ]; then
  refresh_args+=(--refresh-score-paths)
fi

PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.persist_boundary \
  --boundary finalization \
  --repo-root "$git_root" \
  "${refresh_args[@]}"

if git diff --cached --quiet; then
  echo "::error::Finalization produced no staged changes and $LAUNCH_ID is not finalized on $REMOTE/$BRANCH." >&2
  git status --porcelain >&2
  exit 1
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "chore: finalize market watch launch $LAUNCH_ID"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Unexpected dirty paths remain after the finalization commit." >&2
  git status --porcelain >&2
  exit 1
fi

git pull --rebase "$REMOTE" "$BRANCH"

if [ -n "$(git status --porcelain)" ]; then
  echo "::error::Rebase left a dirty worktree after the finalization commit." >&2
  git status --porcelain >&2
  exit 1
fi

if [ "$PUSH" = "1" ]; then
  git push "$REMOTE" "HEAD:$BRANCH"
fi
