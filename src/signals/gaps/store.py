"""Schema creation + upserts for the `gaps` table in the shared derived-
results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap) shares alongside its own result table.

Rows are a **current-state snapshot as of the run**: `status`,
`max_fill_pct`, the milestone dates and `in_reach` describe the last bar
the run saw. Don't read them for an earlier date (a backtest "as of 2024")
-- a gap that filled later would already look closed. For any past date,
load the rows with `read_gaps` and pass them to `relevance.gap_states`,
which rebuilds each gap's state from prices up to that date (or run
`detect(as_of=...)`).
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from src.foundation.market_common.models import Timeframe
from src.signals.gaps.models import Direction, Gap, GapKind

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
    distance_x REAL, in_reach INTEGER,
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
     reaction_atr_after_close, bars_to_reaction_peak, related_id, run_id,
     distance_x, in_reach)
VALUES
    (:id, :ticker, :timeframe, :kind, :direction, :created_at,
     :zone_top, :zone_bottom, :size_atr, :status, :max_fill_pct,
     :first_touch_date, :soft_closed_date, :closed_date,
     :bars_to_first_touch, :bars_to_soft_closed, :bars_to_closed,
     :n_approaches, :volume_ratio_at_creation,
     :reaction_atr_after_close, :bars_to_reaction_peak, :related_id, :run_id,
     :distance_x, :in_reach)
ON CONFLICT (ticker, timeframe, kind, created_at, direction) DO UPDATE SET
    zone_top = excluded.zone_top,
    zone_bottom = excluded.zone_bottom,
    size_atr = excluded.size_atr,
    volume_ratio_at_creation = excluded.volume_ratio_at_creation,
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
    distance_x = excluded.distance_x,
    in_reach = excluded.in_reach,
    run_id = excluded.run_id
    -- Geometry (zone, size, creation volume ratio) is refreshed too: it's
    -- deterministic from the creation bars, but those bars are not fixed --
    -- a re-ingest or a dividend re-adjustment of bars_1d rescales them
    -- (AAPL's stored zones were ~0.1% off a day after storing, 2026-09-30).
"""


# Columns added after the table first shipped -- existing databases get
# them via ALTER TABLE (pure additions, NULL until the next run refreshes
# each row), same approach as avwap.store's std-band columns.
_ADDED_COLUMNS = {"distance_x": "REAL", "in_reach": "INTEGER"}


