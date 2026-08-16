"""Schema creation + upserts for the `sr_lines`/`sr_line_events` tables in
the shared derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap/sr_lines) shares alongside its own result
table(s).

Two tables, not one, unlike the sibling modules: a `Line` carries an
internal `events` list, and the whole point of this persistence layer is
exposing per-event granularity (per-touch penetration/reaction/volume,
per-break reclaim duration) to a downstream model -- burying that in a
JSON blob column would defeat it. `sr_lines` is one row per line, upserted
by natural key; `sr_line_events` is one row per event, wholesale
delete+reinsert per line on every write (an event has no independent
natural key of its own across reruns -- a line's event list is fully
recomputed from scratch every detection run).

Natural key, worked through rather than copied from gaps: a Gap's geometry
is permanently fixed at creation, so gaps' key can just be its creation
bar. A Line's geometry can legitimately drift slightly run-over-run (new
pivots joining an existing horizontal cluster or diagonal inlier set), so
there's no perfectly time-invariant geometry field to key on --
`geometry_bucket` (rounded center or ATR-slope) is a deliberately coarse
disambiguator, not an exact-match key. See `_UPSERT_SQL`'s docstring-style
comment below for why geometry columns, unlike gaps', ARE included in the
`DO UPDATE SET` list.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from src.sr_lines.models import Line

_SR_LINES_SCHEMA = """
CREATE TABLE IF NOT EXISTS sr_lines (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL, timeframe TEXT NOT NULL, preset TEXT NOT NULL,
    kind TEXT NOT NULL,
    first_touch TEXT NOT NULL, origin_side TEXT NOT NULL, geometry_bucket REAL NOT NULL,
    role TEXT NOT NULL, state TEXT NOT NULL,
    center REAL, half_width REAL NOT NULL,
    slope REAL, intercept REAL, origin_index INTEGER, slope_atr_per_bar REAL,
    regime_start TEXT, last_event TEXT,
    age_days_total INTEGER NOT NULL, age_days_regime INTEGER NOT NULL, days_since_last_event INTEGER NOT NULL,
    strength REAL NOT NULL, proximity REAL NOT NULL,
    -- flattened from Line.touch_counts (TouchCounts) -- SQL has no nested
    -- object, so these mirror its fields 1:1 under a touch_/break_ prefix.
    touch_wick INTEGER NOT NULL, touch_body INTEGER NOT NULL, touch_wick_fake INTEGER NOT NULL,
    touch_undercut_and_rally INTEGER NOT NULL, touch_total INTEGER NOT NULL,
    touch_total_from_above INTEGER NOT NULL, touch_total_from_below INTEGER NOT NULL,
    avg_bars_to_reclaim_ur REAL,
    breaks INTEGER NOT NULL, breaks_reclaimed INTEGER NOT NULL,
    touch_breaks_from_above INTEGER NOT NULL, touch_breaks_from_below INTEGER NOT NULL,
    avg_bars_to_reclaim_break REAL, bars_to_reclaim_last_break INTEGER,
    avg_penetration_first_half REAL, avg_penetration_second_half REAL, penetration_trend REAL,
    avg_reaction_atr_touch REAL, avg_volume_ratio_touch REAL, avg_volume_ratio_break REAL,
    diagonal_fit_penalty REAL NOT NULL,
    broken_at TEXT, flipped_at TEXT,
    scores_json TEXT NOT NULL,
    run_id TEXT NOT NULL,
    UNIQUE (ticker, timeframe, preset, kind, first_touch, origin_side, geometry_bucket)
);
"""

_SR_LINE_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sr_line_events (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id TEXT NOT NULL, run_id TEXT NOT NULL, seq INTEGER NOT NULL,
    type TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    penetration_atr REAL NOT NULL, reaction_atr REAL NOT NULL, volume_ratio REAL,
    pending INTEGER NOT NULL,
    reclaimed INTEGER, reclaimed_at TEXT, bars_to_reclaim INTEGER,
    side TEXT
);
"""

_SR_LINE_EVENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sr_line_events_line_id ON sr_line_events(line_id);
"""

_UPSERT_LINE_SQL = """
INSERT INTO sr_lines
    (id, ticker, timeframe, preset, kind, first_touch, origin_side, geometry_bucket,
     role, state, center, half_width, slope, intercept, origin_index, slope_atr_per_bar,
     regime_start, last_event, age_days_total, age_days_regime, days_since_last_event,
     strength, proximity,
     touch_wick, touch_body, touch_wick_fake, touch_undercut_and_rally, touch_total,
     touch_total_from_above, touch_total_from_below,
     avg_bars_to_reclaim_ur, breaks, breaks_reclaimed,
     touch_breaks_from_above, touch_breaks_from_below,
     avg_bars_to_reclaim_break, bars_to_reclaim_last_break,
     avg_penetration_first_half, avg_penetration_second_half, penetration_trend,
     avg_reaction_atr_touch, avg_volume_ratio_touch, avg_volume_ratio_break,
     diagonal_fit_penalty, broken_at, flipped_at, scores_json, run_id)
