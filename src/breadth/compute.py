"""Market breadth: % of an index's constituents above key moving averages,
golden-cross breadth, and advance/decline counts -- computed cross-
sectionally (one row per date, aggregated across every index member that
day), unlike sr_lines/gaps/divergences/fibonacci/avwap which each walk one
ticker's bars chronologically.

Point-in-time correct by construction: membership comes from
`data_processing.db.read_index_membership`, which returns dated intervals,
not today's roster -- a ticker that left the index years ago still counts
on the dates it was actually a member, and a ticker that joined late is
excluded before its own start_date. This is the same survivorship-bias
concern `as_of` truncation guards elsewhere in this codebase, just on the
membership axis instead of the price-bar axis.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.breadth.config import BreadthConfig
from src.data_processing import db
from src.market_common import indicators

_GOLDEN_CROSS_FAST = 50
_GOLDEN_CROSS_SLOW = 200


def _load_closes(conn: sqlite3.Connection, tickers: list[str], source: str) -> pd.DataFrame:
    """Bulk-load `bars_1d` close prices for every ticker in `tickers` (one
    query, not one per ticker) -- long format: ticker, date, close.
    Deliberately not date-bounded here -- a moving average needs real prior
    history to be valid, so the caller filters the *output* window after
    computing indicators over each ticker's full available series (same
    "warm up on the full series, slice after" pattern
    `divergences.detect._indicator_pivots` already uses).
    """
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    placeholders = ",".join("?" for _ in tickers)
    query = (
        f"SELECT ticker, timestamp AS date, close FROM bars_1d "
        f"WHERE source = ? AND ticker IN ({placeholders}) ORDER BY ticker, timestamp"
    )
    df = pd.read_sql_query(query, conn, params=[source, *tickers], parse_dates=["date"])
    return df


def _constituent_counts(membership: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """Point-in-time member count per date, derived purely from membership
    intervals -- independent of whether a member actually has price data
    that day (see `n_with_data` in `compute_breadth` for that, separate,
    axis). A sweep-line over interval start/end+1 deltas, cumsum'd and
    forward-filled onto the real trading-calendar `dates`.
    """
    if membership.empty or len(dates) == 0:
        return pd.Series(0, index=dates, dtype=int)
    sentinel_end = dates.max() + pd.Timedelta(days=1)
    end_filled = membership["end_date"].fillna(sentinel_end) + pd.Timedelta(days=1)
    starts = membership["start_date"].value_counts()
    ends = end_filled.value_counts()
    delta = starts.sub(ends, fill_value=0).sort_index()
    timeline = delta.cumsum()
    return timeline.reindex(dates, method="ffill").fillna(0).astype(int)


def compute_breadth(
    conn: sqlite3.Connection,
    index_name: str,
    config: BreadthConfig,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """One row per date: % of `index_name`'s point-in-time constituents
    above each configured SMA/EMA, golden-cross breadth (% SMA50 > SMA200),
    and advance/decline counts. Equal-weighted only -- see BreadthConfig.

    Returns a DataFrame indexed by date with columns: n_constituents,
    n_with_data, pct_above_sma{period} (per config.sma_periods),
    pct_above_ema{period} (per config.ema_periods), pct_golden_cross
    (only if 50 and 200 are both in sma_periods), n_advancing, n_declining,
    net_advances, ad_ratio. Empty if the index has no membership rows.
    """
    membership = db.read_index_membership(conn, index_name)
    if membership.empty:
        return pd.DataFrame()
    membership = membership.copy()
    membership["start_date"] = pd.to_datetime(membership["start_date"])
    membership["end_date"] = pd.to_datetime(membership["end_date"])

    tickers = sorted(membership["ticker"].unique())
    prices = _load_closes(conn, tickers, config.price_source)
    if prices.empty:
        return pd.DataFrame()
    prices = prices.sort_values(["ticker", "date"])

    for period in config.sma_periods:
        prices[f"sma{period}"] = prices.groupby("ticker")["close"].transform(
            lambda s, p=period: indicators.sma(s, p)
        )
    for period in config.ema_periods:
        prices[f"ema{period}"] = prices.groupby("ticker")["close"].transform(
            lambda s, p=period: indicators.ema(s, p)
        )
    prices["prior_close"] = prices.groupby("ticker")["close"].shift(1)

    # Interval join: expand by ticker (a ticker can have multiple
    # non-overlapping membership intervals if it left and rejoined), then
    # keep only rows where the price date actually falls inside that
    # interval -- this both filters to real members and, since intervals
    # are non-overlapping per ticker, never produces a (ticker, date)
    # duplicate.
    merged = prices.merge(membership[["ticker", "start_date", "end_date"]], on="ticker", how="inner")
    in_interval = (merged["date"] >= merged["start_date"]) & (
        merged["end_date"].isna() | (merged["date"] <= merged["end_date"])
    )
    members = merged[in_interval].copy()

    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    n_constituents = _constituent_counts(membership, dates)

    grouped = members.groupby("date")
    result = pd.DataFrame(index=dates)
    result["n_constituents"] = n_constituents
    # Members with an actual bars_1d row that day -- distinct from a given
    # metric's own (smaller-or-equal) valid-data count, e.g. a ticker with
    # only 100 days of history counts here even though its SMA(200) is
    # still NaN; each pct_* column below excludes NaN on its own via
    # `.where(...)`, so it's never inflated by an unwarmed-up ticker.
    result["n_with_data"] = grouped.size()
    result["n_with_data"] = result["n_with_data"].fillna(0).astype(int)

    for period in config.sma_periods:
        above = (members["close"] > members[f"sma{period}"]).where(members[f"sma{period}"].notna())
        result[f"pct_above_sma{period}"] = above.groupby(members["date"]).mean()
    for period in config.ema_periods:
        above = (members["close"] > members[f"ema{period}"]).where(members[f"ema{period}"].notna())
        result[f"pct_above_ema{period}"] = above.groupby(members["date"]).mean()

    if _GOLDEN_CROSS_FAST in config.sma_periods and _GOLDEN_CROSS_SLOW in config.sma_periods:
        fast_col, slow_col = f"sma{_GOLDEN_CROSS_FAST}", f"sma{_GOLDEN_CROSS_SLOW}"
        both_valid = members[fast_col].notna() & members[slow_col].notna()
        golden = (members[fast_col] > members[slow_col]).where(both_valid)
        result["pct_golden_cross"] = golden.groupby(members["date"]).mean()
    else:
        result["pct_golden_cross"] = np.nan

    advancing = (members["close"] > members["prior_close"]).where(members["prior_close"].notna())
    declining = (members["close"] < members["prior_close"]).where(members["prior_close"].notna())
    result["n_advancing"] = advancing.groupby(members["date"]).sum()
    result["n_declining"] = declining.groupby(members["date"]).sum()
    result["n_advancing"] = result["n_advancing"].fillna(0).astype(int)
    result["n_declining"] = result["n_declining"].fillna(0).astype(int)
    result["net_advances"] = result["n_advancing"] - result["n_declining"]
    result["ad_ratio"] = result["n_advancing"] / result["n_declining"].replace(0, np.nan)

    if start is not None:
        result = result[result.index >= pd.Timestamp(start)]
    if end is not None:
        result = result[result.index <= pd.Timestamp(end)]

    return result


def advance_decline_line(breadth: pd.DataFrame) -> pd.Series:
    """Cumulative A/D line over `breadth`'s own date range -- NOT persisted
    (see compute_breadth's module docstring / this module's design notes):
    a stored absolute cumulative value would be wrong on any partial/
    windowed re-run, since its correct value depends on summing from the
    true start of history, not from wherever a given run's `start` happens
    to be. Compute it on demand from a caller's own full result set instead.
    """
    return breadth["net_advances"].cumsum()
