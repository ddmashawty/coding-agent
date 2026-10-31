#!/usr/bin/env bash
# Copy tests/fixtures/buggy_repo into a throwaway git repo and print its path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/tests/fixtures/buggy_repo"
if [[ ! -d "$SRC" ]]; then
  echo "missing fixture: $SRC" >&2
  exit 1
fi

DEST="${1:-$(mktemp -d "${TMPDIR:-/tmp}/agent0-buggy.XXXXXX")}"
mkdir -p "$DEST"
# Copy sources only. Fixture __pycache__ must not be committed.
find "$SRC" -maxdepth 1 -type f ! -name '*.pyc' -exec cp -a {} "$DEST"/ \;
printf '%s\n' '__pycache__/' '*.pyc' > "$DEST/.gitignore"

git -C "$DEST" init -q
git -C "$DEST" config user.email "test@example.com"
git -C "$DEST" config user.name "test"
git -C "$DEST" config commit.gpgsign false
git -C "$DEST" add -A
git -C "$DEST" commit -q -m "buggy add()"
echo "$DEST"
