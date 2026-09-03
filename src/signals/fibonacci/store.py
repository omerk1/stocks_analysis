"""Schema creation + upserts for fib_sets/fib_levels in the shared derived-
results DB (`data/derived/analysis.sqlite`) -- see `market_common.
derived_db` for the `runs` table every module (gaps/divergences/
fibonacci/avwap) shares alongside its own result table(s).
"""

from __future__ import annotations

import sqlite3

from src.signals.fibonacci.models import FibLevel, FibLevelKind, FibSet, FibSetStatus, FibSwing, SwingDirection
from src.foundation.market_common.models import Timeframe

_FIB_SETS_SCHEMA = """
CREATE TABLE IF NOT EXISTS fib_sets (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT,
    direction TEXT,
    scale_mult REAL,
    origin_date TEXT, origin_price REAL, end_date TEXT, end_price REAL,
    magnitude_atr REAL, duration_bars INTEGER,
    weight REAL, status TEXT,
    invalidated_date TEXT,
    confirmed_at TEXT, run_id TEXT,
    UNIQUE (ticker, timeframe, origin_date, end_date, scale_mult)
);
"""

_FIB_LEVELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS fib_levels (
    id TEXT PRIMARY KEY,
    fib_set_id TEXT REFERENCES fib_sets(id),
    ratio REAL, kind TEXT,
    price REAL,
    n_touches INTEGER, n_violations INTEGER,
    first_touch_date TEXT, last_touch_date TEXT,
    avg_reaction_atr REAL, respected INTEGER,
    UNIQUE (fib_set_id, ratio, kind)
);
"""

# `id` deliberately excluded from DO UPDATE SET, same reasoning as gaps.
# store's own upsert: on conflict, SQLite leaves any column not named in
# SET untouched, so the row's original uuid4 id survives a re-run even
# though this INSERT's own VALUES clause always carries a freshly minted
# one. `RETURNING id` then hands back whichever id actually ended up on
# the row (the fresh one on first insert, the preserved original on a
# conflict) in the same round-trip -- needed here (unlike gaps, which has
# no child table) so fib_levels rows below can be linked to the *real*
# parent id without a separate SELECT.
_UPSERT_SET_SQL = """
INSERT INTO fib_sets (
    id, ticker, timeframe, direction, scale_mult,
    origin_date, origin_price, end_date, end_price,
    magnitude_atr, duration_bars, weight, status, invalidated_date,
    confirmed_at, run_id
) VALUES (
    :id, :ticker, :timeframe, :direction, :scale_mult,
    :origin_date, :origin_price, :end_date, :end_price,
    :magnitude_atr, :duration_bars, :weight, :status, :invalidated_date,
    :confirmed_at, :run_id
)
ON CONFLICT (ticker, timeframe, origin_date, end_date, scale_mult) DO UPDATE SET
    weight = excluded.weight,
    status = excluded.status,
    invalidated_date = excluded.invalidated_date,
    run_id = excluded.run_id
RETURNING id
"""

_UPSERT_LEVEL_SQL = """
INSERT INTO fib_levels (
    id, fib_set_id, ratio, kind, price,
    n_touches, n_violations, first_touch_date, last_touch_date,
    avg_reaction_atr, respected
) VALUES (
    :id, :fib_set_id, :ratio, :kind, :price,
    :n_touches, :n_violations, :first_touch_date, :last_touch_date,
    :avg_reaction_atr, :respected
)
ON CONFLICT (fib_set_id, ratio, kind) DO UPDATE SET
    price = excluded.price,
    n_touches = excluded.n_touches, n_violations = excluded.n_violations,
    first_touch_date = excluded.first_touch_date, last_touch_date = excluded.last_touch_date,
    avg_reaction_atr = excluded.avg_reaction_atr, respected = excluded.respected
