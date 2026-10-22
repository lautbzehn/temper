#!/usr/bin/env bash
# After Claude Code edits a Python file in this repo: format it, let Ruff fix what
# it safely can, then lint it and type-check the project. Anything left goes to
# stderr with exit code 2, which Claude Code hands back to Claude to fix.
set -uo pipefail

file=$(jq -r '.tool_input.file_path // empty')
root=${CLAUDE_PROJECT_DIR:-$PWD}

case "$file" in
  "$root"/*.py) ;;
  *) exit 0 ;;
esac
cd "$root" || exit 0

uv run --quiet ruff format --quiet "$file"
lint=$(uv run --quiet ruff check --fix --quiet --output-format concise "$file" 2>&1)
lint_status=$?
types=$(uv run --quiet mypy 2>&1)
types_status=$?

if (( lint_status != 0 || types_status != 0 )); then
  (( lint_status != 0 )) && echo "$lint" >&2
  (( types_status != 0 )) && echo "$types" >&2
  exit 2
fi
