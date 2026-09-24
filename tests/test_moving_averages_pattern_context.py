"""Tests for M14's pattern-context module (`modules/pattern_context.py`,
PREREGISTRATION.md 2026-09-25). Synthetic fixtures only -- mechanics
(reclaim detection, pattern-window membership, kill criterion), not a
real-data result (that's the real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import pattern_context as pc


def _synthetic_panel(n_tickers: int = 4, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        drift = 3 * np.sin(np.linspace(0, 6, n_days))
        close = 100 + np.cumsum(steps) + drift
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close})
        frame["sma_50"] = frame["close"].rolling(50).mean()
        frame["above_sma_50"] = ((frame["close"] > frame["sma_50"]).astype("boolean")).mask(
            frame["sma_50"].isna()
        )
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_add_pattern_context_flag_marks_only_the_window():
    panel = pd.DataFrame({
        "ticker": ["A"] * 5,
        "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-10", "2020-01-20", "2020-02-15"]),
    })
    patterns = pd.DataFrame({
        "ticker": ["A"],
        "formation_start": pd.to_datetime(["2019-12-01"]),
        "formation_end": pd.to_datetime(["2020-01-10"]),
        "status": ["confirmed"],
        "confidence": [0.9],
    })
    result = pc.add_pattern_context_flag(panel, patterns)
    # 2020-01-10 (formation_end itself) and 2020-01-20 (within 21 bdays after) should be flagged;
    # 2020-01-01/02 (before formation_end) and 2020-02-15 (well past the 21-day window) should not.
    flags = dict(zip(result["date"].dt.strftime("%Y-%m-%d"), result["in_pattern_context"]))
    assert flags["2020-01-01"] is False
    assert flags["2020-01-02"] is False
    assert flags["2020-01-10"] is True
    assert flags["2020-01-20"] is True
    assert flags["2020-02-15"] is False


def test_add_pattern_context_flag_empty_patterns_is_all_false():
    panel = pd.DataFrame({"ticker": ["A", "B"], "date": pd.to_datetime(["2020-01-01", "2020-01-02"])})
    result = pc.add_pattern_context_flag(panel, pd.DataFrame(columns=["ticker", "formation_end"]))
    assert not result["in_pattern_context"].any()


def test_prepare_adds_expected_columns_and_reclaim_flag():
    panel = _synthetic_panel()
    patterns = pd.DataFrame(columns=["ticker", "formation_start", "formation_end", "status", "confidence"])
    working = pc.prepare(panel, patterns)
    for col in ("fwd_ret_21", "mom_tercile", "vol_tercile", "is_reclaim_50", "in_pattern_context"):
        assert col in working.columns
    assert working["is_reclaim_50"].dtype == bool
    assert working["is_reclaim_50"].sum() > 0, "fixture must produce at least one reclaim to be a useful test"


def test_reclaim_is_first_day_of_run_only():
    panel = pd.DataFrame({
        "ticker": ["A"] * 6,
        "date": pd.bdate_range("2020-01-01", periods=6),
        "close": [100.0, 101.0, 102.0, 103.0, 104.0, 103.0],
        "above_sma_50": pd.array([False, False, True, True, True, False], dtype="boolean"),
        "mom_12_1": [0.01] * 6,
        "realized_vol_63": [0.02] * 6,
        "sector": ["tech"] * 6,
    })
    patterns = pd.DataFrame(columns=["ticker", "formation_start", "formation_end", "status", "confidence"])
    working = pc.prepare(panel, patterns)
    reclaim_dates = working.loc[working["is_reclaim_50"], "date"].tolist()
    assert reclaim_dates == [pd.Timestamp("2020-01-03")]


def test_evaluate_kill_criterion_fires_when_ci_spans_zero():
    result = {"c2_ci_low": -0.001, "c2_ci_high": 0.002}
    verdict = pc.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True
    assert verdict["ci_excludes_zero"] is False


def test_evaluate_kill_criterion_does_not_fire_when_ci_excludes_zero_and_edge_clears_floor():
    result = {"c2_ci_low": 0.003, "c2_ci_high": 0.008}
    verdict = pc.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is False
    assert verdict["ci_excludes_zero"] is True


def test_evaluate_kill_criterion_fires_on_nan_ci():
    result = {"c2_ci_low": float("nan"), "c2_ci_high": float("nan")}
    verdict = pc.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True
