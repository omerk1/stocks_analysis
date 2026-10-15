"""Valuation model features (`docs/fundamentals/plan.md`, step 3, part two):
company financials over the market cap. Row t = close of t.

- `earnings_yield`: trailing four quarters' net income over market cap (E/P).
- `sales_yield`: trailing four quarters' revenue over market cap (S/P).
- `book_to_market`: equity at the latest balance-sheet date over market cap;
  NaN when equity isn't positive.

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
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.data_processing import db, market_cap
from src.foundation.data_processing.share_counts import drop_scale_runs
from src.models.features import fundamentals as F

COLUMNS = ("earnings_yield", "sales_yield", "book_to_market")


def _series(g: pd.DataFrame) -> pd.Series:
    s = g.set_index("date")["shares_outstanding"].dropna().sort_index()
    return s[~s.index.duplicated(keep="last")]


def load_shares(conn, tickers: list[str], end, splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(ticker, date, shares_outstanding) dated up to `end`: SEC EDGAR's
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
    columns = ["ticker", "date", "shares_outstanding"]
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
        s = pd.concat([sec, yf]).sort_index()
        kept.append(pd.DataFrame({"ticker": ticker, "date": s.index, "shares_outstanding": s.to_numpy()}))
    return pd.concat(kept, ignore_index=True)[columns] if kept else pd.DataFrame(columns=columns)


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
    return out.assign(known_at=out["dated"] + pd.offsets.BDay(1))


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


def panel_features(bars: pd.DataFrame, ctx) -> pd.DataFrame:
    """Every column for every (ticker, date) row of `bars` (long, the traded
    basis): a `registry.PanelSource`. Reads `ctx.fundamentals`, `ctx.shares`
    and `ctx.splits`; NaN where a ticker has none."""
    rows = F._ns(bars[["ticker", "date", "close"]].sort_values(["ticker", "date"], ignore_index=True), ["date"])
    out = rows[["ticker", "date"]].copy()
    for col in COLUMNS:
        out[col] = np.nan
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
