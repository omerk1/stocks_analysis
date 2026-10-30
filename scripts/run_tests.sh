#!/usr/bin/env bash
# Run pytest with the project venv (the one environment the tests are written
# for; see README "Setup") and a stub `polygon` package first on PYTHONPATH, so
# no test can construct a real Polygon client and reach the network. There is
# one venv, in the main checkout: a worktree runs against the main checkout's
# installed packages, so a branch that changes requirements.txt needs them
# installed there before its tests mean anything. The stub lives in a temp dir
# removed on exit; nothing is written to the repo.
#
# Usage: bash scripts/run_tests.sh [pytest args...]
# Tests run in this script's own checkout (worktree or main), so test paths are
# relative to it and its `src` is the code imported, whatever the caller's cwd.
set -euo pipefail

checkout=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
if ! worktrees=$(git -C "$checkout" worktree list --porcelain) || [[ -z "$worktrees" ]]; then
    echo "can't find the main checkout from $checkout (git worktree list failed); the venv lives there" >&2
    exit 1
fi
first=$(printf '%s\n' "$worktrees" | sed '/^$/q')   # the main entry: lines up to the first blank
main=$(printf '%s\n' "$first" | sed -n 's/^worktree //p')
venv_home=$main
if printf '%s\n' "$first" | grep -qx bare; then
    venv_home=$checkout   # a bare main repo has no working tree to hold the venv
fi
python="$venv_home/venv/bin/python"
if [[ ! -x "$python" ]]; then
    echo "no project venv at $venv_home/venv -- create it as in README 'Setup'" >&2
    exit 1
fi
top=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -n "$top" && "$(cd "$top" && pwd -P)" != "$checkout" ]]; then
    caller=$(cd "$top" && pwd -P)
    echo "note: testing $checkout (this script's checkout), not $caller" >&2
fi
cd "$checkout"

stub=$(mktemp -d)
trap 'rm -rf "$stub"' EXIT
mkdir "$stub/polygon"
cat > "$stub/polygon/__init__.py" <<'PY'
class RESTClient:
    def __init__(self, *a, **k):
        raise RuntimeError("stub polygon client: no network in tests")


class BaseClient:
    pass
PY

PYTHONPATH="$stub${PYTHONPATH:+:$PYTHONPATH}" "$python" -m pytest "$@"
