"""Schema creation + upserts for the `divergences` table in the shared
derived-results DB (`data/derived/analysis.sqlite`) -- see
`market_common.derived_db` for the `runs` table every module (gaps/
divergences/fibonacci/avwap) shares alongside its own result table.
"""

from __future__ import annotations

import json
import sqlite3

from src.foundation.market_common.price_basis import (
    MODULE_PRICE_BASIS,
    resolve_sources,
    source_for,
    source_members,
)
from src.signals.divergences.models import Divergence

# The vendor a legacy run (recorded before `bar_source` existed) read: the
# primary source, by construction -- no fallback existed then.
PRIMARY_SOURCE = source_for(MODULE_PRICE_BASIS["divergences"])

_DIVERGENCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS divergences (
    id TEXT PRIMARY KEY,
    ticker TEXT, timeframe TEXT, indicator TEXT,
    direction TEXT, form TEXT DEFAULT 'regular',
    p1_date TEXT, p2_date TEXT,
    p1_price REAL, p2_price REAL,
    i1_value REAL, i2_value REAL,
    strength REAL,
    duration_bars INTEGER, price_move_atr REAL, indicator_gap_raw REAL,
    appeared_at TEXT, confirmed_at TEXT,
    max_favorable_move_atr REAL, bars_to_max_favorable_move INTEGER,
    invalidated INTEGER, invalidated_at TEXT, outcome_computed_through TEXT,
    confluence_count INTEGER, agreeing_indicators TEXT,
    run_id TEXT,
    UNIQUE (ticker, timeframe, indicator, direction, p2_date)
);
"""

_UPSERT_SQL = """
INSERT INTO divergences
    (id, ticker, timeframe, indicator, direction, form, p1_date, p2_date,
     p1_price, p2_price, i1_value, i2_value, strength,
     duration_bars, price_move_atr, indicator_gap_raw, appeared_at, confirmed_at,
     max_favorable_move_atr, bars_to_max_favorable_move,
     invalidated, invalidated_at, outcome_computed_through,
     confluence_count, agreeing_indicators, run_id)
VALUES
    (:id, :ticker, :timeframe, :indicator, :direction, :form, :p1_date, :p2_date,
     :p1_price, :p2_price, :i1_value, :i2_value, :strength,
     :duration_bars, :price_move_atr, :indicator_gap_raw, :appeared_at, :confirmed_at,
     :max_favorable_move_atr, :bars_to_max_favorable_move,
     :invalidated, :invalidated_at, :outcome_computed_through,
     :confluence_count, :agreeing_indicators, :run_id)
ON CONFLICT (ticker, timeframe, indicator, direction, p2_date) DO UPDATE SET
    -- form is NOT in the natural key: a given (indicator, direction,
    -- p2_date) corresponds to one consecutive price-pivot pair per run,
    -- and a pair resolves to at most one form (see detect._evaluate_pairs).
    -- It IS mutable here: an extreme_equality_tolerance_atr config change
    -- can legitimately flip which form a near-equal-extremes pair reads as.
    form = excluded.form,
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
    -- Cluster membership can change across a rerun (a differently-scoped
    -- config.indicators list, or an as_of change altering which same-swing
    -- rows are even visible) -- same mutability bucket as the outcome
    -- fields just above.
    confluence_count = excluded.confluence_count,
    agreeing_indicators = excluded.agreeing_indicators,
    run_id = excluded.run_id
