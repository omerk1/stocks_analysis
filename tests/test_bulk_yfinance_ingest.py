from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.data_processing import db
from src.data_processing.bulk_yfinance_ingest import JOB_TYPE, _to_yfinance_symbol, backfill_yfinance_daily


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


def _multi_ticker_frame(ticker_closes: dict, dates):
    columns = pd.MultiIndex.from_product(
        [ticker_closes.keys(), ["Open", "High", "Low", "Close", "Volume"]]
    )
    data = {}
    for ticker, close in ticker_closes.items():
        data[(ticker, "Open")] = [close - 1] * len(dates)
        data[(ticker, "High")] = [close + 1] * len(dates)
        data[(ticker, "Low")] = [close - 2] * len(dates)
        data[(ticker, "Close")] = [close] * len(dates)
        data[(ticker, "Volume")] = [1000] * len(dates)
    df = pd.DataFrame(data, index=pd.DatetimeIndex(dates), columns=columns)
    return df


def test_requires_ticker_universe_populated_first():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)

    with pytest.raises(RuntimeError, match="ticker_universe"):
        backfill_yfinance_daily(empty_conn, "2024-01-01", "2024-01-02")


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_stores_each_ticker_from_a_multi_ticker_batch(mock_download, conn):
    mock_download.return_value = _multi_ticker_frame(
        {"AAPL": 100.0, "MSFT": 200.0}, ["2024-01-01", "2024-01-02"]
    )

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-02", batch_size=50, as_of=pd.Timestamp("2024-02-01"))

    aapl = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE)
    msft = db.read_bars(conn, "bars_1d", ticker="MSFT", source=db.YFINANCE)
    assert len(aapl) == 2
    assert len(msft) == 2
    assert aapl.iloc[0]["close"] == 100.0
    assert msft.iloc[0]["close"] == 200.0


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_single_ticker_batch_still_uses_multiindex_shape(mock_download, conn):
    # yf.download always receives a *list*, even for one ticker -- and a
    # list-of-one still comes back MultiIndex-columned by ticker (confirmed
    # against the real API), unlike passing a bare string. Force a batch
    # size of 1 so only AAPL is pending in this call.
    db.record_job_result(conn, JOB_TYPE, "MSFT", "success")
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0}, ["2024-01-01"])

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", batch_size=1, as_of=pd.Timestamp("2024-02-01"))

    result = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE)
    assert len(result) == 1
    assert result.iloc[0]["close"] == 100.0


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_ticker_with_no_data_in_batch_is_flagged_others_still_stored(mock_download, conn):
    frame = _multi_ticker_frame({"AAPL": 100.0, "MSFT": 200.0}, ["2024-01-01"])
    # Simulate MSFT having no real data (e.g. delisted before this range) --
    # all-NaN row rather than missing from the columns entirely.
    frame[("MSFT", "Open")] = np.nan
    frame[("MSFT", "High")] = np.nan
    frame[("MSFT", "Low")] = np.nan
    frame[("MSFT", "Close")] = np.nan
    frame[("MSFT", "Volume")] = np.nan
    mock_download.return_value = frame

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", batch_size=50, as_of=pd.Timestamp("2024-02-01"))

    aapl = db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE)
    msft = db.read_bars(conn, "bars_1d", ticker="MSFT", source=db.YFINANCE)
    assert len(aapl) == 1
    assert msft.empty

    status = conn.execute(
        "SELECT status FROM fetch_jobs WHERE job_type = ? AND key = ?", (JOB_TYPE, "MSFT")
    ).fetchone()[0]
    assert status == "failed"


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_entire_batch_failure_flags_all_tickers_without_infinite_retry(mock_download, conn):
    mock_download.side_effect = ConnectionError("blocked")

    backfill_yfinance_daily(
        conn, "2024-01-01", "2024-01-01", batch_size=50,
        as_of=pd.Timestamp("2024-02-01"), retry_backoff_seconds=0,
    )

    assert mock_download.call_count == 2  # default max_attempts=2, not unbounded
    statuses = dict(
        conn.execute("SELECT key, status FROM fetch_jobs WHERE job_type = ?", (JOB_TYPE,)).fetchall()
    )
    assert statuses == {"AAPL": "failed", "MSFT": "failed"}
    assert db.read_bars(conn, "bars_1d", source=db.YFINANCE).empty


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_resumable_skips_already_succeeded_tickers(mock_download, conn):
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")
    mock_download.return_value = _multi_ticker_frame({"MSFT": 200.0}, ["2024-01-01"])

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", batch_size=50, as_of=pd.Timestamp("2024-02-01"))

    mock_download.assert_called_once_with(
        ["MSFT"], start="2024-01-01", end="2024-01-02", threads=True, progress=False, group_by="ticker"
    )


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_distinct_job_types_do_not_share_resumability(mock_download, conn):
    # "Success" recorded under the default job_type must not cause a
    # different job_type (e.g. a deeper historical backfill) to skip that
    # ticker as if it were already done for the new range too.
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")
    mock_download.return_value = _multi_ticker_frame(
        {"AAPL": 100.0, "MSFT": 200.0}, ["2010-01-04"]
    )

    backfill_yfinance_daily(
        conn, "2010-01-01", "2010-01-04", batch_size=50,
        as_of=pd.Timestamp("2024-02-01"), job_type="yfinance_daily_deep",
    )

    mock_download.assert_called_once_with(
        ["AAPL", "MSFT"], start="2010-01-01", end="2010-01-05",
        threads=True, progress=False, group_by="ticker",
    )
    statuses = dict(
        conn.execute(
            "SELECT key, status FROM fetch_jobs WHERE job_type = ?", ("yfinance_daily_deep",)
        ).fetchall()
    )
    assert statuses == {"AAPL": "success", "MSFT": "success"}


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_tickers_param_restricts_scope_instead_of_reading_reference_table(mock_download, conn):
    # conn's reference table has AAPL and MSFT; restrict this run to AAPL only.
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0}, ["2024-01-01"])

    backfill_yfinance_daily(
        conn, "2024-01-01", "2024-01-01", batch_size=50,
        as_of=pd.Timestamp("2024-02-01"), tickers=["AAPL"],
    )

    mock_download.assert_called_once_with(
        ["AAPL"], start="2024-01-01", end="2024-01-02", threads=True, progress=False, group_by="ticker"
    )
    assert db.read_bars(conn, "bars_1d", ticker="MSFT", source=db.YFINANCE).empty


