#!/usr/bin/env bash
# Run pytest with the project venv (the one environment the tests are written
# for; see README "Setup") and a stub `polygon` package first on PYTHONPATH, so
# no test can construct a real Polygon client and reach the network. The venv
# lives in the main checkout, so this works the same from any worktree. The stub
# lives in a temp dir removed on exit; nothing is written to the repo.
#
# Usage: bash scripts/run_tests.sh [pytest args...]
set -euo pipefail

repo_root=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
python="$repo_root/venv/bin/python"
if [[ ! -x "$python" ]]; then
    echo "no project venv at $repo_root/venv -- create it as in README 'Setup'" >&2
    exit 1
fi

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