VALUES
    (:id, :ticker, :timeframe, :preset, :kind, :first_touch, :origin_side, :geometry_bucket,
     :role, :state, :center, :half_width, :slope, :intercept, :origin_index, :slope_atr_per_bar,
     :regime_start, :last_event, :age_days_total, :age_days_regime, :days_since_last_event,
     :strength, :proximity,
     :touch_wick, :touch_body, :touch_wick_fake, :touch_undercut_and_rally, :touch_total,
     :touch_total_from_above, :touch_total_from_below,
     :avg_bars_to_reclaim_ur, :breaks, :breaks_reclaimed,
     :touch_breaks_from_above, :touch_breaks_from_below,
     :avg_bars_to_reclaim_break, :bars_to_reclaim_last_break,
     :avg_penetration_first_half, :avg_penetration_second_half, :penetration_trend,
     :avg_reaction_atr_touch, :avg_volume_ratio_touch, :avg_volume_ratio_break,
     :diagonal_fit_penalty, :broken_at, :flipped_at, :scores_json, :run_id)
ON CONFLICT (ticker, timeframe, preset, kind, first_touch, origin_side, geometry_bucket) DO UPDATE SET
    -- Deliberate deviation from gaps' upsert pattern: gaps excludes
    -- geometry columns from SET because a gap's geometry never changes
    -- after creation. A Line's geometry (center/half_width/slope/etc) CAN
    -- legitimately evolve slightly run-over-run as new pivots join an
    -- existing cluster/inlier set -- included here on purpose, not an
    -- oversight.
    role = excluded.role, state = excluded.state,
    center = excluded.center, half_width = excluded.half_width,
    slope = excluded.slope, intercept = excluded.intercept,
    origin_index = excluded.origin_index, slope_atr_per_bar = excluded.slope_atr_per_bar,
    regime_start = excluded.regime_start, last_event = excluded.last_event,
    age_days_total = excluded.age_days_total, age_days_regime = excluded.age_days_regime,
    days_since_last_event = excluded.days_since_last_event,
    strength = excluded.strength, proximity = excluded.proximity,
    touch_wick = excluded.touch_wick, touch_body = excluded.touch_body,
    touch_wick_fake = excluded.touch_wick_fake,
    touch_undercut_and_rally = excluded.touch_undercut_and_rally, touch_total = excluded.touch_total,
    touch_total_from_above = excluded.touch_total_from_above,
    touch_total_from_below = excluded.touch_total_from_below,
    avg_bars_to_reclaim_ur = excluded.avg_bars_to_reclaim_ur,
    breaks = excluded.breaks, breaks_reclaimed = excluded.breaks_reclaimed,
    touch_breaks_from_above = excluded.touch_breaks_from_above,
    touch_breaks_from_below = excluded.touch_breaks_from_below,
    avg_bars_to_reclaim_break = excluded.avg_bars_to_reclaim_break,
    bars_to_reclaim_last_break = excluded.bars_to_reclaim_last_break,
    avg_penetration_first_half = excluded.avg_penetration_first_half,
    avg_penetration_second_half = excluded.avg_penetration_second_half,
    penetration_trend = excluded.penetration_trend,
    avg_reaction_atr_touch = excluded.avg_reaction_atr_touch,
    avg_volume_ratio_touch = excluded.avg_volume_ratio_touch,
    avg_volume_ratio_break = excluded.avg_volume_ratio_break,
    diagonal_fit_penalty = excluded.diagonal_fit_penalty,
    broken_at = excluded.broken_at, flipped_at = excluded.flipped_at,
    scores_json = excluded.scores_json, run_id = excluded.run_id
RETURNING id
"""

_EVENT_INSERT_SQL = """
INSERT INTO sr_line_events
    (line_id, run_id, seq, type, start, end, penetration_atr, reaction_atr, volume_ratio,
     pending, reclaimed, reclaimed_at, bars_to_reclaim, side)
VALUES
    (:line_id, :run_id, :seq, :type, :start, :end, :penetration_atr, :reaction_atr, :volume_ratio,
     :pending, :reclaimed, :reclaimed_at, :bars_to_reclaim, :side)
