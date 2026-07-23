import argparse
import sqlite3
from datetime import date

import pandas as pd
import yfinance as yf

from src.data_processing import db
from src.data_processing.retry import attempt_with_limited_retries
from src.utils.config_loader import load_config

JOB_TYPE = "yfinance_daily"


def _fetch_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    # yfinance's `end` is exclusive (confirmed directly against the real API --
    # see yfinance_client.py's _fetch for the same fix), unlike Polygon's
    # inclusive end. Shifted by one day here so callers of this module get the
    # same inclusive-end semantics as bulk_polygon_ingest.py.
    end_inclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return yf.download(
        tickers, start=start, end=end_inclusive, threads=True, progress=False, group_by="ticker"
    )


def _extract_ticker_frame(batch_result: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """`_fetch_batch` always passes a *list* to yf.download, even for a single
    ticker -- and a list-of-one still comes back MultiIndex-columned by
    ticker (confirmed directly against the real API; this is different from
    yf.download('AAPL', ...) with a bare string, which returns a plain frame
    -- that shortcut doesn't apply here since we never call it that way)."""
    frame = batch_result[ticker]
    frame = frame.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    return frame.dropna(how="all")


def backfill_yfinance_daily(
    conn: sqlite3.Connection,
    start: str,
    end: str,
    batch_size: int = 50,
    as_of: pd.Timestamp | None = None,
    retry_backoff_seconds: float = 5.0,
) -> None:
    """Bulk-ingest daily bars for every ticker in the reference table from
    yfinance, batched (yf.download has no official rate limit to design a
    pace around, but batching + a per-batch retry cap keeps a bad batch from
    stalling the whole run).

    Resumable per *ticker*, not per batch -- if 3 of 50 tickers in a batch
    come back empty, only those 3 are marked failed and retried on a later
    run; the other 47 aren't redone. A ticker with no data in the response
    (rather than a request-level failure) is also treated as a miss to
    retry later, not a hard error.
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())

    tickers = db.read_tickers(conn, type_="CS")
    if tickers.empty:
        raise RuntimeError(
            "No tickers in the reference table -- run ticker_universe.py first "
            "to populate it before bulk ingestion."
        )
    all_tickers = sorted(tickers["ticker"])
    pending = db.pending_keys(conn, JOB_TYPE, all_tickers)

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        ok, result, error = attempt_with_limited_retries(
            lambda b=batch: _fetch_batch(b, start, end), backoff_seconds=retry_backoff_seconds
        )
        if not ok:
            for ticker in batch:
                db.record_job_result(conn, JOB_TYPE, ticker, "failed", error)
            print(f"batch of {len(batch)} starting {batch[0]}: FAILED entirely ({error})")
            continue

        for ticker in batch:
            try:
                ticker_bars = _extract_ticker_frame(result, ticker)
            except (KeyError, TypeError) as e:
                db.record_job_result(conn, JOB_TYPE, ticker, "failed", f"no data returned: {e}")
                continue

            if ticker_bars.empty:
                db.record_job_result(conn, JOB_TYPE, ticker, "failed", "no data returned")
                continue

            if ticker_bars.index.tz is not None:
                ticker_bars.index = ticker_bars.index.tz_localize(None)
            ticker_bars["is_partial"] = (
                ticker_bars.index.normalize() >= as_of.normalize()
            ).astype(int)

            db.upsert_bars(conn, "bars_1d", ticker, db.YFINANCE, ticker_bars)
            db.record_job_result(conn, JOB_TYPE, ticker, "success")

        print(f"batch of {len(batch)} starting {batch[0]}: processed")


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-ingest daily bars for every reference ticker from yfinance"
    )
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    backfill_yfinance_daily(conn, args.start, args.end, batch_size=args.batch_size)

    conn.close()


if __name__ == "__main__":
    main()
