"""Shared PIT-universe machinery for the divergence-context study: index
membership intervals (rename-aware) and the per-event point-in-time
membership filter. One implementation, imported by both step-0 and the
Track-B scripts -- the study's event and control pools both pass through
this filter, which is exactly where two silently-diverging copies would
produce plausible wrong pools.

The rename mapping comes from ticker_renames.apply_renames; that module's
polygon_client dependency is now lazy (constructed only by its own CLI), so
importing the helper no longer needs the `polygon` package.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing.ticker_renames import apply_renames

INDEX_NAMES = ["sp500", "nasdaq100"]

# The study's development window (repo invariant #1: holdout locked after
# 2021-12-31; the start is the loaded active-ticker support, DESIGN §3.3).
# One definition for every consumer that reports or filters on the window --
# it was revised once already (2016 -> 2021) and a buried literal would
# silently keep the old one.
DEV_START = "2010-01-01"
DEV_END = "2021-12-31"


def membership_intervals(raw_conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """{price symbol: [(start, end), ...]} over all study indices,
    rename-aware, delisted members included (end = interval end, never
    today)."""
    intervals = pd.concat(
        [apply_renames(raw_conn, db.read_index_membership(raw_conn, name)) for name in INDEX_NAMES],
        ignore_index=True,
    )
    intervals["start"] = pd.to_datetime(intervals["start_date"])
    intervals["end"] = pd.to_datetime(intervals["end_date"]).fillna(pd.Timestamp.max)
    by_ticker: dict[str, list[tuple]] = {}
    for row in intervals.itertuples(index=False):
        by_ticker.setdefault(row.ticker, []).append((row.start, row.end))
    return by_ticker


def pit_member_mask(frame: pd.DataFrame, by_ticker: dict, date_col: str = "p2_date") -> pd.Series:
    """Boolean Series (aligned to frame.index): was the row's ticker a
    member of any study index on its own `date_col` date."""
    dates = pd.to_datetime(frame[date_col])
    keep = [
        any(s <= ts <= e for s, e in by_ticker.get(t, ()))
        for t, ts in zip(frame["ticker"], dates)
    ]
    return pd.Series(keep, index=frame.index)
