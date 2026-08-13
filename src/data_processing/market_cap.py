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

Splits come from Polygon's `/v3/reference/splits` reference endpoint
(`PolygonClient.get_splits`) -- real ground truth (exact execution date and
ratio), not inferred. An earlier version of this module instead inferred
splits statistically from where `shares_outstanding` itself jumps by a
large ratio; that worked, but anchored the split to whatever date
`shares_outstanding`'s filing lag happened to surface the jump on rather
than the true corporate-action date (real AAPL data: the deduplicated raw
share-count series doesn't show the jump until 2020-10-22, seven weeks
after the true 2020-08-31 split). Polygon's splits data has no such lag and
isn't a paid-tier-gated endpoint, so that inference was removed rather than
kept as a second, parallel source of truth -- see `tests/test_market_cap.py`
for the old statistical approach, repurposed there as a regression fixture
proving this explicit-data path reproduces the same validated results.

KNOWN CAVEAT, surfaced by this switch and confirmed on real AAPL data: using
Polygon's true execution date exposes a *separate*, pre-existing data-quality
gap in `shares_outstanding` itself that the old statistical-inference
approach had accidentally been masking. `raw_shares(d)` is an as-of/
forward-filled lookup of whatever `shares_outstanding` last reported on or
before `d` -- but a filing can be dated on or after a split's true execution
date while still holding the stale, pre-split count (confirmed directly:
AAPL's `shares_outstanding` entry literally dated 2020-08-31, its real split
day, still reports the pre-split 4,275,630,080 count; the value doesn't
actually update to the post-split 17,102,499,840 until an entry dated
2020-10-22). Since `cumulative_split_ratio(d)` now correctly flips to 1.0
starting at the *true* 2020-08-31 execution date while `raw_shares(d)` stays
stuck at the stale pre-split count until 2020-10-22, `real_market_cap(d)` is
understated by exactly the split ratio for that whole window -- a real,
reproducible artifact, not a formula bug (the old inferred-date approach
avoided this specific symptom only because it derived the split's "date"
from that same lagged jump in the first place, so both sides of the
formula were laggy together and cancelled by coincidence, not because it
was more correct). Fixing this would require value-level validation of
`shares_outstanding` entries against Polygon's known split ratios -- exactly
the kind of raw-shares statistical inspection this module deliberately
avoids as a *detection* mechanism now, so it's left as a known, tested
(`test_reconcile_market_cap_understates_during_a_real_style_filing_lag_window`)
limitation rather than patched here.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.data_processing import db
from src.data_processing.polygon_client import PolygonClient


def _split_ratio_events(splits: pd.DataFrame) -> pd.Series:
    """Shape a splits DataFrame (as returned by `PolygonClient.get_splits`
    -- columns `execution_date`/`ratio`, at minimum) into a Series indexed
    by execution date and valued at ratio -- what `_cumulative_split_ratio`
    consumes."""
    if splits is None or splits.empty:
        return pd.Series(dtype="float64", name="ratio").rename_axis("execution_date")
    return (
        pd.Series(
            splits["ratio"].to_numpy(),
            index=pd.DatetimeIndex(splits["execution_date"]),
            name="ratio",
        )
        .rename_axis("execution_date")
        .sort_index()
    )


def _cumulative_split_ratio(dates: pd.Index, events: pd.Series) -> pd.Series:
    """For each date, the product of every split's ratio for splits
    occurring strictly after that date -- the factor that scales a stored
    (already-divided-down) price back up to what it really traded at on
    that date."""
    ratio = np.ones(len(dates), dtype="float64")
    for event_date, event_ratio in events.items():
        ratio[dates < event_date] *= event_ratio
    return pd.Series(ratio, index=dates, name="cumulative_split_ratio")


def reconcile_market_cap(
    prices: pd.Series,
    shares: pd.Series,
    splits: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Pure reconciliation core: given a split-adjusted price series (e.g.
    `bars_1d` close), a raw, NOT split-adjusted shares-outstanding series
    (e.g. `shares_outstanding`), both indexed by date, and a splits
    DataFrame (e.g. `PolygonClient.get_splits`'s output -- columns
    `execution_date`/`ratio` at minimum), return a DataFrame indexed by
    `prices`' dates with columns `market_cap`, `shares_outstanding_used`
    (the raw as-of share count actually applied), and
    `cumulative_split_ratio` (the factor applied to `prices` for that date
    -- 1.0 for dates after the most recent split, or throughout if `splits`
    is empty/None).

    `shares` is sparse (filing dates only) and as-of/forward-filled onto
    `prices`' dates -- a date before `shares`' first filing gets NaN
    throughout (no data to reconcile against yet).
    """
    prices = prices.dropna().sort_index()
    shares = shares.dropna().sort_index()

    columns = ["market_cap", "shares_outstanding_used", "cumulative_split_ratio"]
    if prices.empty or shares.empty:
        return pd.DataFrame(columns=columns).rename_axis(prices.index.name or "date")

    events = _split_ratio_events(splits)
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
    polygon_client: PolygonClient,
    table: str = "bars_1d",
    price_source: str = db.POLYGON,
    shares_source: str = db.YFINANCE,
) -> pd.DataFrame:
    """DB-facing wrapper around `reconcile_market_cap`: reads `table`'s
    close prices for `ticker`/`price_source` and `shares_outstanding` for
    `ticker`/`shares_source` from `conn`, fetches `ticker`'s real split
    history live via `polygon_client.get_splits` (a network call -- the
    only reason this wrapper needs a client passed in, unlike a pure
    DB read), aligns everything, and returns the reconciled market-cap
    DataFrame (see `reconcile_market_cap`). Doesn't write anything back to
    `conn` or cache the splits call.
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

    splits = polygon_client.get_splits(ticker)

    return reconcile_market_cap(prices, shares, splits)
