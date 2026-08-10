from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.bulk_shares_outstanding_ingest import JOB_TYPE, backfill_shares_outstanding


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    db.upsert_tickers(
        connection,
        pd.DataFrame(
            [
                ("AAPL", "Apple Inc.", "CS", True, None),
                ("MSFT", "Microsoft", "CS", True, None),
                ("AABA", "Altaba Inc.", "CS", False, "2019-10-07T04:00:00Z"),
            ],
            columns=["ticker", "name", "type", "active", "delisted_utc"],
        ),
    )
    yield connection
    connection.close()


def _shares(dates):
    return pd.Series([1_000_000] * len(dates), index=pd.to_datetime(dates), name="shares_outstanding")


def test_requires_ticker_universe_populated_first():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)
    client = MagicMock()

    with pytest.raises(RuntimeError, match="ticker_universe"):
        backfill_shares_outstanding(client, empty_conn, "2010-01-01", "2024-01-01")


def test_stores_shares_outstanding_for_each_active_ticker(conn):
    client = MagicMock()
    client.get_shares_outstanding.side_effect = lambda t, s, e: _shares(["2020-01-01"])

    backfill_shares_outstanding(client, conn, "2010-01-01", "2024-01-01")

    aapl = db.read_shares_outstanding(conn, "AAPL", db.YFINANCE)
    msft = db.read_shares_outstanding(conn, "MSFT", db.YFINANCE)
    aaba = db.read_shares_outstanding(conn, "AABA", db.YFINANCE)  # delisted -- excluded
    assert len(aapl) == 1
    assert len(msft) == 1
    assert aaba.empty


def test_resumable_skips_already_succeeded_tickers(conn):
    client = MagicMock()
    client.get_shares_outstanding.side_effect = lambda t, s, e: _shares(["2020-01-01"])
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")

    backfill_shares_outstanding(client, conn, "2010-01-01", "2024-01-01")

    client.get_shares_outstanding.assert_called_once_with("MSFT", "2010-01-01", "2024-01-01")


def test_failed_ticker_is_flagged_not_retried_forever_in_place(conn):
    client = MagicMock()
    client.get_shares_outstanding.side_effect = ConnectionError("boom")

    backfill_shares_outstanding(client, conn, "2010-01-01", "2024-01-01", retry_backoff_seconds=0)

    # attempt_with_limited_retries' default max_attempts=2, per ticker.
    assert client.get_shares_outstanding.call_count == 4  # 2 tickers x 2 attempts each

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"AAPL": "failed", "MSFT": "failed"}
    assert db.read_shares_outstanding(conn, "AAPL", db.YFINANCE).empty


def test_a_later_run_retries_only_the_previously_failed_ticker(conn):
    client = MagicMock()
    client.get_shares_outstanding.side_effect = ConnectionError("boom")

    backfill_shares_outstanding(client, conn, "2010-01-01", "2024-01-01", retry_backoff_seconds=0)

    client.get_shares_outstanding.reset_mock()

    def side_effect(ticker, start, end):
        if ticker == "AAPL":
            return _shares(["2020-01-01"])
        raise ConnectionError("still broken")

    client.get_shares_outstanding.side_effect = side_effect
    backfill_shares_outstanding(client, conn, "2010-01-01", "2024-01-01", retry_backoff_seconds=0)

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses["AAPL"] == "success"
    assert statuses["MSFT"] == "failed"
