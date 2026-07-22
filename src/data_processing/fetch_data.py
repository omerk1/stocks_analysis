import argparse
import sqlite3
from datetime import date

import pandas as pd
from dotenv import load_dotenv

from src.data_processing import db, resample
from src.data_processing.polygon_client import PolygonClient
from src.data_processing.yfinance_client import YFinanceClient
from src.utils.config_loader import load_config

_CLIENTS = {
    db.POLYGON: PolygonClient,
    db.YFINANCE: YFinanceClient,
}


def mark_partial(daily_bars: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Flag same-day-or-later bars as partial.

    A source may return an up-to-the-moment OHLC for a trading day that hasn't
    closed yet, not a finalized bar -- this is a same-date heuristic (it
    doesn't know the actual market close time), so a bar fetched right after
    close on its own day will still be marked partial until the next run.
    """
    df = daily_bars.copy()
    df["is_partial"] = (df.index.normalize() >= as_of.normalize()).astype(int)
    return df


def fetch_ticker(
    client: PolygonClient | YFinanceClient,
    source: str,
    ticker: str,
    start: str,
    end: str,
    conn: sqlite3.Connection,
    as_of: pd.Timestamp | None = None,
) -> None:
    """Fetch daily bars for `ticker` from `source`, store them, and recompute
    that source's weekly/monthly bars.

    Weekly/monthly are recomputed from the *entire* stored daily history for
    the ticker+source, not just the newly fetched range -- resampling only the
    new range would miss earlier days belonging to the same still-open
    week/month. Resampling reads back only this source's rows -- reading
    across sources would interleave two independent daily series into one
    resample, which isn't meaningful.
    """
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(date.today())

    new_daily = client.get_daily_bars(ticker, start, end)
    new_daily = mark_partial(new_daily, as_of)
    db.upsert_bars(conn, "bars_1d", ticker, source, new_daily)

    all_daily = db.read_bars(conn, "bars_1d", ticker=ticker, source=source)
    weekly = resample.to_weekly(all_daily, as_of=as_of)
    monthly = resample.to_monthly(all_daily, as_of=as_of)
    db.upsert_bars(conn, "bars_1w", ticker, source, weekly)
    db.upsert_bars(conn, "bars_1mo", ticker, source, monthly)


def main():
    parser = argparse.ArgumentParser(description="Fetch OHLCV bars into SQLite")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD")
    parser.add_argument(
        "--source", choices=sorted(_CLIENTS), default=db.POLYGON, help="Data source (default: polygon)"
    )
    args = parser.parse_args()

    load_dotenv()
    config = load_config()
    db_path = db.default_db_path(config.data_paths.raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = db.get_connection(db_path)
    db.create_tables(conn)

    client = _CLIENTS[args.source]()
    for ticker in args.tickers.split(","):
        ticker = ticker.strip().upper()
        fetch_ticker(client, args.source, ticker, args.start, args.end, conn)
        print(f"{ticker}: stored in {db_path} (source={args.source})")

    conn.close()


if __name__ == "__main__":
    main()
