import argparse
import sqlite3

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.data_processing.yfinance_client import YFinanceClient
from src.foundation.utils.config_loader import load_config

JOB_TYPE = "shares_outstanding"


def backfill_shares_outstanding(
    client: YFinanceClient,
    conn: sqlite3.Connection,
    start: str,
    end: str,
    retry_backoff_seconds: float = 5.0,
    tickers: list[str] | None = None,
) -> None:
    """Backfill `shares_outstanding` from yfinance's `get_shares_full` (see
    `YFinanceClient.get_shares_outstanding` -- Polygon's equivalent
    endpoint returned NOT_AUTHORIZED on our current plan, so yfinance is
    the only source wired up for this).

    One call per ticker, whatever history it returns (real coverage starts
    anywhere from ~2015 to ~2017+ depending on the ticker -- yfinance's own
    floor, not `start`). Resumable per ticker via fetch_jobs, same pattern
    as bulk_ticker_metadata_ingest.py -- a re-run only retries tickers
    missing or previously failed. `start`/`end` bound the request but a
    ticker's own available range may be narrower.

    `tickers`, if given, is the exact universe to backfill (e.g.
    `db.read_index_universe_tickers(conn, ["sp500", "nasdaq100"])` -- see
    `main`'s `--indices` option). Omitted (the default), falls back to
    every active common stock in the `tickers` reference table, matching
    how the deep-history daily bar backfill (Done #12) was actually run in
    practice -- broadening to delisted tickers (real, meaningful history in
    principle, unlike a delisted ticker's *current* market cap) is a
    possible future extension, not attempted here.
    """
    if tickers is None:
        ticker_rows = db.read_tickers(conn, type_="CS", active=True)
        if ticker_rows.empty:
            raise RuntimeError(
                "No tickers in the reference table -- run ticker_universe.py first "
                "to populate it before bulk ingestion."
            )
        tickers = sorted(ticker_rows["ticker"])
    pending = db.pending_keys(conn, JOB_TYPE, tickers)

    for ticker in pending:
        ok, shares, error = attempt_with_limited_retries(
            lambda t=ticker: client.get_shares_outstanding(t, start, end),
            backoff_seconds=retry_backoff_seconds,
        )
        if not ok:
            db.record_job_result(conn, JOB_TYPE, ticker, "failed", error)
            print(f"{ticker}: FAILED ({error})")
            continue

        db.upsert_shares_outstanding(conn, ticker, db.YFINANCE, shares)
        db.record_job_result(conn, JOB_TYPE, ticker, "success")
        print(f"{ticker}: stored ({len(shares)} points)")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-backfill historical shares-outstanding time series from yfinance -- "
        "one call per active ticker"
    )
    parser.add_argument("--start", default="2010-01-01", help="Requested start date (yfinance's own "
        "actual coverage floor per ticker may be later)")
    parser.add_argument("--end", default=None, help="Requested end date (default: today)")
    parser.add_argument(
        "--indices", default=None,
        help="Comma-separated index_membership index_names (e.g. 'sp500,nasdaq100') to scope the "
        "ticker universe to, instead of every active common stock in the tickers reference table",
    )
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    end = args.end or pd.Timestamp.today().strftime("%Y-%m-%d")
    tickers = (
        db.read_index_universe_tickers(conn, [s.strip() for s in args.indices.split(",")])
        if args.indices else None
    )

    client = YFinanceClient()
    backfill_shares_outstanding(client, conn, args.start, end, tickers=tickers)

    conn.close()


if __name__ == "__main__":
    main()
