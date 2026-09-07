"""MA family computation (DESIGN.md §4.1-4.2).

Phase 2's starting subset: SMA and EMA only, lookbacks {20, 50, 200}.
WMA/HMA/KAMA/VWMA and the full lookback grid (§4.2's ultra-short/short/
intermediate/long/weekly/monthly buckets) are later scope, not this
phase's -- and matching them by lag (§4.1's `lag_matched_family_set`)
only matters once there's more than one family's *kernel shape* to
compare, which isn't yet true here.
"""

from __future__ import annotations

import pandas as pd

from src.foundation.market_common.indicators import ema, sma

FAMILIES = ("sma", "ema")
LOOKBACKS = (20, 50, 200)

_COMPUTE = {"sma": sma, "ema": ema}


def compute_ma(close: pd.Series, family: str, lookback: int) -> pd.Series:
    if family not in _COMPUTE:
        raise ValueError(f"Unknown MA family: {family!r} (expected one of {FAMILIES})")
    return _COMPUTE[family](close, lookback)


def ma_column_name(family: str, lookback: int) -> str:
    return f"{family}_{lookback}"
