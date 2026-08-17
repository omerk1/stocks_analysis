"""Schema creation + upsert for the `breadth` table in the shared derived-
results DB (`data/derived/analysis.sqlite`) -- see `market_common.derived_db`
for the `runs` table every module (gaps/divergences/fibonacci/avwap/
sr_lines/breadth) shares alongside its own result table.

Unlike gaps/divergences (one row per detected event, with a uuid `id` that
must survive reruns since a child table or other data could reference it),
a breadth row has no such identity concern: `(index_name, date)` fully and
permanently identifies "the answer" for that day, so it's the primary key
directly -- no separate `id` column, and a plain `INSERT OR REPLACE`
(matching macro_series' pattern, `data_processing/db.py`) rather than
gaps'/divergences' id-preserving `ON CONFLICT ... DO UPDATE`.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

_BREADTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS breadth (
    index_name TEXT NOT NULL,
    date TEXT NOT NULL,
    n_constituents INTEGER NOT NULL,
    n_with_data INTEGER NOT NULL,
    pct_above_sma50 REAL,
    pct_above_sma200 REAL,
    pct_above_ema8 REAL,
    pct_above_ema21 REAL,
    pct_golden_cross REAL,
    n_advancing INTEGER NOT NULL,
    n_declining INTEGER NOT NULL,
    net_advances INTEGER NOT NULL,
    ad_ratio REAL,
    run_id TEXT,
    PRIMARY KEY (index_name, date)
);
"""


def create_breadth_table(conn: sqlite3.Connection) -> None:
    conn.execute(_BREADTH_SCHEMA)
    conn.commit()


def upsert_breadth(conn: sqlite3.Connection, index_name: str, breadth: pd.DataFrame, run_id: str) -> None:
    """Insert/overwrite rows in the `breadth` table for `index_name`,
    keyed by `(index_name, date)`. `breadth` is whatever
    `compute.compute_breadth` returns -- indexed by date, with exactly the
    columns in `_BREADTH_SCHEMA` (minus `index_name`/`run_id`, added here).

    The schema's `pct_above_sma50/sma200/ema8/ema21` columns are fixed to
    `BreadthConfig`'s default periods -- a `compute_breadth` call using
    different `sma_periods`/`ema_periods` would produce differently-named
    columns this function can't see. Fails loudly (not a silent partial
    write) rather than guess.
    """
    if breadth.empty:
        return
    columns = [
        "n_constituents", "n_with_data",
        "pct_above_sma50", "pct_above_sma200", "pct_above_ema8", "pct_above_ema21",
        "pct_golden_cross", "n_advancing", "n_declining", "net_advances", "ad_ratio",
    ]
    missing = [c for c in columns if c not in breadth.columns]
    if missing:
        raise ValueError(
            f"breadth frame is missing expected columns {missing} -- was it computed with "
            "non-default BreadthConfig.sma_periods/ema_periods?"
        )
    rows = []
    for date, row in breadth.iterrows():
        values = [None if pd.isna(row.get(c)) else row.get(c) for c in columns]
        rows.append((index_name, date.strftime("%Y-%m-%d"), *values, run_id))
    conn.executemany(
        f"""
        INSERT OR REPLACE INTO breadth (index_name, date, {", ".join(columns)}, run_id)
        VALUES ({", ".join(["?"] * (len(columns) + 3))})
        """,
        rows,
    )
    conn.commit()


def read_breadth(conn: sqlite3.Connection, index_name: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT * FROM breadth WHERE index_name = ? ORDER BY date", conn, params=(index_name,)
    )
