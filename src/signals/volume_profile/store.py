"""Schema creation + upserts for the `volume_profiles` table in the shared
derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module shares
alongside its own result table. Same shape as avwap.store: one row per
(ticker, timeframe, anchor_date), id preserved across re-runs.
"""

from __future__ import annotations

import json
import sqlite3

from src.foundation.market_common.anchors import AnchorType
from src.signals.volume_profile.models import AnchoredVolumeProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS volume_profiles (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    anchor_date TEXT,
    anchor_types TEXT,
    status TEXT,
    poc REAL, vah REAL, val REAL,
    total_volume REAL, up_volume REAL, down_volume REAL,
    poc_up_volume REAL, poc_down_volume REAL,
    n_bars INTEGER,
    current_close REAL, distance_to_poc_atr REAL, value_area_position TEXT,
    updated_through TEXT,
    run_id TEXT,
    UNIQUE (ticker, timeframe, anchor_date)
);
"""

_MUTABLE = [
    "anchor_types", "status", "poc", "vah", "val",
    "total_volume", "up_volume", "down_volume", "poc_up_volume", "poc_down_volume",
    "n_bars", "current_close", "distance_to_poc_atr", "value_area_position",
    "updated_through", "run_id",
]
_COLUMNS = ["id", "ticker", "timeframe", "anchor_date"] + _MUTABLE

_UPSERT_SQL = f"""
INSERT INTO volume_profiles ({", ".join(_COLUMNS)})
VALUES ({", ".join(":" + c for c in _COLUMNS)})
ON CONFLICT (ticker, timeframe, anchor_date) DO UPDATE SET
    {", ".join(f"{c} = excluded.{c}" for c in _MUTABLE)}
"""


def create_volume_profile_table(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    conn.commit()


def upsert_profiles(conn: sqlite3.Connection, profiles: list[AnchoredVolumeProfile], run_id: str) -> None:
    """Keyed by (ticker, timeframe, anchor_date) -- a re-run never
    duplicates rows, and ON CONFLICT DO UPDATE (not INSERT OR REPLACE)
    keeps each row's original `id` (same reasoning as avwap.store.
    upsert_anchors). An anchor that no longer qualifies arrives here with
    status='stale' from detect.discover_profiles, not omitted."""
    for profile in profiles:
        row = profile.to_dict()
        row["anchor_types"] = json.dumps(row["anchor_types"])
        row["run_id"] = run_id
        conn.execute(_UPSERT_SQL, row)
    conn.commit()


def get_anchor_types(conn: sqlite3.Connection, ticker: str, timeframe: str) -> dict[str, frozenset[AnchorType]]:
    """Previously-stored anchor_types per anchor_date (active and stale
    rows alike), for detect.discover_profiles' staleness comparison."""
    rows = conn.execute(
        "SELECT anchor_date, anchor_types FROM volume_profiles WHERE ticker = ? AND timeframe = ?",
        (ticker, timeframe),
    ).fetchall()
    return {
        anchor_date: frozenset(AnchorType(t) for t in json.loads(types_json))
        for anchor_date, types_json in rows
    }
