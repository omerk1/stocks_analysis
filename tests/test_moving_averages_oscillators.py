"""Tests for M17's oscillator features (`features/oscillators.py`,
PREREGISTRATION.md 2026-09-25). Correctness against hand-computable small
examples, not real-data results (that's the real-panel run, logged
separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.signals.moving_averages.features import oscillators as osc


def test_stochastic_k_at_the_top_of_its_own_range_is_100():
    high = pd.Series([10.0] * 20 + [15.0])
    low = pd.Series([5.0] * 21)
    close = pd.Series([8.0] * 20 + [15.0])
    k = osc.stochastic_k(high, low, close, period=14)
    assert k.iloc[-1] == pytest.approx(100.0)


def test_stochastic_k_at_the_bottom_of_its_own_range_is_0():
    high = pd.Series([10.0] * 21)
    low = pd.Series([5.0] * 20 + [2.0])
    close = pd.Series([8.0] * 20 + [2.0])
    k = osc.stochastic_k(high, low, close, period=14)
    assert k.iloc[-1] == pytest.approx(0.0)


def test_stochastic_k_is_na_when_the_rolling_range_is_flat():
    high = pd.Series([10.0] * 20)
    low = pd.Series([10.0] * 20)
    close = pd.Series([10.0] * 20)
    k = osc.stochastic_k(high, low, close, period=14)
    assert k.iloc[-1] != k.iloc[-1]  # NaN


def test_rsi_is_high_for_a_pure_uptrend():
    close = pd.Series(np.linspace(100, 130, 60))
    r = osc.rsi(close, period=14)
    assert r.iloc[-1] > 70


def test_rsi_is_low_for_a_pure_downtrend():
    close = pd.Series(np.linspace(130, 100, 60))
    r = osc.rsi(close, period=14)
    assert r.iloc[-1] < 30


def test_macd_components_returns_three_series_of_the_same_length():
    close = pd.Series(np.linspace(100, 120, 80) + np.sin(np.arange(80)))
    line, signal, hist = osc.macd_components(close)
    assert len(line) == len(signal) == len(hist) == 80
    # Histogram is the line-minus-signal spread, by definition.
    valid = line.notna() & signal.notna() & hist.notna()
    assert np.allclose((line - signal)[valid], hist[valid], atol=1e-9)
