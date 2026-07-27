import argparse
import sqlite3

import pandas as pd
from dotenv import load_dotenv

from src.data_processing import db
from src.data_processing.polygon_client import PolygonClient
from src.data_processing.retry import attempt_with_limited_retries
from src.utils.config_loader import load_config

JOB_TYPE = "ticker_metadata"

_METADATA_COLUMNS = [
    "ticker",
    "market_cap",
    "sic_code",
    "sic_description",
    "share_class_shares_outstanding",
    "weighted_shares_outstanding",
    "total_employees",
    "primary_exchange",
    "list_date",
]


def backfill_ticker_metadata(
    client: PolygonClient,
    conn: sqlite3.Connection,
    retry_backoff_seconds: float = 5.0,
) -> None:
    """Refresh `ticker_metadata` for every active common stock in the
    `tickers` reference table (populated separately by ticker_universe.py --
    run that first).

    One `get_ticker_details` call per ticker -- there's no bulk endpoint for
    this data, unlike bars. Resumable per ticker via fetch_jobs, same as
    bulk_yfinance_ingest.py: a re-run only retries tickers missing or
    previously failed, and a failing ticker gets a couple of quick retries
    before being flagged and skipped rather than stalling the whole run.

    Scoped to active tickers only -- delisted tickers' current market
    cap/shares outstanding aren't a meaningful "current state" snapshot
    anyway.
    """
    tickers = db.read_tickers(conn, type_="CS", active=True)
    if tickers.empty:
        raise RuntimeError(
            "No tickers in the reference table -- run ticker_universe.py first "
            "to populate it before bulk ingestion."
        )
    all_tickers = sorted(tickers["ticker"])
    pending = db.pending_keys(conn, JOB_TYPE, all_tickers)

    for ticker in pending:
        ok, details, error = attempt_with_limited_retries(
            lambda t=ticker: client.get_ticker_details(t), backoff_seconds=retry_backoff_seconds
        )
        if not ok:
            db.record_job_result(conn, JOB_TYPE, ticker, "failed", error)
            print(f"{ticker}: FAILED ({error})")
            continue

        row = pd.DataFrame([details], columns=_METADATA_COLUMNS)
        db.upsert_ticker_metadata(conn, row)
        db.record_job_result(conn, JOB_TYPE, ticker, "success")
        print(f"{ticker}: stored")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-refresh per-ticker reference metadata (market cap, SIC industry, "
        "shares outstanding, ...) from Polygon -- one call per active ticker"
    )
    parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    client = PolygonClient()
    backfill_ticker_metadata(client, conn)

    conn.close()


if __name__ == "__main__":
    main()