"""


def create_sr_lines_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_SR_LINES_SCHEMA)
    conn.execute(_SR_LINE_EVENTS_SCHEMA)
    conn.execute(_SR_LINE_EVENTS_INDEX)
    conn.commit()


def _geometry_bucket(line: Line) -> float:
    if line.kind.value == "horizontal":
        return round(line.center, 2)
    return round(line.slope_atr_per_bar, 2)


def _line_row(line: Line, ticker: str, timeframe: str, preset: str, run_id: str) -> dict:
    tc = line.touch_counts
    return {
        "id": str(uuid.uuid4()),
        "ticker": ticker, "timeframe": timeframe, "preset": preset,
        "kind": line.kind.value,
        "first_touch": line.first_touch,
        # A zone that was never clearly approached from either side (see
        # events.classify_events' own docstring) leaves origin_side=None --
        # coalesced here since the natural key column is NOT NULL. Rare
        # edge case, not expected on any real detected line.
        "origin_side": line.origin_side or "unknown",
        "geometry_bucket": _geometry_bucket(line),
        "role": line.role.value, "state": line.state.value,
        "center": line.center, "half_width": line.half_width,
        "slope": line.slope, "intercept": line.intercept, "origin_index": line.origin_index,
        "slope_atr_per_bar": line.slope_atr_per_bar,
        "regime_start": line.regime_start, "last_event": line.last_event,
        "age_days_total": line.age_days_total, "age_days_regime": line.age_days_regime,
        "days_since_last_event": line.days_since_last_event,
        "strength": line.strength, "proximity": line.proximity,
        "touch_wick": tc.wick, "touch_body": tc.body, "touch_wick_fake": tc.wick_fake,
        "touch_undercut_and_rally": tc.undercut_and_rally, "touch_total": tc.total,
        "touch_total_from_above": tc.total_from_above, "touch_total_from_below": tc.total_from_below,
        "avg_bars_to_reclaim_ur": tc.avg_bars_to_reclaim_ur,
        "breaks": tc.breaks, "breaks_reclaimed": tc.breaks_reclaimed,
        "touch_breaks_from_above": tc.breaks_from_above, "touch_breaks_from_below": tc.breaks_from_below,
        "avg_bars_to_reclaim_break": tc.avg_bars_to_reclaim_break,
        "bars_to_reclaim_last_break": tc.bars_to_reclaim_last_break,
        "avg_penetration_first_half": line.avg_penetration_first_half,
        "avg_penetration_second_half": line.avg_penetration_second_half,
        "penetration_trend": line.penetration_trend,
        "avg_reaction_atr_touch": line.avg_reaction_atr_touch,
        "avg_volume_ratio_touch": line.avg_volume_ratio_touch,
        "avg_volume_ratio_break": line.avg_volume_ratio_break,
        "diagonal_fit_penalty": line.diagonal_fit_penalty,
        "broken_at": line.broken_at, "flipped_at": line.flipped_at,
        "scores_json": json.dumps(line.scores.to_dict()),
        "run_id": run_id,
    }


def _event_row(line_id: str, run_id: str, seq: int, event) -> dict:
    return {
        "line_id": line_id, "run_id": run_id, "seq": seq,
        "type": event.type.value, "start": event.start, "end": event.end,
        "penetration_atr": event.penetration_atr, "reaction_atr": event.reaction_atr,
        "volume_ratio": event.volume_ratio,
        "pending": int(event.pending),
        "reclaimed": None if event.reclaimed is None else int(event.reclaimed),
        "reclaimed_at": event.reclaimed_at, "bars_to_reclaim": event.bars_to_reclaim,
        "side": event.side,
    }


def upsert_lines(
    conn: sqlite3.Connection, lines: list[Line], ticker: str, timeframe: str, preset: str, run_id: str
) -> None:
    """Insert new line rows / refresh mutable fields (including geometry --
    see `_UPSERT_LINE_SQL`'s comment) on existing ones, keyed by the table's
    UNIQUE natural key. Each line's `sr_line_events` rows are always
    wholesale deleted and reinserted, keyed off the *persisted* id (the
    freshly-minted uuid4 on first insert, or the pre-existing row's id on
    conflict -- `RETURNING id` is what makes that distinction possible
    without a separate SELECT round-trip first).
    """
    for line in lines:
        row = _line_row(line, ticker, timeframe, preset, run_id)
        persisted_id = conn.execute(_UPSERT_LINE_SQL, row).fetchone()[0]
        conn.execute("DELETE FROM sr_line_events WHERE line_id = ?", (persisted_id,))
        conn.executemany(
            _EVENT_INSERT_SQL,
            [_event_row(persisted_id, run_id, seq, e) for seq, e in enumerate(line.events)],
        )
    conn.commit()
