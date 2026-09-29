"""Point-in-time detection of "irrelevant history" -- the part of a
ticker's past that no longer describes the company trading today.

Motivating case: GEVO's split-adjusted 2011 high is $158,160 against a
~$1.50 close, after 6,000x of cumulative reverse splits. An all-time-high
anchor there is meaningless, and its penny-stock years aren't something a
model should learn from as if they were normal trading.

Two separate outputs, because the two uses need different things:

1. `anchor_start_date` -- where anchor discovery (AVWAP, volume profile)
   should start looking. The latest reverse split executed while the
   stock actually traded below `penny_price` (a split done to stay listed,
   not a late 1-for-10 in an established company -- AMC 2023 and SIRI 2024
   don't qualify), provided at least `min_days_after_reset` of history has
   followed it. Hand-reviewed exceptions live in
   `history_break_overrides.HISTORY_RESET_OVERRIDES`.

2. `training_eligibility` -- a per-date flag, never a deletion. A date is
   ineligible if, as of that date: the actual traded (split-unadjusted)
   close was below `penny_price`; a reverse split happened within the last
   `reverse_split_cooldown_days`; or more than `zero_volume_share` of the
   trailing `zero_volume_window` bars had zero volume. Every test looks only
   at data up to the date itself, so a date's flag never depends on what
   happened later -- a normal date that precedes a collapse stays eligible,
   and its (bad) forward return is kept. The zero-volume test is absolute
   per stock rather than a rank against other tickers, because the ticker
   set available here is survivors only.

Both are point-in-time. The one place later data enters is un-adjusting
prices: stored bars are split-adjusted as of today, so the price actually
traded on a date is recovered by multiplying back the splits executed
after it. That undoes an adjustment rather than leaking information --
the traded price itself was public on the day.

Thresholds were chosen against the History Break Review (2026-09-26, 18
hand-labelled tickers) and a full-universe measurement
(`src/analysis/history_break_rules.py`); see docs/done.md.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common.history_break_overrides import HISTORY_RESET_OVERRIDES

_NEVER = object()


@dataclass
class HistoryBreakConfig:
    # Anchor discovery starts at the latest qualifying reset when True.
    enabled: bool = True
    # "Traded as a penny stock": split-unadjusted close below this.
    penny_price: float = 1.0
    # Calendar days before a reverse split whose median unadjusted close
    # decides whether the split was penny-driven (calendar, not bars, so
    # daily and weekly runs agree).
    pre_split_days: int = 30
    # A reset only applies once this much history has followed it; until
    # then the full history is used (a reset 3 months ago would otherwise
    # leave almost nothing to anchor to -- 305 tickers in the 2026-09
    # measurement).
    min_days_after_reset: int = 210
    # Training eligibility: dates within this many days after a reverse split.
    reverse_split_cooldown_days: int = 365
    # Training eligibility: trailing window (bars) and share of zero-volume
    # bars above which a date is "not really trading".
    zero_volume_window: int = 63
    zero_volume_share: float = 0.5


def _as_splits(splits: pd.DataFrame | None) -> pd.DataFrame:
    if splits is None or splits.empty:
        return pd.DataFrame({"execution_date": pd.to_datetime([]), "ratio": pd.Series(dtype="float64")})
    out = splits[["execution_date", "ratio"]].copy()
    out["execution_date"] = pd.to_datetime(out["execution_date"])
    return out.sort_values("execution_date").reset_index(drop=True)


def unadjusted_close(bars: pd.DataFrame, splits: pd.DataFrame | None) -> pd.Series:
    """The close actually traded on each date: the split-adjusted close
    times the product of every split ratio executed after that date (a
    later 1-for-20 has ratio 0.05, so the traded price was adjusted x 0.05).
    """
    sp = _as_splits(splits)
    factor = pd.Series(1.0, index=bars.index)
    for d, r in zip(sp["execution_date"], sp["ratio"]):
        factor[bars.index < d] *= r
    return bars["close"] * factor


def _override(ticker: str | None):
    if ticker is None or ticker not in HISTORY_RESET_OVERRIDES:
        return None
    value = HISTORY_RESET_OVERRIDES[ticker]
    return _NEVER if value is None else pd.Timestamp(value)


def anchor_start_date(
    bars: pd.DataFrame, splits: pd.DataFrame | None, config: HistoryBreakConfig, ticker: str | None = None,
) -> pd.Timestamp | None:
    """Earliest date anchor discovery should consider, or None for "all
    history". `bars` must already be truncated to the as-of date; only
    splits on or before its last bar are candidates."""
    if bars.empty:
        return None
    last = bars.index[-1]
    override = _override(ticker)
    if override is _NEVER:
        return None
    if override is not None:
        return override if override <= last else None

    sp = _as_splits(splits)
    raw = unadjusted_close(bars, sp)
    start = None
    for d, r in zip(sp["execution_date"], sp["ratio"]):
        if r >= 1 or d > last:
            continue
        window = raw[(raw.index < d) & (raw.index >= d - pd.Timedelta(days=config.pre_split_days))]
        if len(window) and float(window.median()) < config.penny_price:
            start = d
    if start is not None and (last - start).days < config.min_days_after_reset:
        return None
    return start


def anchor_start_for(
    conn: sqlite3.Connection, ticker: str, bars: pd.DataFrame, config: HistoryBreakConfig,
) -> pd.Timestamp | None:
    """DB-facing wrapper: reads `ticker`'s yfinance splits (the same
    source whose adjustment `bars_1d` carries)."""
    if not config.enabled:
        return None
    return anchor_start_date(bars, db.read_splits(conn, ticker, db.YFINANCE), config, ticker=ticker)


def training_eligibility(
    bars: pd.DataFrame, splits: pd.DataFrame | None, config: HistoryBreakConfig,
) -> pd.DataFrame:
    """Per-date flags for one ticker, indexed like `bars` (which needs
    `close` and `volume`): unadjusted_close, penny, post_reverse_split,
    dormant, eligible. Marks dates; never drops them."""
    sp = _as_splits(splits)
    out = pd.DataFrame(index=bars.index)
    out["unadjusted_close"] = unadjusted_close(bars, sp)
    out["penny"] = out["unadjusted_close"] < config.penny_price

    # Most recent reverse split on or before each date (none -> NaT).
    rev_dates = pd.DatetimeIndex(sp.loc[sp["ratio"] < 1, "execution_date"])
    pos = rev_dates.searchsorted(bars.index, side="right") - 1
    last_rev = pd.Series(pd.NaT, index=bars.index, dtype="datetime64[ns]")
    has = pos >= 0
    last_rev[has] = rev_dates[pos[has]]
    days_since = (bars.index.to_series() - last_rev).dt.days
    out["post_reverse_split"] = days_since.between(0, config.reverse_split_cooldown_days).fillna(False).astype(bool)

    zero_share = (bars["volume"] <= 0).astype("float64").rolling(
        config.zero_volume_window, min_periods=config.zero_volume_window
    ).mean()
    out["dormant"] = (zero_share > config.zero_volume_share).fillna(False)
    out["eligible"] = ~(out["penny"] | out["post_reverse_split"] | out["dormant"])
    return out
