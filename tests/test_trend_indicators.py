import numpy as np
import pandas as pd
import talib

from src.feature_engineering.trend_indicators import TrendIndicators


def _price_series(n=30, seed=0):
    rng = np.random.default_rng(seed)
    closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
    highs = closes + rng.uniform(0.5, 2, n)
    lows = closes - rng.uniform(0.5, 2, n)
    return highs, lows, closes


def test_average_true_range_percent_matches_atr_over_close():
    highs, lows, closes = _price_series()

    result = TrendIndicators.average_true_range_percent(highs, lows, closes, timeperiod=14)

    expected = talib.ATR(highs, lows, closes, timeperiod=14) / closes * 100
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_stop_and_reverse_accepts_float_acceleration_and_maximum():
    highs, lows, _ = _price_series()

    result = TrendIndicators.stop_and_reverse(highs, lows, acceleration=0.02, maximum=0.2)

    assert isinstance(result, pd.Series)
    assert len(result) == len(highs)
