"""Connection/schema helpers for the derived-results database
(`data/derived/analysis.sqlite`), separate from the raw price DB
(`data/raw/market_data.sqlite`). Every gaps/divergences/fibonacci/avwap
`store.py` writes to this same database and shares the `runs` table
defined here -- centralized so all four have the identical schema instead
of four independently-maintained (and eventually inconsistent) copies of
the same `CREATE TABLE`.

Mirrors `data_processing/db.py`'s own connection/path pattern
(`default_db_path`/`get_connection`/`create_tables`) for consistency with
the rest of this project, applied to the new, second database file.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pandas as pd

_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    as_of TEXT,
    config_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    rows_dropped INTEGER NOT NULL,
    quality_warning INTEGER NOT NULL
);
"""


def default_derived_db_path(derived_data_dir: str | Path) -> Path:
    return Path(derived_data_dir) / "analysis.sqlite"


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def create_runs_table(conn: sqlite3.Connection) -> None:
    conn.execute(_RUNS_SCHEMA)
    conn.commit()


def record_run(
    conn: sqlite3.Connection,
    module: str,
    ticker: str,
    timeframe: str,
    as_of: str | None,
    config_json: str,
    rows_dropped: int,
    quality_warning: bool,
) -> str:
    """Insert a new `runs` row and return its `run_id` -- always a fresh
    insert, never an upsert (each detection run is its own record, unlike
    the mutable result tables each module upserts into by natural key)."""
    run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO runs
            (run_id, module, ticker, timeframe, as_of, config_json, started_at,
             rows_dropped, quality_warning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, module, ticker, timeframe, as_of, config_json,
            pd.Timestamp.now("UTC").isoformat(), rows_dropped, int(quality_warning),
        ),
    )
    conn.commit()
    return run_id
