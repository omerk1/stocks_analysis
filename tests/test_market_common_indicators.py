import pandas as pd

from src.foundation.feature_engineering.price_based_indicators import (
    exponential_moving_average,
    moving_average,
    moving_average_convergence_divergence,
    relative_strength_index,
)
from src.foundation.feature_engineering.trend_indicators import average_true_range
from src.foundation.feature_engineering.volume_indicators import on_balance_volume
from src.foundation.market_common import indicators


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


def test_sma_matches_feature_engineering_directly():
    df = _bars()
    expected = moving_average(df["close"], 10)

    result = indicators.sma(df["close"], 10)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_ema_matches_feature_engineering_directly():
    df = _bars()
    expected = exponential_moving_average(df["close"], 10)

    result = indicators.ema(df["close"], 10)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_ratio_divides_elementwise_on_matching_dates():
    idx = pd.bdate_range("2020-01-01", periods=5)
    target = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], index=idx)
    benchmark = pd.Series([5.0, 5.0, 10.0, 10.0, 25.0], index=idx)

    result = indicators.ratio(target, benchmark)

    expected = pd.Series([2.0, 4.0, 3.0, 4.0, 2.0], index=idx)
    pd.testing.assert_series_equal(result, expected)


def test_ratio_only_keeps_dates_present_in_both_series():
    target = pd.Series([10.0, 20.0, 30.0], index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]))
    # benchmark starts a day later than target (e.g. later ETF listing date)
    benchmark = pd.Series([5.0, 5.0], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))

    result = indicators.ratio(target, benchmark)

    assert list(result.index) == list(pd.to_datetime(["2020-01-02", "2020-01-03"]))
    assert list(result.values) == [4.0, 6.0]


def test_percentile_rank_of_known_values():
    values = pd.Series([10.0, 20.0, 30.0, 40.0])

    result = indicators.percentile_rank(values)

    assert list(result.values) == [25.0, 50.0, 75.0, 100.0]


def test_percentile_rank_averages_ties():
    values = pd.Series([10.0, 10.0, 30.0])

    result = indicators.percentile_rank(values)

    # tied values share the average of the ranks they'd occupy: both 10.0s
    # would occupy ranks 1 and 2 (pct 33.3%/66.7%), averaged to 50%.
    assert result.iloc[0] == result.iloc[1] == 50.0
    assert result.iloc[2] == 100.0


def test_percentile_rank_passes_through_nan():
    values = pd.Series([10.0, float("nan"), 30.0])

    result = indicators.percentile_rank(values)

    assert pd.isna(result.iloc[1])
    assert result.iloc[0] == 50.0
    assert result.iloc[2] == 100.0


def test_mansfield_rs_is_near_zero_for_a_flat_ratio():
    idx = pd.bdate_range("2020-01-01", periods=60)
    flat_ratio = pd.Series([2.0] * 60, index=idx)

    result = indicators.mansfield_rs(flat_ratio, period=10)

    assert (result.dropna().abs() < 1e-9).all()


def test_mansfield_rs_is_positive_when_ratio_is_rising_above_its_average():
    idx = pd.bdate_range("2020-01-01", periods=30)
    rising_ratio = pd.Series([1.0 + i * 0.05 for i in range(30)], index=idx)

    result = indicators.mansfield_rs(rising_ratio, period=10)

    assert result.iloc[-1] > 0