"""


def create_divergences_table(conn: sqlite3.Connection) -> None:
    conn.execute(_DIVERGENCES_SCHEMA)
    _migrate_add_columns(conn)
    conn.commit()


# Columns that postdate the original schema, in the order they were added
# -- same pure-addition ALTER TABLE pattern as gaps/avwap's stores. Found
# the hard way (2026-10-04, first full-universe backfill): the shared
# derived DB's live table predated the confluence columns (Done #44), so
# an upsert naming them failed on EVERY ticker while the fresh-table
# CREATE path -- the only one the tests exercised -- worked. A live table
# can be arbitrarily old; the migration must cover every post-original
# column, not just the newest one.
#
# Defaults match each column's dataclass contract: confluence_count=1
# ("always set, never None" -- a solo divergence IS a cluster of one);
# form='regular' (the only form the module could detect before hidden
# detection existed). Constant DEFAULTs rather than one-shot backfill
# UPDATEs, because pre-migration code from another checkout can keep
# inserting column-omitting rows after this migration has already run.
_MIGRATED_COLUMNS: dict[str, str] = {
    "confluence_count": "INTEGER DEFAULT 1",   # Done #44
    "agreeing_indicators": "TEXT",             # Done #44
    "form": "TEXT DEFAULT 'regular'",          # hidden-divergence detection
}


def _migrate_add_columns(conn: sqlite3.Connection) -> None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(divergences)")}
    for name, sql_type in _MIGRATED_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE divergences ADD COLUMN {name} {sql_type}")
    # Contract repair, idempotent, run on every bootstrap: models.py
    # promises agreeing_indicators is never None (a solo row carries its
    # own indicator's name), but a column-omitting insert from a pre-#44
    # checkout gets confluence_count's DEFAULT 1 with NULL here -- a
    # constant DEFAULT can't reference another column, so the repair has
    # to be an UPDATE.
    conn.execute(
        "UPDATE divergences SET agreeing_indicators = indicator WHERE agreeing_indicators IS NULL"
    )


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


def recorded_run_sources(
    derived_conn: sqlite3.Connection, timeframe: str, ticker: str | None = None
) -> dict[str, str]:
    """ticker -> the `bars_1d.source` its LATEST detection run read, from the
    runs table's config_json (`bar_source`, recorded since the vendor
    fallback landed). A run predating that record read the primary source by
    construction (no fallback existed), so a missing key means "legacy
    primary" and the CALLER substitutes its primary source -- returning it
    here would require this module to know the basis.

    This is what makes vendor drift visible: a ticker whose resolved source
    today differs from the one its stored events were detected on must be
    re-scanned (replace, not upsert -- pivots shift between vendors, and an
    upsert by natural key would leave a mixed-vendor event base)."""
    out: dict[str, str] = {}
    sql = "SELECT ticker, config_json FROM runs WHERE module = 'divergences' AND timeframe = ?"
    params: tuple = (timeframe,)
    if ticker is not None:  # single-ticker callers: don't parse the whole table
        sql += " AND ticker = ?"
        params += (ticker,)
    rows = derived_conn.execute(sql + " ORDER BY started_at", params).fetchall()
    for ticker, config_json in rows:  # later rows overwrite: latest run wins
        source = None
        if config_json and '"bar_source"' in config_json:
            source = json.loads(config_json).get("bar_source")
        out[ticker] = source
    return out


def purge_ticker(derived_conn: sqlite3.Connection, ticker: str, timeframe: str) -> int:
    """Delete a ticker's stored divergences AND their context rows for one
    timeframe (the control pairs are replace-per-ticker in their own
    builder). Used when a ticker's resolved vendor changed since its events
    were stored (the old rows describe pivots on another vendor's prices
    and must not survive next to the rescan's), and by the opt-in
    --purge-unresolved. Returns rows deleted from `divergences`. Commits
    nothing itself; the CLI's vendor-change path calls it only after the
    new vendor's detection succeeded, and the following `record_run`
    commits the purge together with the new run row."""
    n = derived_conn.execute(
        "DELETE FROM divergences WHERE ticker = ? AND timeframe = ?", (ticker, timeframe)
    ).rowcount
    if _table_exists(derived_conn, "divergence_context"):
        derived_conn.execute(
            "DELETE FROM divergence_context WHERE ticker = ? AND timeframe = ?", (ticker, timeframe)
        )
    return n


def vendor_changed(recorded: dict, ticker: str, resolved_source: str) -> bool:
    """True when the ticker HAS prior detection runs and their bars came
    from a different vendor than today's resolution (a legacy run with no
    recorded `bar_source` counts as PRIMARY_SOURCE). Such a ticker's stored
    events describe pivots on another vendor's prices: detection replaces
    them (never upserts -- pivots shift between vendors and the natural-key
    upsert would leave a mixed-vendor event base), and the context/controls
    builders treat it as stale until it has. One definition for the CLI and
    both builders."""
    if ticker not in recorded:
        return False
    return (recorded[ticker] or PRIMARY_SOURCE) != resolved_source


def stored_tickers(derived_conn: sqlite3.Connection, timeframe: str) -> set[str]:
    """Every ticker with at least one stored divergence on `timeframe`."""
    return {
        r[0] for r in derived_conn.execute(
            "SELECT DISTINCT ticker FROM divergences WHERE timeframe = ?", (timeframe,)
        )
    }


# Below this many tickers the per-ticker bar probe beats listing every
# source (a DISTINCT index scan of the 4GB bars_1d, minutes each).
MEMBERS_THRESHOLD = 500


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def forget_ticker(derived_conn: sqlite3.Connection, ticker: str, timeframe: str) -> int:
    """`purge_ticker` plus the ticker's control pairs and its divergence
    `runs` rows: the module forgets it ever scanned the ticker. For tickers
    that no longer resolve (--purge-unresolved): keeping the runs rows would
    leave it "already scanned" with no events -- skipped by --missing-only if
    its dispute is lifted, and fed to the controls builder (whose universe is
    the runs table) as a ticker with no divergences anywhere. Commits nothing.
    Returns rows deleted from `divergences`."""
    n = purge_ticker(derived_conn, ticker, timeframe)
    if _table_exists(derived_conn, "divergence_control_pairs"):
        derived_conn.execute(
            "DELETE FROM divergence_control_pairs WHERE ticker = ? AND timeframe = ?", (ticker, timeframe)
        )
    derived_conn.execute(
        "DELETE FROM runs WHERE module = 'divergences' AND ticker = ? AND timeframe = ?", (ticker, timeframe)
    )
    return n


def purge_flagged(derived_conn: sqlite3.Connection, table: str, flagged: dict[str, str],
                  timeframe: str, logger) -> tuple[int, int]:
    """The context/controls builders' shared handling of `builder_sources`'
    flagged tickers: delete the builder's own rows for each, warn, and
    return (n_unresolved, n_vendor_stale)."""
    counts = {"unresolved": 0, "vendor_stale": 0}
    for ticker, why in flagged.items():
        n = derived_conn.execute(
            f"DELETE FROM {table} WHERE ticker = ? AND timeframe = ?", (ticker, timeframe)
        ).rowcount
        logger.warning("%s: %s -- purged %d stale %s row(s)%s", ticker, why, n, table,
                       "; rescan detection first" if why == "vendor_stale" else "")
        counts[why] += 1
    derived_conn.commit()
    return counts["unresolved"], counts["vendor_stale"]


def builder_sources(raw_conn: sqlite3.Connection, derived_conn: sqlite3.Connection, tickers: list[str],
                    basis, fallback: bool, timeframe: str) -> tuple[dict[str, str], dict[str, str]]:
    """(ticker -> resolved source, ticker -> 'unresolved' | 'vendor_stale')
    for the context and control-pair builders -- one shared rule so the
    two derived stores can't disagree about which tickers they may compute.

    Resolution lists each source once (`members`) only for large ticker
    lists (MEMBERS_THRESHOLD); small builds keep the cheap per-ticker probe.
    Vendor staleness is judged against `timeframe`'s own runs. A ticker that doesn't resolve (whole-history
    dispute or no bars) is 'unresolved'; one whose resolved vendor differs
    from the vendor its stored events were detected on is 'vendor_stale'
    (computing on the new vendor against the old vendor's pivots would be a
    silent cross-vendor mismatch). The builders DELETE their own rows for
    both kinds -- keeping them would turn replace-per-ticker into
    keep-stale for exactly the tickers that went wrong -- and skip them."""
    big = fallback and len(tickers) > MEMBERS_THRESHOLD
    members = source_members(raw_conn, basis, fallback) if big else None
    sources = resolve_sources(raw_conn, tickers, basis, fallback, members=members)
    recorded = recorded_run_sources(derived_conn, timeframe)
    flagged: dict[str, str] = {}
    for t in tickers:
        if t not in sources:
            flagged[t] = "unresolved"
        elif vendor_changed(recorded, t, sources[t]):
            flagged[t] = "vendor_stale"
    return sources, flagged
