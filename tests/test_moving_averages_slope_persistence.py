"""Tests for M6.4's slope-persistence module (`modules/slope_persistence.py`,
PREREGISTRATION.md 2026-09-24). Synthetic-panel tests only -- mechanics
(run construction, censoring, NaN preservation), not a real-data result
(that's the real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import slope_persistence as sp


def _synthetic_panel(n_tickers: int = 4, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        drift = 3 * np.sin(np.linspace(0, 8, n_days))
        close = 100 + np.cumsum(steps) + drift
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close})
        for lb in sp.LOOKBACKS:
            frame[f"sma_{lb}"] = frame["close"].rolling(lb).mean()
            frame[f"slope_log_21_sma_{lb}"] = np.log(frame[f"sma_{lb}"]).diff(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_efficiency_ratio_high_for_a_pure_trend():
    close = pd.Series(np.arange(1, 51, dtype=float) + 100)  # straight-line uptrend
    er = sp.efficiency_ratio(close, period=10)
    assert er.iloc[15:].min() > 0.9  # near-perfect trend -> ER near 1


def test_efficiency_ratio_low_for_pure_oscillation():
    close = pd.Series(100 + np.tile([1.0, -1.0], 30))  # zero net progress, lots of churn
    er = sp.efficiency_ratio(close, period=10)
    assert er.iloc[15:].max() < 0.3


def test_prepare_adds_expected_columns_and_preserves_warmup_nan():
    panel = _synthetic_panel()
    working = sp.prepare(panel)

    for lb in sp.LOOKBACKS:
        col = f"slope_positive_{lb}"
        assert col in working.columns
        # Invariant #9: undefined during the slope's own warmup, not False.
        undefined_mask = working[f"slope_log_21_sma_{lb}"].isna()
        assert working.loc[undefined_mask, col].isna().all()

    assert "vol_tercile" in working.columns
    assert "er_tercile" in working.columns


def test_build_run_table_censoring_on_a_hand_built_series():
    # One ticker, hand-built slope_positive series so the exact runs are
    # known: [T,T,T, F,F, T,T,T,T] -> run0=[T,T,T] (left-censored, dropped),
    # run1=[F,F] (duration=2, event=1), run2=[T,T,T,T] (duration=4, event=0,
    # still active at the ticker's own last row).
    dates = pd.bdate_range("2021-01-01", periods=9)
    values = [True, True, True, False, False, True, True, True, True]
    panel = pd.DataFrame({
        "ticker": ["AAA"] * 9,
        "date": dates,
        "slope_positive_50": values,
        "vol_tercile": [1] * 9,
        "er_tercile": [1] * 9,
        "realized_vol_63": [0.02] * 9,
    })

    table = sp.build_run_table(panel, lookback=50)

    assert len(table) == 2  # run0 dropped
    assert set(zip(table["duration"], table["event"])) == {(2.0, 1), (4.0, 0)}


def test_build_run_table_all_one_run_produces_no_rows():
    # A ticker whose slope never flips has only run 0 (left-censored) --
    # excluded entirely, not reported as a spurious censored observation.
    dates = pd.bdate_range("2021-01-01", periods=5)
    panel = pd.DataFrame({
        "ticker": ["AAA"] * 5,
        "date": dates,
        "slope_positive_50": [True] * 5,
        "vol_tercile": [1] * 5,
        "er_tercile": [1] * 5,
        "realized_vol_63": [0.02] * 5,
    })

    table = sp.build_run_table(panel, lookback=50)
    assert table.empty


def test_evaluate_kill_criterion_module_killed_when_no_stratum_departs():
    results = [
        {"departs_from_null": False},
        {"departs_from_null": False},
    ]
    verdict = sp.evaluate_kill_criterion(results)
    assert verdict["module_killed"] is True
    assert verdict["n_departing"] == 0


def test_evaluate_kill_criterion_not_killed_when_one_stratum_departs():
    results = [
        {"departs_from_null": False},
        {"departs_from_null": True},
    ]
    verdict = sp.evaluate_kill_criterion(results)
    assert verdict["module_killed"] is False
    assert verdict["n_departing"] == 1
