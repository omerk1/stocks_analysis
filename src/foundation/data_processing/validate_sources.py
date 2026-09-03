import argparse
import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.utils.config_loader import load_config


def compare_stored_daily_bars(
    conn: sqlite3.Connection,
    ticker: str,
    source_a: str = db.POLYGON,
    source_b: str = db.YFINANCE,
    start: str | None = None,
    end: str | None = None,
    tolerance: float = 0.01,
) -> pd.DataFrame:
    """Compare two already-stored sources' daily closes for `ticker`.

    An on-demand query over data already fetched by `fetch_data.py` for both
    sources -- doesn't hit either API itself. Returns only the dates where the
    two sources disagree by more than `tolerance` (relative, default 1%); an
    empty result means everything matched within tolerance. Only dates present
    in both sources are compared -- a date missing from one source entirely is
    not flagged here.
    """
    bars_a = db.read_bars(conn, "bars_1d", ticker=ticker, source=source_a, start=start, end=end)
    bars_b = db.read_bars(conn, "bars_1d", ticker=ticker, source=source_b, start=start, end=end)

    col_a, col_b = f"close_{source_a}", f"close_{source_b}"
    merged = bars_a[["close"]].join(bars_b[["close"]], lsuffix=f"_{source_a}", rsuffix=f"_{source_b}", how="inner")
    merged["pct_diff"] = (merged[col_a] - merged[col_b]).abs() / merged[col_b]
    return merged[merged["pct_diff"] > tolerance]


def main():
    parser = argparse.ArgumentParser(
        description="Compare already-stored daily closes across two sources"
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--source-a", default=db.POLYGON)
    parser.add_argument("--source-b", default=db.YFINANCE)
    parser.add_argument("--tolerance", type=float, default=0.01)
    args = parser.parse_args()

    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    conn = db.get_connection(db_path)

    discrepancies = compare_stored_daily_bars(
        conn,
        args.ticker,
        source_a=args.source_a,
        source_b=args.source_b,
        start=args.start,
        end=args.end,
        tolerance=args.tolerance,
    )
    if discrepancies.empty:
        print(f"{args.ticker}: no discrepancies beyond {args.tolerance:.2%} tolerance")
    else:
        print(discrepancies)

    conn.close()


if __name__ == "__main__":
    main()
