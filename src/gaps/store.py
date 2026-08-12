"""Schema creation + upserts for the `gaps` table in the shared derived-
results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap) shares alongside its own result table.
"""

from __future__ import annotations

import sqlite3

from src.gaps.models import Gap

_GAPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS gaps (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    kind TEXT,
    direction TEXT,
    created_at TEXT,
    zone_top REAL, zone_bottom REAL, size_atr REAL,
    status TEXT,
    max_fill_pct REAL,
    first_touch_date TEXT, soft_closed_date TEXT, closed_date TEXT,
    bars_to_first_touch INTEGER, bars_to_soft_closed INTEGER, bars_to_closed INTEGER,
    n_approaches INTEGER, volume_ratio_at_creation REAL,
    reaction_atr_after_close REAL, bars_to_reaction_peak INTEGER,
    related_id TEXT, run_id TEXT,
    UNIQUE (ticker, timeframe, kind, created_at, direction)
);
"""

_UPSERT_SQL = """
INSERT INTO gaps
    (id, ticker, timeframe, kind, direction, created_at,
     zone_top, zone_bottom, size_atr, status, max_fill_pct,
     first_touch_date, soft_closed_date, closed_date,
     bars_to_first_touch, bars_to_soft_closed, bars_to_closed,
     n_approaches, volume_ratio_at_creation,
     reaction_atr_after_close, bars_to_reaction_peak, related_id, run_id)
VALUES
    (:id, :ticker, :timeframe, :kind, :direction, :created_at,
     :zone_top, :zone_bottom, :size_atr, :status, :max_fill_pct,
     :first_touch_date, :soft_closed_date, :closed_date,
     :bars_to_first_touch, :bars_to_soft_closed, :bars_to_closed,
     :n_approaches, :volume_ratio_at_creation,
     :reaction_atr_after_close, :bars_to_reaction_peak, :related_id, :run_id)
ON CONFLICT (ticker, timeframe, kind, created_at, direction) DO UPDATE SET
    status = excluded.status,
    max_fill_pct = excluded.max_fill_pct,
    first_touch_date = excluded.first_touch_date,
    soft_closed_date = excluded.soft_closed_date,
    closed_date = excluded.closed_date,
    bars_to_first_touch = excluded.bars_to_first_touch,
    bars_to_soft_closed = excluded.bars_to_soft_closed,
    bars_to_closed = excluded.bars_to_closed,
    n_approaches = excluded.n_approaches,
    reaction_atr_after_close = excluded.reaction_atr_after_close,
    bars_to_reaction_peak = excluded.bars_to_reaction_peak,
    run_id = excluded.run_id
    -- volume_ratio_at_creation deliberately excluded, same reasoning as
    -- zone_top/zone_bottom/size_atr above it: fully deterministic from the
    -- creation bar's own (never-changing) historical volume, so it's
    -- geometry, not a mutable lifecycle field.
"""


def create_gaps_table(conn: sqlite3.Connection) -> None:
    conn.execute(_GAPS_SCHEMA)
    conn.commit()


def upsert_gaps(conn: sqlite3.Connection, gaps: list[Gap], run_id: str) -> None:
    """Insert new gap rows / refresh the mutable lifecycle fields on
    existing ones, keyed by the table's UNIQUE natural key (ticker,
    timeframe, kind, created_at, direction) -- never a full delete+reinsert.

    Uses ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE so a
    re-run keeps each row's original `id`: REPLACE deletes and reinserts
    the whole row, which would silently swap in this run's freshly
    generated uuid4 (every `detect_gaps` call mints a new one, even for a
    gap it's seen before) unless callers first SELECT the old id -- an
    extra round-trip DO UPDATE's targeted SET avoids entirely, since `id`
    (and the geometry columns, which are deterministic from the same
    creation bar and never need to change) just aren't in the SET list.
    A row whose natural key doesn't reappear in a fresh run is left alone,
    per spec -- this function only ever inserts or updates, never deletes.
    """
    for gap in gaps:
        row = gap.to_dict()
        row["id"] = gap.id
        row["run_id"] = run_id
        conn.execute(_UPSERT_SQL, row)
    conn.commit()
