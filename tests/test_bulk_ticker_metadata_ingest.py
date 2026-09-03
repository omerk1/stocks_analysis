from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.bulk_ticker_metadata_ingest import JOB_TYPE, backfill_ticker_metadata


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


def _details(ticker, market_cap):
    return {
        "ticker": ticker,
        "market_cap": market_cap,
        "sic_code": "3571",
        "sic_description": "ELECTRONIC COMPUTERS",
        "share_class_shares_outstanding": 1_000_000,
        "weighted_shares_outstanding": 1_000_000,
        "total_employees": 1000,
        "primary_exchange": "XNAS",
        "list_date": "2000-01-01",
    }


def test_requires_ticker_universe_populated_first():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)
    client = MagicMock()

    with pytest.raises(RuntimeError, match="ticker_universe"):
        backfill_ticker_metadata(client, empty_conn)


def test_stores_metadata_for_each_active_ticker(conn):
    client = MagicMock()
    client.get_ticker_details.side_effect = lambda t: _details(t, 100.0)

    backfill_ticker_metadata(client, conn)

    result = db.read_ticker_metadata(conn)
    assert set(result["ticker"]) == {"AAPL", "MSFT"}  # AABA (delisted) excluded


def test_resumable_skips_already_succeeded_tickers(conn):
    client = MagicMock()
    client.get_ticker_details.side_effect = lambda t: _details(t, 100.0)
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")

    backfill_ticker_metadata(client, conn)

    client.get_ticker_details.assert_called_once_with("MSFT")


def test_failed_ticker_is_flagged_not_retried_forever_in_place(conn):
    client = MagicMock()
    client.get_ticker_details.side_effect = ConnectionError("boom")

    backfill_ticker_metadata(client, conn, retry_backoff_seconds=0)

    # attempt_with_limited_retries' default max_attempts=2, per ticker.
    assert client.get_ticker_details.call_count == 4  # 2 tickers x 2 attempts each

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"AAPL": "failed", "MSFT": "failed"}
    assert db.read_ticker_metadata(conn).empty


def test_a_later_run_retries_only_the_previously_failed_ticker(conn):
    client = MagicMock()
    client.get_ticker_details.side_effect = ConnectionError("boom")

    backfill_ticker_metadata(client, conn, retry_backoff_seconds=0)

    client.get_ticker_details.reset_mock()

    def side_effect(ticker):
        if ticker == "AAPL":
            return _details("AAPL", 100.0)
        raise ConnectionError("still broken")

    client.get_ticker_details.side_effect = side_effect
    backfill_ticker_metadata(client, conn, retry_backoff_seconds=0)

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses["AAPL"] == "success"
    assert statuses["MSFT"] == "failed"