"""


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_FIB_SETS_SCHEMA)
    conn.execute(_FIB_LEVELS_SCHEMA)
    conn.commit()


def _upsert_fib_set_no_commit(conn: sqlite3.Connection, fib_set: FibSet, run_id: str) -> str:
    swing = fib_set.swing
    row = conn.execute(
        _UPSERT_SET_SQL,
        {
            "id": fib_set.id,
            "ticker": fib_set.ticker,
            "timeframe": fib_set.timeframe.value if hasattr(fib_set.timeframe, "value") else fib_set.timeframe,
            "direction": swing.direction.value,
            "scale_mult": swing.scale_mult,
            "origin_date": swing.origin_date,
            "origin_price": swing.origin_price,
            "end_date": swing.end_date,
            "end_price": swing.end_price,
            "magnitude_atr": swing.magnitude_atr,
            "duration_bars": swing.duration_bars,
            "weight": fib_set.weight,
            "status": fib_set.status.value,
            "invalidated_date": fib_set.invalidated_date,
            "confirmed_at": swing.confirmed_at,
            "run_id": run_id,
        },
    ).fetchone()
    persisted_id = row[0]

    for level in fib_set.levels:
        conn.execute(
            _UPSERT_LEVEL_SQL,
            {
                "id": level.id,
                "fib_set_id": persisted_id,
                "ratio": level.ratio,
                "kind": level.kind.value,
                "price": level.price,
                "n_touches": level.n_touches,
                "n_violations": level.n_violations,
                "first_touch_date": level.first_touch_date,
                "last_touch_date": level.last_touch_date,
                "avg_reaction_atr": level.avg_reaction_atr,
                "respected": int(level.respected),
            },
        )

    return persisted_id


def upsert_fib_set(conn: sqlite3.Connection, fib_set: FibSet, run_id: str) -> str:
    """Insert or refresh one FibSet + its child levels, keyed by the
    swing's own natural key (ticker, timeframe, origin_date, end_date,
    scale_mult). Returns the row's persisted id (== fib_set.id on first
    insert, the pre-existing id on a re-run) -- callers don't need to
    track which case happened.

    Single-set convenience wrapper that commits immediately. For
    persisting a whole detection run's selected sets, use
    `upsert_fib_sets` instead -- it shares one commit across the batch
    rather than one per set.
    """
    persisted_id = _upsert_fib_set_no_commit(conn, fib_set, run_id)
    conn.commit()
    return persisted_id


def upsert_fib_sets(conn: sqlite3.Connection, fib_sets: list[FibSet], run_id: str) -> dict[str, str]:
    """Insert/refresh every fib_set in one transaction, returning
    {fib_set.id: persisted_id} for each. Same result shape cli.py
    previously built itself via a dict comprehension over per-set
    `upsert_fib_set` calls, but with a single shared commit -- matching
    gaps.store.upsert_gaps / divergences.store.upsert_divergences /
    avwap.store.upsert_anchors, which all batch-commit their whole list
    rather than committing once per row. Guards against a crash partway
    through a multi-set run leaving only some of that run's sets persisted.
    """
    persisted_ids = {fib_set.id: _upsert_fib_set_no_commit(conn, fib_set, run_id) for fib_set in fib_sets}
    conn.commit()
    return persisted_ids


def load_fib_set(conn: sqlite3.Connection, set_id: str) -> FibSet | None:
    """Reconstitute one persisted FibSet (+ its levels) by id -- used by
    cli.py's `--set-id` flag to plot a single previously-stored set rather
    than whatever a fresh detection run's own top-K happens to select.
    """
    row = conn.execute(
        """
        SELECT id, ticker, timeframe, direction, scale_mult,
               origin_date, origin_price, end_date, end_price,
               magnitude_atr, duration_bars, weight, status, invalidated_date,
               confirmed_at, run_id
        FROM fib_sets WHERE id = ?
        """,
        (set_id,),
    ).fetchone()
    if row is None:
        return None

    (
        id_, ticker, timeframe, direction, scale_mult,
        origin_date, origin_price, end_date, end_price,
        magnitude_atr, duration_bars, weight, status, invalidated_date,
        confirmed_at, run_id,
    ) = row

    swing = FibSwing(
        origin_date=origin_date, origin_price=origin_price,
        end_date=end_date, end_price=end_price,
        direction=SwingDirection(direction), scale_mult=scale_mult,
        magnitude_atr=magnitude_atr, duration_bars=duration_bars, confirmed_at=confirmed_at,
    )
    levels = [
        FibLevel(
            id=lvl_id, ratio=ratio, kind=FibLevelKind(kind), price=price,
            n_touches=n_touches, n_violations=n_violations,
            first_touch_date=first_touch_date, last_touch_date=last_touch_date,
            avg_reaction_atr=avg_reaction_atr, respected=bool(respected),
        )
        for (
            lvl_id, ratio, kind, price, n_touches, n_violations,
            first_touch_date, last_touch_date, avg_reaction_atr, respected,
        ) in conn.execute(
            """
            SELECT id, ratio, kind, price, n_touches, n_violations,
                   first_touch_date, last_touch_date, avg_reaction_atr, respected
            FROM fib_levels WHERE fib_set_id = ?
            """,
            (id_,),
        ).fetchall()
    ]

    return FibSet(
        id=id_, ticker=ticker, timeframe=Timeframe(timeframe), swing=swing, levels=levels,
        weight=weight, status=FibSetStatus(status), invalidated_date=invalidated_date, run_id=run_id,
    )
