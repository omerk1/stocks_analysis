"""Schema creation + upserts for the `avwap_anchors` table in the shared
derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap) shares alongside its own result table.
"""

from __future__ import annotations

import json
import sqlite3

from src.avwap.models import AnchoredVwap, AnchorType

_ANCHORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS avwap_anchors (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    anchor_date TEXT,
    anchor_types TEXT,
    status TEXT,
    current_value REAL, updated_through TEXT,
    distance_atr REAL, n_crosses INTEGER,
    pct_bars_above REAL, pct_bars_below REAL,
    last_cross_date TEXT, avg_reaction_atr_on_touch REAL,
    run_id TEXT,
    UNIQUE (ticker, timeframe, anchor_date)
);
"""

_UPSERT_SQL = """
INSERT INTO avwap_anchors
    (id, ticker, timeframe, anchor_date, anchor_types, status,
     current_value, updated_through,
     distance_atr, n_crosses, pct_bars_above, pct_bars_below,
     last_cross_date, avg_reaction_atr_on_touch, run_id)
VALUES
    (:id, :ticker, :timeframe, :anchor_date, :anchor_types, :status,
     :current_value, :updated_through,
     :distance_atr, :n_crosses, :pct_bars_above, :pct_bars_below,
     :last_cross_date, :avg_reaction_atr_on_touch, :run_id)
ON CONFLICT (ticker, timeframe, anchor_date) DO UPDATE SET
    anchor_types = excluded.anchor_types,
    status = excluded.status,
    current_value = excluded.current_value,
    updated_through = excluded.updated_through,
    distance_atr = excluded.distance_atr,
    n_crosses = excluded.n_crosses,
    pct_bars_above = excluded.pct_bars_above,
    pct_bars_below = excluded.pct_bars_below,
    last_cross_date = excluded.last_cross_date,
    avg_reaction_atr_on_touch = excluded.avg_reaction_atr_on_touch,
    run_id = excluded.run_id
"""


def create_avwap_table(conn: sqlite3.Connection) -> None:
    conn.execute(_ANCHORS_SCHEMA)
    conn.commit()


def upsert_anchors(conn: sqlite3.Connection, anchors: list[AnchoredVwap], run_id: str) -> None:
    """Keyed by (ticker, timeframe, anchor_date) -- a re-run never
    duplicates rows. ON CONFLICT DO UPDATE (not INSERT OR REPLACE)
    preserves each row's original `id` across conflicts the same way
    gaps.store.upsert_gaps does: discover_anchor_dates mints a fresh uuid4
    every call, but only the mutable fields are ever in the SET list here.
    A date that no longer qualifies for any role simply isn't touched by
    this call (its previous row, if any, is left exactly as-is) --
    anchors.discover_anchor_dates is what turns it into an explicit
    status='stale' UPDATE, by including it in the returned list with
    status flipped rather than omitting it.
    """
    for anchor in anchors:
        row = anchor.to_dict()
        row["anchor_types"] = json.dumps(row["anchor_types"])
        row["id"] = anchor.id
        row["run_id"] = run_id
        conn.execute(_UPSERT_SQL, row)
    conn.commit()


def get_anchor_types(conn: sqlite3.Connection, ticker: str, timeframe: str) -> dict[str, frozenset[AnchorType]]:
    """Previously-stored anchor_types per anchor_date, for feeding
    `anchors.discover_anchor_dates`'s staleness comparison. Deliberately
    includes both active and stale rows -- a stale row's frozen
    anchor_types is exactly what a still-stale run should keep reporting,
    not something to drop from consideration.
    """
    rows = conn.execute(
        "SELECT anchor_date, anchor_types FROM avwap_anchors WHERE ticker = ? AND timeframe = ?",
        (ticker, timeframe),
    ).fetchall()
    return {
        anchor_date: frozenset(AnchorType(t) for t in json.loads(types_json))
        for anchor_date, types_json in rows
    }
