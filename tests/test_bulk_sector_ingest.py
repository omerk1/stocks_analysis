from unittest.mock import MagicMock

import pytest

from src.data_processing import db
from src.data_processing.bulk_sector_ingest import JOB_TYPE, backfill_sectors


@pytest.fixture
def conn():
    connection = db.get_connection(":memory:")
    db.create_tables(connection)
    yield connection
    connection.close()


def _info(ticker, sector="Technology", industry="Consumer Electronics"):
    return {"ticker": ticker, "sector": sector, "industry": industry}


def test_stores_sector_for_each_ticker(conn):
    client = MagicMock()
    client.get_sector_info.side_effect = lambda t: _info(t)

    backfill_sectors(client, conn, ["AAPL", "MSFT"])

    aapl = db.read_ticker_sector(conn, "AAPL")
    msft = db.read_ticker_sector(conn, "MSFT")
    assert aapl.iloc[0]["sector"] == "Technology"
    assert msft.iloc[0]["sector"] == "Technology"


def test_resumable_skips_already_succeeded_tickers(conn):
    client = MagicMock()
    client.get_sector_info.side_effect = lambda t: _info(t)
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")

    backfill_sectors(client, conn, ["AAPL", "MSFT"])

    client.get_sector_info.assert_called_once_with("MSFT")


def test_failed_ticker_is_flagged_not_retried_forever_in_place(conn):
    client = MagicMock()
    client.get_sector_info.side_effect = ConnectionError("boom")

    backfill_sectors(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    # attempt_with_limited_retries' default max_attempts=2, per ticker.
    assert client.get_sector_info.call_count == 4  # 2 tickers x 2 attempts each

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"AAPL": "failed", "MSFT": "failed"}
    assert db.read_ticker_sector(conn, "AAPL").empty


def test_a_later_run_retries_only_the_previously_failed_ticker(conn):
    client = MagicMock()
    client.get_sector_info.side_effect = ConnectionError("boom")

    backfill_sectors(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    client.get_sector_info.reset_mock()

    def side_effect(ticker):
        if ticker == "AAPL":
            return _info("AAPL")
        raise ConnectionError("still broken")

    client.get_sector_info.side_effect = side_effect
    backfill_sectors(client, conn, ["AAPL", "MSFT"], retry_backoff_seconds=0)

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses["AAPL"] == "success"
    assert statuses["MSFT"] == "failed"


def test_a_ticker_with_no_sector_data_is_stored_as_a_success_with_null_values(conn):
    client = MagicMock()
    client.get_sector_info.side_effect = lambda t: _info(t, sector=None, industry=None)

    backfill_sectors(client, conn, ["GEVO"])

    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"GEVO": "success"}
    result = db.read_ticker_sector(conn, "GEVO")
    assert len(result) == 1
    assert result.iloc[0]["sector"] is None
