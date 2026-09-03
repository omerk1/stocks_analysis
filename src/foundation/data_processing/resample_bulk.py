import argparse
import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing.fetch_data import resample_and_store
from src.foundation.utils.config_loader import load_config


def resample_all_tickers(conn: sqlite3.Connection, source: str, as_of: pd.Timestamp | None = None) -> None:
    """Recompute weekly/monthly bars for every ticker with stored daily bars
    for `source`. Pure computation over already-stored data -- no API calls,
    so no rate limit applies; this is the step that follows a bulk daily
    ingestion (which stores many tickers' rows per call but doesn't resample
    them itself).
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.today()

    tickers = db.read_bars(conn, "bars_1d", source=source)["ticker"].unique()
    for ticker in tickers:
        resample_and_store(conn, ticker, source, as_of)


def main():
    parser = argparse.ArgumentParser(
        description="Recompute weekly/monthly bars for every ticker with stored daily bars"
    )
    parser.add_argument("--source", required=True, choices=[db.POLYGON, db.YFINANCE])
    args = parser.parse_args()

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)

    tickers = db.read_bars(conn, "bars_1d", source=args.source)["ticker"].unique()
    print(f"Resampling {len(tickers)} tickers (source={args.source})...")
    resample_all_tickers(conn, args.source)
    print("Done.")

    conn.close()


if __name__ == "__main__":
    main()
