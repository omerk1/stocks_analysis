"""Tests for M9's regime-conditional-lookback module
(`modules/regime_conditional_lookback.py`, PREREGISTRATION.md 2026-09-24).
Synthetic-panel tests only -- mechanics (regime lag safety, best-lookback
selection, adaptive-signal switching, kill criterion), not a real-data
result (that's the real-panel run, logged separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import regime_conditional_lookback as rcl


def _synthetic_panel(n_tickers: int = 6, n_days: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        drift = 3 * np.sin(np.linspace(0, 6, n_days))
        close = 100 + np.cumsum(steps) + drift
        frame = pd.DataFrame({
            "ticker": ticker, "date": dates, "close": close,
            "high": close + rng.uniform(0.1, 0.5, n_days),
            "low": close - rng.uniform(0.1, 0.5, n_days),
            "volume": rng.uniform(1e6, 5e6, n_days),
        })
        frame["ema_20"] = frame["close"].ewm(span=20, adjust=False).mean()
        frame["ema_50"] = frame["close"].ewm(span=50, adjust=False).mean()
        frame["above_ema_20"] = ((frame["close"] > frame["ema_20"]).astype("boolean")).mask(frame["ema_20"].isna())
        frame["above_ema_50"] = ((frame["close"] > frame["ema_50"]).astype("boolean")).mask(frame["ema_50"].isna())
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_prepare_adds_expected_columns():
    panel = _synthetic_panel()
    working = rcl.prepare(panel)
    for col in ("ema_10", "above_ema_10", "er_raw", "adx_raw", "er_regime", "adx_regime", "fwd_ret_21", "above_kama"):
        assert col in working.columns


def test_regime_features_are_one_bar_lagged():
    """The regime bucket used to condition row t's forward return must be
    knowable as of t-1's close -- checked directly, not assumed.
    """
    panel = _synthetic_panel(n_tickers=1, n_days=100)
    working = rcl.prepare(panel)

    from src.signals.moving_averages.features import regime

    raw_er = regime.efficiency_ratio(panel.sort_values("date")["close"].reset_index(drop=True), rcl.ER_PERIOD)
    lagged_er = working.sort_values("date")["er_raw"].reset_index(drop=True)
    assert lagged_er.iloc[20] == raw_er.iloc[19]
    assert pd.isna(lagged_er.iloc[0])


def test_best_lookback_per_regime_picks_largest_correctly_signed_delta():
    descriptive = pd.DataFrame({
        "regime_bucket": ["choppy", "choppy", "choppy", "trending", "trending", "trending"],
        "lookback": [10, 20, 50, 10, 20, 50],
        "c2": [0.001, 0.005, -0.002, 0.003, 0.001, 0.0005],
        "below_threshold": [False, False, False, False, False, False],
    })
    mapping = rcl.best_lookback_per_regime(descriptive)
    assert mapping["choppy"] == 20  # largest positive c2 among eligible
    assert mapping["trending"] == 10


def test_best_lookback_per_regime_ignores_negative_and_below_threshold_cells():
    descriptive = pd.DataFrame({
        "regime_bucket": ["moderate", "moderate"],
        "lookback": [10, 20],
        "c2": [0.01, -0.01],
        "below_threshold": [True, False],
    })
    mapping = rcl.best_lookback_per_regime(descriptive)
    # lookback 10 is below_threshold (excluded), lookback 20 has negative c2
    # (wrong sign, excluded) -- no eligible cell.
    assert mapping["moderate"] is None


def test_adaptive_signal_switches_lookback_by_current_regime():
    panel = _synthetic_panel(n_tickers=2, n_days=100)
    working = rcl.prepare(panel)
    working["er_regime"] = pd.Categorical(
        ["choppy"] * (len(working) // 2) + ["trending"] * (len(working) - len(working) // 2),
        categories=["choppy", "moderate", "trending"],
    )
    mapping = {"choppy": 20, "trending": 50, "moderate": None}
    signal = rcl.adaptive_signal(working, mapping, fallback_lookback=20)

    choppy_mask = working["er_regime"] == "choppy"
    trending_mask = working["er_regime"] == "trending"
    pd.testing.assert_series_equal(
        signal[choppy_mask].astype("boolean"), working.loc[choppy_mask, "above_ema_20"].astype("boolean"),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        signal[trending_mask].astype("boolean"), working.loc[trending_mask, "above_ema_50"].astype("boolean"),
        check_names=False,
    )


def test_adaptive_signal_falls_back_when_mapping_is_none():
    panel = _synthetic_panel(n_tickers=1, n_days=100)
    working = rcl.prepare(panel)
    working["er_regime"] = pd.Categorical(["moderate"] * len(working), categories=["choppy", "moderate", "trending"])
    mapping = {"choppy": 10, "moderate": None, "trending": 50}
    signal = rcl.adaptive_signal(working, mapping, fallback_lookback=20)
    pd.testing.assert_series_equal(
        signal.astype("boolean"), working["above_ema_20"].astype("boolean"), check_names=False,
    )


def test_regime_persistence_excess_is_zero_for_a_fully_memoryless_series():
    rng = np.random.default_rng(0)
    n = 5000
    working = pd.DataFrame({
        "ticker": ["T0"] * n,
        "date": pd.bdate_range("2020-01-01", periods=n),
        "er_regime": pd.Categorical(
            rng.choice(["choppy", "moderate", "trending"], size=n, p=[0.3, 0.4, 0.3]),
            categories=["choppy", "moderate", "trending"],
        ),
    })
    result = rcl.regime_persistence(working, horizon=21)
    # A genuinely i.i.d. draw's empirical persistence should sit close to
    # the memoryless base rate (0.3^2+0.4^2+0.3^2=0.34), not exactly equal
    # (finite-sample noise), but within a generous tolerance.
    row = result.iloc[0]
    assert abs(row["empirical_persistence_rate"] - row["memoryless_persistence_rate"]) < 0.03


def test_evaluate_kill_criterion_kills_when_ci_spans_zero():
    result = {"diff_point": 0.001, "diff_ci_low": -0.002, "diff_ci_high": 0.003, "incremental_cost_hurdle_annual": 0.01}
    verdict = rcl.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True
    assert verdict["reason"] == "ci_spans_zero"


def test_evaluate_kill_criterion_kills_when_ci_excludes_zero_but_fails_cost():
    result = {"diff_point": 0.0005, "diff_ci_low": 0.0001, "diff_ci_high": 0.001, "incremental_cost_hurdle_annual": 0.05}
    verdict = rcl.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is True
    assert verdict["reason"] == "clears_ci_not_cost"


def test_evaluate_kill_criterion_survives_when_ci_excludes_zero_and_clears_cost():
    result = {"diff_point": 0.005, "diff_ci_low": 0.003, "diff_ci_high": 0.007, "incremental_cost_hurdle_annual": 0.01}
    verdict = rcl.evaluate_kill_criterion(result)
    assert verdict["module_killed"] is False
    assert verdict["reason"] == "clears_ci_and_cost"
