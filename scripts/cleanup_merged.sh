#!/usr/bin/env bash
# Remove local branches whose GitHub PR is MERGED: their worktree (only if under
# .claude/worktrees/), the local branch, and the remote branch on origin.
# Dry run by default.
#
# Usage: bash scripts/cleanup_merged.sh [--dry-run|--apply]
#
# A branch is cleaned only if all of these hold:
#   - gh pr list --head <branch> --state merged finds a PR, and no PR on it is OPEN
#   - neither it nor its PR head is main, and it is not checked out in the main
#     checkout or the one running this script
#   - if checked out in a worktree, that worktree is under .claude/worktrees/ and clean
#   - the local tip is the merged PR's head commit or an ancestor of it, so commits
#     made after the merge are never lost (squash merges need branch -D)
#   - the remote branch, if it still exists, points at the PR's head commit
# Worktrees on a detached HEAD are never touched.
set -euo pipefail

mode=dry-run
case "${1:-}" in
  "" | --dry-run) mode=dry-run ;;
  --apply) mode=apply ;;
  *) echo "usage: $0 [--dry-run|--apply]" >&2; exit 2 ;;
esac

main_root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
wt_prefix="$main_root/.claude/worktrees/"
current=$(git branch --show-current)

act() {
  if [ "$mode" = apply ]; then echo "  + $*"; "$@" </dev/null
  else echo "  (dry-run) $*"; fi
}

worktree_of() {
  git -C "$main_root" worktree list --porcelain | awk -v ref="refs/heads/$1" '
    /^worktree /{p=substr($0,10)} $0=="branch " ref {print p}'
}

echo "mode: $mode"
while read -r branch upstream <&3; do
  # The PR head is the upstream's name when it tracks some origin/<x> other than
  # main (a new branch cut from origin/main tracks it until first pushed).
  head=$branch
  case "$upstream" in origin/main) ;; origin/*) head=${upstream#origin/} ;; esac

  wt=$(worktree_of "$branch")
  if [ "$branch" = main ] || [ "$head" = main ] || [ "$branch" = "$current" ] \
    || [ "$wt" = "$main_root" ]; then
    echo "SKIP $branch: main or checked out here"; continue
  fi
  if [ -n "$wt" ] && [ "${wt#"$wt_prefix"}" = "$wt" ]; then
    echo "SKIP $branch: checked out outside .claude/worktrees/ ($wt)"; continue
  fi
  if [ "$(gh pr list --head "$head" --state open --json number --jq length </dev/null)" != 0 ]; then
    echo "SKIP $branch: has an open PR"; continue
  fi
  pr=$(gh pr list --head "$head" --state merged --json number,headRefOid \
    --jq '.[0] // empty | "\(.number) \(.headRefOid)"' </dev/null)
  if [ -z "$pr" ]; then echo "SKIP $branch: no merged PR"; continue; fi
  num=${pr%% *}; oid=${pr#* }

  if ! git cat-file -e "$oid^{commit}" 2>/dev/null; then
    echo "SKIP $branch: PR #$num head $oid not present locally"; continue
  fi
  if ! git merge-base --is-ancestor "$branch" "$oid"; then
    echo "SKIP $branch: has commits not in merged PR #$num"; continue
  fi
  if [ -n "$wt" ] && [ -n "$(git -C "$wt" status --porcelain)" ]; then
    echo "SKIP $branch: worktree $wt has uncommitted changes"; continue
  fi
  remote_oid=$(git ls-remote --heads origin "refs/heads/$head" </dev/null | cut -f1)
  if [ -n "$remote_oid" ] && [ "$remote_oid" != "$oid" ]; then
    echo "SKIP $branch: origin/$head moved past PR #$num"; continue
  fi

  echo "CLEAN $branch (PR #$num merged)"
  if [ -n "$wt" ]; then act git -C "$main_root" worktree remove "$wt"; fi
  act git -C "$main_root" branch -D "$branch"
  if [ -n "$remote_oid" ]; then act git -C "$main_root" push origin --delete "$head"
  else echo "  origin/$head already gone"; fi
done 3< <(git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads)
