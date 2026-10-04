import json

import pytest

from src.models import trial_log
from src.models.trial_log import COLUMNS, append_row, read_trials, trial

SPEC = {
    "feature_groups": {"baseline": "supported"}, "universe": ["sp500"],
    "liquidity_floors": {"sp500": 20e6}, "cells": [[21, 2.0, 1.0]], "fold_scheme": "expanding",
    "seeds": [0, 1, 2], "hyperparameters": {"max_iter": 200}, "open_holdout": False,
}


def test_a_recorded_trial_is_logged(tmp_path):
    path = tmp_path / "TRIALS.csv"
    with trial("E1", SPEC, trials_path=path, artifacts_root=tmp_path / "art") as t:
        assert t.dir.is_dir()
        t.record(metrics={"brier_diff": [-0.01, -0.02, -0.001]}, n_dates=1800, outcome="beats B4")
    rows = read_trials(path)
    assert list(rows.columns) == COLUMNS and len(rows) == 1
    row = rows.iloc[0]
    assert row["status"] == trial_log.OK and row["experiment_id"] == "E1" and row["n_dates"] == 1800
    assert json.loads(row["cells"]) == [[21, 2.0, 1.0]] and not row["open_holdout"]
    assert row["trial_id"] == t.trial_id and t.trial_id in str(t.dir)


def test_a_failed_trial_is_logged_and_the_error_kept(tmp_path):
    path = tmp_path / "TRIALS.csv"
    with pytest.raises(RuntimeError, match="boom"):
        with trial("E1", SPEC, trials_path=path, artifacts_root=tmp_path) as t:
            raise RuntimeError("boom")
    row = read_trials(path).iloc[0]
    assert row["status"] == trial_log.FAILED and "boom" in row["outcome"]


def test_an_unrecorded_trial_is_abandoned_not_dropped(tmp_path):
    path = tmp_path / "TRIALS.csv"
    with trial("E1", SPEC, trials_path=path, artifacts_root=tmp_path):
        pass
    with trial("E1", SPEC, trials_path=path, artifacts_root=tmp_path) as t:
        t.record({}, 10, "x")
    assert read_trials(path)["status"].tolist() == [trial_log.ABANDONED, trial_log.OK]


def test_a_spec_missing_a_field_is_refused_before_running(tmp_path):
    path = tmp_path / "TRIALS.csv"
    spec = {k: v for k, v in SPEC.items() if k != "open_holdout"}
    with pytest.raises(ValueError, match="open_holdout"):
        with trial("E1", spec, trials_path=path, artifacts_root=tmp_path):
            pass
    assert not path.exists()


def test_appending_to_a_file_with_other_columns_is_refused(tmp_path):
    path = tmp_path / "TRIALS.csv"
    path.write_text("a,b\n")
    with pytest.raises(ValueError, match="columns"):
        append_row({c: None for c in COLUMNS}, path)


def test_the_committed_log_has_the_current_columns():
    assert list(read_trials().columns) == COLUMNS
