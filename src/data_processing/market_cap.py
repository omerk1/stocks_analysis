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

FILING-LAG BRIDGE: using Polygon's true execution date exposed a *separate*,
pre-existing data-quality gap in `shares_outstanding` itself -- a filing can
be dated on or after a split's true execution date while still holding the
stale, pre-split count (confirmed directly on real AAPL data: the entry
literally dated 2020-08-31, the real split day, still reports the pre-split
4,275,630,080 count; the value doesn't actually update to the post-split
17,102,499,840 until an entry dated 2020-10-22, seven weeks later). Naively
trusting `shares_outstanding` at face value understates `real_market_cap(d)`
by the split ratio for that whole window.

This is fixed by `_bridge_filing_lag`, *not* by reintroducing the removed
statistical split detection: that removed logic had to guess whether a split
happened at all from a noisy jump. Here the split's existence, date, and
exact ratio are already known facts from `PolygonClient.get_splits` -- the
only open question is whether a specific `shares_outstanding` row at/after a
*known* split's execution date has caught up to that already-known fact yet.
For each split, in chronological order, `_bridge_filing_lag` takes the last
raw value before the split as the pre-split baseline, then walks forward
through rows at/after the execution date: as long as a row is still
`scale_consistent` with that baseline (i.e. within `FILING_LAG_TOLERANCE` --
reusing the same instinct as the removed split-jump detector, just at a
tighter threshold since this is a narrower yes/no question with a known
target, not an open-ended "did anything change" scan) it's replaced with
`baseline * ratio`; the first row that's *not* still close to the baseline is
assumed to be the real post-split filing finally landing, and every row from
there on is trusted as-is, un-synthesized.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from src.data_processing import db
from src.data_processing.polygon_client import PolygonClient
from src.market_common.indicators import scale_consistent

# How close a shares_outstanding row at/after a known split's execution date
# can still be to the pre-split baseline before it's trusted as the real,
# caught-up post-split filing. Tighter than the removed split-*detection*
# threshold (1.5) on purpose: real organic quarter-over-quarter drift caps
# out well under this on real data (AAPL 2015-2026: ~1.08x max), and unlike
# detection this only has to distinguish "still near the *known* baseline"
# from "diverged from it" for one specific, already-known split -- no need
# for the wider margin blind jump detection required.
FILING_LAG_TOLERANCE = 1.2


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


def _bridge_filing_lag(
    shares: pd.Series, events: pd.Series, tolerance: float = FILING_LAG_TOLERANCE
) -> pd.Series:
    """Synthesize corrected values for `shares_outstanding` rows that fall
    at/after a known split's execution date but still hold the stale
    pre-split count (see this module's docstring). `shares` must already be
    sorted ascending and NaN-free; `events` is `_split_ratio_events`'s
    output (execution date -> ratio), also sorted ascending.

    Processes splits in chronological order so a later split's baseline
    reflects any earlier correction already applied. A split with no row
    before its execution date (no baseline to compare against) is left
    alone -- nothing to bridge.
    """
    corrected = shares.copy()
    for execution_date, ratio in events.items():
        prior = corrected[corrected.index < execution_date]
        if prior.empty:
            continue
        baseline = prior.iloc[-1]

        for date in corrected.index[corrected.index >= execution_date]:
            if not scale_consistent(corrected.loc[date], baseline, max_ratio=tolerance):
                # Diverged from the pre-split baseline -- the real post-split
                # filing has landed; trust it and everything after it as-is.
                break
            corrected.loc[date] = baseline * ratio
    return corrected


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
    throughout (no data to reconcile against yet). Before that lookup,
    `shares` rows that fall at/after a known split's execution date but
    still hold a stale, not-yet-updated pre-split count are bridged (see
    `_bridge_filing_lag` and this module's docstring) so `market_cap` stays
    continuous across the split rather than dipping during the filing lag.
    """
    prices = prices.dropna().sort_index()
    shares = shares.dropna().sort_index()

    columns = ["market_cap", "shares_outstanding_used", "cumulative_split_ratio"]
    if prices.empty or shares.empty:
        return pd.DataFrame(columns=columns).rename_axis(prices.index.name or "date")

    events = _split_ratio_events(splits)
    shares = _bridge_filing_lag(shares, events)
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
    splits: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """DB-facing wrapper around `reconcile_market_cap`: reads `table`'s
    close prices for `ticker`/`price_source` and `shares_outstanding` for
    `ticker`/`shares_source` from `conn`, aligns everything against
    `ticker`'s split history, and returns the reconciled market-cap
    DataFrame (see `reconcile_market_cap`). Doesn't write anything back to
    `conn`.

    `splits`, if given (e.g. `db.read_splits(conn, ticker)`, from the local
    cache `bulk_splits_ingest.py` builds), is used directly instead of
    fetching live -- skips both the network call and Polygon's free-tier
    5-calls/min rate limit, the real cost of computing this in bulk across
    many tickers. Omitted (the default), falls back to the original
    behavior: one live `polygon_client.get_splits(ticker)` call per
    invocation, uncached.
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

    if splits is None:
        splits = polygon_client.get_splits(ticker)

    return reconcile_market_cap(prices, shares, splits)
