import numpy as np
import pandas as pd
import pytest

from src.feature_engineering.momentum_indicators import MomentumIndicators


def test_rate_of_change_matches_percent_change_formula():
    closes = pd.Series([100.0, 110.0, 121.0, 133.1])

    result = MomentumIndicators.rate_of_change(closes, timeperiod=2)

    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(21.0)
    assert result.iloc[3] == pytest.approx(21.0)


def test_williams_r_is_bounded_between_minus_100_and_0():
    highs = pd.Series(np.random.default_rng(0).uniform(100, 110, 30))
    lows = highs - np.random.default_rng(1).uniform(1, 5, 30)
    closes = (highs + lows) / 2

    result = MomentumIndicators.williams_r(highs, lows, closes, timeperiod=14)

    valid = result.dropna()
    assert (valid <= 0).all()
    assert (valid >= -100).all()


def test_williams_r_hits_zero_at_the_period_high():
    # Constant series where the last bar's close equals the period high --
    # Williams %R should be at its ceiling, 0.
    highs = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    lows = pd.Series([9.0, 10.0, 11.0, 12.0, 13.0])
    closes = pd.Series([9.5, 10.5, 11.5, 12.5, 14.0])

    result = MomentumIndicators.williams_r(highs, lows, closes, timeperiod=5)

    assert result.iloc[-1] == pytest.approx(0.0)
