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
    moving_average_convergence_divergence,
    relative_strength_index,
)
from src.feature_engineering.trend_indicators import average_true_range
from src.feature_engineering.volume_indicators import on_balance_volume


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    return average_true_range(df["high"], df["low"], df["close"], timeperiod=period)


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
