#!/usr/bin/env bash
# Merge a validated scheduled-output PR and publish Pages only after merge.
# Draft arrival is not a trust signal: callers must already have passed the
# data-only, trusted-main, review-identity, and canonical-book gates.
set -euo pipefail

PR_URL="${PR_URL:-${1:-}}"
if [ -z "$PR_URL" ]; then
  echo "::error::PR_URL is required"
  exit 1
fi

draft="$(gh pr view "$PR_URL" --json isDraft --jq .isDraft)"
if [ "$draft" = "true" ]; then
  gh pr ready "$PR_URL"
fi

state="$(gh pr view "$PR_URL" --json state --jq .state)"
if [ "$state" != "MERGED" ]; then
  gh pr merge "$PR_URL" --squash --delete-branch
  state="$(gh pr view "$PR_URL" --json state --jq .state)"
fi
if [ "$state" != "MERGED" ]; then
  echo "::error::Scheduled output PR did not merge (state=$state). Pages deployment was not dispatched."
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Manual Market Watch launches finalize and dispatch Pages only after the accepted
# provider output has been merged and the launch's stage 06/07 state is durably
# committed on main. Do not publish from this pre-continuation merge step.
if [ "${MW_PAGES_REQUIRE_LAUNCH:-}" = "1" ]; then
  if [ -n "${MW_PAGES_OUTPUT:-}" ] && [ -f "${MW_PAGES_OUTPUT}" ]; then
    launch_id="$(python3 -c 'import json,os; print(json.load(open(os.environ["MW_PAGES_OUTPUT"])).get("launch_id") or "")')"
    if [ -z "$launch_id" ]; then
      echo "Skipping manual launch continuation: accepted output is not bound to a launch_id."
      exit 0
    fi
    echo "Accepted manual output merged for $launch_id; durable launch continuation owns finalization and Pages."
    exit 0
  fi
  echo "Skipping manual launch continuation: MW_PAGES_OUTPUT is unavailable."
  exit 0
fi

# Legacy/manual callers outside the one-command launch path keep the explicit
# dispatch behavior below.
if [ "${MW_PAGES_REQUIRE_LAUNCH:-}" = "1" ] && [ -z "${MW_PAGES_LAUNCH_ID:-}" ] && [ -n "${MW_PAGES_OUTPUT:-}" ] && [ -f "${MW_PAGES_OUTPUT}" ]; then
  eval "$(MW_PAGES_OUTPUT="$MW_PAGES_OUTPUT" python3 -c 'import json,os,shlex; d=json.load(open(os.environ["MW_PAGES_OUTPUT"])); print("export MW_PAGES_LAUNCH_ID=%s" % shlex.quote(str(d.get("launch_id") or ""))); print("export MW_PAGES_REVIEW_ID=%s" % shlex.quote(str(d.get("review_id") or "")))')"
fi
if [ "${MW_PAGES_REQUIRE_LAUNCH:-}" = "1" ] && [ -z "${MW_PAGES_LAUNCH_ID:-}" ]; then
  echo "Skipping GitHub Pages dispatch: accepted output is not bound to an authorized launch_id."
  exit 0
fi

if [ -n "${MW_PAGES_LAUNCH_ID:-}" ]; then
  export MW_PAGES_REPO_ROOT="${MW_PAGES_REPO_ROOT:-$REPO_ROOT}"
  export MW_PAGES_STATE_ROOT="${MW_PAGES_STATE_ROOT:-$REPO_ROOT}"
  if ! PYTHONPATH="$REPO_ROOT" python3 - <<'PY'
import os
import sys

from scripts.market_watch_launch.pages import authorize_pages_dispatch

launch_id = os.environ["MW_PAGES_LAUNCH_ID"]
review_id = os.environ.get("MW_PAGES_REVIEW_ID", "")
state_root = os.environ.get("MW_PAGES_STATE_ROOT", "")
root = os.environ.get("MW_PAGES_REPO_ROOT", "")

ok = authorize_pages_dispatch(
    launch_id=launch_id,
    review_id=review_id,
    state_root=state_root,
    root=root,
)
sys.exit(0 if ok else 2)
PY
  then
    echo "Skipping GitHub Pages dispatch: launch ${MW_PAGES_LAUNCH_ID} is not authorized for production publish."
    exit 0
  fi
fi

echo "Accepted scheduled output is on main; dispatching GitHub Pages."
gh workflow run deploy-pages.yml --ref main
