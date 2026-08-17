import argparse
import sqlite3

from dotenv import load_dotenv

from src.data_processing import db
from src.data_processing.polygon_client import PolygonClient
from src.data_processing.retry import attempt_with_limited_retries
from src.utils.config_loader import load_config

JOB_TYPE = "splits"


def backfill_splits(
    client: PolygonClient,
    conn: sqlite3.Connection,
    tickers: list[str],
    retry_backoff_seconds: float = 5.0,
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
    pending = db.pending_keys(conn, JOB_TYPE, tickers)

    for ticker in pending:
        ok, splits, error = attempt_with_limited_retries(
            lambda t=ticker: client.get_splits(t),
            backoff_seconds=retry_backoff_seconds,
        )
        if not ok:
            db.record_job_result(conn, JOB_TYPE, ticker, "failed", error)
            print(f"{ticker}: FAILED ({error})")
            continue

        db.upsert_splits(conn, ticker, db.POLYGON, splits)
        db.record_job_result(conn, JOB_TYPE, ticker, "success")
        print(f"{ticker}: stored ({len(splits)} splits)")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-backfill stock-split history from Polygon -- one call per ticker"
    )
    parser.add_argument(
        "--indices", default="sp500,nasdaq100",
        help="Comma-separated index_membership index_names to source the ticker universe from",
    )
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    index_names = [s.strip() for s in args.indices.split(",")]
    tickers = db.read_index_universe_tickers(conn, index_names)
    if not tickers:
        raise RuntimeError(
            f"No tickers found in index_membership for {index_names} -- "
            "run index_membership.refresh_index_membership first."
        )

    client = PolygonClient()
    backfill_splits(client, conn, tickers)

    conn.close()


if __name__ == "__main__":
    main()
