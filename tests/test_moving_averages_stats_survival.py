"""Tests for `stats/survival.py` (M6.4's new Kaplan-Meier/GBM-null
machinery). Hand-computable examples for the estimator itself; smoke/sanity
checks for the stochastic GBM simulation (exact values aren't
hand-checkable, but shape/bounds/monotonicity are).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.stats import survival as surv


def test_kaplan_meier_matches_hand_computed_example():
    durations = pd.Series([1, 2, 2, 3])
    events = pd.Series([1, 1, 0, 1])

    km = surv.kaplan_meier(durations, events)

    assert list(km["time"]) == [1.0, 2.0, 3.0]
    assert km["survival"].iloc[0] == pytest.approx(0.75)
    assert km["survival"].iloc[1] == pytest.approx(0.5)
    assert km["survival"].iloc[2] == pytest.approx(0.0)
    assert list(km["at_risk"]) == [4, 3, 1]


def test_kaplan_meier_censored_only_duration_gets_no_row():
    # A duration whose only occurrence is censored (event=0) contributes to
    # at_risk at earlier times but must not produce its own row (standard
    # KM convention: only event times get a step).
    durations = pd.Series([1, 5])
    events = pd.Series([1, 0])

    km = surv.kaplan_meier(durations, events)

    assert list(km["time"]) == [1.0]
    assert km["at_risk"].iloc[0] == 2


def test_kaplan_meier_empty_input_returns_empty_frame():
    km = surv.kaplan_meier(pd.Series([], dtype=float), pd.Series([], dtype=int))
    assert km.empty


def test_survival_at_step_function_lookup():
    durations = pd.Series([1, 2, 2, 3])
    events = pd.Series([1, 1, 0, 1])
    km = surv.kaplan_meier(durations, events)

    assert surv.survival_at(km, 0) == pytest.approx(1.0)
    assert surv.survival_at(km, 1) == pytest.approx(0.75)
    assert surv.survival_at(km, 1.5) == pytest.approx(0.75)
    assert surv.survival_at(km, 2) == pytest.approx(0.5)
    assert surv.survival_at(km, 100) == pytest.approx(0.0)


def test_survival_at_empty_table_is_nan():
    empty = pd.DataFrame(columns=["time", "survival", "at_risk", "events"])
    assert np.isnan(surv.survival_at(empty, 5))


def test_simulate_gbm_paths_shape_and_moments():
    paths = surv.simulate_gbm_paths(n_paths=2000, n_days=100, mu=0.0005, sigma=0.02, seed=0)

    assert paths.shape == (2000, 100)
    log_returns = np.diff(np.log(paths), axis=1)
    assert log_returns.mean() == pytest.approx(0.0005, abs=0.001)
    assert log_returns.std() == pytest.approx(0.02, abs=0.002)


def test_slope_sign_runs_single_path_hand_example():
    # 2 leading NaNs (warmup), then T,T,T,F,F,T -- run0=[T,T,T] left-censored
    # (dropped), run1=[F,F] duration=2 event=1 (ends in an observed flip),
    # run2=[T] duration=1 event=0 (still active when the path ends).
    path = np.array([np.nan, np.nan, 1.0, 1.0, 1.0, 0.0, 0.0, 1.0])

    pairs = surv._slope_sign_runs_single_path(path)

    assert pairs == [(2.0, 1), (1.0, 0)]


def test_slope_sign_runs_single_path_all_nan_returns_empty():
    path = np.array([np.nan, np.nan, np.nan])
    assert surv._slope_sign_runs_single_path(path) == []


def test_slope_sign_runs_single_path_single_run_is_left_censored_only():
    # Only one run ever observed (no flip at all) -- it's both the first
    # and last run, so it's dropped as left-censored, not reported as
    # right-censored either (its start is unknown, same as any other
    # first run).
    path = np.array([1.0, 1.0, 1.0, 1.0])
    assert surv._slope_sign_runs_single_path(path) == []


def test_gbm_null_survival_smoke_and_sanity():
    result = surv.gbm_null_survival(
        n_paths=500, n_days=300, mu=0.0003, sigma=0.02, sma_period=20, slope_k=21, seed=0, n_groups=25,
    )

    assert result["n_runs"] > 0
    km = result["km"]
    # Survival must be non-increasing (a valid KM curve).
    assert (km["survival"].diff().dropna() <= 1e-9).all()
    for lo, hi in result["envelope"].values():
        if not np.isnan(lo):
            assert 0.0 <= lo <= hi <= 1.0
