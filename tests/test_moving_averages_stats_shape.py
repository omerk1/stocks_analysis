"""Tests for `stats/shape.py` (DESIGN.md §6.11.1; CLAUDE.md invariant #10):
hit rate (vs. matched control), win/loss magnitude ratio, skew. Descriptive
only -- no CI, no kill criterion -- so these are plain value-recovery tests
on synthetic data with a known-planted shape, not bootstrap/CI tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.stats.shape import distribution_shape, hit_rate_deltas


def test_hit_rate_deltas_recovers_a_planted_hit_rate_gap():
    # Event group: always positive (hit rate 1.0). Control: always
    # negative (hit rate 0.0). C1 delta should land near +1.0.
    n_dates, n_tickers = 60, 10
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(n_tickers):
            is_event = i < 5
            value = 0.01 if is_event else -0.01
            rows.append({"date": date, "ticker": f"T{i}", "is_event": is_event, "value": value, "sector": "X"})
    panel = pd.DataFrame(rows)

    result = hit_rate_deltas(panel, "is_event", "value", match_cols=["sector"])

    assert result["hit_rate"] == pytest.approx(1.0)
    assert result["hit_rate_delta_c1"] == pytest.approx(1.0, abs=1e-9)
    assert result["hit_rate_delta_c2"] == pytest.approx(1.0, abs=1e-9)


def test_hit_rate_deltas_is_zero_when_event_and_control_have_identical_sign_mix():
    # Both groups (10 tickers each) have the same 50/50 positive/negative
    # mix on every date -- hit rate delta should be exactly zero, not
    # just near it.
    n_dates = 40
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(20):
            is_event = i < 10
            value = 0.01 if (i % 10) < 5 else -0.01
            rows.append({"date": date, "ticker": f"T{i}", "is_event": is_event, "value": value, "sector": "X"})
    panel = pd.DataFrame(rows)

    result = hit_rate_deltas(panel, "is_event", "value", match_cols=["sector"])

    assert result["hit_rate"] == pytest.approx(0.5)
    assert result["hit_rate_delta_c1"] == pytest.approx(0.0, abs=1e-9)
    assert result["hit_rate_delta_c2"] == pytest.approx(0.0, abs=1e-9)


def test_hit_rate_deltas_omits_c2_when_match_cols_not_given():
    panel = pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=5).repeat(4),
        "ticker": ["A", "B", "C", "D"] * 5,
        "is_event": [True, True, False, False] * 5,
        "value": [0.01, 0.01, -0.01, -0.01] * 5,
    })
    result = hit_rate_deltas(panel, "is_event", "value")
    assert "hit_rate_delta_c1" in result
    assert "hit_rate_delta_c2" not in result


def test_distribution_shape_recovers_a_planted_win_loss_ratio():
    # Wins average +0.04, losses average -0.02 -> ratio exactly 2.0.
    values = pd.Series([0.04] * 50 + [-0.02] * 50)
    result = distribution_shape(values)

    assert result["win_loss_ratio"] == pytest.approx(2.0)
    assert result["n_wins"] == 50
    assert result["n_losses"] == 50
    assert result["mean_win"] == pytest.approx(0.04)
    assert result["mean_loss"] == pytest.approx(-0.02)


def test_distribution_shape_positive_skew_for_a_right_skewed_distribution():
    # Many small losses, a few large wins -- classic "loses small often,
    # wins large rarely" shape, positive skew.
    rng = np.random.default_rng(0)
    small_losses = -np.abs(rng.normal(0.005, 0.002, 900))
    large_wins = np.abs(rng.normal(0.05, 0.01, 100))
    values = pd.Series(np.concatenate([small_losses, large_wins]))

    result = distribution_shape(values)

    assert result["skew"] > 0
    assert result["win_loss_ratio"] > 1  # wins are much bigger than losses on average


def test_distribution_shape_handles_no_losses():
    values = pd.Series([0.01, 0.02, 0.03])
    result = distribution_shape(values)
    assert result["n_losses"] == 0
    assert np.isnan(result["win_loss_ratio"])


def test_distribution_shape_drops_nan_before_computing():
    values = pd.Series([0.01, np.nan, -0.01, 0.02, np.nan])
    result = distribution_shape(values)
    assert result["n_wins"] + result["n_losses"] == 3  # NaNs excluded, zeros also excluded (none here)
