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
if ! main=$(git -C "$checkout" worktree list --porcelain | sed -n '1s/^worktree //p') || [[ -z "$main" ]]; then
    echo "can't find the main checkout from $checkout (git worktree list failed); the venv lives there" >&2
    exit 1
fi
python="$main/venv/bin/python"
[[ -x "$python" ]] || python="$checkout/venv/bin/python"   # a bare main repo holds no venv
if [[ ! -x "$python" ]]; then
    echo "no project venv at $main/venv -- create it as in README 'Setup'" >&2
    exit 1
fi
caller=$(cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" && pwd -P)
if [[ "$caller" != "$checkout" && -n "$(git rev-parse --show-toplevel 2>/dev/null)" ]]; then
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
