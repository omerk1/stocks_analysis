import pandas as pd
import pytest

from src.data_processing import db


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(rows):
    """rows: list of (date_str, open, high, low, close, volume, is_partial)"""
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_upsert_and_read_roundtrip(conn):
    bars = _bars(
        [
            ("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 0),
            ("2024-01-02", 100.5, 103.0, 100.0, 102.0, 1500, 0),
        ]
    )
    db.upsert_bars(conn, "bars_1d", "AAPL", bars)

    result = db.read_bars(conn, "bars_1d", ticker="AAPL")

    assert len(result) == 2
    assert result.iloc[0]["close"] == 100.5
    assert result.iloc[1]["close"] == 102.0
    assert "ticker" not in result.columns


def test_upsert_replaces_existing_row_not_duplicates(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", _bars([("2024-01-01", 100.0, 101.0, 99.0, 100.5, 1000, 1)]))
    db.upsert_bars(conn, "bars_1d", "AAPL", _bars([("2024-01-01", 100.0, 105.0, 99.0, 104.0, 2000, 0)]))

    result = db.read_bars(conn, "bars_1d", ticker="AAPL")

    assert len(result) == 1
    assert result.iloc[0]["close"] == 104.0
    assert result.iloc[0]["is_partial"] == 0


def test_read_filters_by_ticker_and_date_range(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
    db.upsert_bars(conn, "bars_1d", "MSFT", _bars([("2024-01-01", 2, 2, 2, 2, 2, 0)]))
    db.upsert_bars(
        conn,
        "bars_1d",
        "AAPL",
        _bars([("2024-06-01", 1, 1, 1, 1, 1, 0)]),
    )

    result = db.read_bars(conn, "bars_1d", ticker="AAPL", start="2024-02-01", end="2024-12-31")

    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2024-06-01")


def test_read_without_ticker_includes_ticker_column(conn):
    db.upsert_bars(conn, "bars_1d", "AAPL", _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
    db.upsert_bars(conn, "bars_1d", "MSFT", _bars([("2024-01-01", 2, 2, 2, 2, 2, 0)]))

    result = db.read_bars(conn, "bars_1d")

    assert set(result["ticker"]) == {"AAPL", "MSFT"}


def test_upsert_rejects_unknown_table(conn):
    with pytest.raises(ValueError):
        db.upsert_bars(conn, "not_a_table", "AAPL", _bars([("2024-01-01", 1, 1, 1, 1, 1, 0)]))
