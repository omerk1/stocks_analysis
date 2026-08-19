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
FRED = "fred"

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

# Point-in-time index/composite membership (e.g. "which tickers were in the
# S&P 500 on 2020-06-01"). Each row is a contiguous membership interval, not a
# per-day snapshot -- start_date/end_date bracket when a ticker was a member
# (end_date NULL means still current). A ticker can have multiple rows for the
# same index if it left and later rejoined.
_INDEX_MEMBERSHIP_SCHEMA = """
CREATE TABLE IF NOT EXISTS index_membership (
    index_name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    PRIMARY KEY (index_name, ticker, start_date)
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

# Point-in-time snapshot of per-ticker reference metadata (Polygon's
# get_ticker_details -- the only endpoint with market cap/SIC classification,
# and it's per-ticker with no bulk equivalent). One row per ticker, overwritten
# on each refresh -- this is "current state", not a history of past values.
_TICKER_METADATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker TEXT PRIMARY KEY,
    market_cap REAL,
    sic_code TEXT,
    sic_description TEXT,
    share_class_shares_outstanding REAL,
    weighted_shares_outstanding REAL,
    total_employees REAL,
    primary_exchange TEXT,
    list_date TEXT,
    updated_at TEXT NOT NULL
);
"""

# Real historical time series, unlike ticker_metadata above -- yfinance's
# get_shares_full(ticker, start, end) returns actual point-in-time share
# counts (from real filing dates), not just a current snapshot. Deliberately
# NOT split-adjusted to match bars_1d's adjusted price convention -- these are
# the raw counts as reported, so a naive shares_outstanding x price market-cap
# calculation will be wrong across a stock split unless the caller explicitly
# reconciles the two conventions first (see yfinance_client.py's docstring for
# the real AAPL example that surfaced this: a ~4x jump in raw share count
# lands exactly on the 2020-08-31 4-for-1 split date). Source is part of the
# key even though only yfinance is wired up today -- consistent with every
# other per-source table in this file.
_SHARES_OUTSTANDING_SCHEMA = """
CREATE TABLE IF NOT EXISTS shares_outstanding (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    shares_outstanding REAL,
    source TEXT NOT NULL,
    PRIMARY KEY (ticker, date, source)
);
"""

# Local cache of a ticker's stock-split history (PolygonClient.get_splits) --
# built so market_cap.py's historical_market_cap can be given a pre-fetched
# splits frame instead of making a live, rate-limited (5/min free-tier) call
# every invocation. `source` included for consistency with every other table
# here even though Polygon is the only wired-up source today (same as
# macro_series always being source=FRED today).
_SPLITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS splits (
    ticker TEXT NOT NULL,
    execution_date TEXT NOT NULL,
    split_from REAL,
    split_to REAL,
    ratio REAL,
    source TEXT NOT NULL,
    PRIMARY KEY (ticker, execution_date, source)
);
"""

# Point-in-time snapshot of GICS-style sector/industry classification, from
# yfinance's `.info` -- a different taxonomy from ticker_metadata's Polygon
# SIC code/description above, kept in its own table rather than folded into
# ticker_metadata since the source and column shape both differ. Current
# state only (overwritten on refresh), same convention as ticker_metadata.
_TICKER_SECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_sector (
    ticker TEXT PRIMARY KEY,
    sector TEXT,
    industry TEXT,
    updated_at TEXT NOT NULL
);
"""

