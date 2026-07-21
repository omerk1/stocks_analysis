import numpy as np
import pandas as pd

from src.feature_engineering import volume_indicators


def test_on_balance_volume_matches_hand_computed_sequence():
    closes = pd.Series([10.0, 11.0, 10.5, 10.5, 12.0])  # up, down, flat, up
    volumes = pd.Series([100.0, 200.0, 150.0, 120.0, 300.0])

    result = volume_indicators.on_balance_volume(closes, volumes)

    assert result.tolist() == [100.0, 300.0, 150.0, 150.0, 450.0]


def test_money_flow_index_is_bounded_between_0_and_100():
    rng = np.random.default_rng(0)
    closes = pd.Series(100 + np.cumsum(rng.normal(0, 1, 30)))
    highs = closes + rng.uniform(0.5, 2, 30)
    lows = closes - rng.uniform(0.5, 2, 30)
    volumes = pd.Series(rng.uniform(1000, 5000, 30))

    result = volume_indicators.money_flow_index(highs, lows, closes, volumes, timeperiod=14)

    valid = result.dropna()
    assert (valid >= 0).all()
    assert (valid <= 100).all()
