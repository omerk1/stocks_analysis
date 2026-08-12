"""Schema creation + upserts for the `divergences` table in the shared
derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap) shares alongside its own result table.
"""

from __future__ import annotations

import sqlite3

from src.divergences.models import Divergence

_DIVERGENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS divergences (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT, indicator TEXT,
    direction TEXT,
    p1_date TEXT, p2_date TEXT,
    p1_price REAL, p2_price REAL,
    i1_value REAL, i2_value REAL,
    strength REAL,
    duration_bars INTEGER, price_move_atr REAL, indicator_gap_raw REAL,
    appeared_at TEXT, confirmed_at TEXT,
    max_favorable_move_atr REAL, bars_to_max_favorable_move INTEGER,
    invalidated INTEGER, invalidated_at TEXT, outcome_computed_through TEXT,
    run_id TEXT,
    UNIQUE (ticker, timeframe, indicator, direction, p2_date)
);
"""

_UPSERT_SQL = """
INSERT INTO divergences
    (id, ticker, timeframe, indicator, direction, p1_date, p2_date,
     p1_price, p2_price, i1_value, i2_value, strength,
     duration_bars, price_move_atr, indicator_gap_raw, appeared_at, confirmed_at,
     max_favorable_move_atr, bars_to_max_favorable_move,
     invalidated, invalidated_at, outcome_computed_through, run_id)
VALUES
    (:id, :ticker, :timeframe, :indicator, :direction, :p1_date, :p2_date,
     :p1_price, :p2_price, :i1_value, :i2_value, :strength,
     :duration_bars, :price_move_atr, :indicator_gap_raw, :appeared_at, :confirmed_at,
     :max_favorable_move_atr, :bars_to_max_favorable_move,
     :invalidated, :invalidated_at, :outcome_computed_through, :run_id)
ON CONFLICT (ticker, timeframe, indicator, direction, p2_date) DO UPDATE SET
    strength = excluded.strength,
    i1_value = excluded.i1_value,
    i2_value = excluded.i2_value,
    duration_bars = excluded.duration_bars,
    price_move_atr = excluded.price_move_atr,
    indicator_gap_raw = excluded.indicator_gap_raw,
    confirmed_at = excluded.confirmed_at,
    -- Outcome fields are mutable, unlike p1/p2 geometry -- a rerun with
    -- more bars available (a later as_of, or simply more time having
    -- passed) can walk further and should refresh these, same reasoning
    -- gaps' lifecycle fields are already in this SET list for.
    max_favorable_move_atr = excluded.max_favorable_move_atr,
    bars_to_max_favorable_move = excluded.bars_to_max_favorable_move,
    invalidated = excluded.invalidated,
    invalidated_at = excluded.invalidated_at,
    outcome_computed_through = excluded.outcome_computed_through,
    run_id = excluded.run_id
"""


def create_divergences_table(conn: sqlite3.Connection) -> None:
    conn.execute(_DIVERGENCES_SCHEMA)
    conn.commit()


def upsert_divergences(conn: sqlite3.Connection, divergences: list[Divergence], run_id: str) -> None:
    """Insert new divergence rows / refresh the fields that can legitimately
    change on a re-run (strength, the paired indicator values, confirmed_at,
    run_id), keyed by the table's UNIQUE natural key -- never a full
    delete+reinsert.

    p1/p2 dates and prices are the natural key's own basis (p2_date is part
    of it) and are deterministic from the same price-pivot geometry each
    time, so they're intentionally left out of the SET clause -- same
    reasoning as gaps.store.upsert_gaps for its own geometry columns.

    Uses ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE so a
    re-run keeps each row's original `id`: REPLACE deletes and reinserts the
    whole row, which would silently swap in this run's freshly generated
    uuid4 (every `detect_divergences` call mints a new one, even for a
    divergence it's seen before) unless callers first SELECT the old id.
    A row whose natural key doesn't reappear in a fresh run is left alone --
    this function only ever inserts or updates, never deletes.
    """
    for divergence in divergences:
        row = divergence.to_dict()
        row["id"] = divergence.id
        row["run_id"] = run_id
        conn.execute(_UPSERT_SQL, row)
    conn.commit()
