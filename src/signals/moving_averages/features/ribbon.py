"""Ribbon width (MA dispersion) feature (DESIGN.md M7; PREREGISTRATION.md,
2026-09-22).

`ribbon_width`: coefficient-of-variation dispersion of the SMA ribbon
{20,50,150,200} at each (ticker,date) row -- std/mean of the four already-
cached SMA columns, arithmetic on already-lagged inputs (every column in
the cached panel is already passed through `features/panel.py::apply_lag`
at build time -- CLAUDE.md invariant #2 -- so a column derived purely from
already-lagged inputs needs no re-lagging of its own, same convention
`modules/slope_conditioner.py::prepare`'s `slope_sign_sma_k` uses).

`ribbon_width_pctile`: per-ticker rolling min-max scaling of `ribbon_width`
over its own trailing window -- "where does today's dispersion sit within
its own recent range," 0 = most compressed, 1 = most dispersed. This is a
fast, fully-vectorized rolling range position, not an exact rolling
percentile rank (which would need an O(n*window) rolling `.apply` per
ticker) -- the same construction family `features/context.py`'s own
`dist_from_52w_high`/`dist_from_52w_low` already uses for a conceptually
identical "position within a trailing range" question. Documented as an
approximation, not silently substituted.
"""

from __future__ import annotations

import pandas as pd

# Same 252-trading-day (~1 year) window convention as
# `features/distance.py::DIST_Z_WINDOW` and `features/context.py
# ::FIFTY_TWO_WEEK_WINDOW` -- rolling, per-ticker, never full-sample
# (CLAUDE.md invariant #3).
RIBBON_WIDTH_WINDOW = 252

RIBBON_SMA_COLS = ("sma_20", "sma_50", "sma_150", "sma_200")


def ribbon_width(panel: pd.DataFrame, sma_cols: tuple[str, ...] = RIBBON_SMA_COLS) -> pd.Series:
    """Coefficient-of-variation dispersion of the SMA ribbon at each row:
    std(sma_20, sma_50, sma_150, sma_200) / mean(...). NaN wherever any
    input SMA is NaN (warmup) via pandas' own row-wise arithmetic NaN
    propagation -- this is arithmetic, not a comparison, so CLAUDE.md
    invariant #9's explicit-masking requirement (for comparison-derived
    booleans) doesn't apply here; propagation is already correct by
    construction.
    """
    values = panel[list(sma_cols)]
    # skipna=False (not the pandas default True): a NaN in any one SMA
    # (warmup) must propagate to `width`, not be silently dropped from a
    # 3-of-4-input std/mean -- caught by this module's own test.
    return values.std(axis=1, skipna=False) / values.mean(axis=1, skipna=False)


def ribbon_width_pctile(
    width: pd.Series, ticker: pd.Series, window: int = RIBBON_WIDTH_WINDOW
) -> pd.Series:
    """Per-ticker rolling min-max scaling of `width` over its own trailing
    `window`: (width - rolling_min) / (rolling_max - rolling_min), in
    [0, 1]. NaN during the rolling warmup (`min_periods=window`, no partial
    windows) and wherever the trailing range is exactly zero (a
    perfectly flat ribbon for `window` days running -- degenerate, not a
    meaningful 0 or 1 read, masked rather than silently reported as 0/1).
    """
    df = pd.DataFrame({"_width": width.to_numpy(), "_ticker": ticker.to_numpy()}, index=width.index)
    grouped = df.groupby("_ticker")["_width"]
    roll_min = grouped.transform(lambda s: s.rolling(window, min_periods=window).min())
    roll_max = grouped.transform(lambda s: s.rolling(window, min_periods=window).max())
    span = roll_max - roll_min
    pctile = (width - roll_min) / span
    return pctile.mask(span == 0)
