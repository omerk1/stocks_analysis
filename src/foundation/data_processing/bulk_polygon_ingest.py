import argparse
import sqlite3
from datetime import date

import pandas as pd
from dotenv import load_dotenv

from src.foundation.data_processing import db
from src.foundation.data_processing.polygon_client import PolygonClient
from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.utils.config_loader import load_config

JOB_TYPE = "polygon_grouped_daily"


def backfill_grouped_daily(
    client: PolygonClient,
    conn: sqlite3.Connection,
    start: str,
    end: str,
    as_of: pd.Timestamp | None = None,
    retry_backoff_seconds: float = 5.0,
) -> None:
    """Bulk-ingest daily bars for the whole market, one grouped-daily call per
    trading day, filtered down to tickers in the `tickers` reference table
    (populated separately by ticker_universe.py -- run that first).

    Resumable: each date's outcome is recorded in fetch_jobs, so a re-run
    only retries dates that are missing or previously failed, not the whole
    range. A failing date gets a couple of quick retries (attempt_with_limited_retries)
    and then is marked failed and skipped -- not retried indefinitely in
    place, so one bad day can't stall an hours-long backfill. Weekends/
    holidays just come back with 0 tickers, which is a normal success, not a
    failure.
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())

    tickers = db.read_tickers(conn, type_="CS")
    if tickers.empty:
        raise RuntimeError(
            "No tickers in the reference table -- run ticker_universe.py first "
            "to populate it before bulk ingestion."
        )
    valid_tickers = set(tickers["ticker"])

    all_dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]
    pending = db.pending_keys(conn, JOB_TYPE, all_dates)

    for day in pending:
        ok, bars, error = attempt_with_limited_retries(
            lambda d=day: client.get_grouped_daily_bars(d), backoff_seconds=retry_backoff_seconds
        )
        if not ok:
            db.record_job_result(conn, JOB_TYPE, day, "failed", error)
            print(f"{day}: FAILED ({error})")
            continue

        bars = bars[bars["ticker"].isin(valid_tickers)].copy()
        bars["timestamp"] = pd.Timestamp(day)
        bars["is_partial"] = int(pd.Timestamp(day).normalize() >= as_of.normalize())
        db.upsert_bars_bulk(conn, "bars_1d", db.POLYGON, bars)
        db.record_job_result(conn, JOB_TYPE, day, "success")
        print(f"{day}: stored {len(bars)} tickers")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-ingest daily bars for the whole market from Polygon (grouped-daily, one call/day)"
    )
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    client = PolygonClient()
    backfill_grouped_daily(client, conn, args.start, args.end)

    conn.close()


if __name__ == "__main__":
    main()
