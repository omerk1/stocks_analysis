import pandas as pd

from src.feature_engineering.price_based_indicators import (
    moving_average_convergence_divergence,
    relative_strength_index,
)
from src.feature_engineering.trend_indicators import average_true_range
from src.feature_engineering.volume_indicators import on_balance_volume
from src.market_common import indicators


def _bars(n: int = 40) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=n)
    # Not flat -- ATR/RSI/MACD need real variation to be meaningful, but
    # values themselves don't matter here, only that the wrapper matches
    # calling feature_engineering directly with the same inputs.
    close = pd.Series([100 + (i % 7) - (i % 3) for i in range(n)], index=idx, dtype=float)
    return pd.DataFrame(
        {
            "open": close, "high": close + 1.0, "low": close - 1.0,
            "close": close, "volume": [1_000_000.0 + i * 100 for i in range(n)],
        },
        index=idx,
    )


def test_atr_matches_feature_engineering_directly():
    df = _bars()
    expected = average_true_range(df["high"], df["low"], df["close"], timeperiod=14)

    result = indicators.atr(df, 14)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_rsi_matches_feature_engineering_directly():
    df = _bars()
    expected = relative_strength_index(df["close"], window=14)

    result = indicators.rsi(df["close"], 14)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_macd_matches_feature_engineering_directly_and_returns_three_series():
    df = _bars()
    expected = moving_average_convergence_divergence(df["close"], fastperiod=12, slowperiod=26, signalperiod=9)

    line, signal, hist = indicators.macd(df["close"], 12, 26, 9)

    pd.testing.assert_series_equal(line, expected[0], check_names=False)
    pd.testing.assert_series_equal(signal, expected[1], check_names=False)
    pd.testing.assert_series_equal(hist, expected[2], check_names=False)


def test_obv_matches_feature_engineering_directly():
    df = _bars()
    expected = on_balance_volume(df["close"], df["volume"])

    result = indicators.obv(df["close"], df["volume"])

    pd.testing.assert_series_equal(result, expected, check_names=False)
