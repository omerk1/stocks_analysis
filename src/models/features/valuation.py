"""Valuation model features (`docs/fundamentals/plan.md`, step 3, part two):
company financials over the market cap, and the change in the share count.
Row t = close of t.

- `earnings_yield`: trailing four quarters' net income over market cap (E/P).
- `sales_yield`: trailing four quarters' revenue over market cap (S/P).
- `book_to_market`: equity at the latest balance-sheet date over market cap;
  NaN when equity isn't positive.
- `share_change_yoy`: log of the latest known share count over the count
  dated a year before it (the nearest within `SHARE_CHANGE_TOLERANCE` days):
  positive is dilution, negative buybacks. The part of an EPS change that
  net income misses (`fundamentals.sue_net_income`). A log ratio, not a
  percentage: halving and doubling are equally large, and a stock-funded
  merger that multiplies the count doesn't swamp the scale. Mergers and
  spin-offs stay in: issuing stock to buy a company is dilution, and a
  spin-off leaves the parent's count alone.

Yields rather than P/E and P/S: a P/E is undefined at zero earnings and flips
from the most expensive to the cheapest end as earnings cross zero, while
E/P runs through zero continuously, so a loss maker ranks below every
profitable company instead of being dropped.

The market cap is the price that traded on t times the share count known on
t, never an adjusted price level: the close on the traded basis is
split-adjusted (a split after t rescales it), so `market_caps` puts the count
on the same split basis instead, and a later split rescales the two in
opposite ways. The leakage gate's `future_split` perturbation checks that. A share count is known from the session after its filing date (the
date carries no time, and a filing accepted after the close isn't usable on
that close). A count is carried across the splits executed since its date
(each known from its execution day), and a filing that still reports the
pre-split count after a split is bridged as `market_cap.reconcile_market_cap`
does. Like the filings values, a share count goes stale `fundamentals.MAX_AGE_DAYS` after its date.

The share change must not read a split as dilution, but the vendors' splits
also hold spin-offs' price factors (EBAY 2.376 for PayPal, NI, YUM, HPE),
which leave the count alone. So a split between the two counts (or up to
`STALE_FILING_DAYS` before a year-ago count that still reports the pre-split
count) is taken out only where it
explains their change: where the change less the split's log ratio is
smaller than the change itself. That also handles a filing, on either side,
that still reports the pre-split count (no bridge needed), and uses only the
splits executed by the later count's date, never a later one. It misreads a
real change about half a split's size (+-20% across a 3-for-2). Both counts
come from the same source (`load_shares`' SEC or yfinance).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.data_processing import db, market_cap
from src.foundation.data_processing.share_counts import drop_scale_runs
from src.models.features import fundamentals as F

COLUMNS = ("earnings_yield", "sales_yield", "book_to_market", "share_change_yoy")
SHARE_CHANGE_DAYS, SHARE_CHANGE_TOLERANCE = 365, 30
STALE_FILING_DAYS = 120  # a filing up to this long after a split may still report the pre-split count


def _series(g: pd.DataFrame) -> pd.Series:
    s = g.set_index("date")["shares_outstanding"].dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


def load_shares(conn, tickers: list[str], end, splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(ticker, date, shares_outstanding, source) dated up to `end`: SEC EDGAR's
    counts, and yfinance's on a date where SEC filed nothing in the
    `fundamentals.MAX_AGE_DAYS` before (decided on the filing dates alone, so
    from the past only: SEC's series stops early for many multi-class
    issuers, V and MA in 2010; a bad SEC filing that the cleaning below
    drops still holds yfinance off for those days: a gap, never a wrong
    count). Then scale errors (~1e3/1e6 off) and placeholders (under
    1/1,000 of their neighbours) are dropped per source
    (`share_counts.drop_scale_runs`, SEC's judged against yfinance's counts
    as at the SEC ingest). That cleaning judges a ticker's whole series up
    to `end`, with hindsight, and the leakage gate can't see it (it perturbs
    the loaded counts): accepted as a data fix like the SEC ingest's."""
    columns = ["ticker", "date", "shares_outstanding", "source"]
    marks = ", ".join("?" * len(tickers))
    raw = pd.read_sql_query(
        f"SELECT ticker, source, date, shares_outstanding FROM shares_outstanding "
        f"WHERE source IN (?, ?) AND ticker IN ({marks}) AND date <= ?",
        conn, params=[db.SEC_EDGAR, db.YFINANCE, *tickers, str(pd.Timestamp(end).date())], parse_dates=["date"])
    kept = []
    for ticker, g in raw.groupby("ticker", sort=False):
        sec, yf = _series(g[g["source"] == db.SEC_EDGAR]), _series(g[g["source"] == db.YFINANCE])
        factor = lambda s: market_cap.split_factor(s.index, splits.get(ticker))
        reference = yf if len(yf) else None  # all of yfinance's, before the hand-off filter
        if len(sec) and len(yf):
            last_sec = pd.Series(sec.index, index=sec.index).reindex(yf.index, method="ffill")
            yf = yf[~((yf.index - last_sec).dt.days <= F.MAX_AGE_DAYS).to_numpy()]
        if len(yf):
            yf = drop_scale_runs(yf, split_factor=factor(yf))
        if len(sec):
            sec = drop_scale_runs(sec, split_factor=factor(sec), reference=reference)
        for source, s in ((db.SEC_EDGAR, sec), (db.YFINANCE, yf)):
            kept.append(pd.DataFrame({"ticker": ticker, "date": s.index, "shares_outstanding": s.to_numpy(),
                                      "source": source}))
    if not kept:
        return pd.DataFrame(columns=columns)
    return pd.concat(kept, ignore_index=True).sort_values(["ticker", "date"], kind="stable", ignore_index=True)[columns]


