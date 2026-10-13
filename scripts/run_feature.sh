#!/usr/bin/env bash
# Run a headless Claude Code session on a feature spec in a fresh worktree
# (.claude/worktrees/<slug>, branch feat/<slug> off origin/main), log its
# stream-json output to ~/claude-runs/, then summarise what it did.
# This script never pushes, merges or deletes anything. If the spec says to,
# the session itself pushes and opens the PR.
#
# Usage: bash scripts/run_feature.sh <slug> <spec-file> [budget_usd=5]
set -euo pipefail

usage() { echo "usage: $0 <slug> <spec-file> [budget_usd=5]" >&2; exit 2; }
[ $# -ge 2 ] && [ $# -le 3 ] || usage
slug=$1
spec=$2
budget=${3:-5}

[[ $slug =~ ^[a-z0-9-]+$ ]] || { echo "bad slug '$slug': must match ^[a-z0-9-]+\$" >&2; exit 2; }
[[ $budget =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "bad budget '$budget': must be a number" >&2; exit 2; }
[ -f "$spec" ] || { echo "spec file not found: $spec" >&2; exit 1; }
spec=$(CDPATH= cd -- "$(dirname -- "$spec")" >/dev/null && pwd -P)/$(basename -- "$spec")  # absolute, survives the cd below
for tool in claude jq gh; do
  command -v "$tool" >/dev/null || { echo "$tool not found" >&2; exit 1; }
done

main_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
branch=feat/$slug
wt=$main_root/.claude/worktrees/$slug

if git -C "$main_root" show-ref --verify --quiet "refs/heads/$branch"; then
  echo "branch $branch already exists" >&2; exit 1
fi
if [ -e "$wt" ] || git -C "$main_root" worktree list --porcelain | grep -qxF "worktree $wt"; then
  echo "worktree $wt already exists" >&2; exit 1
fi

git -C "$main_root" fetch origin
if git -C "$main_root" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  echo "remote branch origin/$branch already exists" >&2; exit 1
fi
git -C "$main_root" worktree add --no-track "$wt" -b "$branch" origin/main
cd "$wt"

mkdir -p "$HOME/claude-runs"
log=$HOME/claude-runs/$slug-$(date +%Y%m%d-%H%M%S).jsonl
errlog=${log%.jsonl}.err
echo "worktree: $wt"
echo "log:      $log  (follow with: tail -f $log)"
echo "stderr:   $errlog"

cmd=(claude -p --model sonnet --permission-mode auto --permission-prompts none
     --max-budget-usd "$budget" --max-turns 150 --output-format stream-json --verbose)
if command -v caffeinate >/dev/null; then cmd=(caffeinate -i "${cmd[@]}"); fi

# The prompt goes in on stdin, so a spec starting with '-' (e.g. '---' front
# matter) can't be read as an option. The header pins the real slug and branch,
# whatever the spec's own placeholders say.
prompt() {
  printf 'This run: slug `%s`, branch `%s`, worktree `%s`. Wherever the spec below says `<slug>`, use `%s`.\n\n' \
    "$slug" "$branch" "$wt" "$slug"
  cat "$spec"
}

set +e
"${cmd[@]}" < <(prompt) >"$log" 2> >(tee "$errlog" >&2)
rc=$?
set -e

# The last result message; fromjson? skips any line that isn't JSON.
result=$(jq -cR 'fromjson? | select(.type == "result")' "$log" | tail -n 1)

echo
echo "== exit code: $rc"
if [ -n "$result" ]; then
  echo "== result subtype: $(jq -r '.subtype // "n/a"' <<<"$result")"
  echo "== total_cost_usd: $(jq -r '.total_cost_usd // "n/a"' <<<"$result")"
  echo "== permission denials: $(jq '.permission_denials // [] | length' <<<"$result")"
  jq -r '.permission_denials // [] | .[]
         | "  \(.tool_name): \(.tool_input.command // (.tool_input | tostring))"' <<<"$result"
else
  echo "== no result message in the log (run aborted before finishing?)"
fi
echo "== commits (origin/main..HEAD):"
git log --oneline origin/main..HEAD
echo "== git status --short:"
git status --short
echo "== PRs with head $branch:"
gh pr list --head "$branch" --state all || echo "  (gh pr list failed)"
exit "$rc"
