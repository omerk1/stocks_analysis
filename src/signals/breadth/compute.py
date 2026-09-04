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

WEIGHTING: every metric below is really a weighted aggregate over a date's
members -- `config.weighting="equal"` (the original, still-default
behavior) gives every member weight 1.0, so each formula reduces exactly
to a plain count/mean; `weighting="cap"` weights each member by its real
historical market cap that date instead, via `_load_market_caps`
(`data_processing.market_cap.reconcile_market_cap`, split-reconciled,
using the local splits cache so no live Polygon call is made). A member
with no weight available for a date (cap-weighted: no market-cap data yet,
e.g. before its shares_outstanding history starts) is excluded from both
the numerator and denominator that date, same treatment as an unwarmed-up
SMA -- never silently a wrong 0.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.signals.breadth.config import WEIGHTING_CHOICES, BreadthConfig
from src.foundation.data_processing import db
from src.foundation.data_processing import market_cap
from src.foundation.market_common import indicators

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


def _load_shares_outstanding(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    """Bulk-load `shares_outstanding` for every ticker in `tickers` (one
    query, not one per ticker, same discipline as `_load_closes`) --
    source hardcoded to yfinance, the only source with real historical
    share-count data (see `yfinance_client.get_shares_outstanding`'s
    docstring; Polygon's equivalent isn't authorized on this project's
    plan)."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "shares_outstanding"])
    placeholders = ",".join("?" for _ in tickers)
    query = (
        f"SELECT ticker, date, shares_outstanding FROM shares_outstanding "
        f"WHERE source = ? AND ticker IN ({placeholders}) ORDER BY ticker, date"
    )
    return pd.read_sql_query(query, conn, params=[db.YFINANCE, *tickers], parse_dates=["date"])


def _load_splits(conn: sqlite3.Connection, tickers: list[str]) -> pd.DataFrame:
    """Bulk-load the local `splits` cache for every ticker in `tickers`
    (one query, not one per ticker) -- source hardcoded to Polygon, the
    only wired-up splits source (matches `db.read_splits`'s own default).
    Never a live Polygon call: this reads the cache `bulk_splits_ingest.py`
    already backfilled, exactly what it was built for."""
    if not tickers:
        return pd.DataFrame(columns=["ticker", "execution_date", "split_from", "split_to", "ratio"])
    placeholders = ",".join("?" for _ in tickers)
    query = (
        f"SELECT ticker, execution_date, split_from, split_to, ratio FROM splits "
        f"WHERE source = ? AND ticker IN ({placeholders}) ORDER BY ticker, execution_date"
    )
    return pd.read_sql_query(query, conn, params=[db.POLYGON, *tickers], parse_dates=["execution_date"])


def _load_market_caps(conn: sqlite3.Connection, prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Bulk market cap per (ticker, date) for `tickers` -- long format:
    ticker, date, market_cap. `prices` is the caller's *already-loaded*
    `_load_closes` result (not re-queried here -- `compute_breadth` loads
    it once for the whole run; re-fetching the same close prices a second
    time just for this would double the `bars_1d` read on every cap-
    weighted run for no reason). Two more bulk queries (shares
    outstanding, splits), then `market_cap.reconcile_market_cap` (a pure,
    no-DB-access function) is looped per ticker in Python to do the actual
    split-reconciliation -- not `market_cap.historical_market_cap`, which
    is single-ticker end-to-end (its own `db.read_bars`/
    `db.read_shares_outstanding` calls per invocation) and would reissue
    one query per ticker per table here, exactly the N+1 pattern this
    module's `_load_closes` docstring already rejects.

    A ticker with no shares_outstanding data at all contributes no rows
    (not zero-filled) -- nothing to reconcile against yet.
    """
    if prices.empty:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])

    shares = _load_shares_outstanding(conn, tickers)
    if shares.empty:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])
    splits = _load_splits(conn, tickers)

    shares_by_ticker = {
        ticker: group.set_index("date")["shares_outstanding"]
        for ticker, group in shares.groupby("ticker")
    }
    splits_by_ticker = dict(tuple(splits.groupby("ticker"))) if not splits.empty else {}

    frames = []
    for ticker, price_group in prices.groupby("ticker"):
        ticker_shares = shares_by_ticker.get(ticker)
        if ticker_shares is None or ticker_shares.empty:
            continue
        price_series = price_group.set_index("date")["close"].sort_index()
        reconciled = market_cap.reconcile_market_cap(
            price_series, ticker_shares, splits_by_ticker.get(ticker)
        )
        if reconciled.empty:
            continue
        frames.append(
            pd.DataFrame(
                {"ticker": ticker, "date": reconciled.index, "market_cap": reconciled["market_cap"].to_numpy()}
            )
        )
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])
    return pd.concat(frames, ignore_index=True)


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


