from unittest.mock import patch

import pandas as pd

from src.foundation.data_processing.yfinance_client import YFinanceClient


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


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_daily_bars_drops_time_and_tz(mock_ticker_cls):
    index = pd.to_datetime(["2024-01-01 00:00:00-05:00", "2024-01-02 00:00:00-05:00"])
    mock_ticker_cls.return_value.history.return_value = _raw_history(index)

    df = YFinanceClient().get_daily_bars("AAPL", "2024-01-01", "2024-01-03")

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None
    assert (df.index == df.index.normalize()).all()


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_hourly_bars_keeps_time_drops_tz(mock_ticker_cls):
    index = pd.to_datetime(["2024-01-02 09:30:00-05:00", "2024-01-02 10:30:00-05:00"])
    mock_ticker_cls.return_value.history.return_value = _raw_history(index)

    df = YFinanceClient().get_hourly_bars("AAPL", "2024-01-02", "2024-01-03")

    assert df.index.tz is None
    # converted to UTC (from -05:00), so hour shifts from 09:30/10:30 to 14:30/15:30
    assert df.index[0].hour == 14


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_empty_response_returns_empty_frame_with_expected_columns(mock_ticker_cls):
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

    df = YFinanceClient().get_daily_bars("AAPL", "2024-01-01", "2024-01-03")

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_end_date_is_shifted_to_be_inclusive(mock_ticker_cls):
    # yfinance's own `end` is exclusive (confirmed directly against the real
    # API); this client shifts it by a day so callers get the same
    # inclusive-end semantics as Polygon.
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

    YFinanceClient().get_daily_bars("AAPL", "2024-01-01", "2024-01-03")

    _, kwargs = mock_ticker_cls.return_value.history.call_args
    assert kwargs["end"] == "2024-01-04"


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_shares_outstanding_drops_time_and_tz(mock_ticker_cls):
    index = pd.to_datetime(["2020-08-03 00:00:00-04:00", "2020-08-04 00:00:00-04:00"])
    mock_ticker_cls.return_value.get_shares_full.return_value = pd.Series(
        [4_283_940_096, 4_275_630_080], index=index
    )

    result = YFinanceClient().get_shares_outstanding("AAPL", "2020-08-01", "2020-08-10")

    assert result.index.tz is None
    assert (result.index == result.index.normalize()).all()
    assert result.name == "shares_outstanding"
    assert result.index.name == "date"


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_shares_outstanding_handles_a_tz_naive_index(mock_ticker_cls):
    # Regression: confirmed live against several real delisted/acquired
    # tickers (e.g. X, XEC, XLNX, YHOO) -- yfinance returns a tz-naive index
    # for these instead of the usual tz-aware one, and the old code's
    # unconditional tz_convert("UTC") raised TypeError ("Cannot convert
    # tz-naive timestamps") for every one of them (167 failures in one real
    # ~1,400-ticker backfill run, all this exact error).
    index = pd.to_datetime(["2015-11-04", "2016-03-14"])
    assert index.tz is None
    mock_ticker_cls.return_value.get_shares_full.return_value = pd.Series(
        [200_000_000, 199_000_000], index=index
    )

    result = YFinanceClient().get_shares_outstanding("X", "2010-01-01", "2020-01-01")

    assert result.index.tz is None
    assert list(result.values) == [200_000_000, 199_000_000]
    assert (result.index == result.index.normalize()).all()


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_shares_outstanding_deduplicates_same_day_entries_keeping_last(mock_ticker_cls):
    # Regression: real AAPL data around its 2020-08-31 4-for-1 split has
    # genuine same-calendar-day duplicate rows (2 of 6 in a real check),
    # most likely a same-day filing revision -- the later value should win,
    # same "keep last" convention used elsewhere in this project
    # (sr_lines/data.py's load_bars).
    index = pd.to_datetime([
        "2020-08-04 00:00:00-04:00", "2020-08-04 00:00:00-04:00", "2020-08-31 00:00:00-04:00",
    ])
    mock_ticker_cls.return_value.get_shares_full.return_value = pd.Series(
        [4_383_370_240, 4_275_630_080, 4_275_630_080], index=index
    )

    result = YFinanceClient().get_shares_outstanding("AAPL", "2020-08-01", "2020-09-01")

    assert len(result) == 2
    assert result.iloc[0] == 4_275_630_080  # the later of the two 2020-08-04 rows


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_shares_outstanding_handles_none_response(mock_ticker_cls):
    # get_shares_full returns None (not an empty Series/DataFrame) for a
    # ticker with no share-count history available.
    mock_ticker_cls.return_value.get_shares_full.return_value = None

    result = YFinanceClient().get_shares_outstanding("XYZ", "2020-01-01", "2020-02-01")

    assert result.empty
    assert result.name == "shares_outstanding"


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_sector_info_extracts_sector_and_industry(mock_ticker_cls):
    mock_ticker_cls.return_value.get_info.return_value = {
        "sector": "Technology", "industry": "Consumer Electronics", "longName": "Apple Inc.",
    }

    result = YFinanceClient().get_sector_info("AAPL")

    assert result == {"ticker": "AAPL", "sector": "Technology", "industry": "Consumer Electronics"}


@patch("src.foundation.data_processing.yfinance_client.yf.Ticker")
def test_get_sector_info_handles_missing_fields(mock_ticker_cls):
    mock_ticker_cls.return_value.get_info.return_value = {}

    result = YFinanceClient().get_sector_info("XYZ")

    assert result == {"ticker": "XYZ", "sector": None, "industry": None}
