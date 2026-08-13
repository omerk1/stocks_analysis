from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data_processing.polygon_client import PolygonClient


def _make_agg(timestamp_ms, close):
    return MagicMock(
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1_000_000,
        vwap=close,
        timestamp=timestamp_ms,
        transactions=100,
    )


def _make_grouped_agg(ticker, close):
    return MagicMock(ticker=ticker, open=close - 1, high=close + 1, low=close - 2, close=close, volume=1_000_000)


def _make_ticker(ticker, name="Some Co", type_="CS", delisted_utc=None):
    return MagicMock(ticker=ticker, name=name, type=type_, delisted_utc=delisted_utc)


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(ValueError):
        PolygonClient(api_key=None)


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_daily_bars_shapes_dataframe(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.get_aggs.return_value = [
        _make_agg(1704067200000, 100.0),  # 2024-01-01
        _make_agg(1704153600000, 102.0),  # 2024-01-02
    ]

    client = PolygonClient(api_key="fake-key")
    df = client.get_daily_bars("AAPL", "2024-01-01", "2024-01-02")

    assert list(df.columns) == ["open", "high", "low", "close", "volume", "vwap", "transactions"]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 100.0
    assert df.iloc[1]["close"] == 102.0


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_daily_bars_paces_through_shared_rate_limiter(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.get_aggs.return_value = []
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    client.get_daily_bars("AAPL", "2024-01-01", "2024-01-02")

    rate_limiter.wait.assert_called_once()


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_grouped_daily_bars_shapes_dataframe(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.get_grouped_daily_aggs.return_value = [
        _make_grouped_agg("AAPL", 100.0),
        _make_grouped_agg("MSFT", 200.0),
    ]
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    df = client.get_grouped_daily_bars("2024-01-02")

    assert list(df.columns) == ["ticker", "open", "high", "low", "close", "volume"]
    assert set(df["ticker"]) == {"AAPL", "MSFT"}
    rate_limiter.wait.assert_called_once()


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_ticker_details_shapes_dict_and_paces_through_rate_limiter(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.get_ticker_details.return_value = MagicMock(
        ticker="AAPL",
        market_cap=4_891_183_295_120.0,
        sic_code="3571",
        sic_description="ELECTRONIC COMPUTERS",
        share_class_shares_outstanding=15_000_000_000,
        weighted_shares_outstanding=15_100_000_000,
        total_employees=164_000,
        primary_exchange="XNAS",
        list_date="1980-12-12",
    )
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    details = client.get_ticker_details("AAPL")

    assert details == {
        "ticker": "AAPL",
        "market_cap": 4_891_183_295_120.0,
        "sic_code": "3571",
        "sic_description": "ELECTRONIC COMPUTERS",
        "share_class_shares_outstanding": 15_000_000_000,
        "weighted_shares_outstanding": 15_100_000_000,
        "total_employees": 164_000,
        "primary_exchange": "XNAS",
        "list_date": "1980-12-12",
    }
    rate_limiter.wait.assert_called_once()


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_splits_shapes_dataframe_sorted_ascending_and_paces_through_rate_limiter(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    # Out of order on purpose (real API returns newest-first) -- confirms
    # get_splits sorts ascending rather than trusting call order.
    mock_client.list_splits.return_value = iter(
        [
            MagicMock(execution_date="2020-08-31", split_from=1, split_to=4, ticker="AAPL"),
            MagicMock(execution_date="2014-06-09", split_from=1, split_to=7, ticker="AAPL"),
        ]
    )
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    splits = client.get_splits("AAPL")

    assert list(splits["execution_date"]) == list(pd.to_datetime(["2014-06-09", "2020-08-31"]))
    assert list(splits["split_from"]) == [1, 1]
    assert list(splits["split_to"]) == [7, 4]
    assert list(splits["ratio"]) == [7.0, 4.0]
    rate_limiter.wait.assert_called_once()


@patch("src.data_processing.polygon_client.RESTClient")
def test_get_splits_empty_when_no_splits(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.list_splits.return_value = iter([])
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    splits = client.get_splits("XYZ")

    assert splits.empty
    assert list(splits.columns) == ["execution_date", "split_from", "split_to", "ratio"]


@patch("src.data_processing.polygon_client.RESTClient")
def test_list_common_stock_tickers_paginates_and_paces_per_page(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    # Two full pages of size 2, then a short final page -- generator-backed,
    # like the real library's auto-paginating iterator.
    all_tickers = [_make_ticker("A"), _make_ticker("B"), _make_ticker("C"), _make_ticker("D"), _make_ticker("E")]
    mock_client.list_tickers.return_value = iter(all_tickers)
    rate_limiter = MagicMock()

    client = PolygonClient(api_key="fake-key", rate_limiter=rate_limiter)
    df = client.list_common_stock_tickers(active=True, page_size=2)

    assert list(df["ticker"]) == ["A", "B", "C", "D", "E"]
    assert (df["active"] == True).all()  # noqa: E712
    # 2 full pages (2 items each) + 1 short page (1 item) = 3 wait() calls
    assert rate_limiter.wait.call_count == 3


@patch("src.data_processing.polygon_client.RESTClient")
def test_list_common_stock_tickers_includes_delisted_metadata(mock_rest_client_cls):
    mock_client = mock_rest_client_cls.return_value
    mock_client.list_tickers.return_value = iter(
        [_make_ticker("AABA", name="Altaba Inc.", delisted_utc="2019-10-07T04:00:00Z")]
    )

    client = PolygonClient(api_key="fake-key")
    df = client.list_common_stock_tickers(active=False, page_size=1000)

    assert df.iloc[0]["delisted_utc"] == "2019-10-07T04:00:00Z"
    assert df.iloc[0]["active"] == False  # noqa: E712