def _shares_known(shares: pd.DataFrame, splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per ticker, its counts with the stale post-split filings bridged, each
    known from the first business day after its date. `basis`: the split
    factor at that date (`market_cap.split_factor`), to carry the count
    across the splits between its date and a later day."""
    parts = []
    for ticker, g in shares.groupby("ticker", sort=False):
        s = _series(g)
        events = market_cap._split_ratio_events(splits.get(ticker))
        if len(events):
            s = market_cap._bridge_filing_lag(s, events)
        parts.append(pd.DataFrame({"ticker": ticker, "dated": s.index, "shares": s.to_numpy(),
                                   "basis": market_cap.split_factor(s.index, splits.get(ticker)).to_numpy()}))
    if not parts:
        return pd.DataFrame(columns=["ticker", "dated", "shares", "basis", "known_at"])
    out = F._ns(pd.concat(parts, ignore_index=True), ["dated"])
    return out.assign(known_at=_known_from(out["dated"]))


def _known_from(dated: pd.Series) -> pd.Series:
    """A count dated d is usable from the next session: the date carries no
    time, and the filing may come after the close."""
    return dated + pd.offsets.BDay(1)


def market_caps(rows: pd.DataFrame, shares: pd.DataFrame, splits: dict[str, pd.DataFrame]) -> pd.Series:
    """For each (ticker, date, close) row (close on the traded basis): the
    traded close times the latest share count known that day, carried
    across any split since that count's date (until the next filing a
    2-for-1 would otherwise halve the cap); NaN without a fresh count.

    Traded close = close x f(t) and the carried count = count x f(d) / f(t),
    with f the split factor (`market_cap.split_factor`, the splits after a
    date) and d the count's date, so the cap is close x count x f(d): both
    on today's split basis, which a later split rescales in opposite ways."""
    known = _shares_known(shares, splits).sort_values("known_at", kind="stable")
    left = rows[["ticker", "date"]].assign(row=np.arange(len(rows))).sort_values("date", kind="stable")
    m = pd.merge_asof(left, known[["ticker", "known_at", "dated", "shares", "basis"]], left_on="date",
                      right_on="known_at", by="ticker", direction="backward").sort_values("row")
    fresh = (m["date"] - m["dated"]).dt.days <= F.MAX_AGE_DAYS
    cap = rows["close"].to_numpy(dtype=float) * (m["shares"] * m["basis"]).to_numpy(dtype=float)
    return pd.Series(np.where(fresh, cap, np.nan), index=rows.index)


