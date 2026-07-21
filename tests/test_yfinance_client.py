from unittest.mock import MagicMock, patch

import pandas as pd

from src.data_processing.yfinance_client import YFinanceClient


def _raw_history(index, n_rows=2):
    return pd.DataFrame(
        {
            "Open": [100.0] * n_rows,
            "High": [101.0] * n_rows,
            "Low": [99.0] * n_rows,
            "Close": [100.5] * n_rows,
            "Volume": [1000] * n_rows,
            "Dividends": [0.0] * n_rows,
            "Stock Splits": [0.0] * n_rows,
        },
        index=index,
    )


@patch("src.data_processing.yfinance_client.yf.Ticker")
def test_get_daily_bars_drops_time_and_tz(mock_ticker_cls):
    index = pd.to_datetime(["2024-01-01 00:00:00-05:00", "2024-01-02 00:00:00-05:00"])
    mock_ticker_cls.return_value.history.return_value = _raw_history(index)

    df = YFinanceClient().get_daily_bars("AAPL", "2024-01-01", "2024-01-03")

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None
    assert (df.index == df.index.normalize()).all()


@patch("src.data_processing.yfinance_client.yf.Ticker")
def test_get_hourly_bars_keeps_time_drops_tz(mock_ticker_cls):
    index = pd.to_datetime(["2024-01-02 09:30:00-05:00", "2024-01-02 10:30:00-05:00"])
    mock_ticker_cls.return_value.history.return_value = _raw_history(index)

    df = YFinanceClient().get_hourly_bars("AAPL", "2024-01-02", "2024-01-03")

    assert df.index.tz is None
    # converted to UTC (from -05:00), so hour shifts from 09:30/10:30 to 14:30/15:30
    assert df.index[0].hour == 14


@patch("src.data_processing.yfinance_client.yf.Ticker")
def test_empty_response_returns_empty_frame_with_expected_columns(mock_ticker_cls):
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

    df = YFinanceClient().get_daily_bars("AAPL", "2024-01-01", "2024-01-03")

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
