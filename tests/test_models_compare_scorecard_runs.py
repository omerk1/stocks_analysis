"""scripts/compare_scorecard_runs.py: two runs are paired only from one known environment."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from src.models import trial_log

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compare_scorecard_runs.py"
spec = importlib.util.spec_from_file_location("compare_scorecard_runs", SCRIPT)
compare_scorecard_runs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_scorecard_runs)

HERE = trial_log.environment()


def _cells(*envs) -> dict:
    """One logged row per cell, each fitted in the given environment (None: not logged)."""
    universe = lambda env: json.dumps({"indices": ["sp500"], **({"environment": env} if env else {})})  # noqa: E731
    return {(21, 2.0, float(i)): pd.Series({"universe": universe(e)}) for i, e in enumerate(envs)}


def test_runs_from_one_environment_compare():
    compare_scorecard_runs.check_environments(_cells(HERE, HERE), _cells(HERE), "S3", "S1v")


@pytest.mark.parametrize("new, old", [
    ((HERE,), ({**HERE, "scikit-learn": "1.5.1"},)),     # the reference fitted under other versions (S1r)
    ((HERE, {**HERE, "numpy": "1.26.4"}), (HERE,)),      # one run's cells split across environments
    ((HERE,), (None,)),                                  # a reference from before environments were logged
    ((None,), (None,)),                                  # both unknown: not known to be one environment
])
def test_runs_not_from_one_known_environment_are_refused(new, old):
    with pytest.raises(SystemExit, match="--across-environments"):
        compare_scorecard_runs.check_environments(_cells(*new), _cells(*old), "S3", "S1v")
