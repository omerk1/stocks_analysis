"""Schema creation + upserts for the `market_structure_events` table in
the shared derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap/patterns) shares alongside its own result
table.
"""

from __future__ import annotations

import sqlite3

from src.signals.market_structure.models import TrendState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_structure_events (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT, event TEXT, direction TEXT,
    broken_pivot_price REAL, broken_pivot_timestamp TEXT, broken_pivot_kind TEXT,
    broken_at TEXT, close REAL, volume_confirmed INTEGER,
    run_id TEXT,
    UNIQUE (ticker, timeframe, broken_at, event)
);
"""

_UPSERT_SQL = """
INSERT INTO market_structure_events
    (id, ticker, timeframe, event, direction,
     broken_pivot_price, broken_pivot_timestamp, broken_pivot_kind,
     broken_at, close, volume_confirmed, run_id)
VALUES
    (:id, :ticker, :timeframe, :event, :direction,
     :broken_pivot_price, :broken_pivot_timestamp, :broken_pivot_kind,
     :broken_at, :close, :volume_confirmed, :run_id)
ON CONFLICT (ticker, timeframe, broken_at, event) DO UPDATE SET
    direction = excluded.direction,
    close = excluded.close,
    volume_confirmed = excluded.volume_confirmed,
    run_id = excluded.run_id
"""


def create_market_structure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_SCHEMA)
    conn.commit()


def upsert_events(conn: sqlite3.Connection, events: list[TrendState], run_id: str) -> None:
    """Insert new event rows / refresh the fields that can legitimately
    change on a re-run (direction, close, volume_confirmed, run_id), keyed
    by the table's UNIQUE natural key -- never a full delete+reinsert.
    Uses ON CONFLICT ... DO UPDATE rather than INSERT OR REPLACE so a
    re-run keeps each row's original `id`, same reasoning as
    divergences.store.upsert_divergences.
    """
    for event in events:
        row = {
            "id": event.id,
            "ticker": event.ticker,
            "timeframe": event.timeframe.value,
            "event": event.event.value,
            "direction": event.direction.value,
            "broken_pivot_price": event.broken_pivot.value,
            "broken_pivot_timestamp": event.broken_pivot.timestamp,
            "broken_pivot_kind": event.broken_pivot.kind.value,
            "broken_at": event.broken_at,
            "close": event.close,
            "volume_confirmed": int(event.volume_confirmed),
            "run_id": run_id,
        }
        conn.execute(_UPSERT_SQL, row)
    conn.commit()
