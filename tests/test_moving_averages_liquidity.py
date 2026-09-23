"""Tests for `features/liquidity.py` -- M12's relative-volume/dollar-volume/
VWMA primitives (DESIGN.md line ~971; PREREGISTRATION.md, 2026-09-23).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.moving_averages.features import liquidity


def test_relative_volume_nan_during_warmup():
    volume = pd.Series(np.arange(1, 21, dtype=float))
    result = liquidity.relative_volume(volume, window=5)
    assert result.iloc[:4].isna().all()
    assert result.iloc[4:].notna().all()


def test_relative_volume_one_when_volume_constant():
    volume = pd.Series([100.0] * 20)
    result = liquidity.relative_volume(volume, window=5)
    assert np.allclose(result.iloc[4:], 1.0)


def test_relative_volume_above_one_on_a_spike():
    volume = pd.Series([100.0] * 10 + [500.0])
    result = liquidity.relative_volume(volume, window=5)
    # trailing 5-day average including the spike itself: (100*4+500)/5 = 180
    assert result.iloc[-1] == 500.0 / 180.0


def test_dollar_volume_is_elementwise_product():
    close = pd.Series([10.0, 20.0, 30.0])
    volume = pd.Series([100.0, 200.0, 300.0])
    result = liquidity.dollar_volume(close, volume)
    assert list(result) == [1000.0, 4000.0, 9000.0]


def test_vwma_equals_price_when_volume_constant():
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    volume = pd.Series([100.0] * 5)
    result = liquidity.vwma(close, volume, window=3)
    # equal-weighted volume -> VWMA collapses to a plain rolling mean of close
    expected = close.rolling(3).mean()
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_vwma_weights_toward_high_volume_days():
    close = pd.Series([10.0, 10.0, 20.0])
    volume = pd.Series([1.0, 1.0, 100.0])
    result = liquidity.vwma(close, volume, window=3)
    # dominated by the last (high-volume) day's price, close to 20, far from
    # the unweighted mean (13.33)
    assert result.iloc[-1] > 19.0


def test_vwma_nan_during_warmup():
    close = pd.Series(np.arange(1, 11, dtype=float))
    volume = pd.Series([10.0] * 10)
    result = liquidity.vwma(close, volume, window=4)
    assert result.iloc[:3].isna().all()
    assert result.iloc[3:].notna().all()
