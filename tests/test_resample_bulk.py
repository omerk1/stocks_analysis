import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.resample_bulk import resample_all_tickers


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _daily(rows):
    """rows: list of (ticker, date_str, open, high, low, close, volume, is_partial)"""
    return pd.DataFrame(
        rows,
        columns=["ticker", "timestamp", "open", "high", "low", "close", "volume", "is_partial"],
    )


def test_resamples_every_ticker_with_stored_daily_bars(conn):
    bars = _daily(
        [
            ("AAPL", "2024-01-01", 100, 101, 99, 100, 1000, 0),
            ("AAPL", "2024-01-02", 100, 101, 99, 101, 1000, 0),
            ("MSFT", "2024-01-01", 200, 201, 199, 200, 2000, 0),
        ]
    )
    db.upsert_bars_bulk(conn, "bars_1d", db.POLYGON, bars)

    resample_all_tickers(conn, db.POLYGON, as_of=pd.Timestamp("2024-02-01"))

    weekly = db.read_bars(conn, "bars_1w", source=db.POLYGON)
    assert set(weekly["ticker"]) == {"AAPL", "MSFT"}
    aapl_week = weekly[weekly["ticker"] == "AAPL"].iloc[0]
    assert aapl_week["close"] == 101
    assert aapl_week["is_partial"] == 0


def test_only_resamples_the_given_source(conn):
    db.upsert_bars_bulk(
        conn, "bars_1d", db.POLYGON,
        _daily([("AAPL", "2024-01-01", 100, 101, 99, 100, 1000, 0)]),
    )
    db.upsert_bars_bulk(
        conn, "bars_1d", db.YFINANCE,
        _daily([("MSFT", "2024-01-01", 200, 201, 199, 200, 2000, 0)]),
    )

    resample_all_tickers(conn, db.POLYGON, as_of=pd.Timestamp("2024-02-01"))

    weekly = db.read_bars(conn, "bars_1w", source=db.POLYGON)
    assert set(weekly["ticker"]) == {"AAPL"}
