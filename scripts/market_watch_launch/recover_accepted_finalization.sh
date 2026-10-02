#!/usr/bin/env bash
# Replay Stage 06–07 for an already-accepted launch whose finalization commit
# never reached the remote branch. The inbox scheduled_output.json is immutable.
# No trader, PM, learning-model, or provider call. Pages is not dispatched.
set -euo pipefail

LAUNCH_ID="${LAUNCH_ID:?LAUNCH_ID is required}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
PUSH="${PUSH:-1}"
RESET_TO_REMOTE="${RESET_TO_REMOTE:-1}"
REFRESH_SCORE_PATHS="${REFRESH_SCORE_PATHS:-1}"

SOURCE_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${SOURCE_REPO}${PYTHONPATH:+:${PYTHONPATH}}"
export MW_DEFER_PAGES=1
unset MW_ENABLE_PAGES_DISPATCH || true

git_root="$(git rev-parse --show-toplevel)"
cd "$git_root"

preflight() {
  local -a args=(
    --launch-id "$LAUNCH_ID"
    --run-id "$RUN_ID"
    --repo-root "$git_root"
  )
  if [ -n "${PROVIDER_PAYLOAD_PATH:-}" ]; then
    args+=(--provider-payload "$PROVIDER_PAYLOAD_PATH")
  fi
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery preflight "${args[@]}"
}

inbox="data/overnight/inbox/${RUN_ID}/scheduled_output.json"
if [ "$RESET_TO_REMOTE" = "1" ]; then
  git fetch "$REMOTE" "$BRANCH"
  git reset --hard "$REMOTE/$BRANCH"
fi
if [ -z "${PROVIDER_PAYLOAD_PATH:-}" ]; then
  export PROVIDER_PAYLOAD_PATH="$git_root/$inbox"
fi
payload_sha="$(preflight)"

if PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery check-finalized \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --repo-root "$git_root" \
  --remote "$REMOTE" \
  --branch "$BRANCH"
then
  echo "Launch $LAUNCH_ID already finalized on $REMOTE/$BRANCH; skipping continuation."
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery assert-published \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --repo-root "$git_root" \
    --remote "$REMOTE" \
    --branch "$BRANCH" \
    --expect-sha256 "$payload_sha" >/dev/null
  exit 0
fi

export LAUNCH_ID RUN_ID
if [ -n "${CONTINUATION_CMD:-}" ]; then
  # Test hook. Production leaves this unset and runs the in-repo continuation.
  $CONTINUATION_CMD
else
  LAUNCH_ID="$LAUNCH_ID" \
  PROVIDER_PAYLOAD_PATH="$PROVIDER_PAYLOAD_PATH" \
  MW_DEFER_PAGES=1 \
  PYTHONPATH="$SOURCE_REPO" \
    python3 -m scripts.market_watch_launch.continuation
fi

after_sha="$(PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery preflight \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --repo-root "$git_root" \
  --provider-payload "$PROVIDER_PAYLOAD_PATH")"
if [ "$after_sha" != "$payload_sha" ]; then
  echo "::error::scheduled_output.json changed during continuation" >&2
  exit 1
fi

LAUNCH_ID="$LAUNCH_ID" \
RUN_ID="$RUN_ID" \
REMOTE="$REMOTE" \
BRANCH="$BRANCH" \
PUSH="$PUSH" \
REFRESH_SCORE_PATHS="$REFRESH_SCORE_PATHS" \
  bash "$SOURCE_REPO/scripts/market_watch_launch/commit_finalization.sh"

final_sha="$(PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery preflight \
  --launch-id "$LAUNCH_ID" \
  --run-id "$RUN_ID" \
  --repo-root "$git_root" \
  --provider-payload "$PROVIDER_PAYLOAD_PATH")"
if [ "$final_sha" != "$payload_sha" ]; then
  echo "::error::scheduled_output.json changed during the finalization commit" >&2
  exit 1
fi

if [ "$PUSH" = "1" ]; then
  git fetch "$REMOTE" "$BRANCH"
  PYTHONPATH="$SOURCE_REPO" python3 -m scripts.market_watch_launch.recovery assert-published \
    --launch-id "$LAUNCH_ID" \
    --run-id "$RUN_ID" \
    --repo-root "$git_root" \
    --remote "$REMOTE" \
    --branch "$BRANCH" \
    --expect-sha256 "$payload_sha" >/dev/null
fi
