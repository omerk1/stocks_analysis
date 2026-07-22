import sqlite3
from pathlib import Path

import pandas as pd

# Table per timeframe, as opposed to one table with a timeframe discriminator
# column -- keeps each timeframe's row count and indexing independent, and
# matches how these are queried (always scoped to one timeframe at a time).
TABLES = ("bars_1d", "bars_1w", "bars_1mo", "bars_1h")

# Source names -- shared constants so callers don't hand-type strings that
# could typo-diverge (e.g. "yfinance" vs "y_finance") across modules.
POLYGON = "polygon"
YFINANCE = "yfinance"

BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "is_partial"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    ticker TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    is_partial INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ticker, timestamp, source)
);
"""


def default_db_path(raw_data_dir: str | Path) -> Path:
    return Path(raw_data_dir) / "market_data.sqlite"


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def create_tables(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        conn.execute(_SCHEMA.format(table=table))
    conn.commit()


def upsert_bars(
    conn: sqlite3.Connection, table: str, ticker: str, source: str, bars: pd.DataFrame
) -> None:
    """Insert or replace rows in `table` for `ticker`/`source`.

    `bars` must be indexed by timestamp with columns open/high/low/close/volume/is_partial.
    Existing rows sharing a (ticker, timestamp, source) key are overwritten -- this
    is how an in-progress (is_partial=1) period gets updated in place as new data
    arrives. Different sources for the same ticker/timestamp are independent rows,
    not a collision -- that's the whole point of keying on source too.
    """
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    if bars.empty:
        return

    rows = [
        (
            ticker,
            _serialize_timestamp(ts),
            source,
            _as_float(row.open),
            _as_float(row.high),
            _as_float(row.low),
            _as_float(row.close),
            _as_float(row.volume),
            int(row.is_partial),
        )
        for ts, row in bars.iterrows()
    ]

    conn.executemany(
        f"""
        INSERT OR REPLACE INTO {table}
            (ticker, timestamp, source, open, high, low, close, volume, is_partial)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_bars(
    conn: sqlite3.Connection,
    table: str,
    ticker: str | None = None,
    source: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Read bars from `table`, indexed by timestamp and sorted ascending.

    Includes a `ticker` and/or `source` column when that filter isn't specified
    (i.e. the read could span multiple tickers/sources). Leaving `source`
    unspecified with multiple sources present will interleave rows from
    different sources for the same ticker -- pass `source` explicitly for any
    read that needs a single continuous series (e.g. before resampling).
    """
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")

    query = f"SELECT * FROM {table} WHERE 1=1"
    params: list = []
    if ticker is not None:
        query += " AND ticker = ?"
        params.append(ticker)
    if source is not None:
        query += " AND source = ?"
        params.append(source)
    if start is not None:
        query += " AND timestamp >= ?"
        params.append(_serialize_timestamp(pd.Timestamp(start)))
    if end is not None:
        query += " AND timestamp <= ?"
        params.append(_serialize_timestamp(pd.Timestamp(end)))
    query += " ORDER BY timestamp ASC"

    df = pd.read_sql_query(query, conn, params=params, parse_dates=["timestamp"])
    df = df.set_index("timestamp")
    drop_columns = [col for col, filt in (("ticker", ticker), ("source", source)) if filt is not None]
    if drop_columns:
        df = df.drop(columns=drop_columns)
    return df


def _serialize_timestamp(ts: pd.Timestamp) -> str:
    return ts.isoformat()


def _as_float(value) -> float | None:
    """Coerce numpy scalar types (int64, float64, ...) to a native Python
    float/None. sqlite3 doesn't recognize numpy scalars as int/float/None and
    silently binds them as BLOBs via the buffer protocol instead of erroring,
    so this must run before every bind, not just for the "obviously numpy" columns.
    """
    if pd.isna(value):
        return None
    return float(value)
