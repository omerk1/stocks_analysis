import argparse
import sqlite3

from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing.polygon_client import PolygonClient
from src.foundation.data_processing.yfinance_client import YFinanceClient
from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.utils.config_loader import load_config

JOB_TYPE = "splits"
# Separate fetch_jobs key per source, so a finished yfinance pass never makes
# a later Polygon pass skip tickers (or vice versa) -- the `splits` table
# already keys rows by source, and resumability has to match.
JOB_TYPE_YFINANCE = "splits_yfinance"
_JOB_TYPES = {db.POLYGON: JOB_TYPE, db.YFINANCE: JOB_TYPE_YFINANCE}


def backfill_splits(
    client: PolygonClient,
    conn: sqlite3.Connection,
    tickers: list[str],
    retry_backoff_seconds: float = 5.0,
    source: str = db.POLYGON,
) -> None:
    """Backfill `splits` for every ticker in `tickers` from Polygon's
    `/v3/reference/splits` (`PolygonClient.get_splits` -- one call per
    ticker, already returns its *entire* split history, no date-range
    looping needed). Resumable per ticker via `fetch_jobs`, same pattern as
    `bulk_shares_outstanding_ingest.py` -- a re-run only retries tickers
    missing or previously failed.

    Built so `market_cap.py`'s `historical_market_cap` can be given a
    pre-fetched local `splits` frame instead of making a live, rate-limited
    (Polygon free tier: 5 calls/min) call every invocation -- at ~1,400
    tickers (S&P 500 + Nasdaq-100, all-time), that's the difference between
    one ~4.7-hour backfill and paying that same cost on every future run.
    """
    job_type = _JOB_TYPES[source]
    pending = db.pending_keys(conn, job_type, tickers)

    for ticker in pending:
        ok, splits, error = attempt_with_limited_retries(
            lambda t=ticker: client.get_splits(t),
            backoff_seconds=retry_backoff_seconds,
        )
        if not ok:
            db.record_job_result(conn, job_type, ticker, "failed", error)
            print(f"{ticker}: FAILED ({error})")
            continue

        db.upsert_splits(conn, ticker, source, splits)
        db.record_job_result(conn, job_type, ticker, "success")
        print(f"{ticker}: stored ({len(splits)} splits)")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-backfill stock-split history -- one call per ticker"
    )
    parser.add_argument(
        "--source", default=db.POLYGON, choices=[db.POLYGON, db.YFINANCE],
        help="polygon (default; free tier is 5 calls/min) or yfinance (no hard cap, and the "
        "same source as bars_1d, so its splits match the bars' own adjustment)",
    )
    universe = parser.add_mutually_exclusive_group()
    universe.add_argument(
        "--indices", default="sp500,nasdaq100",
        help="Comma-separated index_membership index_names to source the ticker universe from",
    )
    universe.add_argument(
        "--all-active", action="store_true",
        help="Every active common stock in the tickers reference table instead of --indices",
    )
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    tickers = db.read_universe_tickers(conn, None if args.all_active else args.indices)

    client = PolygonClient() if args.source == db.POLYGON else YFinanceClient()
    backfill_splits(client, conn, tickers, source=args.source)

    conn.close()


if __name__ == "__main__":
    main()
