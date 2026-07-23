from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.bulk_polygon_ingest import JOB_TYPE, backfill_grouped_daily


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    db.upsert_tickers(
        connection,
        pd.DataFrame(
            [("AAPL", "Apple Inc.", "CS", True, None), ("MSFT", "Microsoft", "CS", True, None)],
            columns=["ticker", "name", "type", "active", "delisted_utc"],
        ),
    )
    yield connection
    connection.close()


def _grouped_bars(rows):
    """rows: list of (ticker, open, high, low, close, volume)"""
    return pd.DataFrame(rows, columns=["ticker", "open", "high", "low", "close", "volume"])


def test_requires_ticker_universe_populated_first():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)
    client = MagicMock()

    with pytest.raises(RuntimeError, match="ticker_universe"):
        backfill_grouped_daily(client, empty_conn, "2024-01-01", "2024-01-02")


def test_stores_bars_filtered_to_known_tickers(conn):
    client = MagicMock()
    client.get_grouped_daily_bars.return_value = _grouped_bars(
        [
            ("AAPL", 100, 101, 99, 100.5, 1000),
            ("MSFT", 200, 201, 199, 200.5, 2000),
            ("JUNKWARRANT", 1, 1, 1, 1, 1),  # not in the tickers reference table
        ]
    )

    backfill_grouped_daily(client, conn, "2024-01-01", "2024-01-01", as_of=pd.Timestamp("2024-02-01"))

    result = db.read_bars(conn, "bars_1d", source=db.POLYGON)
    assert set(result["ticker"]) == {"AAPL", "MSFT"}


def test_resumable_skips_already_succeeded_dates(conn):
    client = MagicMock()
    client.get_grouped_daily_bars.return_value = _grouped_bars([("AAPL", 100, 101, 99, 100.5, 1000)])

    backfill_grouped_daily(client, conn, "2024-01-01", "2024-01-02", as_of=pd.Timestamp("2024-02-01"))
    assert client.get_grouped_daily_bars.call_count == 2  # 2024-01-01 and 2024-01-02 (both weekdays)

    # Re-run over a wider range that includes the same two already-done dates
    # plus one new one -- only the new date should trigger a fresh call.
    client.get_grouped_daily_bars.reset_mock()
    backfill_grouped_daily(client, conn, "2024-01-01", "2024-01-03", as_of=pd.Timestamp("2024-02-01"))

    assert client.get_grouped_daily_bars.call_count == 1
    client.get_grouped_daily_bars.assert_called_once_with("2024-01-03")


def test_failed_date_is_flagged_not_retried_forever_in_place(conn):
    client = MagicMock()
    client.get_grouped_daily_bars.side_effect = ConnectionError("boom")

    backfill_grouped_daily(
        client, conn, "2024-01-01", "2024-01-01",
        as_of=pd.Timestamp("2024-02-01"), retry_backoff_seconds=0,
    )

    # attempt_with_limited_retries' default max_attempts=2 -- exactly 2 calls,
    # not an unbounded retry loop.
    assert client.get_grouped_daily_bars.call_count == 2

    row = conn.execute(
        "SELECT status, last_error FROM fetch_jobs WHERE job_type = ? AND key = ?",
        (JOB_TYPE, "2024-01-01"),
    ).fetchone()
    assert row[0] == "failed"
    assert "boom" in row[1]

    # No rows stored for the failed date.
    result = db.read_bars(conn, "bars_1d", source=db.POLYGON)
    assert result.empty


def test_a_later_run_retries_only_the_previously_failed_date(conn):
    client = MagicMock()
    client.get_grouped_daily_bars.side_effect = ConnectionError("boom")

    backfill_grouped_daily(
        client, conn, "2024-01-01", "2024-01-02",
        as_of=pd.Timestamp("2024-02-01"), retry_backoff_seconds=0,
    )
    assert client.get_grouped_daily_bars.call_count == 4  # 2 dates x 2 attempts each, both failed

    # Second run: 01-01 now succeeds, 01-02 still fails.
    client.get_grouped_daily_bars.reset_mock()

    def side_effect(day):
        if day == "2024-01-01":
            return _grouped_bars([("AAPL", 100, 101, 99, 100.5, 1000)])
        raise ConnectionError("still broken")

    client.get_grouped_daily_bars.side_effect = side_effect
    backfill_grouped_daily(
        client, conn, "2024-01-01", "2024-01-02",
        as_of=pd.Timestamp("2024-02-01"), retry_backoff_seconds=0,
    )

    # Both previously-failed dates get retried (neither had succeeded yet).
    assert client.get_grouped_daily_bars.call_count == 3  # 01-01 succeeds (1 call), 01-02 fails (2 calls)

    statuses = dict(
        conn.execute(
            "SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)
        ).fetchall()
    )
    assert statuses["2024-01-01"] == "success"
    assert statuses["2024-01-02"] == "failed"
