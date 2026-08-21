"""§3.3 volume confirmation: relative-volume helper shared by every
detector's breakout check and by scoring's volume-signature component.
"""

from __future__ import annotations

import pandas as pd

from src.market_common import indicators


def rel_volume(bar_volume: float, volume_sma_at_bar: float) -> float | None:
    """`bar_volume / volume_sma_at_bar` -- None (not 0.0) when the SMA
    isn't available (warmup NaN or zero volume history), so callers don't
    mistake "unknown" for "confirmed zero volume expansion."""
    if pd.isna(volume_sma_at_bar) or volume_sma_at_bar <= 0:
        return None
    return bar_volume / volume_sma_at_bar


def volume_sma(volume: pd.Series, period: int) -> pd.Series:
    return indicators.sma(volume, period)


def is_breakout_volume_confirmed(bar_volume: float, volume_sma_at_bar: float, breakout_volume_mult: float) -> bool:
    rv = rel_volume(bar_volume, volume_sma_at_bar)
    return rv is not None and rv >= breakout_volume_mult
