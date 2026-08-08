"""ATR-adaptive ZigZag swing pivot detection.

A swing high is confirmed once price subsequently falls at least
`pivot_atr_mult * ATR` (ATR taken at the pivot bar itself, not the
confirming bar) from that high; symmetric for swing lows. Pivots alternate
high/low by construction (standard ZigZag semantics).

Every pivot records `confirmed_at`: the bar at which the reversal threshold
was actually met. A pivot "exists" at its own timestamp but is only
*knowable* once confirmed -- this is what makes correct `as_of()` lookahead
filtering possible later (a pivot with confirmed_at > as_of must not be used).
"""

from __future__ import annotations

import pandas as pd

from src.feature_engineering.trend_indicators import average_true_range
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Pivot, PivotKind


def compute_atr(bars: pd.DataFrame, config: SRConfig) -> pd.Series:
    return average_true_range(bars["high"], bars["low"], bars["close"], timeperiod=config.atr_period)


def detect_pivots(bars: pd.DataFrame, config: SRConfig, atr: pd.Series | None = None) -> list[Pivot]:
    if atr is None:
        atr = compute_atr(bars, config)

    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    idx = bars.index
    n = len(bars)
    if n < 2:
        return []

    pivots: list[Pivot] = []

    cand_high_price, cand_high_i = highs[0], 0
    cand_low_price, cand_low_i = lows[0], 0
    direction: str | None = None  # None (bootstrap) | "seeking_low" | "seeking_high"

    def _make_pivot(kind: PivotKind, price: float, at_i: int, confirmed_i: int) -> Pivot:
        return Pivot(
            kind=kind,
            timestamp=idx[at_i].isoformat(),
            price=float(price),
            confirmed_at=idx[confirmed_i].isoformat(),
            atr_at_pivot=float(atr.iloc[at_i]),
            bar_index=at_i,
        )

    for i in range(1, n):
        if highs[i] > cand_high_price:
            cand_high_price, cand_high_i = highs[i], i
        if lows[i] < cand_low_price:
            cand_low_price, cand_low_i = lows[i], i

        atr_high = atr.iloc[cand_high_i]
        atr_low = atr.iloc[cand_low_i]

        if direction is None:
            high_reversal = (
                cand_high_i < i and pd.notna(atr_high)
                and (cand_high_price - lows[i]) >= config.pivot_atr_mult * atr_high
            )
            low_reversal = (
                cand_low_i < i and pd.notna(atr_low)
                and (highs[i] - cand_low_price) >= config.pivot_atr_mult * atr_low
            )
            if high_reversal:
                pivots.append(_make_pivot(PivotKind.HIGH, cand_high_price, cand_high_i, i))
                direction = "seeking_low"
                cand_low_price, cand_low_i = lows[i], i
            elif low_reversal:
                pivots.append(_make_pivot(PivotKind.LOW, cand_low_price, cand_low_i, i))
                direction = "seeking_high"
                cand_high_price, cand_high_i = highs[i], i

        elif direction == "seeking_low":
            if pd.notna(atr_low) and (highs[i] - cand_low_price) >= config.pivot_atr_mult * atr_low:
                pivots.append(_make_pivot(PivotKind.LOW, cand_low_price, cand_low_i, i))
                direction = "seeking_high"
                cand_high_price, cand_high_i = highs[i], i

        else:  # seeking_high
            if pd.notna(atr_high) and (cand_high_price - lows[i]) >= config.pivot_atr_mult * atr_high:
                pivots.append(_make_pivot(PivotKind.HIGH, cand_high_price, cand_high_i, i))
                direction = "seeking_low"
                cand_low_price, cand_low_i = lows[i], i

    return pivots
