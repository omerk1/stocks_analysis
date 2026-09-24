"""Oscillator features for M17 -- nonlinearity probe (DESIGN.md lines
~867-887; PREREGISTRATION.md, 2026-09-24/25). Module-local raw (un-lagged)
computations; `modules/nonlinearity_probe.py` applies
`features/panel.py::apply_lag` before using any of these to condition on a
forward outcome (CLAUDE.md invariant #2).

Three distinct mathematical operations on a return window, DESIGN's own
framing -- none of them a linear filter of past returns the way every
M1-M16 feature is:
- `macd_histogram`/`macd_line`/`macd_signal`: gain/loss decomposition via
  two EMAs of price (reuses `market_common.indicators.macd`, itself a
  thin wrapper over this repo's existing talib-backed implementation --
  not a second MACD).
- `rsi`: gain/loss asymmetry -- `max(r,0)` vs `max(-r,0)`, ratioed
  (reuses `market_common.indicators.rsi`).
- `stochastic_k`: rank-within-range -- position of `close` within the
  trailing `[low, high]` band. No existing wrapper in
  `market_common.indicators` (checked directly before building this) --
  built here from the panel's own `high`/`low`/`close` columns, the same
  three columns M6.6/M9 already used for their own new features.
"""

from __future__ import annotations

import pandas as pd

from src.foundation.market_common.indicators import macd as _macd_wrapper
from src.foundation.market_common.indicators import rsi as _rsi_wrapper

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14
STOCH_PERIOD = 14


def macd_components(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(macd_line, signal_line, histogram) at canonical (12,26,9) params.
    Caller must pass a single ticker's close series, already sorted by
    date -- same convention as every other per-ticker feature in this
    study.
    """
    return _macd_wrapper(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    return _rsi_wrapper(close, period=period)


def stochastic_k(high: pd.Series, low: pd.Series, close: pd.Series, period: int = STOCH_PERIOD) -> pd.Series:
    """%K: `(close - rolling_low) / (rolling_high - rolling_low) * 100`,
    over a trailing `period`-bar window (Wilder/Lane's own canonical
    period). NaN where the rolling range is zero (a `period`-bar flat
    price) rather than a divide-by-zero inf/nan mix -- explicit, not
    incidental.
    """
    rolling_low = low.rolling(period).min()
    rolling_high = high.rolling(period).max()
    span = rolling_high - rolling_low
    k = (close - rolling_low) / span * 100
    return k.where(span > 0)
