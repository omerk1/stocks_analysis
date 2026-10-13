#!/usr/bin/env bash
# Remove local branches whose GitHub PR is MERGED: their worktree (only if under
# .claude/worktrees/), the local branch, and the remote branch on origin.
# Dry run by default.
#
# Usage: bash scripts/cleanup_merged.sh [--dry-run|--apply]
#
# A branch is cleaned only if all of these hold:
#   - no PR with it as head is OPEN, and a MERGED one has the local tip as its head
#     commit or an ancestor of it, so commits made after the merge are never lost
#     (a squash merge leaves the branch unmerged in git's eyes, so the delete is
#     forced; it is a compare-and-delete on the checked tip, run after the
#     worktree is removed, so a commit landing meanwhile keeps the branch)
#   - neither it nor its PR head is main, and it is not checked out in the main
#     checkout or the one running this script
#   - if checked out in a worktree, that worktree is under .claude/worktrees/, still
#     exists, has no uncommitted changes, no gitignored files other than symlinks and
#     Python/OS caches (worktree remove deletes them), and no process has its cwd in it
#   - the remote branch, if it still exists, points at the PR's head commit, checked
#     again right before the remote delete
# Worktrees on a detached HEAD are never touched. Any gh or git failure aborts.
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
worktrees=$(git -C "$main_root" worktree list --porcelain)
refs=$(git for-each-ref --format='%(refname:lstrip=2) %(upstream:short)' refs/heads)
command -v lsof >/dev/null || { echo "lsof not found; can't tell which worktrees are in use" >&2; exit 1; }

act() {
  if [ "$mode" = apply ]; then echo "  + $*"; "$@" </dev/null
  else echo "  (dry-run) $*"; fi
}

worktree_of() {
  printf '%s\n' "$worktrees" | awk -v ref="refs/heads/$1" '
    /^worktree /{p=substr($0,10)} $0=="branch " ref {print p}'
}

# Whether a running process has its cwd in worktree $1 (which must be readable).
# Best effort: lsof sees only processes this user may inspect, and a process
# writing there with its cwd elsewhere isn't seen. It exits non-zero when some
# processes are unreadable, so its status is ignored, but an empty list (this
# shell has a cwd) aborts. A worktree that can't be entered counts as in use.
in_use() {
  local real cwds
  real=$(cd "$1" 2>/dev/null && pwd -P) || { echo "  can't enter $1" >&2; return 0; }
  cwds=$(lsof -a -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)
  if [ -z "$cwds" ]; then echo "lsof listed no processes; can't tell if $1 is in use" >&2; exit 1; fi
  printf '%s\n' "$cwds" | awk -v wt="$real" '$0==wt || index($0, wt "/")==1 {f=1} END {exit !f}'
}

# Whether branch $1 still points at $2 and is checked out only in worktree $3
# (empty: nowhere), on a fresh read.
unchanged() {
  [ "$(git rev-parse -q --verify "refs/heads/$1" || true)" = "$2" ] || return 1
  worktrees=$(git -C "$main_root" worktree list --porcelain)
  [ "$(worktree_of "$1")" = "$3" ]
}

remote_tip() {
  git ls-remote --heads origin "refs/heads/$1" </dev/null | cut -f1
}

