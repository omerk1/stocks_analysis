"""Context features (DESIGN.md §4.3, "Context") -- specifically the momentum
and volatility controls the C2 matched control (§6.1) needs, added now
because M4 is the first module that needs C2 (see PREREGISTRATION.md).

`dist_from_52w_high`/`dist_from_52w_low` added for M2 (PREREGISTRATION.md,
2026-09-12 -- Minervini Trend Template criteria 6/7 need them directly).
Still not built here: `days_to_next_earnings`, `gap_pct`,
`dollar_volume_pctile`, and the full IBD-style `rs_rank` (the
`relative_strength` module's rating, not this module's simpler `mom_12_1`
-- M2 reuses that module's `compute_stock_vs_market` directly rather than
duplicating it here, see `modules/stack_minervini.py`) are later scope.
"""

from __future__ import annotations

import pandas as pd

# 252 trading days ~= 1 year -- same rolling-window convention as
# `distance.py::DIST_Z_WINDOW`, per-ticker, never full-sample (CLAUDE.md
# invariant #3).
FIFTY_TWO_WEEK_WINDOW = 252


def mom_12_1(close: pd.Series) -> pd.Series:
    """12-month return skipping the most recent month: close[t-21] /
    close[t-252] - 1 -- the momentum control DESIGN §7.1's regression
    names directly (`mom_12_1`). Computed here rather than via the fuller
    `relative_strength` module's rs_rating pipeline (index-membership-
    scoped, sector-ETF-benchmarked -- heavier machinery than a tercile
    bucket needs for C2; see PREREGISTRATION.md).
    """
    return close.shift(21) / close.shift(252) - 1


def realized_vol_63(close: pd.Series) -> pd.Series:
    """63-trading-day rolling standard deviation of daily returns -- the
    vol control for C2 matching (DESIGN §6.1: "same vol decile").
    """
    return close.pct_change().rolling(63).std()


def mom_1_0(close: pd.Series) -> pd.Series:
    """1-month return, no skip: close[t]/close[t-21] - 1 -- the short-term
    reversal control added for M1's confound check (PREREGISTRATION.md,
    2026-09-09 addendum). `mom_12_1` deliberately *skips* this exact
    window; nothing else in the existing C2 match set (momentum/vol/
    sector) controls for it, and being above a short MA is mechanically
    correlated with having just risen over roughly this same window.
    """
    return close.pct_change(21)


def dist_from_52w_high(close: pd.Series, window: int = FIFTY_TWO_WEEK_WINDOW) -> pd.Series:
    """close / rolling_252d_max(close) - 1 -- always <= 0 (or NaN). NaN for
    a ticker's first `window` days (`.rolling(window)`'s own min_periods
    default is the full window), same warmup shape as `dist_z`'s 252-day
    self-normalisation -- not zero/false, per CLAUDE.md invariant #9.
    Trend-Template criterion 7 ("within 25% of the 52-week high") is
    `dist_from_52w_high >= -0.25`, built in `modules/stack_minervini.py`
    with its own explicit NaN mask -- a bare comparison on this column
    would silently read the warmup region as "not within 25%" (False)
    instead of undefined.
    """
    return close / close.rolling(window).max() - 1


def dist_from_52w_low(close: pd.Series, window: int = FIFTY_TWO_WEEK_WINDOW) -> pd.Series:
    """close / rolling_252d_min(close) - 1 -- always >= 0 (or NaN). Same
    warmup-NaN shape as `dist_from_52w_high`. Trend-Template criterion 6
    ("at least 30% above the 52-week low") is `dist_from_52w_low >= 0.30`,
    built in `modules/stack_minervini.py` with its own explicit NaN mask.
    """
    return close / close.rolling(window).min() - 1
