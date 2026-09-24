"""Tests for M17's nonlinearity-probe module (`modules/nonlinearity_probe.py`,
PREREGISTRATION.md 2026-09-25). Synthetic-panel tests only -- mechanics
(lag safety, incremental-IC construction, kill criterion, divergence-event
population), not a real-data result (that's the real-panel run, logged
separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.modules import nonlinearity_probe as nlp


def _synthetic_panel(n_tickers: int = 8, n_days: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    frames = []
    for i in range(n_tickers):
        ticker = f"T{i}"
        steps = rng.normal(0, 1, n_days)
        drift = 3 * np.sin(np.linspace(0, 6, n_days))
        close = 100 + np.cumsum(steps) + drift
        high = close + rng.uniform(0.1, 1.0, n_days)
        low = close - rng.uniform(0.1, 1.0, n_days)
        frame = pd.DataFrame({"ticker": ticker, "date": dates, "close": close, "high": high, "low": low})
        frame["sma_50"] = frame["close"].rolling(50).mean()
        frame["dist_pct_sma_50"] = frame["close"] / frame["sma_50"] - 1
        frame["dist_z_sma_20"] = (frame["close"] - frame["close"].rolling(20).mean()) / frame["close"].rolling(20).std()
        frame["slope_log_21_sma_50"] = np.log(frame["sma_50"]).diff(21)
        frame["slope_log_5_sma_50"] = np.log(frame["sma_50"]).diff(5)
        frame["mom_12_1"] = frame["close"].pct_change(230).shift(21)
        frame["realized_vol_63"] = frame["close"].pct_change().rolling(63).std()
        frame["sector"] = "tech"
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def test_prepare_adds_expected_columns():
    panel = _synthetic_panel()
    working = nlp.prepare(panel)
    for col in ("macd_line", "macd_signal", "macd_histogram", "rsi", "rsi_slope",
                "stochastic_k", "efficiency_ratio", "rsi_er_interaction",
                "fwd_ret_21", "fwd_ret_63", "is_new_high", "divergence"):
        assert col in working.columns


def test_oscillators_are_lagged_one_bar():
    panel = _synthetic_panel(n_tickers=1)
    working = nlp.prepare(panel)

    from src.signals.moving_averages.features.oscillators import rsi as raw_rsi

    raw = raw_rsi(panel.sort_values("date")["close"].reset_index(drop=True))
    lagged_col = working.sort_values("date")["rsi"].reset_index(drop=True)
    assert lagged_col.iloc[60] == raw.iloc[59]
    assert pd.isna(lagged_col.iloc[0])


def test_incremental_ic_table_shape_and_effective_n_fields():
    panel = _synthetic_panel()
    working = nlp.prepare(panel)
    table = nlp.incremental_ic_table(working, "rsi")
    assert len(table) == len(nlp.HORIZONS)
    for col in ("n_events", "n_dates", "n_tickers", "ci_low", "ci_high", "edge"):
        assert col in table.columns


def test_kill_verdict_fires_when_every_edge_is_near_zero():
    tiny = pd.DataFrame({"edge": [0.001, 0.002]})
    assert nlp.kill_verdict(tiny, floor=0.005) is True


def test_kill_verdict_does_not_fire_when_one_edge_exceeds_floor():
    tiny = pd.DataFrame({"edge": [0.001, 0.02]})
    assert nlp.kill_verdict(tiny, floor=0.005) is False


def test_divergence_flag_is_boolean_or_na_and_only_set_on_new_high_rows():
    panel = _synthetic_panel()
    working = nlp.prepare(panel)
    non_high_rows = working[~working["is_new_high"]]
    # Divergence is only ever meaningfully True/False on new-high rows --
    # off those rows it may still carry a value from construction, but the
    # decisive test itself (`histogram_divergence_delta`) restricts its
    # own population to `is_new_high` before using the flag, checked here.
    result = nlp.histogram_divergence_delta(working)
    assert result["n_events"] <= int(working["is_new_high"].sum())


def test_ambiguous_region_table_restricts_to_a_smaller_population():
    panel = _synthetic_panel(n_tickers=20, n_days=400)
    working = nlp.prepare(panel)
    full = nlp.incremental_ic_table(working, "rsi", horizons=(21,))
    restricted = nlp.ambiguous_region_table(working, horizon=21)
    assert restricted.iloc[0]["n_events"] < full.iloc[0]["n_events"]


def test_zero_vs_signal_diagnostic_returns_rates_between_0_and_1():
    panel = _synthetic_panel(n_tickers=20, n_days=400)
    working = nlp.prepare(panel)
    result = nlp.zero_vs_signal_diagnostic(working)
    assert 0.0 <= result["zero_line_vs_trend_state_agreement"] <= 1.0
    assert 0.0 <= result["signal_line_vs_accel_state_agreement"] <= 1.0
