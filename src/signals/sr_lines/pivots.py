"""ATR-adaptive ZigZag swing pivot detection -- sr_lines-specific wrapper
around `market_common.pivots.detect_pivots`, supplying real OHLC
high/low and the price/ATR-based threshold this package has always used.

See `market_common/pivots.py` for the actual (now generic) detection
state machine -- not duplicated here.
"""

from __future__ import annotations

import pandas as pd

from src.foundation.market_common import indicators as market_common_indicators
from src.foundation.market_common import pivots as market_common_pivots
from src.foundation.market_common.models import Pivot
from src.signals.sr_lines.config import SRConfig


def compute_atr(bars: pd.DataFrame, config: SRConfig) -> pd.Series:
    return market_common_indicators.atr(bars, config.atr_period)


def detect_pivots(bars: pd.DataFrame, config: SRConfig, atr: pd.Series | None = None) -> list[Pivot]:
    if atr is None:
        atr = compute_atr(bars, config)
    return market_common_pivots.detect_pivots(
        bars["high"], bars["low"],
        threshold_fn=lambda i: config.pivot_atr_mult * atr.iloc[i],
        magnitude_fn=lambda i: atr.iloc[i],
    )
