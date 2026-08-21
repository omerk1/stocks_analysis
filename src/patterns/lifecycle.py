"""§3.5 state machine, shared across every detector: PENDING -> CONFIRMED ->
ACTIVE -> (HIT_TARGET | INVALIDATED_FAILED_BREAKOUT), with PENDING able to
resolve directly to INVALIDATED or EXPIRED before any breakout ever happens.

Deliberately generic over *how* a pattern's trigger level is expressed:
`trigger_at(bar_index) -> float` and `pre_breakout_invalidated_at(bar_index)
-> bool` are callables the detector builds from its own geometry, not
assumptions baked in here -- a flat neckline (double top/bottom, this
phase's only caller) passes a constant-returning `trigger_at`; a sloped
H&S neckline or a triangle boundary (later phases) can pass a real
per-bar-index function without this module changing at all.

Status granularity, matching the design doc's own architecture diagram
(§1: "CONFIRMED -> (ACTIVE -> HIT_TARGET | INVALIDATED | EXPIRED)"):
  - CONFIRMED: breakout just happened on the *last* bar currently visible
    -- there's no data yet to walk forward and check target/failure.
  - ACTIVE: breakout happened and at least one subsequent bar has been
    walked, with neither target hit nor a failed-breakout reclaim yet.
  - EXPIRED is only reachable from PENDING (§3.5's own wording: "pattern
    exceeds max lifespan ... without confirming or invalidating") -- once
    CONFIRMED, a pattern that just sits there indefinitely stays ACTIVE,
    it doesn't expire.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from src.market_common.models import Direction
from src.patterns import volume as volume_mod
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternStatus


def apply_lifecycle(
    df: pd.DataFrame,
    match: PatternMatch,
    *,
    formation_end_bar_index: int,
    formation_bars: int,
    trigger_at: Callable[[int], float],
    pre_breakout_invalidated_at: Callable[[int], bool],
    volume: pd.Series,
    volume_sma_series: pd.Series,
    config: PatternConfig,
) -> PatternMatch:
    """Walk forward from `formation_end_bar_index` (exclusive) through the
    end of `df`, resolving `match.status` (and, once a breakout is found,
    `match.breakout_bar`/`match.entry_price`/`match.volume_confirmed`) in
    place. Returns `match` for convenience; also mutates it.

    `match.direction` decides which side is "the breakout": BEARISH breaks
    *below* `trigger_at` (a close under `trigger_at(i) * (1 -
    breakout_buffer_pct)`), BULLISH breaks *above* it. `match.target_price`
    must already be set by the caller (pure geometry, computed once at
    detection time -- see e.g. detectors/double_top_bottom.py) since
    target-hit is checked against it here.
    """
    is_bearish = match.direction == Direction.BEARISH
    buffer = config.breakout_buffer_pct
    n = len(df)
    closes = df["close"].to_numpy()
    pending_deadline = formation_end_bar_index + int(config.expire_lifespan_mult * formation_bars)

    breakout_bar: int | None = None
    for i in range(formation_end_bar_index + 1, n):
        if i > pending_deadline:
            match.status = PatternStatus.EXPIRED
            return match

        level = trigger_at(i)
        close = float(closes[i])
        broke = (close < level * (1 - buffer)) if is_bearish else (close > level * (1 + buffer))
        if broke:
            breakout_bar = i
            break
        if pre_breakout_invalidated_at(i):
            match.status = PatternStatus.INVALIDATED
            return match

    if breakout_bar is None:
        # Ran out of visible bars before either a breakout or the pending
        # deadline -- still forming, as far as this view can tell.
        match.status = PatternStatus.PENDING
        return match

    match.breakout_bar = breakout_bar
    match.entry_price = float(closes[breakout_bar])
    rel_vol = volume_mod.rel_volume(float(volume.iloc[breakout_bar]), float(volume_sma_series.iloc[breakout_bar]))
    match.volume_confirmed = rel_vol is not None and rel_vol >= config.breakout_volume_mult

    if breakout_bar == n - 1:
        match.status = PatternStatus.CONFIRMED
        return match

    reclaim_deadline = breakout_bar + config.failed_breakout_reclaim_bars
    target = match.target_price
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    for i in range(breakout_bar + 1, n):
        if target is not None:
            hit = lows[i] <= target if is_bearish else highs[i] >= target
            if hit:
                match.status = PatternStatus.HIT_TARGET
                return match

        if i <= reclaim_deadline:
            level = trigger_at(i)
            close = float(closes[i])
            reclaimed = (close > level * (1 + buffer)) if is_bearish else (close < level * (1 - buffer))
            if reclaimed:
                match.status = PatternStatus.INVALIDATED_FAILED_BREAKOUT
                return match

    match.status = PatternStatus.ACTIVE
    return match
