"""Reconciles `bars_1d`'s split-adjusted price series against
`shares_outstanding`'s raw (NOT split-adjusted) share-count history into a
real historical market cap -- the follow-up `db.py`/`yfinance_client.py`
both flagged as not attempted when `shares_outstanding` was added (Done #31).

The reconciliation, derived and verified against real AAPL data around its
2020-08-31 4-for-1 split:

A split multiplies the real share count by the split ratio and divides the
real price by the same ratio (total value is split-invariant at the moment
of a split). `bars_1d`'s stored price at a past date is the real historical
price *divided* by the cumulative split ratio between that date and now (so
it stays comparable to today's price scale). `shares_outstanding`'s stored
count at a past date, by contrast, is the real count that actually existed
then -- never rescaled. So:

    real_market_cap(d) = bars_1d_price(d) * cumulative_split_ratio(d) * raw_shares(d)

where `cumulative_split_ratio(d)` is the product of every split's ratio
that occurred after `d` (up to the most recent data) -- i.e. exactly the
factor needed to scale the already-divided-down stored price back up to
what it really traded at on date `d`.

Splits are detected directly from where `raw_shares` itself jumps by a
large ratio (reusing `market_common.indicators.scale_consistent`'s
same-scale check, at a much tighter threshold tuned for share counts
rather than ATR) -- confirmed on real AAPL data (2015-2026) that ordinary
quarter-over-quarter share-count drift (buybacks/issuance) never exceeds
~1.08x, while the one real split shows up as a clean ~4.0x jump. This
self-corrects for the filing lag `shares_outstanding` has relative to the
true corporate-action date (real AAPL data: the deduplicated raw series
doesn't actually show its jump until 2020-10-22, seven weeks after the
true 2020-08-31 split) -- the split's *detected* date is used consistently
for both the raw-share as-of lookup and the cumulative-ratio cutoff, so the
two always cancel correctly regardless of where that date falls.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.data_processing import db
from src.market_common.indicators import scale_consistent

# Real quarter-over-quarter share-count drift from buybacks/issuance never
# comes close to this on real data (AAPL 2015-2026: max ~1.08x other than
# its one real split); the smallest common split ratio (3-for-2) is 1.5x.
# Sits with real margin below genuine splits and above organic drift.
SPLIT_DETECTION_MIN_RATIO = 1.5


def detect_split_events(shares: pd.Series, min_ratio: float = SPLIT_DETECTION_MIN_RATIO) -> pd.Series:
    """Detect apparent stock-split jumps in a raw shares-outstanding series.

    Returns a Series indexed by the date each jump lands on (the first date
    the post-jump value appears), valued at the raw ratio (post/pre) --
    >1 for a forward split, <1 for a reverse split. Consecutive values that
    aren't `scale_consistent` (i.e. differ by more than `min_ratio`) are
    treated as a split rather than organic share-count change; see this
    module's docstring for why `min_ratio`'s default sits safely between
    the two on real data.
    """
    shares = shares.dropna().sort_index()
    events: dict = {}
    prev_value = None
    for date, value in shares.items():
        if prev_value is not None and not scale_consistent(prev_value, value, max_ratio=min_ratio):
            events[date] = value / prev_value
        prev_value = value
    return pd.Series(events, dtype="float64", name="split_ratio").rename_axis("date")


def _cumulative_split_ratio(dates: pd.Index, events: pd.Series) -> pd.Series:
    """For each date, the product of every detected split's ratio for
    splits occurring strictly after that date -- the factor that scales a
    stored (already-divided-down) price back up to what it really traded
    at on that date."""
    ratio = np.ones(len(dates), dtype="float64")
    for event_date, event_ratio in events.items():
        ratio[dates < event_date] *= event_ratio
    return pd.Series(ratio, index=dates, name="cumulative_split_ratio")


def reconcile_market_cap(
    prices: pd.Series,
    shares: pd.Series,
    min_split_ratio: float = SPLIT_DETECTION_MIN_RATIO,
) -> pd.DataFrame:
    """Pure reconciliation core: given a split-adjusted price series (e.g.
    `bars_1d` close) and a raw, NOT split-adjusted shares-outstanding
    series (e.g. `shares_outstanding`), both indexed by date, return a
    DataFrame indexed by `prices`' dates with columns `market_cap`,
    `shares_outstanding_used` (the raw as-of share count actually applied),
    and `cumulative_split_ratio` (the factor applied to `prices` for that
    date -- 1.0 for dates after the most recent detected split).

    `shares` is sparse (filing dates only) and as-of/forward-filled onto
    `prices`' dates -- a date before `shares`' first filing gets NaN
    throughout (no data to reconcile against yet).
    """
    prices = prices.dropna().sort_index()
    shares = shares.dropna().sort_index()

    columns = ["market_cap", "shares_outstanding_used", "cumulative_split_ratio"]
    if prices.empty or shares.empty:
        return pd.DataFrame(columns=columns).rename_axis(prices.index.name or "date")

    events = detect_split_events(shares, min_ratio=min_split_ratio)
    shares_asof = shares.reindex(prices.index, method="ffill")
    cumulative_ratio = _cumulative_split_ratio(prices.index, events)

    result = pd.DataFrame(
        {
            "market_cap": prices * cumulative_ratio * shares_asof,
            "shares_outstanding_used": shares_asof,
            "cumulative_split_ratio": cumulative_ratio,
        },
        index=prices.index,
    )
    result.index.name = prices.index.name or "date"
    return result


def historical_market_cap(
    conn: sqlite3.Connection,
    ticker: str,
    table: str = "bars_1d",
    price_source: str = db.POLYGON,
    shares_source: str = db.YFINANCE,
    min_split_ratio: float = SPLIT_DETECTION_MIN_RATIO,
) -> pd.DataFrame:
    """DB-facing wrapper around `reconcile_market_cap`: reads `table`'s
    close prices for `ticker`/`price_source` and `shares_outstanding` for
    `ticker`/`shares_source`, aligns them, and returns the reconciled
    market-cap DataFrame (see `reconcile_market_cap`). Read/compute-only --
    doesn't write anything back to `conn`.
    """
    bars = db.read_bars(conn, table, ticker=ticker, source=price_source)
    prices = bars["close"].rename("close")
    prices.index = prices.index.normalize()
    prices.index.name = "date"

    shares_df = db.read_shares_outstanding(conn, ticker, shares_source)
    shares = pd.Series(
        shares_df["shares_outstanding"].to_numpy(),
        index=pd.to_datetime(shares_df["date"]),
        name="shares_outstanding",
    ).rename_axis("date")

    return reconcile_market_cap(prices, shares, min_split_ratio=min_split_ratio)
