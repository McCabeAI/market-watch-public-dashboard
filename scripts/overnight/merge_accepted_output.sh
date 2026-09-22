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

echo "Accepted scheduled output is on main; dispatching GitHub Pages."
gh workflow run deploy-pages.yml --ref main
