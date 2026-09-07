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
# CLAUDE.md invariant #3.
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


def above(close: pd.Series, ma: pd.Series) -> pd.Series:
    """1[close > ma]."""
    return close > ma
