"""Shared trendline/level geometry used across pattern detectors (design doc
§3.1/§3.2): prior-trend qualification, touch-tolerance checking, and line
fitting through pivots.

`fit_line` re-exports `market_common.trendline_fit.fit_line` under this
module so detector code has one place to import trendline helpers from --
NOT sr_lines' own candidate-search machinery (see
docs/features/chart_pattern_detection_design_notes.md for why those two
don't share more than this one primitive).
"""

from __future__ import annotations

from typing import Callable, Literal

import numpy as np
import pandas as pd

from src.market_common.models import Pivot
from src.market_common.trendline_fit import fit_line

__all__ = [
    "fit_line", "prior_trend_pct", "has_prior_trend", "level_tolerance", "touches_level", "count_touches",
    "r_squared", "convergence_apex_bar",
]


def prior_trend_pct(
    df: pd.DataFrame,
    pivot: Pivot,
    min_bars: int,
    direction: Literal["up", "down"],
    lookback_bars: int | None = None,
) -> float | None:
    """§3.1: magnitude of the move (in %) leading into `pivot`, or None if
    fewer than `min_bars` of prior history is available to measure over.

    `direction="up"` for a pattern whose first pivot is a top forming after
    an uptrend (H&S, double top, cup & handle); `"down"` for a pattern
    whose first pivot is a bottom forming after a downtrend (inverse H&S,
    double bottom). Looks back up to `lookback_bars` (default 3x min_bars)
    bars before the pivot for the extreme the move started from.

    This is a plain magnitude measurement over the available lookback, per
    §3.1's "≥X% over ≥N bars" wording -- it does NOT filter out a move that
    happens to be concentrated in just a few of those bars (e.g. a 2-bar
    spike within an otherwise-flat lookback window still measures as a
    large, qualifying move). That kind of single-bar-dominance filtering is
    a distinct, pattern-specific concern the design doc only calls for in
    cup & handle's own roundedness check (§4.4), not a general prior-trend
    requirement.
    """
    lookback_bars = lookback_bars or min_bars * 3
    start = max(0, pivot.bar_index - lookback_bars)
    window = df.iloc[start : pivot.bar_index + 1]
    if len(window) < min_bars + 1:
        return None

    if direction == "up":
        extreme_price = float(window["low"].min())
    else:
        extreme_price = float(window["high"].max())

    if extreme_price <= 0:
        return None

    if direction == "up":
        return (pivot.price - extreme_price) / extreme_price * 100
    return (extreme_price - pivot.price) / extreme_price * 100


def has_prior_trend(
    df: pd.DataFrame,
    pivot: Pivot,
    min_pct: float,
    min_bars: int,
    direction: Literal["up", "down"],
    lookback_bars: int | None = None,
) -> bool:
    """§3.1 hard-gate wrapper around `prior_trend_pct` -- does `pivot` sit
    at the end of a move reaching at least `min_pct`."""
    pct = prior_trend_pct(df, pivot, min_bars, direction, lookback_bars)
    return pct is not None and pct >= min_pct


def level_tolerance(price: float, atr: float, atr_mult: float, pct: float) -> float:
    """§3.2: max(atr_mult * ATR, pct * price) -- the tolerance band a bar's
    high/low must fall within to count as "touching" a flat level or
    trendline at `price`."""
    return max(atr_mult * atr, pct * price)


def touches_level(bar_price: float, level_price: float, tolerance: float) -> bool:
    return abs(bar_price - level_price) <= tolerance


def count_touches(
    highs: pd.Series,
    lows: pd.Series,
    atr: pd.Series,
    level_at: Callable[[int], float],
    atr_mult: float,
    pct: float,
) -> int:
    """Count bars (by integer position, 0-indexed against `highs`/`lows`)
    whose high or low falls within tolerance of `level_at(position)` --
    used both as a hard-gate input (min_touches_per_line) and as a §6.1
    cleanliness sub-metric (point count vs. minimum). `level_at` takes a
    flat level as `lambda i: constant` or a fitted trendline's price at
    that position for a sloped boundary."""
    n = len(highs)
    highs_arr = highs.to_numpy()
    lows_arr = lows.to_numpy()
    atr_arr = atr.to_numpy()
    count = 0
    for i in range(n):
        a = atr_arr[i]
        if pd.isna(a):
            continue
        level = level_at(i)
        tol = level_tolerance(level, float(a), atr_mult, pct)
        if touches_level(highs_arr[i], level, tol) or touches_level(lows_arr[i], level, tol):
            count += 1
    return count


def r_squared(xs: np.ndarray, ys: np.ndarray, slope: float, intercept: float) -> float:
    """§6.1 "Trendline fit (R²)" cleanliness metric: how well `ys` actually
    sits on the fitted line `slope*xs+intercept`, vs. just being the
    least-squares best-effort through noisy points. Trivially 1.0 for a
    2-point line (H&S's neckline) -- only differentiates once a line has
    3+ points behind it (a triangle boundary, Phase 3), per §6.1's own
    note. Can be negative for a genuinely bad fit; callers wanting a
    [0,1] score clip it themselves (same division of labor as elsewhere
    in this module: geometry here, score-shaping in scoring.py)."""
    predicted = slope * xs + intercept
    ss_res = float(np.sum((ys - predicted) ** 2))
    ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
    if ss_tot == 0:
        return 1.0
    return 1 - ss_res / ss_tot


def convergence_apex_bar(
    upper_slope: float, upper_intercept: float, lower_slope: float, lower_intercept: float,
) -> float | None:
    """Bar index (may be fractional) where two fitted boundary lines
    intersect -- a triangle/wedge's apex (§4.3 point 5 / §4.6). None if
    the lines are parallel (upper_slope == lower_slope): no convergence,
    not a valid triangle/wedge at all. Solves
    `upper_slope*x + upper_intercept == lower_slope*x + lower_intercept`.

    Range-at-a-bar (`upper_at(i) - lower_at(i)`) is linear in `i` since
    both boundaries are linear, so checking convergence doesn't need to
    separately evaluate "range at start" vs. "range at end" the way the
    design doc's wording suggests -- `upper_slope < lower_slope` (the
    upper boundary rising slower / falling faster than the lower one) is
    the single condition under which range shrinks as `i` increases,
    for *any* pair of points. Callers gate on that directly."""
    denom = upper_slope - lower_slope
    if denom == 0:
        return None
    return (lower_intercept - upper_intercept) / denom
