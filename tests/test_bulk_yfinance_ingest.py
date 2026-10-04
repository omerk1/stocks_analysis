from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.foundation.data_processing.bulk_yfinance_ingest import (
    FULL_HISTORY_START, JOB_TYPE, backfill_yfinance_daily, update_split_only_incremental,
)
from src.foundation.data_processing.yfinance_client import to_yfinance_symbol


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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_resumable_skips_already_succeeded_tickers(mock_download, conn):
    db.record_job_result(conn, JOB_TYPE, "AAPL", "success")
    mock_download.return_value = _multi_ticker_frame({"MSFT": 200.0}, ["2024-01-01"])

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", batch_size=50, as_of=pd.Timestamp("2024-02-01"))

    mock_download.assert_called_once_with(
        ["MSFT"], start="2024-01-01", end="2024-01-02", threads=True, progress=False, group_by="ticker", auto_adjust=True
    )


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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
        threads=True, progress=False, group_by="ticker", auto_adjust=True,
    )
    statuses = dict(
        conn.execute(
            "SELECT key, status FROM fetch_jobs WHERE job_type = ?", ("yfinance_daily_deep",)
        ).fetchall()
    )
    assert statuses == {"AAPL": "success", "MSFT": "success"}


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_tickers_param_restricts_scope_instead_of_reading_reference_table(mock_download, conn):
    # conn's reference table has AAPL and MSFT; restrict this run to AAPL only.
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0}, ["2024-01-01"])

    backfill_yfinance_daily(
        conn, "2024-01-01", "2024-01-01", batch_size=50,
        as_of=pd.Timestamp("2024-02-01"), tickers=["AAPL"],
    )

    mock_download.assert_called_once_with(
        ["AAPL"], start="2024-01-01", end="2024-01-02", threads=True, progress=False, group_by="ticker", auto_adjust=True
    )
    assert db.read_bars(conn, "bars_1d", ticker="MSFT", source=db.YFINANCE).empty


def test_tickers_param_does_not_require_reference_table_populated():
    empty_conn = db.get_connection(":memory:")
    db.create_tables(empty_conn)

    with patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download") as mock_download:
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
    assert to_yfinance_symbol("BF.A") == "BF-A"
    assert to_yfinance_symbol("AAPL") == "AAPL"  # no dot, unaffected


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
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


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_end_date_is_shifted_to_be_inclusive(mock_download, conn):
    # yfinance's own `end` is exclusive; this module shifts it by a day so
    # callers get the same inclusive-end semantics as Polygon.
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0, "MSFT": 200.0}, ["2024-03-10"])

    backfill_yfinance_daily(conn, "2024-03-01", "2024-03-10", batch_size=50, as_of=pd.Timestamp("2024-04-01"))

    _, kwargs = mock_download.call_args
    assert kwargs["end"] == "2024-03-11"


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_split_only_requests_unadjusted_closes_and_stores_them_under_their_own_source(mock_download, conn):
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0, "MSFT": 200.0}, ["2024-01-01"])

    backfill_yfinance_daily(
        conn, "2024-01-01", "2024-01-01", as_of=pd.Timestamp("2024-02-01"),
        job_type="yfinance_daily_split_only", split_only=True,
    )

    assert mock_download.call_args.kwargs["auto_adjust"] is False
    assert len(db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE_SPLIT_ONLY)) == 1
    assert db.read_bars(conn, "bars_1d", ticker="AAPL", source=db.YFINANCE).empty


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_default_run_keeps_fully_adjusted_closes(mock_download, conn):
    mock_download.return_value = _multi_ticker_frame({"AAPL": 100.0, "MSFT": 200.0}, ["2024-01-01"])

    backfill_yfinance_daily(conn, "2024-01-01", "2024-01-01", as_of=pd.Timestamp("2024-02-01"))

    assert mock_download.call_args.kwargs["auto_adjust"] is True


# --- incremental split-only updates -----------------------------------------

def _store_split_only(conn, ticker, closes: dict):
    c = pd.Series(list(closes.values()), index=pd.DatetimeIndex(list(closes)), dtype=float)
    bars = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0, "is_partial": 0})
    db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE_SPLIT_ONLY, bars)


def _frame(ticker_closes: dict) -> pd.DataFrame:
    """MultiIndex batch frame like yf.download's: ticker -> {date: close}."""
    index = pd.DatetimeIndex(sorted({d for closes in ticker_closes.values() for d in closes}))
    data = {}
    for ticker, closes in ticker_closes.items():
        close = pd.Series({pd.Timestamp(d): c for d, c in closes.items()}, dtype=float).reindex(index)
        data[(ticker, "Open")] = close
        data[(ticker, "High")] = close + 1
        data[(ticker, "Low")] = close - 1
        data[(ticker, "Close")] = close
        data[(ticker, "Volume")] = close * 0 + 1000
    return pd.DataFrame(data, index=index)


def _closes(conn, ticker):
    bars = db.read_bars(conn, "bars_1d", ticker=ticker, source=db.YFINANCE_SPLIT_ONLY)
    return {ts.strftime("%Y-%m-%d"): c for ts, c in bars["close"].items()}


