#!/usr/bin/env bash
# Run pytest with a stub `polygon` package on PYTHONPATH, so test files that
# import polygon_client (tests/test_models_*.py,
# tests/test_market_common_price_basis.py) collect in an environment whose
# installed polygon package lacks RESTClient. The stub lives in a temp dir
# removed on exit; nothing is written to the repo.
#
# Usage: bash scripts/run_tests.sh [pytest args...]
set -euo pipefail

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

PYTHONPATH="$stub${PYTHONPATH:+:$PYTHONPATH}" python3 -m pytest "$@"
