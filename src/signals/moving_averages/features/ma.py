"""MA family computation (DESIGN.md §4.1-4.2).

Phase 2's starting subset: SMA and EMA only, lookbacks {20, 50, 150, 200}.
WMA/HMA/KAMA/VWMA and the full lookback grid (§4.2's ultra-short/short/
intermediate/long/weekly/monthly buckets) are later scope, not this
phase's -- and matching them by lag (§4.1's `lag_matched_family_set`)
only matters once there's more than one family's *kernel shape* to
compare, which isn't yet true here.

150 added for M2 (PREREGISTRATION.md, 2026-09-12) -- Minervini's Trend
Template needs SMA150 directly (criteria 1/2/4), and it's already in
DESIGN §4.2's own lookback grid ("Long: 150, 200, 250"), not a new
lookback invented for this module. Additive only: every existing {20,50,
200} column at every family is unchanged, this just adds sma_150/ema_150
(and everything derived from them -- dist_pct/atr/z, above, slope,
run_length) to the cached panel. ema_150 is a side effect of looping
`FAMILIES x LOOKBACKS` together, not itself needed by M2 -- harmless
(same shape as every other lookback's EMA companion), not exercised by
any test.
"""

from __future__ import annotations

import pandas as pd

from src.foundation.market_common.indicators import ema, sma

FAMILIES = ("sma", "ema")
LOOKBACKS = (20, 50, 150, 200)

_COMPUTE = {"sma": sma, "ema": ema}


def compute_ma(close: pd.Series, family: str, lookback: int) -> pd.Series:
    if family not in _COMPUTE:
        raise ValueError(f"Unknown MA family: {family!r} (expected one of {FAMILIES})")
    return _COMPUTE[family](close, lookback)


def ma_column_name(family: str, lookback: int) -> str:
    return f"{family}_{lookback}"