AS_OF = pd.Timestamp("2024-01-20")
STORED = {"2024-01-08": 10.0, "2024-01-09": 11.0, "2024-01-10": 12.0}


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_appends_new_days_when_overlap_matches(mock_download, conn):
    _store_split_only(conn, "AAPL", STORED)
    mock_download.return_value = _frame({"AAPL": {"2024-01-09": 11.0, "2024-01-10": 12.0, "2024-01-11": 13.0}})

    report = update_split_only_incremental(conn, as_of=AS_OF, tickers=["AAPL"])

    assert (report["appended"], report["refetched"], report["failed"]) == (1, 0, 0)
    mock_download.assert_called_once()
    assert mock_download.call_args.kwargs["start"] == "2023-12-31"  # last stored bar - overlap
    assert mock_download.call_args.kwargs["auto_adjust"] is False
    assert _closes(conn, "AAPL") == {**STORED, "2024-01-11": 13.0}


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_refetches_full_history_when_overlap_changed(mock_download, conn):
    # A 2-for-1 split since the last fetch halves every earlier split-only close.
    _store_split_only(conn, "AAPL", STORED)
    mock_download.side_effect = [
        _frame({"AAPL": {"2024-01-09": 5.5, "2024-01-10": 6.0, "2024-01-11": 6.5}}),
        _frame({"AAPL": {"2024-01-08": 5.0, "2024-01-09": 5.5, "2024-01-10": 6.0, "2024-01-11": 6.5}}),
    ]

    report = update_split_only_incremental(conn, as_of=AS_OF, tickers=["AAPL"])

    assert (report["refetched"], report["appended"]) == (1, 0)
    assert "overlap closes differ" in report["refetch_reasons"]["AAPL"]
    assert mock_download.call_args_list[1].kwargs["start"] == FULL_HISTORY_START
    assert _closes(conn, "AAPL") == {"2024-01-08": 5.0, "2024-01-09": 5.5, "2024-01-10": 6.0, "2024-01-11": 6.5}


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_refuses_a_refetch_shorter_than_stored_history(mock_download, conn):
    # Yahoo truncating old history must not delete what's stored.
    _store_split_only(conn, "AAPL", STORED)
    mock_download.side_effect = [
        _frame({"AAPL": {"2024-01-10": 6.0, "2024-01-11": 6.5}}),
        _frame({"AAPL": {"2024-01-19": 6.0}}),
    ]

    report = update_split_only_incremental(conn, as_of=AS_OF, tickers=["AAPL"])

    assert report["failed"] == 1 and "not replaced" in report["failures"]["AAPL"]
    assert _closes(conn, "AAPL") == STORED


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_full_fetch_for_ticker_without_stored_bars(mock_download, conn):
    mock_download.return_value = _frame({"MSFT": {"2024-01-10": 20.0, "2024-01-11": 21.0}})

    report = update_split_only_incremental(conn, as_of=AS_OF, tickers=["MSFT"])

    assert report["refetched"] == 1 and report["refetch_reasons"]["MSFT"] == "no stored bars"
    mock_download.assert_called_once()
    assert mock_download.call_args.kwargs["start"] == FULL_HISTORY_START
    assert _closes(conn, "MSFT") == {"2024-01-10": 20.0, "2024-01-11": 21.0}


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_no_new_data(mock_download, conn):
    _store_split_only(conn, "AAPL", STORED)
    mock_download.return_value = _frame({"AAPL": {"2024-01-09": 11.0, "2024-01-10": 12.0}})

    report = update_split_only_incremental(conn, as_of=AS_OF, tickers=["AAPL"])

    assert (report["no_new_data"], report["appended"], report["refetched"]) == (1, 0, 0)
    assert conn.execute("SELECT status FROM fetch_jobs WHERE key = 'AAPL'").fetchone()[0] == "success"


@patch("src.foundation.data_processing.bulk_yfinance_ingest.yf.download")
def test_incremental_groups_tickers_by_fetch_window_over_the_default_universe(mock_download, conn):
    # Default universe: tickers with split-only bars plus active CS tickers (MSFT has none -> full fetch).
    _store_split_only(conn, "AAPL", STORED)
    _store_split_only(conn, "OLD", {"2024-01-02": 7.0})
    mock_download.side_effect = [
        _frame({"OLD": {"2024-01-02": 7.0}}),                        # window from OLD's last bar
        _frame({"AAPL": {"2024-01-10": 12.0, "2024-01-11": 13.0}}),  # window from AAPL's last bar
        _frame({"MSFT": {"2024-01-11": 21.0}}),                      # full fetch
    ]

    report = update_split_only_incremental(conn, as_of=AS_OF)

    starts = [c.kwargs["start"] for c in mock_download.call_args_list]
    assert starts == ["2023-12-23", "2023-12-31", FULL_HISTORY_START]
    assert (report["appended"], report["no_new_data"], report["refetched"]) == (1, 1, 1)