def create_gaps_table(conn: sqlite3.Connection) -> None:
    conn.execute(_GAPS_SCHEMA)
    have = {row[1] for row in conn.execute("PRAGMA table_info(gaps)")}
    for name, sql_type in _ADDED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE gaps ADD COLUMN {name} {sql_type}")
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
    just isn't in the SET list. Geometry is refreshed along with the
    lifecycle fields (bar data can be re-adjusted). This function never
    deletes; `prune_gaps` removes rows a fresh run no longer finds.
    """
    for gap in gaps:
        row = gap.to_dict()
        row["id"] = gap.id
        row["run_id"] = run_id
        conn.execute(_UPSERT_SQL, row)
    for ticker, timeframe in {(g.ticker, g.timeframe.value) for g in gaps}:
        _relink_fvgs(conn, ticker, timeframe)
    conn.commit()


def _relink_fvgs(conn: sqlite3.Connection, ticker: str, timeframe: str) -> None:
    """Re-derive every FVG's `related_id` from the stored rows, by detection's
    own rule: an FVG relates to the classic gap created on the same bar in
    the same direction. Done in SQL after each write rather than trusting
    the ids detection minted -- an existing classic row keeps its original
    id on upsert, so a freshly detected FVG would point at an id that was
    never stored, and a pruned classic gap would leave its FVG pointing at
    a deleted row."""
    conn.execute(
        """
        UPDATE gaps SET related_id = (
            SELECT c.id FROM gaps c
            WHERE c.ticker = gaps.ticker AND c.timeframe = gaps.timeframe AND c.kind = 'classic'
              AND c.created_at = gaps.created_at AND c.direction = gaps.direction
        )
        WHERE kind = 'fvg' AND ticker = ? AND timeframe = ?
        """,
        (ticker, timeframe),
    )


def prune_gaps(
    conn: sqlite3.Connection, ticker: str, timeframe: Timeframe | str, gaps: list[Gap], through: str | None = None,
) -> int:
    """Delete stored gaps for (ticker, timeframe) that this run's `gaps` no
    longer contain -- after a bar re-ingest or re-adjustment a gap can stop
    qualifying (its size drops under min_gap_atr) and would otherwise keep
    its old row forever. Only rows created on or before `through` (the
    run's as_of; None = the whole history) are candidates, so an earlier-
    as_of run never deletes gaps that postdate it. Returns rows deleted."""
    timeframe = Timeframe(timeframe)
    keep = {(g.kind.value, g.direction.value, pd.Timestamp(g.created_at).isoformat()) for g in gaps}
    rows = conn.execute(
        "SELECT id, kind, direction, created_at FROM gaps WHERE ticker = ? AND timeframe = ?",
        (ticker, timeframe.value),
    ).fetchall()
    cutoff = pd.Timestamp(through) if through is not None else None
    doomed = [
        r[0] for r in rows
        if (r[1], r[2], pd.Timestamp(r[3]).isoformat()) not in keep
        and (cutoff is None or pd.Timestamp(r[3]) <= cutoff)
    ]
    conn.executemany("DELETE FROM gaps WHERE id = ?", [(i,) for i in doomed])
    if doomed:
        _relink_fvgs(conn, ticker, timeframe.value)
    conn.commit()
    return len(doomed)


def read_gaps(
    conn: sqlite3.Connection, ticker: str, timeframe: Timeframe | str, bars: pd.DataFrame | None = None,
) -> list[Gap]:
    """Stored gaps for (ticker, timeframe) as `Gap` objects, for feeding
    `relevance.gap_states` -- so a backtest over many dates can use the
    stored backfill instead of re-detecting from prices.

    Only the creation-time fields are loaded (zone, kind, direction,
    created_at, size_atr, volume_ratio_at_creation): they're fixed when the
    gap forms, so they're safe for any date after it. The current-state
    lifecycle fields are left at their defaults on purpose -- `gap_states`
    recomputes them per date, and they must never be read for a past one.
    The rows must come from a run with the same `GapConfig` the caller
    passes to `gap_states`, **on the same bar data**: zones are prices, so
    if `bars_1d` has been re-ingested or re-adjusted since the run (e.g.
    yfinance's dividend adjustment rescales all history slightly on each
    new dividend -- AAPL moved ~0.1% within a day in 2026-09), stored zones
    no longer line up with current prices. Pass `bars` (the frame you'll
    give `gap_states`) to check every stored zone against the creation
    bars it came from, and -- when the bars came from the shared loader
    and so carry `attrs["price_basis"]` -- that the rows were computed on
    the same price basis; either mismatch raises StaleGapsError -- rerun
    the detection instead.
    """
    timeframe = Timeframe(timeframe)
    rows = conn.execute(
        "SELECT id, kind, direction, created_at, zone_top, zone_bottom, size_atr, volume_ratio_at_creation, "
        "related_id FROM gaps WHERE ticker = ? AND timeframe = ? ORDER BY created_at",
        (ticker, timeframe.value),
    ).fetchall()
    gaps = [
        Gap(
            id=r[0], ticker=ticker, timeframe=timeframe, kind=GapKind(r[1]), direction=Direction(r[2]),
            created_at=pd.Timestamp(r[3]).isoformat(), zone_top=r[4], zone_bottom=r[5], size_atr=r[6],
            volume_ratio_at_creation=r[7], related_id=r[8],
        )
        for r in rows
    ]
    if bars is not None:
        bars_basis = bars.attrs.get("price_basis")
        if bars_basis is not None:
            stored = stored_price_bases(conn, ticker, timeframe)
            if stored and stored != {bars_basis}:
                raise StaleGapsError(
                    f"{ticker}/{timeframe.value}: stored gaps are on price basis {sorted(stored)}, the bars are "
                    f"{bars_basis!r} -- rerun gaps detection (see docs/decisions/price-basis.md)"
                )
        stale = stale_gap_ids(gaps, bars)
        if stale:
            raise StaleGapsError(
                f"{ticker}/{timeframe.value}: {len(stale)} of {len(gaps)} stored gaps don't match the current "
                "bars (data re-ingested or re-adjusted since the run) -- rerun gaps detection"
            )
    return gaps


class StaleGapsError(ValueError):
    pass


def stored_price_bases(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe | str) -> set[str]:
    """Price bases the stored rows for (ticker, timeframe) were computed on,
    from each row's run settings. Runs from before the setting existed
    loaded the `yfinance` source, i.e. total_return."""
    timeframe = Timeframe(timeframe)
    try:
        rows = conn.execute(
            "SELECT DISTINCT r.config_json FROM gaps g JOIN runs r ON r.run_id = g.run_id "
            "WHERE g.ticker = ? AND g.timeframe = ?",
            (ticker, timeframe.value),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()  # no `runs` table (a bare test DB): nothing to check against
    return {json.loads(r[0] or "{}").get("price_basis", "total_return") for r in rows}


def stale_gap_ids(gaps: list[Gap], bars: pd.DataFrame, rel_tol: float = 1e-6) -> list[str]:
    """Ids of gaps whose zone doesn't equal the bar prices it was detected
    from: a classic gap spans bar t-1's high/low to bar t's low/high, an
    FVG bar t-2's to bar t's (see detect.detect_gaps), so both edges are
    exact prices of known bars. Also flags gaps whose creation date isn't
    a bar at all."""
    idx = bars.index
    high, low = bars["high"].to_numpy(dtype=float), bars["low"].to_numpy(dtype=float)
    close = lambda a, b: abs(a - b) <= rel_tol * max(1.0, abs(b))
    bad = []
    for g in gaps:
        try:
            t = idx.get_loc(pd.Timestamp(g.created_at))
        except KeyError:
            bad.append(g.id)
            continue
        back = 1 if g.kind == GapKind.CLASSIC else 2
        if t - back < 0:
            bad.append(g.id)
            continue
        if g.direction == Direction.BULLISH:
            expected = (high[t - back], low[t])       # (bottom, top)
        else:
            expected = (high[t], low[t - back])
        if not (close(g.zone_bottom, expected[0]) and close(g.zone_top, expected[1])):
            bad.append(g.id)
    return bad
