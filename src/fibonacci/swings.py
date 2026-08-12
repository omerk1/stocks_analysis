"""Multi-scale swing detection.

Runs `market_common.pivots.detect_pivots` once per `config.scales` entry,
independently -- NOT a single pass with several thresholds merged. A big
ATR multiplier surfaces macro cycles that a small one would drown in
noise-confirmed micro-swings; a small multiplier surfaces tradeable swings
that a big one would merge into nothing. Running them as separate passes
lets both kinds of swing exist simultaneously as distinct, independently
useful `FibSwing`s -- collapsing this into one "smart" pass would defeat
the entire point of the multi-scale design.

Every consecutive pair of opposite-kind pivots from one scale's pass forms
a swing: LOW -> HIGH is an "up" swing (origin=the LOW, end=the HIGH),
HIGH -> LOW is a "down" swing (mirror). `detect_pivots` alternates
high/low by construction, so every consecutive pair is automatically
opposite-kind.
"""

from __future__ import annotations

import pandas as pd

from src.fibonacci.config import FibConfig
from src.fibonacci.models import FibSwing, SwingDirection
from src.market_common.indicators import scale_consistent
from src.market_common.models import Pivot, PivotKind
from src.market_common.pivots import detect_pivots


def _swings_from_pivots(pivots: list[Pivot], scale_mult: float, atr: pd.Series) -> list[FibSwing]:
    swings: list[FibSwing] = []
    for origin, end in zip(pivots, pivots[1:]):
        if origin.kind == PivotKind.LOW and end.kind == PivotKind.HIGH:
            direction = SwingDirection.UP
        elif origin.kind == PivotKind.HIGH and end.kind == PivotKind.LOW:
            direction = SwingDirection.DOWN
        else:
            continue  # unreachable given detect_pivots' alternation guarantee

        end_atr = atr.iloc[end.bar_index]
        origin_atr = atr.iloc[origin.bar_index]
        if pd.isna(end_atr) or end_atr <= 0:
            continue  # can't compute a meaningful magnitude_atr; skip rather than divide by ~0
        if not scale_consistent(origin_atr, end_atr):
            # ATR at the swing's two ends is on wildly different scales --
            # almost always a large stock split between them (see
            # scale_consistent's docstring) -- dividing the raw price delta
            # by just the end-side ATR would produce a magnitude_atr that's
            # off by whatever factor the split applied, not a real swing size.
            continue

        swings.append(
            FibSwing(
                origin_date=origin.timestamp,
                origin_price=origin.value,
                end_date=end.timestamp,
                end_price=end.value,
                direction=direction,
                scale_mult=scale_mult,
                magnitude_atr=abs(end.value - origin.value) / end_atr,
                duration_bars=end.bar_index - origin.bar_index,
                confirmed_at=end.confirmed_at,
                origin_bar_index=origin.bar_index,
                end_bar_index=end.bar_index,
            )
        )
    return swings


def _dedup_cross_scale(swings: list[FibSwing], tolerance: int) -> list[FibSwing]:
    """Two swings (from different scales) whose origin AND end bar indices
    both fall within `tolerance` bars of each other are the same real swing
    surfacing at multiple scales -- keep only the highest-scale instance.
    Swings sharing just one endpoint (a nested or partially-overlapping
    move) are NOT duplicates and are both kept -- that's a different,
    independently valid swing, not noise.

    Processing highest-scale first and only ever comparing a candidate
    against what's already been kept means the survivor of any duplicate
    group is always its highest-scale member, matching the spec.
    """
    kept: list[FibSwing] = []
    for swing in sorted(swings, key=lambda s: s.scale_mult, reverse=True):
        is_duplicate = any(
            abs(swing.origin_bar_index - k.origin_bar_index) <= tolerance
            and abs(swing.end_bar_index - k.end_bar_index) <= tolerance
            for k in kept
        )
        if not is_duplicate:
            kept.append(swing)
    return sorted(kept, key=lambda s: s.origin_bar_index)


def detect_swings(close: pd.Series, atr: pd.Series, config: FibConfig) -> list[FibSwing]:
    """`close`/`atr` are expected to already be warmup-trimmed and
    as-of-filtered by the caller (engine.py) -- this function is purely
    the scale-fan-out + swing-building + filter + dedup mechanics.
    """
    all_swings: list[FibSwing] = []
    for scale in config.scales:
        pivots = detect_pivots(close, threshold_fn=lambda i, s=scale: s * atr.iloc[i])
        scale_swings = _swings_from_pivots(pivots, scale, atr)
        all_swings.extend(s for s in scale_swings if s.magnitude_atr >= config.min_swing_atr)

    return _dedup_cross_scale(all_swings, config.dedup_bar_tolerance)
