from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.bulk_splits_ingest import JOB_TYPE, backfill_splits


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _splits(rows=(("2020-08-31", 1.0, 4.0, 4.0),)):
    return pd.DataFrame(
        {
            "execution_date": pd.to_datetime([r[0] for r in rows]),
            "split_from": [r[1] for r in rows], "split_to": [r[2] for r in rows], "ratio": [r[3] for r in rows],
        }
    )


def test_stores_splits_for_each_ticker(conn):
    client = MagicMock()
    client.get_splits.side_effect = lambda t: _splits()

    backfill_splits(client, conn, ["AAPL", "MSFT"])

    aapl = db.read_splits(conn, "AAPL", db.POLYGON)
    msft = db.read_splits(conn, "MSFT", db.POLYGON)
    assert len(aapl) == 1
    assert len(msft) == 1


def test_resumable_skips_already_succeeded_tickers(conn):
    client = MagicMock()
    client.get_splits.side_effect = lambda t: _splits()
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")

    backfill_splits(client, conn, ["AAPL", "MSFT"])

    client.get_splits.assert_called_once_with("MSFT")


def test_failed_ticker_is_flagged_not_retried_forever_in_place(conn):
    client = MagicMock()
    client.get_splits.side_effect = ConnectionError("boom")

    backfill_splits(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    # attempt_with_limited_retries' default max_attempts=2, per ticker.
    assert client.get_splits.call_count == 4  # 2 tickers x 2 attempts each

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"AAPL": "failed", "MSFT": "failed"}
    assert db.read_splits(conn, "AAPL", db.POLYGON).empty


def test_a_later_run_retries_only_the_previously_failed_ticker(conn):
    client = MagicMock()
    client.get_splits.side_effect = ConnectionError("boom")

    backfill_splits(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    client.get_splits.reset_mock()

    def side_effect(ticker):
        if ticker == "AAPL":
            return _splits()
        raise ConnectionError("still broken")

    client.get_splits.side_effect = side_effect
    backfill_splits(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses["AAPL"] == "success"
    assert statuses["MSFT"] == "failed"


def test_a_ticker_with_no_splits_is_stored_as_a_success_with_zero_rows(conn):
    client = MagicMock()
    client.get_splits.side_effect = lambda t: pd.DataFrame(
        columns=["execution_date", "split_from", "split_to", "ratio"]
    )

    backfill_splits(client, conn, ["GEVO"])

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"GEVO": "success"}
    assert db.read_splits(conn, "GEVO", db.POLYGON).empty