# Macro/meta-financial time series (e.g. FRED's M2SL, DGS10, CPIAUCSL) --
# same shape as shares_outstanding above with ticker swapped for series_id,
# since these are market-wide series with no associated ticker. A refresh
# overwrites to the source's latest-known value per date (INSERT OR REPLACE,
# same as every other table here) rather than tracking revision vintages --
# e.g. FRED revises GDP repeatedly after first release, and we deliberately
# only keep "current best known value," not an ALFRED-style history of edits.
_MACRO_SERIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS macro_series (
    series_id TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    source TEXT NOT NULL,
    -- Point-in-time pair, nullable -- when this (series_id, date)
    -- observation was actually first published, and what it said at that
    -- moment (fred_client.get_series_first_release/ALFRED vintage data).
    -- Distinct from `value`, which stays "latest-known/most-revised" --
    -- these are for a point-in-time-safe join (market_common.macro.
    -- as_of_join), not a replacement for `value`'s existing meaning. NULL
    -- for rows fetched before this column existed, or where FRED couldn't
    -- serve first-release data (see SAME_DAY_PUBLISHED_SERIES for the one
    -- case that's expected, not just "not backfilled yet").
    published_at TEXT,
    first_published_value REAL,
    PRIMARY KEY (series_id, date, source)
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
    conn.execute(_TICKER_METADATA_SCHEMA)
    conn.execute(_TICKER_SECTOR_SCHEMA)
    conn.execute(_INDEX_MEMBERSHIP_SCHEMA)
    conn.execute(_SHARES_OUTSTANDING_SCHEMA)
    conn.execute(_MACRO_SERIES_SCHEMA)
    conn.execute(_SPLITS_SCHEMA)
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

    bars = _drop_invalid_ohlc(bars, context=f"{ticker}/{source}")
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

    bars = _drop_invalid_ohlc(bars, context=f"bulk/{source}")
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


def upsert_ticker_metadata(conn: sqlite3.Connection, metadata: pd.DataFrame) -> None:
    """Insert or replace rows in the `ticker_metadata` table.

    `metadata` must have columns: ticker, market_cap, sic_code, sic_description,
    share_class_shares_outstanding, weighted_shares_outstanding, total_employees,
    primary_exchange, list_date. Each ticker is a single overwritten row (a
    current snapshot, not a history), so a re-run just refreshes stale values.
    """
    if metadata.empty:
        return

    now = pd.Timestamp.now("UTC").isoformat()
    rows = [
        (
            row.ticker,
            _as_float(row.market_cap),
            row.sic_code,
            row.sic_description,
            _as_float(row.share_class_shares_outstanding),
            _as_float(row.weighted_shares_outstanding),
            _as_float(row.total_employees),
            row.primary_exchange,
            row.list_date,
            now,
        )
        for row in metadata.itertuples()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO ticker_metadata
            (ticker, market_cap, sic_code, sic_description,
             share_class_shares_outstanding, weighted_shares_outstanding,
             total_employees, primary_exchange, list_date, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_ticker_metadata(conn: sqlite3.Connection, ticker: str | None = None) -> pd.DataFrame:
    query = "SELECT * FROM ticker_metadata WHERE 1=1"
    params: list = []
    if ticker is not None:
        query += " AND ticker = ?"
        params.append(ticker)
    return pd.read_sql_query(query, conn, params=params)


def upsert_ticker_sector(conn: sqlite3.Connection, sectors: pd.DataFrame) -> None:
    """Insert or replace rows in the `ticker_sector` table.

    `sectors` must have columns: ticker, sector, industry. Each ticker is a
    single overwritten row (a current snapshot, not a history), same
    convention as `upsert_ticker_metadata`.
    """
    if sectors.empty:
        return

    now = pd.Timestamp.now("UTC").isoformat()
    rows = [(row.ticker, row.sector, row.industry, now) for row in sectors.itertuples()]
    conn.executemany(
        """
        INSERT OR REPLACE INTO ticker_sector (ticker, sector, industry, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_ticker_sector(conn: sqlite3.Connection, ticker: str | None = None) -> pd.DataFrame:
    query = "SELECT * FROM ticker_sector WHERE 1=1"
    params: list = []
    if ticker is not None:
        query += " AND ticker = ?"
        params.append(ticker)
    return pd.read_sql_query(query, conn, params=params)


def upsert_shares_outstanding(conn: sqlite3.Connection, ticker: str, source: str, shares: pd.Series) -> None:
    """Insert or replace rows in the `shares_outstanding` table for
    `ticker`/`source`. `shares` must be a Series of share counts indexed by
    date -- a real historical time series, unlike `upsert_ticker_metadata`'s
    single overwritten row. A re-run just fills in/refreshes whatever dates
    the caller passes, same overwrite-on-conflict semantics as `upsert_bars`.
    """
    if shares.empty:
        return
    rows = [(ticker, _serialize_date(date), _as_float(value), source) for date, value in shares.items()]
    conn.executemany(
        """
        INSERT OR REPLACE INTO shares_outstanding (ticker, date, shares_outstanding, source)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_shares_outstanding(conn: sqlite3.Connection, ticker: str, source: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, shares_outstanding FROM shares_outstanding WHERE ticker = ? AND source = ? ORDER BY date",
        conn, params=(ticker, source),
    )


def upsert_splits(conn: sqlite3.Connection, ticker: str, source: str, splits: pd.DataFrame) -> None:
    """Insert or replace rows in the `splits` table for `ticker`/`source`.
    `splits` must have columns execution_date/split_from/split_to/ratio (see
    `PolygonClient.get_splits`'s return shape) -- a ticker's full split
    history in one frame, same overwrite-on-conflict semantics as
    `upsert_shares_outstanding`.
    """
    if splits.empty:
        return
    rows = [
        (
            ticker, _serialize_date(row.execution_date),
            _as_float(row.split_from), _as_float(row.split_to), _as_float(row.ratio), source,
        )
        for row in splits.itertuples()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO splits (ticker, execution_date, split_from, split_to, ratio, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_splits(conn: sqlite3.Connection, ticker: str, source: str = POLYGON) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT execution_date, split_from, split_to, ratio FROM splits "
        "WHERE ticker = ? AND source = ? ORDER BY execution_date",
        conn, params=(ticker, source), parse_dates=["execution_date"],
    )


def upsert_macro_series(
    conn: sqlite3.Connection,
    series_id: str,
    source: str,
    values: pd.Series,
    publication: pd.DataFrame | None = None,
) -> None:
    """Insert or replace rows in the `macro_series` table for `series_id`/
    `source`. `values` must be a Series of floats indexed by date -- same
    overwrite-on-conflict semantics as `upsert_shares_outstanding` (a re-run
    refreshes to the source's latest-known value per date).

    `publication`, if given, is indexed by date with `published_at`/
    `first_published_value` columns (see `fred_client.get_series_first_release`)
    -- looked up per date in `values.index` (the authoritative date axis;
    `publication` need not cover every date `values` does, e.g. a date
    outside whatever window a first-release query happened to return).
    Missing/absent dates get NULL for both new columns.
    """
    if values.empty:
        return
    rows = []
    for date, value in values.items():
        pub_row = publication.loc[date] if publication is not None and date in publication.index else None
        published_at = None if pub_row is None else pub_row["published_at"]
        first_published_value = None if pub_row is None else _as_float(pub_row["first_published_value"])
        rows.append(
            (series_id, _serialize_date(date), _as_float(value), source, published_at, first_published_value)
        )
    conn.executemany(
        """
        INSERT OR REPLACE INTO macro_series
            (series_id, date, value, source, published_at, first_published_value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_macro_series(conn: sqlite3.Connection, series_id: str, source: str = FRED) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, value, published_at, first_published_value "
        "FROM macro_series WHERE series_id = ? AND source = ? ORDER BY date",
        conn, params=(series_id, source),
    )


def replace_index_membership(conn: sqlite3.Connection, index_name: str, membership: pd.DataFrame) -> None:
    """Replace all `index_membership` rows for `index_name` with `membership`.

    `membership` must have columns: ticker, start_date, end_date (end_date may
    be null/NaN for a still-current member). This is a full delete-then-insert
    per index, not an upsert -- these come from a re-downloaded/recomputed
    dataset each refresh, and a full replace is simpler and safer than trying
    to reconcile against whatever was stored from a previous version of the
    upstream source (which could itself revise past intervals, not just add
    new ones).
    """
    conn.execute("DELETE FROM index_membership WHERE index_name = ?", (index_name,))
    if not membership.empty:
        rows = [
            (
                index_name,
                row.ticker,
                _serialize_date(row.start_date),
                _serialize_date(row.end_date),
            )
            for row in membership.itertuples()
        ]
        conn.executemany(
            """
            INSERT INTO index_membership (index_name, ticker, start_date, end_date)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
    conn.commit()


def read_index_membership(
    conn: sqlite3.Connection,
    index_name: str,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Read membership rows for `index_name`. With `as_of` given, returns only
    tickers that were members on that date (start_date <= as_of and (end_date
    is null or end_date >= as_of)) -- i.e. the point-in-time constituent list.
    Without it, returns every stored interval (including past, non-current ones).
    """
    query = "SELECT * FROM index_membership WHERE index_name = ?"
    params: list = [index_name]
    if as_of is not None:
        as_of_str = _serialize_date(pd.Timestamp(as_of))
        query += " AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)"
        params.extend([as_of_str, as_of_str])
    return pd.read_sql_query(query, conn, params=params)


def read_index_universe_tickers(conn: sqlite3.Connection, index_names: list[str]) -> list[str]:
    """Every distinct ticker that has *ever* been a member of any of
    `index_names` -- not just today's roster (matches `index_membership`'s
    own point-in-time scope). Shared by bulk backfill scripts that need "all
    S&P 500 + Nasdaq-100 tickers, ever" as their universe (e.g.
    `bulk_splits_ingest.py`, `bulk_shares_outstanding_ingest.py`'s
    `--indices` option) rather than each re-deriving the same query.
    """
    if not index_names:
        return []
    placeholders = ",".join("?" for _ in index_names)
    rows = conn.execute(
        f"SELECT DISTINCT ticker FROM index_membership WHERE index_name IN ({placeholders})",
        index_names,
    ).fetchall()
    return sorted(row[0] for row in rows)


def _serialize_date(value) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


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


def _drop_invalid_ohlc(bars: pd.DataFrame, context: str) -> pd.DataFrame:
    """Reject rows with impossible OHLC values -- confirmed via a real
    yfinance deep-history pull (2010-2026, ~2.15M rows) to occur for ~0.2% of
    rows, concentrated in older history and specific low-quality tickers
    (e.g. one ticker's `close` sitting outside that day's `high`/`low` range
    entirely, or all-zero OHLC with a nonzero close). This isn't an
    adjustment-convention difference like Polygon-vs-yfinance close prices --
    it's corrupted data that would silently poison downstream calculations,
    so these rows are dropped, not stored.

    NaN-safe without a separate isna check: every comparison against NaN
    (e.g. `NaN > 0`) evaluates to False in pandas, so a row with any missing
    OHLC value fails the `valid` mask the same way an out-of-range value does.
    """
    valid = (
        (bars["open"] > 0)
        & (bars["high"] > 0)
        & (bars["low"] > 0)
        & (bars["close"] > 0)
        & (bars["high"] >= bars["low"])
        & (bars["open"] >= bars["low"])
        & (bars["open"] <= bars["high"])
        & (bars["close"] >= bars["low"])
        & (bars["close"] <= bars["high"])
    )
    dropped = int((~valid).sum())
    if dropped:
        print(f"WARNING: dropped {dropped} row(s) with invalid OHLC values for {context}")
    return bars[valid]
