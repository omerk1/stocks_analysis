from unittest.mock import MagicMock, patch

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
