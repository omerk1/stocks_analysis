"""Outcome tracking: did a divergence's implied reversal actually happen.

Before this, `detect.py` stopped dead at `confirmed_at` -- a `Divergence`
row was a static snapshot of the pattern itself (the two price/indicator
pivot pairs, a strength score, raw magnitude components), with zero record
of what price did afterward. A divergence's entire point is predicting a
reversal, so "did it work" is the single most valuable feature this module
was missing -- unlike gaps (has a fill lifecycle), fibonacci (now has
per-level touch tracking), and avwap (now has interaction tracking), which
all already answer some version of "what happened after detection."
"""

from __future__ import annotations

import pandas as pd

from src.signals.divergences.config import DivergenceConfig
from src.signals.divergences.models import Direction, Divergence


def apply_outcome(bars: pd.DataFrame, atr: pd.Series, divergence: Divergence, config: DivergenceConfig) -> Divergence:
    """Walk forward from `confirmed_at`'s bar (exclusive) for up to
    `config.outcome_window_bars`, measuring the ATR-normalized best move in
    the direction the divergence implies (price rising for BULLISH, falling
    for BEARISH) and whether price ever moved beyond p2's own extreme
    against that implied direction (the pattern's own "higher low"/"lower
    high" thesis failing outright).

    `p2_price` doubles as both the invalidation threshold and the
    favorable-move baseline -- it's the same reference point either way:
    "how far has price moved away from the level that defined this
    divergence," just read in opposite directions.
    """
    confirmed_ts = pd.Timestamp(divergence.confirmed_at)
    after = bars[bars.index > confirmed_ts]
    if after.empty:
        divergence.outcome_computed_through = None
        return divergence

    window = after.iloc[: config.outcome_window_bars]
    idx = window.index
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    atr_window = atr.reindex(idx).to_numpy()
    n = len(window)

    is_bullish = divergence.direction == Direction.BULLISH
    reference_price = divergence.p2_price

    max_favorable = 0.0
    bars_to_max: int | None = None
    invalidated = False
    invalidated_at: str | None = None
    any_valid = False

    for i in range(n):
        a = atr_window[i]
        if pd.isna(a) or a == 0:
            continue
        any_valid = True

        if is_bullish:
            if not invalidated and lows[i] < reference_price:
                invalidated = True
                invalidated_at = idx[i].isoformat()
            favorable = max(0.0, (highs[i] - reference_price) / a)
        else:
            if not invalidated and highs[i] > reference_price:
                invalidated = True
                invalidated_at = idx[i].isoformat()
            favorable = max(0.0, (reference_price - lows[i]) / a)

        if favorable > max_favorable:
            max_favorable = favorable
            bars_to_max = i + 1  # +1: the first bar after confirmed_at is "1 bar later"

    divergence.max_favorable_move_atr = max_favorable if any_valid else None
    divergence.bars_to_max_favorable_move = bars_to_max
    divergence.invalidated = invalidated
    divergence.invalidated_at = invalidated_at
    divergence.outcome_computed_through = idx[-1].isoformat()

    return divergence
