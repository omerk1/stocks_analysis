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

# The single source of truth for "which tickers exist" -- price-data
# ingestion for any source reads this table rather than each maintaining its
# own ticker list. Includes inactive/delisted tickers (with delisted_utc) on
# purpose, to avoid survivorship bias.
_TICKERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    type TEXT,
    active INTEGER NOT NULL,
    delisted_utc TEXT,
    updated_at TEXT NOT NULL
);
"""

# Generic progress ledger for resumable bulk jobs -- e.g. job_type
# "polygon_grouped_daily" with key = date, or "yfinance_daily" with
# key = ticker. A re-run only needs to retry keys not marked 'success'
# (see pending_keys), instead of redoing completed work or looping
# indefinitely on a stuck item in place.
_FETCH_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetch_jobs (
    job_type TEXT NOT NULL,
    key TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_type, key)
);
"""


def default_db_path(raw_data_dir: str | Path) -> Path:
    return Path(raw_data_dir) / "market_data.sqlite"


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def create_tables(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        conn.execute(_SCHEMA.format(table=table))
    conn.execute(_TICKERS_SCHEMA)
    conn.execute(_FETCH_JOBS_SCHEMA)
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


def upsert_bars_bulk(conn: sqlite3.Connection, table: str, source: str, bars: pd.DataFrame) -> None:
    """Insert or replace rows for *many tickers* in one commit.

    `bars` must have columns: ticker, timestamp, open, high, low, close,
    volume, is_partial (a plain DataFrame, not indexed by timestamp like
    `upsert_bars` expects -- there's no single "the ticker" here). For bulk
    ingestion (e.g. one grouped-daily response covering thousands of tickers)
    -- calling `upsert_bars` once per ticker would mean thousands of
    individual commits; this does it in one.
    """
    if table not in TABLES:
        raise ValueError(f"Unknown table: {table}")
    if bars.empty:
        return

    rows = [
        (
            row.ticker,
            _serialize_timestamp(pd.Timestamp(row.timestamp)),
            source,
            _as_float(row.open),
            _as_float(row.high),
            _as_float(row.low),
            _as_float(row.close),
            _as_float(row.volume),
            int(row.is_partial),
        )
        for row in bars.itertuples()
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


def upsert_tickers(conn: sqlite3.Connection, tickers: pd.DataFrame) -> None:
    """Insert or replace rows in the `tickers` reference table.

    `tickers` must have columns: ticker, name, type, active, delisted_utc.
    """
    if tickers.empty:
        return

    now = pd.Timestamp.now("UTC").isoformat()
    rows = [
        (row.ticker, row.name, row.type, int(row.active), row.delisted_utc, now)
        for row in tickers.itertuples()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO tickers (ticker, name, type, active, delisted_utc, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_tickers(
    conn: sqlite3.Connection, type_: str | None = None, active: bool | None = None
) -> pd.DataFrame:
    query = "SELECT * FROM tickers WHERE 1=1"
    params: list = []
    if type_ is not None:
        query += " AND type = ?"
        params.append(type_)
    if active is not None:
        query += " AND active = ?"
        params.append(int(active))
    return pd.read_sql_query(query, conn, params=params)


def record_job_result(
    conn: sqlite3.Connection, job_type: str, key: str, status: str, error: str | None = None
) -> None:
    """Record a bulk-job attempt's outcome for (`job_type`, `key`). `status`
    is "success" or "failed". Attempt count accumulates across calls so it
    reflects total attempts over the job's lifetime, not just this call.
    """
    now = pd.Timestamp.now("UTC").isoformat()
    existing = conn.execute(
        "SELECT attempts FROM fetch_jobs WHERE job_type = ? AND key = ?", (job_type, key)
    ).fetchone()
    attempts = (existing[0] if existing else 0) + 1
    conn.execute(
        """
        INSERT OR REPLACE INTO fetch_jobs (job_type, key, status, attempts, last_error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_type, key, status, attempts, error, now),
    )
    conn.commit()


def pending_keys(conn: sqlite3.Connection, job_type: str, all_keys: list[str]) -> list[str]:
    """Of `all_keys`, return those not yet marked 'success' for `job_type` --
    i.e. never attempted, or previously failed. Order is preserved from
    `all_keys`. This is what lets a re-run retry only misses instead of
    redoing completed work.
    """
    if not all_keys:
        return []
    placeholders = ",".join("?" for _ in all_keys)
    succeeded = {
        row[0]
        for row in conn.execute(
            f"""
            SELECT key FROM fetch_jobs
            WHERE job_type = ? AND status = 'success' AND key IN ({placeholders})
            """,
            (job_type, *all_keys),
        ).fetchall()
    }
    return [key for key in all_keys if key not in succeeded]


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
