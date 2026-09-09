"""Distance-from-MA features (DESIGN.md §4.3, "Position").

Phase 2's starting subset: `dist_pct`, `dist_atr`, `dist_z`, and the
`above` state boolean. `dist_pctile`, `days_above`/`days_below`,
`touched_today`, and `near_atr` are §4.3 features not in this phase's
scope.
"""

from __future__ import annotations

import pandas as pd

# Trailing window for the self-normalised z-score (DESIGN §4.3: "per-ticker
# self-normalisation" over 252d) -- rolling, never full-sample, per
# CLAUDE.md's no-full-sample-statistics invariant.
DIST_Z_WINDOW = 252


def dist_pct(close: pd.Series, ma: pd.Series) -> pd.Series:
    """(close - ma) / ma."""
    return (close - ma) / ma


def dist_atr(close: pd.Series, ma: pd.Series, atr: pd.Series) -> pd.Series:
    """(close - ma) / ATR(14)."""
    return (close - ma) / atr


def dist_z(dist_pct_series: pd.Series, window: int = DIST_Z_WINDOW) -> pd.Series:
    """Rolling z-score of `dist_pct_series` over its own trailing `window`
    days -- per-ticker self-normalisation (DESIGN §4.3), never a
    full-sample mean/std. Caller must pass a single ticker's series,
    already sorted by date (the panel builder applies this per ticker via
    groupby, same convention every per-ticker feature here follows).
    """
    rolling_mean = dist_pct_series.rolling(window).mean()
    rolling_std = dist_pct_series.rolling(window).std()
    return (dist_pct_series - rolling_mean) / rolling_std


def above(a: pd.Series, b: pd.Series) -> pd.Series:
    """1[a > b], `pd.NA` wherever either operand is NA (e.g. `b`'s own MA
    warmup window) -- a plain `a > b` comparison silently reads a NaN
    operand as "not greater than" (`False`) instead of undefined, since
    pandas comparison operators (unlike arithmetic) don't propagate
    missing values on their own. Returns pandas nullable "boolean" dtype,
    not plain `bool`/`object` -- assigning NA into a plain `bool` array
    upcasts to `object` (the same failure mode `features/panel.py`'s own
    lag-then-cast ordering exists to avoid for every other boolean
    feature).

    Named `a`/`b`, not `close`/`ma`: also reused as a generic "is-above"
    comparison for MA-vs-MA (see `stacked_sma`/`stacked_ema`,
    `features/panel.py`), not just close-vs-MA.
    """
    result = (a > b).astype("boolean")
    return result.mask(a.isna() | b.isna())
