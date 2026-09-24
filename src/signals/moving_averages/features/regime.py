"""Regime features -- ER/ADX/vol regime (DESIGN.md, "M9 -- Regime-conditional
lookback", lines ~935-944; PREREGISTRATION.md, 2026-09-24). Module-local
raw (un-lagged) computations; `modules/regime_conditional_lookback.py`
applies `features/panel.py::apply_lag` before using any of these to
condition on a forward outcome (CLAUDE.md invariant #2).

`efficiency_ratio` is the same Kaufman construction `features/kernels.py
::kama` already computes inline for its own adaptive smoothing constant --
extracted here as a standalone, reusable function. **Reconciled 2026-09-25**:
`modules/slope_persistence.py` (M6.4), which had built its own local,
temporary copy of this identical formula in parallel before this module
landed, now imports this one directly. `kernels.py::kama` is still left as
its own inline computation (not refactored to import this) to avoid
touching already-merged, tested code for a module outside this one's own
scope -- noted, not resolved, lower priority (no known correctness
difference there, unlike the M6.4 case).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def efficiency_ratio(close: pd.Series, period: int = 10) -> pd.Series:
    """Kaufman's Efficiency Ratio: net directional change over `period`
    bars divided by the sum of absolute bar-to-bar changes over the same
    window -- 1.0 for a straight-line move, near 0 for pure chop. Identical
    formula to `features/kernels.py::kama`'s own inline `er` (same
    `er_period=10` default, Kaufman's own canonical choice).
    """
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    return (change / volatility).replace([np.inf, -np.inf], np.nan)


def average_directional_index(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Wilder's ADX (period=14, Wilder's own canonical choice -- matches
    this study's existing `atr_14`'s own period, both Wilder constructions).
    Standard formulation: directional movement (+DM/-DM) from consecutive
    high/low, Wilder-smoothed (an EMA with alpha=1/period, `adjust=False`)
    true range and directional movement, DI+/DI- as smoothed DM over
    smoothed TR, DX = 100*|DI+ - DI-|/(DI+ + DI-), ADX = Wilder-smoothed DX.
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)

    alpha = 1.0 / period
    smoothed_tr = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_plus_dm = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smoothed_minus_dm = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    # First `2*period` rows are warmup (DM/TR smoothing, then DX smoothing
    # on top) -- explicitly NaN rather than a numerically-defined but
    # meaningless early value.
    adx.iloc[: 2 * period] = np.nan
    return adx


# Fixed, pre-registered thresholds (PREREGISTRATION.md's M9 entry) --
# Kaufman's and Wilder's own published conventions, not tuned to this
# panel's data. CLAUDE.md's own instruction for this module: do not nudge
# these after seeing a result.
ER_CHOPPY_MAX = 0.3
ER_TRENDING_MIN = 0.6
ADX_NO_TREND_MAX = 20.0
ADX_TRENDING_MIN = 25.0


def er_regime(er: pd.Series) -> pd.Series:
    """3-bucket categorical: 'choppy' (ER < 0.3), 'moderate' (0.3-0.6),
    'trending' (ER >= 0.6) -- Kaufman's own published interpretation of ER,
    not a threshold fit to this study's data. NaN where `er` itself is NaN
    (CLAUDE.md invariant #9 -- a `pd.cut`-based bucket already preserves
    this by construction, verified by this module's own tests).
    """
    return pd.cut(
        er, bins=[-np.inf, ER_CHOPPY_MAX, ER_TRENDING_MIN, np.inf],
        labels=["choppy", "moderate", "trending"], right=False,
    )


def adx_regime(adx: pd.Series) -> pd.Series:
    """3-bucket categorical: 'no_trend' (ADX < 20), 'developing' (20-25),
    'trending' (ADX >= 25) -- Wilder's own published convention.
    """
    return pd.cut(
        adx, bins=[-np.inf, ADX_NO_TREND_MAX, ADX_TRENDING_MIN, np.inf],
        labels=["no_trend", "developing", "trending"], right=False,
    )
