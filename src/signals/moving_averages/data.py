"""Phase 0 data hygiene checks for the moving-averages study (DESIGN.md §3.4).

These sit on top of `market_common.data.validate_bars`, which already covers
hard OHLC-validity checks and its own jump/intraday-range soft-flag pass
shared by every other detector module (see `src/foundation/market_common/
data.py`). What's added here is specific to DESIGN.md §3.4 and not general
enough to belong in that shared loader: flat-run detection (forward-filled
halts), a flat ±50% single-day move flag (DESIGN's own stated threshold,
distinct from `validate_bars`' ratio-based [1/3, 3] check), and the
universe-level delisted-coverage/spot-check audits, which only make sense
against the whole ingested DB, not a single ticker's bar frame.
"""

from __future__ import annotations

import random
import sqlite3

import pandas as pd

# DESIGN.md §3.4: "Returns beyond ±50% in a day flagged and manually reviewed
# (usually bad data or a corporate action)."
LARGE_MOVE_THRESHOLD = 0.5

# Consecutive trading days with an *exactly* identical close before a run is
# flagged as a suspected forward-filled halt. Real trading essentially never
# produces 3+ bit-identical closes in a row; a forward-filled gap does,
# by construction (DESIGN.md §3.4: "no forward-filled prices across halts
# creating flat MA segments").
MIN_FLAT_RUN = 3


def flag_forward_filled_halts(bars: pd.DataFrame, min_run: int = MIN_FLAT_RUN) -> pd.DataFrame:
    """Rows that are part of a run of >= `min_run` consecutive trading days
    with an identical close. Returns the flagged rows with `run_id`/
    `run_length` columns appended; empty (same columns, zero rows) if none
    found. `bars` must have a `close` column, indexed by date.
    """
    if bars.empty:
        return bars.assign(run_id=pd.Series(dtype="int64"), run_length=pd.Series(dtype="int64"))

    close = bars["close"]
    changed = close.ne(close.shift(1)).fillna(True)
    run_id = changed.cumsum()
    run_length = run_id.map(run_id.value_counts())

    flagged = bars.assign(run_id=run_id, run_length=run_length)
    return flagged[flagged["run_length"] >= min_run]


def flag_large_moves(bars: pd.DataFrame, threshold: float = LARGE_MOVE_THRESHOLD) -> pd.DataFrame:
    """Rows where the close-to-close return magnitude exceeds `threshold`
    (DESIGN.md §3.4's ±50% default) -- flagged for manual review, never
    dropped here. `bars` must have a `close` column, indexed by date.
    """
    ret = bars["close"] / bars["close"].shift(1) - 1
    flagged = bars.assign(ret=ret)
    return flagged[ret.abs() > threshold]


def sp500_full_coverage_tickers(
    conn: sqlite3.Connection,
    as_of: str,
    coverage_start: str,
    coverage_end: str,
    source: str = "yfinance",
) -> list[str]:
    """S&P 500 constituents as of `as_of` (point-in-time membership, via
    `index_membership`), restricted to tickers with `bars_1d` coverage
    spanning at least [`coverage_start`, `coverage_end`]. This is the exact
    universe-selection query the moving-averages study's real `build-panel`
    runs use (see `cli.py`'s `--universe sp500` option) -- written here,
    not left in a one-off script, so the 408-ticker universe M4's first
    pass (PREREGISTRATION.md, 2026-09-08) ran against is reproducible from
    committed code.

    Not a general-purpose universe builder -- DESIGN.md §3.2's U1/U2/U3
    tiers aren't buildable yet (Phase 0 found point-in-time market-cap data
    too thin); this is specifically "S&P 500 membership plus a coverage
    floor," a pragmatic stand-in until a real tiered universe exists.
    """
    query = """
        SELECT im.ticker
        FROM index_membership im
        JOIN bars_1d b ON b.ticker = im.ticker AND b.source = ?
        WHERE im.index_name = 'sp500' AND im.start_date <= ?
          AND (im.end_date IS NULL OR im.end_date >= ?)
        GROUP BY im.ticker
        HAVING MIN(b.timestamp) <= ? AND MAX(b.timestamp) >= ?
    """
    rows = conn.execute(query, (source, as_of, as_of, coverage_start, coverage_end)).fetchall()
    return sorted(row[0] for row in rows)


def delisted_coverage_by_year(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per calendar year: how many *delisted* (`tickers.active = 0`)
    tickers have at least one `bars_1d` row that year, across any source.
    DESIGN.md §3.4's sanity check: "Delisted-name count per year is
    non-trivial and roughly matches expectation (if you have zero
    delistings, your data vendor is lying to you)." Empty result means
    zero delisted-ticker price history has ever been ingested -- a
    survivorship-biased universe, per CLAUDE.md's no-dropping-delisted-tickers invariant.
    """
    query = """
        SELECT substr(b.timestamp, 1, 4) AS year, COUNT(DISTINCT b.ticker) AS delisted_tickers_with_bars
        FROM bars_1d b
        JOIN tickers t ON t.ticker = b.ticker
        WHERE t.active = 0
        GROUP BY year
        ORDER BY year
    """
    return pd.read_sql_query(query, conn)


def spot_check_sample(
    conn: sqlite3.Connection, n: int = 20, seed: int = 42, source: str = "yfinance"
) -> pd.DataFrame:
    """A reproducible random sample of `n` (ticker, date) bars for manual
    verification against an external chart provider (DESIGN.md §3.4).
    Uses Python's own `random.Random(seed)` rather than SQLite's unseeded
    `RANDOM()`, so the same `seed` against the same DB content always
    returns the same rows -- one ticker chosen per draw (with a uniformly
    random row within that ticker's history via `COUNT`+`OFFSET`), not a
    global random draw across all rows, so the picked tickers are also
    themselves reproducible and inspectable.
    """
    rng = random.Random(seed)
    tickers = pd.read_sql_query(
        "SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", conn, params=(source,)
    )["ticker"].tolist()
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])

    chosen = rng.sample(tickers, min(n, len(tickers)))
    rows = []
    for ticker in chosen:
        count = conn.execute(
            "SELECT COUNT(*) FROM bars_1d WHERE ticker = ? AND source = ?", (ticker, source)
        ).fetchone()[0]
        if count == 0:
            continue
        offset = rng.randrange(count)
        row = conn.execute(
            """
            SELECT ticker, timestamp, open, high, low, close, volume FROM bars_1d
            WHERE ticker = ? AND source = ? ORDER BY timestamp LIMIT 1 OFFSET ?
            """,
            (ticker, source, offset),
        ).fetchone()
        rows.append(row)

    return pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close", "volume"])
