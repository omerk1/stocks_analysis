"""Generic ATR-adaptive ZigZag pivot detection.

Generalized from sr_lines' original price-only pivot detector: works on
*any* numeric series (price, or an indicator like RSI/MACD-histogram/OBV),
confirmed once the series reverses by at least `threshold_fn(bar_index)`
from a running candidate extreme. Pivots alternate high/low by
construction (standard ZigZag semantics).

Every pivot records `confirmed_at`: the bar at which the reversal
threshold was actually met -- a pivot "exists" at its own timestamp but is
only *knowable* once confirmed, which is what makes correct `as_of()`
lookahead filtering possible.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from src.market_common.models import Pivot, PivotKind


def detect_pivots(
    highs: pd.Series,
    lows: pd.Series | None = None,
    *,
    threshold_fn: Callable[[int], float],
    magnitude_fn: Callable[[int], float] | None = None,
) -> list[Pivot]:
    """`highs`/`lows` are the series tracked for candidate swing-high/
    swing-low extremes respectively -- pass real OHLC `high`/`low` for
    true-price pivots (sr_lines' own usage), or leave `lows` as `None`
    (defaults to `highs`) for the single-series case every other caller
    here wants (RSI, MACD histogram, OBV, or price via `close`).

    `threshold_fn(bar_index) -> float` is evaluated at a *candidate*
    pivot's own bar index (not the current scanning position) and is what
    the reversal magnitude must clear to confirm that pivot -- e.g.
    `lambda i: pivot_atr_mult * atr.iloc[i]` for price, a flat constant for
    RSI, `lambda i: std_mult * rolling_std.iloc[i]` for MACD histogram/OBV.
    May return NaN (e.g. during an indicator's warm-up period) -- such a
    candidate simply can't confirm yet, not an error.

    `magnitude_fn`, if given, is what gets stored on the resulting `Pivot`
    as `threshold_at_pivot` -- defaults to `threshold_fn` itself. Kept
    separate because a caller's confirmation threshold and the "raw
    magnitude" it wants recorded for its own downstream use aren't always
    the same number: sr_lines' price pivots confirm reversals at
    `pivot_atr_mult * ATR` but need `threshold_at_pivot` to store *raw*,
    unmultiplied ATR, since a separately-configured multiplier
    (`zone_width_atr`) gets applied to it again downstream for a genuinely
    different purpose (candidate clustering, not reversal confirmation) --
    storing the already-multiplied value would silently double-scale that.
    """
    if lows is None:
        lows = highs

    highs_arr = highs.to_numpy()
    lows_arr = lows.to_numpy()
    idx = highs.index
    n = len(highs)
    if n < 2:
        return []

    if magnitude_fn is None:
        magnitude_fn = threshold_fn

    pivots: list[Pivot] = []

    cand_high_price, cand_high_i = highs_arr[0], 0
    cand_low_price, cand_low_i = lows_arr[0], 0
    direction: str | None = None  # None (bootstrap) | "seeking_low" | "seeking_high"

    def _make_pivot(kind: PivotKind, value: float, at_i: int, confirmed_i: int) -> Pivot:
        return Pivot(
            kind=kind,
            timestamp=idx[at_i].isoformat(),
            value=float(value),
            confirmed_at=idx[confirmed_i].isoformat(),
            threshold_at_pivot=float(magnitude_fn(at_i)),
            bar_index=at_i,
        )

    for i in range(1, n):
        if highs_arr[i] > cand_high_price:
            cand_high_price, cand_high_i = highs_arr[i], i
        if lows_arr[i] < cand_low_price:
            cand_low_price, cand_low_i = lows_arr[i], i

        thr_high = threshold_fn(cand_high_i)
        thr_low = threshold_fn(cand_low_i)

        if direction is None:
            high_reversal = (
                cand_high_i < i and pd.notna(thr_high)
                and (cand_high_price - lows_arr[i]) >= thr_high
            )
            low_reversal = (
                cand_low_i < i and pd.notna(thr_low)
                and (highs_arr[i] - cand_low_price) >= thr_low
            )
            if high_reversal:
                pivots.append(_make_pivot(PivotKind.HIGH, cand_high_price, cand_high_i, i))
                direction = "seeking_low"
                cand_low_price, cand_low_i = lows_arr[i], i
            elif low_reversal:
                pivots.append(_make_pivot(PivotKind.LOW, cand_low_price, cand_low_i, i))
                direction = "seeking_high"
                cand_high_price, cand_high_i = highs_arr[i], i

        elif direction == "seeking_low":
            if pd.notna(thr_low) and (highs_arr[i] - cand_low_price) >= thr_low:
                pivots.append(_make_pivot(PivotKind.LOW, cand_low_price, cand_low_i, i))
                direction = "seeking_high"
                cand_high_price, cand_high_i = highs_arr[i], i

        else:  # seeking_high
            if pd.notna(thr_high) and (cand_high_price - lows_arr[i]) >= thr_high:
                pivots.append(_make_pivot(PivotKind.HIGH, cand_high_price, cand_high_i, i))
                direction = "seeking_low"
                cand_low_price, cand_low_i = lows_arr[i], i

    return pivots
