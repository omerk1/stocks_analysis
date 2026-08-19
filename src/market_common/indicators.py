"""DataFrame-in indicator adapters, shared by sr_lines and the gaps/
divergences/fibonacci/avwap modules.

These are thin wrappers, not reimplementations -- `src/feature_engineering/`
already has tested, talib-backed RSI/MACD/OBV/ATR (Series-in/Series-out).
Duplicating that logic here under a second name/signature would be exactly
the kind of drift risk this project has caught and fixed elsewhere (one
tuned, one not, silently diverging over time). This module exists purely to
give every caller here one consistent DataFrame-based surface
(`atr(df, period)`, not `average_true_range(df["high"], df["low"],
df["close"], timeperiod=period)` repeated at every call site) over the
existing feature_engineering functions.
"""

from __future__ import annotations

import pandas as pd

from src.feature_engineering.price_based_indicators import (
    exponential_moving_average,
    moving_average,
    moving_average_convergence_divergence,
    relative_strength_index,
)
from src.feature_engineering.trend_indicators import average_true_range
from src.feature_engineering.volume_indicators import on_balance_volume


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    return average_true_range(df["high"], df["low"], df["close"], timeperiod=period)


def sma(close: pd.Series, period: int) -> pd.Series:
    return moving_average(close, period)


def ema(close: pd.Series, period: int) -> pd.Series:
    return exponential_moving_average(close, period)


def rsi(close: pd.Series, period: int) -> pd.Series:
    return relative_strength_index(close, window=period)


def macd(
    close: pd.Series, fast: int, slow: int, signal: int
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    return moving_average_convergence_divergence(
        close, fastperiod=fast, slowperiod=slow, signalperiod=signal
    )


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return on_balance_volume(close, volume)


def ratio(target: pd.Series, benchmark: pd.Series) -> pd.Series:
    """`target / benchmark`, aligned on their common date index (inner join)
    -- the first cross-*ticker* join primitive in this codebase (every
    existing reindex/align elsewhere here is within one ticker's own
    series). Used by `relative_strength` to build an RS ratio line between
    a stock/sector and its benchmark; a date either series lacks a value
    for (e.g. before the benchmark ETF's own listing date) is simply
    dropped, not filled or guessed.
    """
    aligned_target, aligned_benchmark = target.align(benchmark, join="inner")
    return aligned_target / aligned_benchmark


def percentile_rank(values: pd.Series) -> pd.Series:
    """Percentile rank (0-100) of each value within `values` -- e.g. all
    tickers' trailing returns on one date, for the IBD-style RS Rating.
    NaNs are excluded from the ranking (not ranked, not counted as peers)
    and pass through as NaN in the result.
    """
    return values.rank(pct=True) * 100


def mansfield_rs(ratio_series: pd.Series, period: int = 52) -> pd.Series:
    """Mansfield relative-strength oscillator: how far `ratio_series` (an
    RS ratio line, e.g. from `ratio()`) sits above/below its own trailing
    `period`-length average, as a percentage. Positive means the
    outperformance embedded in the ratio is currently strengthening beyond
    its own recent norm, not just "is outperforming" (that's the raw ratio
    trending up already) -- 0 is "right at its own recent average," not
    "target == benchmark."
    """
    return (ratio_series / sma(ratio_series, period) - 1) * 100


def scale_consistent(a: float, b: float, max_ratio: float = 10.0) -> bool:
    """True if two same-unit magnitude samples (typically ATR, or an ATR-
    derived threshold) -- taken at two different points of a swing/pivot
    pair that can be years apart -- are close enough in scale that dividing
    a delta spanning them by just one of the two is still meaningful.

    Exists because a raw price delta straddling a large stock split (e.g. a
    reverse split) inherits whatever back-adjustment factor applied to the
    older side, while an ATR/threshold sampled at only one end doesn't --
    confirmed on real data: AMC's 2023 1-for-10 reverse split leaves
    ATR(14) at ~27.7 shortly before it and ~0.23 shortly after (119x), while
    every legitimate large swing checked (SMCI, LCID, MU, MA) stayed under
    5x. `max_ratio=10.0` sits with real margin on both sides of that split.
    NaN/non-positive inputs can't be judged and are treated as inconsistent
    (caller should skip, not divide by them anyway).
    """
    if pd.isna(a) or pd.isna(b) or a <= 0 or b <= 0:
        return False
    return max(a, b) / min(a, b) <= max_ratio