def test_tickers_param_does_not_require_reference_table_populated():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)

    with patch("src.data_processing.bulk_yfinance_ingest.yf.download") as mock_download:
        mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0}, ["2024-01-01"])
        backfill_yfinance_daily(
            empty_conn, "2024-01-01", "2024-01-01", batch_size=50,
            as_of=pd.Timestamp("2024-02-01"), tickers=["AAPL"],
        )

    assert len(db.read_bars(empty_conn, "bars_1d", ticker="AAPL", source=db.YFINANCE)) == 1
    empty_conn.close()


def test_to_yfinance_symbol_translates_dots_to_hyphens():
    # Polygon uses '.' for share classes (e.g. BF.A); yfinance needs '-'
    # (confirmed directly against the real API -- the dotted form returns
    # "possibly delisted", the hyphenated one returns real data).
    assert _to_yfinance_symbol("BF.A") == "BF-A"
    assert _to_yfinance_symbol("AAPL") == "AAPL"  # no dot, unaffected


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_dotted_ticker_is_translated_for_the_api_call_but_stored_under_original(mock_download, conn):
    db.upsert_tickers(
        conn,
        pd.DataFrame(
            [("BF.A", "Brown-Forman Class A", "CS", True, None)],
            columns=["ticker", "name", "type", "active", "delisted_utc"],
        ),
    )
    # Simulate real yfinance behavior: the response is keyed by the
    # hyphenated symbol we called it with, not the original dotted ticker.
    mock_download.return_value = _multi_ticker_frame(
        {"AAPL": 100.0, "MSFT": 200.0, "BF-A": 50.0}, ["2024-01-01"]
    )

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", batch_size=50, as_of=pd.Timestamp("2024-02-01"))

    called_tickers = mock_download.call_args[0][0]
    assert "BF-A" in called_tickers
    assert "BF.A" not in called_tickers

    result = db.read_bars(conn, "bars_1d", ticker="BF.A", source=db.YFINANCE)
    assert len(result) == 1
    assert result.iloc[0]["close"] == 50.0

    status = conn.execute(
        "SELECT status FROM fetch_jobs WHERE job_type = ? AND key = ?", (JOB_TYPE, "BF.A")
    ).fetchone()[0]
    assert status == "success"


@patch("src.data_processing.bulk_yfinance_ingest.yf.download")
def test_end_date_is_shifted_to_be_inclusive(mock_download, conn):
    # yfinance's own `end` is exclusive; this module shifts it by a day so
    # callers get the same inclusive-end semantics as Polygon.
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0, "MSFT": 200.0}, ["2024-03-10"])

    backfill_yfinance_daily(conn, "2024-03-01", "2024-03-10", batch_size=50, as_of=pd.Timestamp("2024-04-01"))

    _, kwargs = mock_download.call_args
    assert kwargs["end"] == "2024-03-11"
