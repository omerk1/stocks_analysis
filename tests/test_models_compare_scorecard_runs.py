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
    compare_scorecard_runs.check_environments(_cells(HERE, HERE), _cells(HERE, HERE), "S3", "S1v")
    # a cell only one run has isn't compared, so its environment doesn't count
    compare_scorecard_runs.check_environments(_cells(HERE, None), _cells(HERE), "S3", "S1v")


@pytest.mark.parametrize("new, old, says", [
    ((HERE,), ({**HERE, "scikit-learn": "1.5.1"},), "scikit-learn"),   # the reference under other versions (S1r)
    ((HERE, {**HERE, "numpy": "1.26.4"}), (HERE, HERE), "numpy"),       # one run's cells split across two
    ((HERE,), (None,), "not recorded"),                                 # a reference from before the field
    ((None,), (None,), "not recorded"),                                 # both unknown: not known to be one
])
def test_runs_not_from_one_known_environment_are_refused(new, old, says):
    with pytest.raises(SystemExit, match=f"{says}.*--across-environments"):
        compare_scorecard_runs.check_environments(_cells(*new), _cells(*old), "S3", "S1v")


def test_runs_without_a_shared_cell_are_refused():
    other = {(63, 2.0, 1.0): _cells(HERE)[(21, 2.0, 0.0)]}
    with pytest.raises(SystemExit, match="share no cell"):
        compare_scorecard_runs.check_environments(_cells(HERE), other, "S3", "S1v")
