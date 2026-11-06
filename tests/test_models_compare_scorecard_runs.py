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


def _check(new: dict, old: dict) -> None:
    compare_scorecard_runs.check_environments(new, old, sorted(set(new) & set(old)), "S3", "S1v")


def test_runs_from_one_environment_compare():
    _check(_cells(HERE, HERE), _cells(HERE, HERE))
    # a cell only one run has isn't compared, so its environment doesn't count
    _check(_cells(HERE, None), _cells(HERE))


@pytest.mark.parametrize("new, old, says", [
    ((HERE,), ({**HERE, "scikit-learn": "1.5.1"},), "scikit-learn"),   # the reference under other versions (S1r)
    ((HERE, {**HERE, "numpy": "1.26.4"}), (HERE, HERE), "numpy"),       # one run's cells split across two
    ((HERE,), (None,), "not recorded"),                                 # a reference from before the field
    ((None,), (None,), "not recorded"),                                 # both unknown: not known to be one
])
def test_runs_not_from_one_known_environment_are_refused(new, old, says):
    with pytest.raises(SystemExit, match=f"{says}.*--across-environments"):
        _check(_cells(*new), _cells(*old))


@pytest.mark.parametrize("across", [False, True])
def test_runs_without_a_shared_cell_are_refused(monkeypatch, across):
    """Refused before anything is read, with or without --across-environments."""
    groups = json.dumps({"rank": "ev_atr"})
    log = pd.DataFrame({"experiment_id": ["S3", "S1v"], "status": "ok", "feature_groups": groups,
                        "cells": [json.dumps([{"horizon": h, "upper": 2.0, "lower": 1.0}]) for h in (21, 63)],
                        "universe": json.dumps({"environment": HERE})})
    monkeypatch.setattr(trial_log, "read_trials", lambda: log)
    with pytest.raises(SystemExit, match="share no cell"):
        compare_scorecard_runs.compare("S3", "S1v", Path("unread"), Path("unread"), Path("unread"), across)