def _weighted_fraction(
    condition: pd.Series, valid: pd.Series, weight: pd.Series, date: pd.Series
) -> pd.Series:
    """Weighted mean of boolean `condition` among rows where `valid` is
    True and `weight` isn't NaN -- weight=1.0 everywhere reduces exactly to
    a plain fraction (today's original equal-weight pct_above_sma/ema/
    golden_cross behavior: count(condition)/count(valid))."""
    valid = valid & weight.notna()
    numerator = (condition.astype(float) * weight).where(valid, 0.0).groupby(date).sum()
    denominator = weight.where(valid, 0.0).groupby(date).sum()
    return numerator / denominator.replace(0, np.nan)


def _weighted_sum(condition: pd.Series, valid: pd.Series, weight: pd.Series, date: pd.Series) -> pd.Series:
    """Weighted sum of boolean `condition` among rows where `valid` is True
    and `weight` isn't NaN -- weight=1.0 everywhere reduces exactly to a
    plain count (today's original equal-weight n_advancing/n_declining)."""
    valid = valid & weight.notna()
    return (condition.astype(float) * weight).where(valid, 0.0).groupby(date).sum()


def compute_breadth(
    conn: sqlite3.Connection,
    index_name: str,
    config: BreadthConfig,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """One row per date: % of `index_name`'s point-in-time constituents
    above each configured SMA/EMA, golden-cross breadth (% SMA50 > SMA200),
    and advance/decline -- weighted per `config.weighting` (see this
    module's docstring and BreadthConfig.weighting).

    Returns a DataFrame indexed by date with columns: n_constituents,
    n_with_data (both always unweighted -- a member-count question is
    meaningless to weight), pct_above_sma{period} (per config.sma_periods),
    pct_above_ema{period} (per config.ema_periods), pct_golden_cross
    (only if 50 and 200 are both in sma_periods), n_advancing, n_declining
    (weighted sums -- literal counts under "equal", summed market cap under
    "cap"), net_advances, ad_ratio. Empty if the index has no membership
    rows, or (cap-weighted only) no member has any market-cap data yet.
    """
    if config.weighting not in WEIGHTING_CHOICES:
        raise ValueError(f"Unknown weighting {config.weighting!r} -- expected one of {WEIGHTING_CHOICES}")

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

    if config.weighting == "cap":
        market_caps = _load_market_caps(conn, prices, tickers)
        if market_caps.empty:
            return pd.DataFrame()
        members = members.merge(market_caps, on=["ticker", "date"], how="left")
        members["weight"] = members["market_cap"]
    else:
        members["weight"] = 1.0

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

    weight, date = members["weight"], members["date"]

    for period in config.sma_periods:
        above = members["close"] > members[f"sma{period}"]
        valid = members[f"sma{period}"].notna()
        result[f"pct_above_sma{period}"] = _weighted_fraction(above, valid, weight, date)
    for period in config.ema_periods:
        above = members["close"] > members[f"ema{period}"]
        valid = members[f"ema{period}"].notna()
        result[f"pct_above_ema{period}"] = _weighted_fraction(above, valid, weight, date)

    if _GOLDEN_CROSS_FAST in config.sma_periods and _GOLDEN_CROSS_SLOW in config.sma_periods:
        fast_col, slow_col = f"sma{_GOLDEN_CROSS_FAST}", f"sma{_GOLDEN_CROSS_SLOW}"
        both_valid = members[fast_col].notna() & members[slow_col].notna()
        golden = members[fast_col] > members[slow_col]
        result["pct_golden_cross"] = _weighted_fraction(golden, both_valid, weight, date)
    else:
        result["pct_golden_cross"] = np.nan

    prior_valid = members["prior_close"].notna()
    advancing = members["close"] > members["prior_close"]
    declining = members["close"] < members["prior_close"]
    # Assign first (aligns the groupby result onto result's full date
    # index -- a date with zero rows in `members` at all, not just NaN
    # values, isn't a key in the groupby output and becomes NaN here),
    # *then* fillna -- fillna before this alignment (on the smaller,
    # groupby-only series) wouldn't touch those missing-key dates at all.
    result["n_advancing"] = _weighted_sum(advancing, prior_valid, weight, date)
    result["n_declining"] = _weighted_sum(declining, prior_valid, weight, date)
    result["n_advancing"] = result["n_advancing"].fillna(0)
    result["n_declining"] = result["n_declining"].fillna(0)
    if config.weighting == "equal":
        # Preserve the original equal-weight dtype exactly (plain integer
        # counts) -- cap-weighted sums are real dollar figures, not counts,
        # so they stay float.
        result["n_advancing"] = result["n_advancing"].astype(int)
        result["n_declining"] = result["n_declining"].astype(int)
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
