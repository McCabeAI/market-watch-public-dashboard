#!/usr/bin/env bash
# Compare-and-swap trusted ChatGPT PM state onto main.
# Ticket text is not an input. If main moved, this is a conflict, not a rebase.
set -euo pipefail

BASE_SHA="${BASE_SHA:?BASE_SHA is required}"
APPLY_STATUS="${APPLY_STATUS:?APPLY_STATUS is required}"
GENERATED_DIR="${GENERATED_DIR:?GENERATED_DIR is required}"
COMMIT_JSON="${COMMIT_JSON:?COMMIT_JSON is required}"
REMOTE="${REMOTE:-origin}"

write_commit() {
  COMMIT_STATUS="$1" COMMIT_SHA="${2:-}" HEAD_SHA="${3:-}" python3 -c 'import json,os; json.dump({"status": os.environ["COMMIT_STATUS"], "commit_sha": os.environ.get("COMMIT_SHA", ""), "head_sha": os.environ.get("HEAD_SHA", "")}, open(os.environ["COMMIT_JSON"], "w"), sort_keys=True); open(os.environ["COMMIT_JSON"], "a").write("\n")'
}

if ! [[ "$BASE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  write_commit rejected
  echo "base sha is not 40 hex" >&2
  exit 1
fi

if [ "$APPLY_STATUS" != "applied" ]; then
  head_sha="$(git rev-parse HEAD 2>/dev/null || true)"
  write_commit skipped "" "$head_sha"
  exit 0
fi

top="$(git rev-parse --show-toplevel)"
generated="$(cd "$GENERATED_DIR" && pwd)"
case "$generated" in
  "$top"|"$top"/*)
    write_commit rejected
    echo "generated dir must live outside the worktree" >&2
    exit 1
    ;;
esac

if [ ! -d "$generated" ]; then
  write_commit rejected
  echo "generated state is missing" >&2
  exit 1
fi

git fetch "$REMOTE" main
current="$(git rev-parse "$REMOTE/main")"
if [ "$current" != "$BASE_SHA" ]; then
  write_commit conflict
  echo "main moved from $BASE_SHA to $current; refusing to overlay" >&2
  exit 2
fi

git reset --hard "$REMOTE/main"
git clean -fd
git checkout -B main "$REMOTE/main"

copy_tree() {
  local name="$1"
  if [ -d "$generated/$name" ]; then
    rm -rf "$name"
    mkdir -p "$(dirname "$name")"
    cp -a "$generated/$name" "$name"
  fi
}

mkdir -p data/pm
copy_tree data/pm/books
copy_tree data/pm/review_packets
copy_tree data/pm/public
copy_tree data/pm/data_requests
copy_tree data/pm/decisions
copy_tree data/trading

if [ -e data/pm/books ]; then git add data/pm/books; fi
if [ -e data/pm/review_packets ]; then git add data/pm/review_packets; fi
if [ -e data/pm/public ]; then git add data/pm/public; fi
if [ -e data/pm/data_requests ]; then git add data/pm/data_requests; fi
if [ -e data/pm/decisions ]; then git add data/pm/decisions; fi
if [ -e data/trading ]; then git add data/trading; fi

while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    data/pm/books|data/pm/books/*) ;;
    data/pm/review_packets|data/pm/review_packets/*) ;;
    data/pm/public|data/pm/public/*) ;;
    data/pm/data_requests|data/pm/data_requests/*) ;;
    data/pm/decisions|data/pm/decisions/*) ;;
    data/trading|data/trading/*) ;;
    *)
      write_commit rejected
      echo "refusing unexpected path $path" >&2
      exit 1
      ;;
  esac
done < <(git diff --cached --name-only)

if git diff --cached --quiet; then
  write_commit noop "" "$(git rev-parse HEAD)"
  exit 0
fi

git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -m "chore: apply trusted ChatGPT PM issue decision"

git fetch "$REMOTE" main
current="$(git rev-parse "$REMOTE/main")"
if [ "$current" != "$BASE_SHA" ]; then
  write_commit conflict
  echo "main moved during commit; refusing to push" >&2
  exit 2
fi

if ! git push "$REMOTE" "HEAD:main"; then
  git fetch "$REMOTE" main
  if [ "$(git rev-parse HEAD)" != "$(git rev-parse "$REMOTE/main")" ]; then
    write_commit conflict
    echo "push rejected; canonical main unchanged" >&2
    exit 2
  fi
fi

sha="$(git rev-parse HEAD)"
if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  write_commit rejected
  exit 1
fi
write_commit applied "$sha" "$sha"
exit 0
