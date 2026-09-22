#!/usr/bin/env bash
# Overlay trusted deterministic acceptance state onto the scheduled-output branch.
# Retries are safe: untracked files left by apply on trusted main are removed
# before checkout, and an identical tree does not create another commit.
set -euo pipefail

HEAD_REF="${HEAD_REF:?HEAD_REF is required}"
RUN_ID="${RUN_ID:?RUN_ID is required}"
GENERATED_DIR="${GENERATED_DIR:?GENERATED_DIR is required}"
REMOTE="${REMOTE:-origin}"
PUSH="${PUSH:-1}"

if [ ! -d "$GENERATED_DIR" ]; then
  echo "::error::Generated acceptance state is missing: $GENERATED_DIR"
  exit 1
fi

# Apply runs in this worktree before the branch switch. Copy first when the
# generated tree lives inside the repo so git clean cannot delete it.
top="$(git rev-parse --show-toplevel)"
generated="$(cd "$GENERATED_DIR" && pwd)"
case "$generated" in
  "$top"|"$top"/*)
    staged="$(mktemp -d)"
    cp -a "$generated"/. "$staged"/
    generated="$staged"
    ;;
esac

git reset --hard
git clean -fd
git fetch "$REMOTE" "$HEAD_REF"
git checkout -B "$HEAD_REF" "$REMOTE/$HEAD_REF"

rm -rf data/overnight/books
cp -a "$generated/books" data/overnight/books
mkdir -p "data/overnight/runs/$RUN_ID"
cp -a "$generated/runs/$RUN_ID/." "data/overnight/runs/$RUN_ID/"
if [ -d "$generated/pm" ]; then
  mkdir -p data/pm
  for name in books review_packets public data_requests; do
    if [ -e "$generated/pm/$name" ]; then
      rm -rf "data/pm/$name"
      cp -a "$generated/pm/$name" "data/pm/$name"
    fi
  done
fi
if [ -d "$generated/trading" ]; then
  rm -rf data/trading
  mkdir -p data/trading
  cp -a "$generated/trading/." data/trading/
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data/overnight/books "data/overnight/runs/$RUN_ID"
if [ -d "$generated/pm" ]; then
  for name in books review_packets public data_requests; do
    if [ -e "data/pm/$name" ]; then
      git add "data/pm/$name"
    fi
  done
fi
if [ -d "$generated/trading" ]; then
  git add data/trading
fi
if git diff --cached --quiet; then
  echo "Deterministic acceptance state already matches $HEAD_REF; no additional commit."
  exit 0
fi
git commit -m "chore: apply overnight decisions $RUN_ID"
if [ "$PUSH" = "1" ]; then
  git push "$REMOTE" "HEAD:$HEAD_REF"
fi