def share_changes(rows: pd.DataFrame, shares: pd.DataFrame, splits: dict[str, pd.DataFrame]) -> pd.Series:
    """For each (ticker, date) row: `share_change_yoy` from the latest count
    known that day (NaN once it's stale) and the count dated
    `SHARE_CHANGE_DAYS` before it, within `SHARE_CHANGE_TOLERANCE` days, less
    each split between them that explains their change (module docstring).
    Both counts from the same source (`shares` needs `load_shares`' source
    column): SEC's and yfinance's differ for multi-class issuers (one class
    vs all), so the hand-off would read as a change."""
    # as filed, no bridge: the splits are judged below
    s = shares[shares["shares_outstanding"] > 0]
    s = s.assign(dated=pd.to_datetime(s["date"]).astype("M8[ns]")).sort_values("dated", kind="stable")
    s = s.drop_duplicates(["ticker", "source", "dated"], keep="last")
    counts = pd.DataFrame({"ticker": s["ticker"].to_numpy(), "source": s["source"].to_numpy(),
                           "dated": s["dated"].to_numpy(), "known_at": _known_from(s["dated"]).to_numpy(),
                           "level": np.log(s["shares_outstanding"].to_numpy(dtype=float))})
    left = counts.assign(target=counts["dated"] - pd.Timedelta(days=SHARE_CHANGE_DAYS), row=np.arange(len(counts)))
    right = counts[["ticker", "source", "dated", "level"]].rename(columns={"dated": "target", "level": "level_ago"})
    right = right.assign(dated_ago=right["target"])
    m = pd.merge_asof(left.sort_values("target"), right.sort_values("target"), on="target", by=["ticker", "source"],
                      direction="nearest", tolerance=pd.Timedelta(days=SHARE_CHANGE_TOLERANCE)).sort_values("row")
    change = (m["level"] - m["level_ago"]).to_numpy()
    by_ticker = counts.groupby("ticker", sort=False)
    for ticker, at in m.groupby("ticker", sort=False).indices.items():
        if ticker not in splits:
            continue
        ago, now, c = m["dated_ago"].to_numpy()[at], m["dated"].to_numpy()[at], change[at]
        level_ago, source = m["level_ago"].to_numpy()[at], m["source"].to_numpy()[at]
        mine = by_ticker.get_group(ticker)
        for when, ratio in market_cap._split_ratio_events(splits.get(ticker)).items():  # chronological
            # a year-ago count dated up to STALE_FILING_DAYS after the split is judged too,
            # if it still reports the pre-split count (as `market_cap._bridge_filing_lag` tells it)
            before = mine[mine["dated"] < when].groupby("source")["level"].last()
            pre = pd.Series(source).map(before).to_numpy(dtype=float)
            stale = (ago < when + np.timedelta64(STALE_FILING_DAYS, "D")) & (
                np.abs(level_ago - pre) < np.log(market_cap.FILING_LAG_TOLERANCE))
            less = c - np.log(ratio)
            between = ((ago < when) | stale) & (now >= when)
            c = np.where(between & (np.abs(less) < np.abs(c)), less, c)
        change[at] = c
    events = pd.DataFrame({"ticker": m["ticker"].to_numpy(), "known_at": m["known_at"].to_numpy(),
                           "period_end": m["dated"].to_numpy(), "value": change})
    return F._as_of(rows, events)


def panel_features(bars: pd.DataFrame, ctx) -> pd.DataFrame:
    """Every column for every (ticker, date) row of `bars` (long, the traded
    basis): a `registry.PanelSource`. Reads `ctx.fundamentals`, `ctx.shares`
    and `ctx.splits`; NaN where a ticker has none (the share change needs no
    filings)."""
    rows = F._ns(bars[["ticker", "date", "close"]].sort_values(["ticker", "date"], ignore_index=True), ["date"])
    out = rows[["ticker", "date"]].copy()
    for col in COLUMNS:
        out[col] = np.nan
    if ctx.shares is not None and len(ctx.shares):
        out["share_change_yoy"] = share_changes(rows, ctx.shares, ctx.splits or {})
    if ctx.shares is not None and len(ctx.shares) and ctx.fundamentals is not None and len(ctx.fundamentals):
        cap = market_caps(rows, ctx.shares, ctx.splits or {})
        cap = cap.where(cap > 0)
        inputs = F.valuation_inputs(ctx.fundamentals)
        out["earnings_yield"] = F._as_of(rows, inputs["net_income_ttm"]) / cap
        out["sales_yield"] = F._as_of(rows, inputs["revenue_ttm"]) / cap
        equity = F._as_of(rows, inputs["equity"])
        out["book_to_market"] = equity.where(equity > 0) / cap
    out[list(COLUMNS)] = out[list(COLUMNS)].astype("float32")
    return out
