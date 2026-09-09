"""Tests for the block-bootstrap inference layer (DESIGN.md §6.2/§6.3),
built for M4's tier assignment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.stats.controls import c2_delta
from src.signals.moving_averages.stats.inference import (
    block_bootstrap_delta,
    block_bootstrap_series,
    block_bootstrap_spread,
)


def _panel(n_dates=100, n_tickers=20, effect=0.01, seed=0):
    """Synthetic panel: `is_event` planted with a known constant effect
    over a matched control, one sector, one match bucket -- enough strata
    for a meaningful bootstrap, small enough to run fast.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(n_tickers):
            is_event = i < n_tickers // 2
            noise = rng.normal(0, 0.02)
            value = (effect if is_event else 0.0) + noise
            rows.append({
                "date": date, "ticker": f"T{i}", "is_event": is_event,
                "value": value, "sector": "X", "bucket": 0,
            })
    return pd.DataFrame(rows)


def test_block_bootstrap_delta_ci_covers_the_planted_effect():
    panel = _panel(effect=0.01, n_dates=150)

    result = block_bootstrap_delta(
        panel, "is_event", "value", match_cols=["sector", "bucket"],
        date_col="date", block_length=10, n_boot=200, seed=0,
    )

    assert result["point_estimate"] == pytest.approx(0.01, abs=0.005)
    assert result["ci_low"] < 0.01 < result["ci_high"]
    assert result["n_dates"] == 150
    assert result["n_boot"] == 200


def test_block_bootstrap_delta_ci_excludes_zero_for_a_real_effect():
    # A clean, large planted effect with enough dates should give a CI
    # that doesn't straddle zero -- the basic "can this even detect a
    # real signal" check.
    panel = _panel(effect=0.05, n_dates=200)

    result = block_bootstrap_delta(
        panel, "is_event", "value", match_cols=["sector", "bucket"],
        date_col="date", block_length=10, n_boot=200, seed=0,
    )

    assert result["ci_low"] > 0


def test_block_bootstrap_delta_ci_straddles_zero_for_no_effect():
    panel = _panel(effect=0.0, n_dates=200)

    result = block_bootstrap_delta(
        panel, "is_event", "value", match_cols=["sector", "bucket"],
        date_col="date", block_length=10, n_boot=200, seed=0,
    )

    assert result["ci_low"] < 0 < result["ci_high"]


def test_block_bootstrap_spread_point_estimate_matches_manual_decile_diff():
    n_dates, n_tickers = 100, 10
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=n_dates)
    rows = []
    for date in dates:
        for i in range(n_tickers):
            rows.append({
                "date": date, "ticker": f"T{i}", "decile": i,
                "value": i * 0.01 + rng.normal(0, 0.001),
                "sector": "X", "bucket": 0,
            })
    panel = pd.DataFrame(rows)

    result = block_bootstrap_spread(
        panel, decile_col="decile", decile_low=0, decile_high=9,
        value_col="value", match_cols=["sector", "bucket"], date_col="date",
        block_length=10, n_boot=100, seed=0,
    )

    manual_low = c2_delta(panel.assign(is_event=panel["decile"] == 0), "is_event", "value",
                           match_cols=["sector", "bucket"], date_col="date")
    manual_high = c2_delta(panel.assign(is_event=panel["decile"] == 9), "is_event", "value",
                            match_cols=["sector", "bucket"], date_col="date")

    assert result["point_estimate"] == pytest.approx(manual_high - manual_low, abs=1e-6)
    assert result["ci_low"] > 0  # a real, large planted decile gradient


def test_block_bootstrap_delta_handles_empty_input():
    panel = pd.DataFrame(columns=["date", "is_event", "value", "sector"])

    result = block_bootstrap_delta(panel, "is_event", "value", match_cols=["sector"])

    assert result["n_dates"] == 0
    assert pd.isna(result["point_estimate"])


def test_block_bootstrap_series_ci_covers_a_planted_constant():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=150)
    values = pd.Series(rng.normal(0.02, 0.05, size=len(dates)), index=dates)

    result = block_bootstrap_series(values, block_length=10, n_boot=200, seed=0)

    assert result["point_estimate"] == pytest.approx(0.02, abs=0.01)
    assert result["ci_low"] < 0.02 < result["ci_high"]
    assert result["n_dates"] == 150
    assert result["n_boot"] == 200


def test_block_bootstrap_series_ci_excludes_zero_for_a_real_effect():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=200)
    values = pd.Series(rng.normal(0.10, 0.05, size=len(dates)), index=dates)

    result = block_bootstrap_series(values, block_length=10, n_boot=200, seed=0)

    assert result["ci_low"] > 0


def test_block_bootstrap_series_ci_straddles_zero_for_no_effect():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=200)
    values = pd.Series(rng.normal(0.0, 0.05, size=len(dates)), index=dates)

    result = block_bootstrap_series(values, block_length=10, n_boot=200, seed=0)

    assert result["ci_low"] < 0 < result["ci_high"]


def test_block_bootstrap_series_drops_nan_dates_before_resampling():
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2020-01-01", periods=150)
    values = pd.Series(rng.normal(0.02, 0.05, size=len(dates)), index=dates)
    values.iloc[::5] = np.nan  # thin out every 5th date, as a real
    # per-date IC series would have on a date with too few names

    result = block_bootstrap_series(values, block_length=10, n_boot=100, seed=0)

    assert result["n_dates"] == values.notna().sum()


def test_block_bootstrap_series_handles_empty_input():
    result = block_bootstrap_series(pd.Series(dtype=float), block_length=10)

    assert result["n_dates"] == 0
    assert pd.isna(result["point_estimate"])


def test_block_bootstrap_series_rejects_a_degenerate_block_length():
    dates = pd.bdate_range("2020-01-01", periods=40)
    values = pd.Series(np.zeros(len(dates)), index=dates)

    with pytest.raises(ValueError, match="too large relative to n_dates"):
        block_bootstrap_series(values, block_length=42)


def test_block_bootstrap_delta_rejects_a_degenerate_block_length():
    """block_length must be small relative to n_dates -- with too few
    blocks, a single circular block wraps around and covers nearly the
    whole date range almost every draw regardless of the random start,
    collapsing boot_std and understating uncertainty rather than
    measuring it. Must raise, not silently return an overconfident CI.
    """
    panel = _panel(n_dates=40)  # well above DESIGN §6.9's MIN_DATES=30

    with pytest.raises(ValueError, match="too large relative to n_dates"):
        block_bootstrap_delta(
            panel, "is_event", "value", match_cols=["sector", "bucket"],
            date_col="date", block_length=42,  # the module's own default
        )
