import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.validate_sources import compare_stored_daily_bars


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _bars(dates_and_closes):
    rows = [(d, c, c, c, c, 1000, 0) for d, c in dates_and_closes]
    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_partial"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_no_discrepancies_within_tolerance(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0), ("2024-01-02", 101.0)]),
    )
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([("2024-01-01", 100.05), ("2024-01-02", 100.99)]),
    )

    result = compare_stored_daily_bars(conn, "AAPL", tolerance=0.01)

    assert result.empty


def test_flags_dates_beyond_tolerance(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0), ("2024-01-02", 101.0)]),
    )
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([("2024-01-01", 100.0), ("2024-01-02", 150.0)]),
    )

    result = compare_stored_daily_bars(conn, "AAPL", tolerance=0.01)

    assert len(result) == 1
    assert result.index[0] == pd.Timestamp("2024-01-02")


def test_only_compares_dates_present_in_both_sources(conn):
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.POLYGON,
        _bars([("2024-01-01", 100.0), ("2024-01-02", 101.0)]),
    )
    db.upsert_bars(
        conn, "bars_1d", "AAPL", db.YFINANCE,
        _bars([("2024-01-01", 100.0)]),
    )

    result = compare_stored_daily_bars(conn, "AAPL", tolerance=0.01)

    assert result.empty  # 01-02 missing from yfinance side, not flagged as a mismatch
