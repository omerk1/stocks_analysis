import argparse
import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.data_processing.yfinance_client import YFinanceClient
from src.foundation.utils.config_loader import load_config

JOB_TYPE = "sector"


def backfill_sectors(
    client: YFinanceClient,
    conn: sqlite3.Connection,
    tickers: list[str],
    retry_backoff_seconds: float = 5.0,
) -> None:
    """Backfill `ticker_sector` for every ticker in `tickers` from yfinance's
    `.info` (`YFinanceClient.get_sector_info` -- one call per ticker, no bulk
    endpoint). Resumable per ticker via `fetch_jobs`, same pattern as
    `bulk_splits_ingest.py`/`bulk_ticker_metadata_ingest.py` -- a re-run only
    retries tickers missing or previously failed.

    Built so `relative_strength` can look up a ticker's sector -> sector-ETF
    benchmark locally instead of making a live call per ticker at compute
    time.
    """
    pending = db.pending_keys(conn, JOB_TYPE, tickers)

    for ticker in pending:
        ok, info, error = attempt_with_limited_retries(
            lambda t=ticker: client.get_sector_info(t),
            backoff_seconds=retry_backoff_seconds,
        )
        if not ok:
            db.record_job_result(conn, JOB_TYPE, ticker, "failed", error)
            print(f"{ticker}: FAILED ({error})")
            continue

        row = pd.DataFrame([info], columns=["ticker", "sector", "industry"])
        db.upsert_ticker_sector(conn, row)
        db.record_job_result(conn, JOB_TYPE, ticker, "success")
        print(f"{ticker}: stored (sector={info['sector']})")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-backfill GICS-style sector/industry classification from "
        "yfinance -- one call per ticker"
    )
    parser.add_argument(
        "--indices", default="sp500,nasdaq100",
        help="Comma-separated index_membership index_names to source the ticker universe from",
    )
    args = parser.parse_args()

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

    client = YFinanceClient()
    backfill_sectors(client, conn, tickers)

    conn.close()


if __name__ == "__main__":
    main()
