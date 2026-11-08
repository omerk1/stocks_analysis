"""scripts/compare_scorecard_runs.py: two runs are paired only from one known
environment and one seed set, and the pair's B4 predictions are compared."""

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


def test_runs_on_other_seeds_are_refused():
    """Each side's B4 is refitted on its own seeds: a seed-1 run against a
    seed-0 one would mix seed noise into the pair."""
    rows = lambda *seeds: {(21, 2.0, float(i)): pd.Series({"seeds": json.dumps(s)})  # noqa: E731
                           for i, s in enumerate(seeds)}
    check = lambda new, old: compare_scorecard_runs.check_seeds(  # noqa: E731
        new, old, sorted(set(new) & set(old)), "S2_no_market_v_seed1", "S1v")
    check(rows([1], [1]), rows([1], [1]))
    for new, old in ((rows([1]), rows([0])), (rows([1], [0]), rows([1], [1]))):
        with pytest.raises(SystemExit, match="one seed set"):
            check(new, old)


def test_reference_gap_compares_the_b4_predictions(tmp_path):
    """Equal B4 predictions, in any row order, have no gap; one probability
    off gives its size, a missing row gives inf. The model's own predictions
    are split off and don't count."""
    p = pd.DataFrame({"ticker": ["A", "B"], "date": pd.to_datetime(["2015-01-02"] * 2), "hit": [1, 0],
                      "fold": [2015] * 2, "p_up": [0.4, 0.3], "p_down": [0.3, 0.3], "p_neither": [0.3, 0.4]})
    def write(name, b4, model):
        (tmp_path / name).mkdir()
        pd.concat([b4.assign(model="B4"), model.assign(model="model")]).to_parquet(
            tmp_path / name / "predictions.parquet", index=False)
        return compare_scorecard_runs.predictions(pd.Series({"trial_id": name, "feature_groups": "{}"}), tmp_path)
    off = p.assign(p_up=[0.4, 0.32])
    (ma, a), (mb, b), (_, c), (_, d) = (write("a", p, p), write("b", p.iloc[::-1], off), write("c", off, p),
                                        write("d", p.iloc[:1], p))
    assert len(ma) == len(mb) == 2 and set(mb.p_up) == {0.4, 0.32}
    gap = compare_scorecard_runs.reference_gap
    assert gap(a, b) == 0
    assert gap(a, c) == pytest.approx(0.02)
    assert gap(a, d) == float("inf")
    assert gap(a, a.assign(p_up=[0.4, None])) == float("inf")      # NaN on one side only
