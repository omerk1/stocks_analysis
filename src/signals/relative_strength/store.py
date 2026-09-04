"""Schema creation + upsert for the `relative_strength` (stock-vs-market and
stock-vs-sector, one row per ticker/date/comparison) and
`sector_relative_strength` (sector-vs-market, one row per sector/date)
tables in the shared derived-results DB (`data/derived/analysis.sqlite`) --
see `market_common.derived_db` for the `runs` table every module shares.

Two tables, not one, because the key shapes genuinely differ (ticker vs
sector as the row identity) -- collapsing them into one table with a lot of
nullable columns would be worse than two small, fully-populated ones.
Neither needs a separate `id` column: same reasoning as `breadth/store.py`
-- the key tuple fully and permanently identifies "the answer" for that
row, so a plain `INSERT OR REPLACE` is enough.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

_RELATIVE_STRENGTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS relative_strength (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    comparison TEXT NOT NULL,
    benchmark TEXT,
    rs_ratio REAL,
    rs_mansfield REAL,
    rs_rating REAL,
    run_id TEXT,
    PRIMARY KEY (ticker, date, comparison)
);
"""

_SECTOR_RELATIVE_STRENGTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS sector_relative_strength (
    sector TEXT NOT NULL,
    date TEXT NOT NULL,
    benchmark TEXT,
    rs_ratio REAL,
    rs_mansfield REAL,
    rs_rating REAL,
    run_id TEXT,
    PRIMARY KEY (sector, date)
);
"""

_COLUMNS = ["benchmark", "rs_ratio", "rs_mansfield", "rs_rating"]


def create_relative_strength_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_RELATIVE_STRENGTH_SCHEMA)
    conn.execute(_SECTOR_RELATIVE_STRENGTH_SCHEMA)
    conn.commit()


def upsert_relative_strength(
    conn: sqlite3.Connection, comparison: str, rs: pd.DataFrame, run_id: str
) -> None:
    """Insert/overwrite rows in `relative_strength` for `comparison`
    ("vs_market" or "vs_sector"), keyed by `(ticker, date, comparison)`.
    `rs` is whatever `compute.compute_stock_vs_market`/
    `compute_stock_vs_sector` returns: columns ticker, date, benchmark,
    rs_ratio, rs_mansfield, rs_rating.
    """
    if rs.empty:
        return
    missing = [c for c in ["ticker", "date", *_COLUMNS] if c not in rs.columns]
    if missing:
        raise ValueError(f"relative-strength frame is missing expected columns {missing}")

    rows = [
        (
            row.ticker,
            pd.Timestamp(row.date).strftime("%Y-%m-%d"),
            comparison,
            *[None if pd.isna(getattr(row, c)) else getattr(row, c) for c in _COLUMNS],
            run_id,
        )
        for row in rs.itertuples()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO relative_strength
            (ticker, date, comparison, benchmark, rs_ratio, rs_mansfield, rs_rating, run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_relative_strength(
    conn: sqlite3.Connection, ticker: str, comparison: str | None = None
) -> pd.DataFrame:
    query = "SELECT * FROM relative_strength WHERE ticker = ?"
    params: list = [ticker]
    if comparison is not None:
        query += " AND comparison = ?"
        params.append(comparison)
    return pd.read_sql_query(query + " ORDER BY date", conn, params=params)


def upsert_sector_relative_strength(conn: sqlite3.Connection, rs: pd.DataFrame, run_id: str) -> None:
    """Insert/overwrite rows in `sector_relative_strength`, keyed by
    `(sector, date)`. `rs` is whatever `compute.compute_sector_vs_market`
    returns: columns sector, date, benchmark, rs_ratio, rs_mansfield,
    rs_rating.
    """
    if rs.empty:
        return
    missing = [c for c in ["sector", "date", *_COLUMNS] if c not in rs.columns]
    if missing:
        raise ValueError(f"sector relative-strength frame is missing expected columns {missing}")

    rows = [
        (
            row.sector,
            pd.Timestamp(row.date).strftime("%Y-%m-%d"),
            *[None if pd.isna(getattr(row, c)) else getattr(row, c) for c in _COLUMNS],
            run_id,
        )
        for row in rs.itertuples()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO sector_relative_strength
            (sector, date, benchmark, rs_ratio, rs_mansfield, rs_rating, run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def read_sector_relative_strength(conn: sqlite3.Connection, sector: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM sector_relative_strength WHERE sector = ? ORDER BY date", conn, params=(sector,)
    )