# Gitignored files that `worktree remove` would delete, minus symlinks (only the
# link goes) and caches that are safe to lose.
ignored_files() {
  git -C "$1" ls-files --others --ignored --exclude-standard -z |
    while IFS= read -r -d '' f; do
      case "$f" in
        */__pycache__/* | __pycache__/* | .pytest_cache/* | .mypy_cache/* | *.pyc | *.DS_Store) ;;
        *) [ -L "$1/$f" ] || printf '%s\n' "$f" ;;
      esac
    done
}

echo "mode: $mode"
while read -r branch upstream <&3; do
  # The PR head is the upstream's name when it tracks some origin/<x> other than
  # main (a new branch cut from origin/main tracks it until first pushed).
  head=$branch
  case "$upstream" in origin/main) ;; origin/*) head=${upstream#origin/} ;; esac
  ref="refs/heads/$branch"
  if ! tip=$(git rev-parse -q --verify "$ref"); then
    echo "SKIP $branch: deleted since the run started"; continue
  fi

  wt=$(worktree_of "$branch")
  if [ "$branch" = main ] || [ "$head" = main ] || [ "$branch" = "$current" ] \
    || [ "$wt" = "$main_root" ]; then
    echo "SKIP $branch: main or checked out here"; continue
  fi
  if [ -n "$wt" ] && [ "${wt#"$wt_prefix"}" = "$wt" ]; then
    echo "SKIP $branch: checked out outside .claude/worktrees/ ($wt)"; continue
  fi

  # A plain assignment, so set -e aborts if gh fails.
  prs=$(gh pr list --head "$head" --state all --json state,number,headRefOid \
    --jq '.[] | "\(.state) \(.number) \(.headRefOid)"' </dev/null)
  if printf '%s\n' "$prs" | grep -q '^OPEN '; then
    echo "SKIP $branch: has an open PR"; continue
  fi
  num=; oid=
  while read -r state n o; do
    [ "$state" = MERGED ] || continue
    if git cat-file -e "$o^{commit}" 2>/dev/null && git merge-base --is-ancestor "$tip" "$o"; then
      num=$n; oid=$o; break
    fi
  done <<<"$prs"
  if [ -z "$num" ]; then
    if printf '%s\n' "$prs" | grep -q '^MERGED '; then
      echo "SKIP $branch: has commits in no merged PR (or the PR head isn't fetched)"
    else
      echo "SKIP $branch: no merged PR"
    fi
    continue
  fi

  if [ -n "$wt" ]; then
    if [ ! -d "$wt" ]; then
      echo "SKIP $branch: worktree $wt is missing (git worktree prune)"; continue
    fi
    if [ ! -r "$wt" ] || [ ! -x "$wt" ]; then
      echo "SKIP $branch: can't read worktree $wt"; continue
    fi
    if ! dirty=$(git -C "$wt" status --porcelain) || ! ignored=$(ignored_files "$wt"); then
      echo "SKIP $branch: git status failed in worktree $wt"; continue
    fi
    if [ -n "$dirty" ]; then
      echo "SKIP $branch: worktree $wt has uncommitted changes"; continue
    fi
    if [ -n "$ignored" ]; then
      echo "SKIP $branch: worktree $wt has gitignored files, e.g. $(printf '%s\n' "$ignored" | head -1)"
      continue
    fi
    if in_use "$wt"; then
      echo "SKIP $branch: a running process has its cwd in $wt"; continue
    fi
  fi
  remote_oid=$(remote_tip "$head")
  if [ -n "$remote_oid" ] && [ "$remote_oid" != "$oid" ]; then
    echo "SKIP $branch: origin/$head moved past PR #$num"; continue
  fi

  if ! unchanged "$branch" "$tip" "$wt"; then
    echo "SKIP $branch: moved, deleted or checked out somewhere new during the checks"; continue
  fi

  echo "CLEAN $branch (PR #$num merged)"
  if [ -n "$wt" ]; then
    act git -C "$main_root" worktree remove "$wt"
    if [ "$mode" = apply ] && ! unchanged "$branch" "$tip" ""; then
      echo "  KEEP $branch and origin/$head: moved or checked out again during the worktree removal"; continue
    fi
  fi
  # Compare-and-delete: refused if a commit landed since the checks. Then drop
  # its tracking config, as branch -D would.
  if [ "$mode" = apply ]; then
    echo "  + git update-ref -d $ref $tip"
    if ! git -C "$main_root" update-ref -d "$ref" "$tip" </dev/null; then
      echo "  KEEP $branch and origin/$head: update-ref failed (git's error above)"; continue
    fi
    if git -C "$main_root" config --get-regexp "^branch\.$(printf '%s' "$branch" | sed 's/[.[\*^$]/\\&/g')\." >/dev/null; then
      echo "  + git config --remove-section branch.$branch"
      git -C "$main_root" config --remove-section "branch.$branch" ||
        echo "  WARN: branch.$branch config left behind (git's error above)"
    fi
  else
    echo "  (dry-run) git update-ref -d $ref $tip; drop branch.$branch config"
  fi
  if [ -z "$remote_oid" ]; then
    echo "  origin/$head already gone"
  elif [ "$mode" = apply ] && [ "$(remote_tip "$head")" != "$oid" ]; then
    echo "  KEEP origin/$head: it moved past PR #$num since the check"
  else
    act git -C "$main_root" push origin --delete "$head"
  fi
done 3<<<"$refs"
