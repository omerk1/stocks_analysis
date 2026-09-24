"""Tests for the whole-grid FDR pass's own machinery
(`stats/multiple_testing.py`, DESIGN.md §6.6).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.stats.inference import InsufficientBlocksError
from src.signals.moving_averages.stats.multiple_testing import (
    benjamini_hochberg,
    p_value_from_ci,
    white_reality_check,
)


def test_p_value_from_ci_is_small_for_a_ci_far_from_zero():
    p = p_value_from_ci(point_estimate=-0.01, ci_low=-0.012, ci_high=-0.008)
    assert p < 0.01


def test_p_value_from_ci_is_close_to_one_minus_ci_level_when_ci_touches_zero():
    # A CI whose edge is exactly at zero is the textbook boundary case:
    # the two-sided p-value should sit right around 1 - ci_level.
    p = p_value_from_ci(point_estimate=0.005, ci_low=0.0, ci_high=0.01)
    assert math.isclose(p, 0.10, abs_tol=0.02)


def test_p_value_from_ci_is_nan_for_a_nan_ci():
    assert math.isnan(p_value_from_ci(float("nan"), float("nan"), float("nan")))
    assert math.isnan(p_value_from_ci(0.01, float("nan"), 0.02))


def test_benjamini_hochberg_rejects_all_when_every_p_is_tiny():
    p_values = [0.001, 0.002, 0.0005, 0.003]
    reject = benjamini_hochberg(p_values, q=0.10)
    assert reject.all()


def test_benjamini_hochberg_rejects_none_when_every_p_is_large():
    p_values = [0.5, 0.8, 0.95, 0.6]
    reject = benjamini_hochberg(p_values, q=0.10)
    assert not reject.any()


def test_benjamini_hochberg_step_up_includes_every_rank_up_to_the_largest_passing_one():
    # p=0.03 (rank 2, threshold .04) and p=0.02 (rank 1, threshold .02)
    # both individually clear their own rank's threshold; p=0.07 (rank 3,
    # threshold .06) does not, and nothing past it does either -- so BH's
    # step-up rule stops at rank 2, rejecting exactly those two.
    p_values = [0.03, 0.07, 0.02, 0.20, 0.50]  # sorted: .02,.03,.07,.20,.50
    reject = benjamini_hochberg(p_values, q=0.10)
    assert reject.tolist() == [True, False, True, False, False]

    # Now push the middle p-value down so rank 3 itself clears .06 -- BH's
    # step-up property should then also sweep in every smaller rank.
    p_values_lower = [0.03, 0.05, 0.02, 0.20, 0.50]  # sorted: .02,.03,.05,.20,.50
    reject_lower = benjamini_hochberg(p_values_lower, q=0.10)
    assert reject_lower.tolist() == [True, True, True, False, False]


def test_benjamini_hochberg_ignores_nan_p_values_without_shrinking_others_rank():
    with_nan = benjamini_hochberg([0.01, float("nan"), 0.02, 0.5], q=0.10)
    without_nan = benjamini_hochberg([0.01, 0.02, 0.5], q=0.10)
    assert with_nan[1] == False  # noqa: E712 -- NaN cell never rejected
    assert with_nan[0] == without_nan[0]
    assert with_nan[2] == without_nan[1]
    assert with_nan[3] == without_nan[2]


def test_benjamini_hochberg_returns_all_false_for_empty_or_all_nan_input():
    assert not benjamini_hochberg([], q=0.10).any()
    assert not benjamini_hochberg([float("nan"), float("nan")], q=0.10).any()


def _synthetic_diffs(n_dates: int = 200, n_candidates: int = 7, best_mean: float = 0.0, seed: int = 0) -> pd.DataFrame:
    """`n_candidates` columns of pure noise (mean 0, std 1), except
    candidate 0's mean is shifted by `best_mean` -- lets a test control
    exactly how much real outperformance (if any) the best candidate has.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    data = {f"candidate_{i}": rng.normal(0.0, 1.0, n_dates) for i in range(n_candidates)}
    data["candidate_0"] = data["candidate_0"] + best_mean
    return pd.DataFrame({"date": dates, **data})


def test_white_reality_check_identifies_the_best_candidate():
    diffs = _synthetic_diffs(best_mean=5.0, seed=1)  # huge, unmistakable edge
    result = white_reality_check(diffs, block_length=10, n_boot=200, seed=0)
    assert result["best_candidate"] == "candidate_0"
    assert result["candidate_means"]["candidate_0"] > max(
        v for k, v in result["candidate_means"].items() if k != "candidate_0"
    )


def test_white_reality_check_rejects_when_the_best_candidate_has_a_real_large_edge():
    diffs = _synthetic_diffs(best_mean=5.0, seed=1)
    result = white_reality_check(diffs, block_length=10, n_boot=500, seed=0)
    assert result["p_value"] < 0.05


def test_white_reality_check_does_not_reject_under_the_pure_null():
    # No real outperformance anywhere -- the best-of-7 by chance alone
    # should not usually look like a huge, unmistakable effect.
    diffs = _synthetic_diffs(best_mean=0.0, seed=2)
    result = white_reality_check(diffs, block_length=10, n_boot=500, seed=0)
    assert result["p_value"] > 0.05


def test_white_reality_check_raises_on_too_few_dates_for_block_length():
    diffs = _synthetic_diffs(n_dates=10, seed=3)
    with pytest.raises(InsufficientBlocksError):
        white_reality_check(diffs, block_length=42, n_boot=50, seed=0)


def test_white_reality_check_drops_rows_with_any_missing_candidate():
    diffs = _synthetic_diffs(n_dates=100, seed=4)
    diffs.loc[0, "candidate_1"] = float("nan")
    result = white_reality_check(diffs, block_length=10, n_boot=50, seed=0)
    assert result["n_dates"] == 99
