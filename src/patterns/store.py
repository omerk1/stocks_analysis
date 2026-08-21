"""Schema creation + upserts for the `pattern_matches` table in the shared
derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap/patterns) shares alongside its own result
table. One table, `pattern_type` discriminator column, same shape of
decision sr_lines already made for its own horizontal/diagonal `kind`
column (see docs/features/chart_pattern_detection_design_notes.md).

`key_levels`/`trendlines`/`notes`/`pivots` are variable-shape per pattern
type (design doc §5: key_levels' keys differ by pattern) -- stored as JSON
text columns, same convention sr_lines' `scores_json`/avwap's
`anchor_types` JSON columns already use for exactly this reason (no native
array/dict column type in SQLite).

Current-state-only, like gaps/divergences/sr_lines: a later run overwrites
an earlier run's mutable fields (status/confidence/etc.) on the same
natural key rather than keeping history -- see the module's own design
notes for why a dedicated backtest harness (re-running `scanner.detect(
as_of=X)` fresh, not reading this table's past) is the right tool for
point-in-time analysis, deferred for now (docs/backlog.md).
"""

from __future__ import annotations

import json
import sqlite3

from src.patterns.models import PatternMatch

_PATTERN_MATCHES_SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_matches (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    pattern_type TEXT, direction TEXT,
    pivots_json TEXT, key_levels_json TEXT, trendlines_json TEXT,
    status TEXT,
    breakout_bar INTEGER, entry_price REAL, stop_price REAL, target_price REAL,
    confidence REAL, volume_confirmed INTEGER,
    formation_start TEXT, formation_end TEXT,
    notes_json TEXT, run_id TEXT,
    UNIQUE (ticker, timeframe, pattern_type, formation_start, formation_end)
);
"""

_UPSERT_SQL = """
INSERT INTO pattern_matches
    (id, ticker, timeframe, pattern_type, direction,
     pivots_json, key_levels_json, trendlines_json,
     status, breakout_bar, entry_price, stop_price, target_price,
     confidence, volume_confirmed, formation_start, formation_end, notes_json, run_id)
VALUES
    (:id, :ticker, :timeframe, :pattern_type, :direction,
     :pivots_json, :key_levels_json, :trendlines_json,
     :status, :breakout_bar, :entry_price, :stop_price, :target_price,
     :confidence, :volume_confirmed, :formation_start, :formation_end, :notes_json, :run_id)
ON CONFLICT (ticker, timeframe, pattern_type, formation_start, formation_end) DO UPDATE SET
    status = excluded.status,
    breakout_bar = excluded.breakout_bar,
    entry_price = excluded.entry_price,
    confidence = excluded.confidence,
    volume_confirmed = excluded.volume_confirmed,
    notes_json = excluded.notes_json,
    run_id = excluded.run_id
    -- direction/pivots_json/key_levels_json/trendlines_json/stop_price/
    -- target_price deliberately excluded: fixed geometry from the
    -- defining pivots, never changes for a given natural key.
"""


def create_pattern_matches_table(conn: sqlite3.Connection) -> None:
    conn.execute(_PATTERN_MATCHES_SCHEMA)
    conn.commit()


def upsert_pattern_matches(conn: sqlite3.Connection, matches: list[PatternMatch], run_id: str) -> None:
    """Insert new pattern rows / refresh the mutable lifecycle fields on
    existing ones, keyed by the table's UNIQUE natural key -- never a full
    delete+reinsert. Uses ON CONFLICT ... DO UPDATE (not INSERT OR REPLACE)
    so a re-run keeps each row's original `id`, same reasoning as
    gaps.store.upsert_gaps."""
    for match in matches:
        d = match.to_dict()
        row = {
            "id": match.id,
            "ticker": d["ticker"],
            "timeframe": d["timeframe"],
            "pattern_type": d["pattern_type"],
            "direction": d["direction"],
            "pivots_json": json.dumps(d["pivots"]),
            "key_levels_json": json.dumps(d["key_levels"]),
            "trendlines_json": json.dumps(d["trendlines"]),
            "status": d["status"],
            "breakout_bar": d["breakout_bar"],
            "entry_price": d["entry_price"],
            "stop_price": d["stop_price"],
            "target_price": d["target_price"],
            "confidence": d["confidence"],
            "volume_confirmed": int(d["volume_confirmed"]),
            "formation_start": d["formation_start"],
            "formation_end": d["formation_end"],
            "notes_json": json.dumps(d["notes"]),
            "run_id": run_id,
        }
        conn.execute(_UPSERT_SQL, row)
    conn.commit()
