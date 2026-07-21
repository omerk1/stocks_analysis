from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.fetch_data import fetch_ticker, mark_partial


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _daily(rows):
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def test_mark_partial_flags_today_and_later_only():
    daily = _daily(
        [
            ("2024-01-01", 100, 101, 99, 100, 1000),
            ("2024-01-02", 100, 101, 99, 100, 1000),
        ]
    )
    result = mark_partial(daily, as_of=pd.Timestamp("2024-01-02"))

    assert result.loc["2024-01-01", "is_partial"] == 0
    assert result.loc["2024-01-02", "is_partial"] == 1


def test_fetch_ticker_stores_daily_and_derived_weekly_monthly(conn):
    client = MagicMock()
    client.get_daily_bars.return_value = _daily(
        [
            ("2024-01-01", 100, 105, 99, 102, 1000),
            ("2024-01-02", 102, 103, 98, 99, 1100),
        ]
    )

    fetch_ticker(client, "AAPL", "2024-01-01", "2024-01-02", conn, as_of=pd.Timestamp("2024-01-02"))

    daily = db.read_bars(conn, "bars_1d", ticker="AAPL")
    weekly = db.read_bars(conn, "bars_1w", ticker="AAPL")
    monthly = db.read_bars(conn, "bars_1mo", ticker="AAPL")

    assert len(daily) == 2
    assert len(weekly) == 1
    assert weekly.iloc[0]["is_partial"] == 1  # week still in progress
    assert len(monthly) == 1
    assert monthly.iloc[0]["is_partial"] == 1


def test_fetch_ticker_second_run_updates_in_progress_period_in_place(conn):
    client = MagicMock()
    client.get_daily_bars.return_value = _daily([("2024-01-01", 100, 105, 99, 102, 1000)])
    fetch_ticker(client, "AAPL", "2024-01-01", "2024-01-01", conn, as_of=pd.Timestamp("2024-01-01"))

    client.get_daily_bars.return_value = _daily([("2024-01-02", 102, 103, 98, 99, 1100)])
    fetch_ticker(client, "AAPL", "2024-01-02", "2024-01-02", conn, as_of=pd.Timestamp("2024-01-02"))

    weekly = db.read_bars(conn, "bars_1w", ticker="AAPL")

    # Still a single weekly row (same label), now reflecting both days -- not a
    # stale row from the first run plus a duplicate from the second.
    assert len(weekly) == 1
    assert weekly.iloc[0]["close"] == 99
    assert weekly.iloc[0]["volume"] == 1000 + 1100
