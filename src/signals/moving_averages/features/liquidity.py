"""Volume/liquidity features (DESIGN.md line ~971, M12 -- "Volume and
liquidity interaction"). Module-local, not part of the cached panel
(`features/panel.py`'s own docstring: "Not yet built... VWMA" -- this adds
a minimal, module-local VWMA stub for M12's own use, not the general MA-
kernel infrastructure DESIGN assigns to M8).

Every function here takes raw per-ticker `close`/`volume` series (the
panel's own un-lagged OHLCV columns, `_NON_FEATURE_COLUMNS` in
`features/panel.py`) and returns a same-bar ("as of that day's close")
value -- the caller is responsible for passing the result through
`features/panel.py::apply_lag` before using it to condition on a forward
outcome (CLAUDE.md invariant #2), the same division of labor
`modules/stack_minervini.py`'s `rs_rating` join and
`modules/context_conditioning.py`'s `vix_tercile` join already use for a
feature added outside `_build_ticker_features`.
"""

from __future__ import annotations

import pandas as pd

# 63 trading days ~= 1 quarter -- same order of magnitude as
# `features/context.py::realized_vol_63`'s own trailing window, for the
# same reason: long enough to smooth out day-of-week/index-rebalancing
# noise, short enough to track a real change in a name's typical turnover.
RELATIVE_VOLUME_WINDOW = 63


def relative_volume(volume: pd.Series, window: int = RELATIVE_VOLUME_WINDOW) -> pd.Series:
    """Today's volume relative to its own trailing `window`-day average
    (inclusive of today) -- 1.0 means "typical" turnover, 2.0 means "twice
    the recent average." NaN for the first `window` - 1 rows of a ticker's
    history (`.rolling(window)`'s own min_periods default is the full
    window), same warmup shape as every other rolling feature in this
    study (CLAUDE.md invariant #9 -- not zero/one, undefined).
    """
    return volume / volume.rolling(window).mean()


def dollar_volume(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Close price times share volume -- the raw liquidity magnitude DESIGN
    asks for a cross-sectional percentile of (`stats.controls.
    cross_sectional_bucket` does the percentile/decile step; this is just
    the input to it). No warmup -- defined wherever close/volume are.
    """
    return close * volume


def vwma(close: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """Volume-weighted moving average over the trailing `window` days:
    sum(close * volume) / sum(volume). A minimal, module-local stub -- M8
    (DESIGN's own owner of the general MA-kernel-family infrastructure)
    will eventually build a fuller VWMA; this is only what M12 needs to
    compute `vwma_sma_divergence` at the same lookbacks the cached panel's
    SMA already uses. NaN for the first `window` - 1 rows, same warmup
    shape as `compute_ma`'s own SMA.
    """
    dollar = close * volume
    return dollar.rolling(window).sum() / volume.rolling(window).sum()
