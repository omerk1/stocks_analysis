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

`apply_lifecycle_bidirectional` (Phase 3, triangles/wedges) is a second
entry point for patterns whose breakout side isn't fixed by the pattern's
own geometry -- a triangle confirms on a close beyond *either* boundary,
direction unknown until it happens (design doc §4.3/§4.6). It shares
`apply_lifecycle`'s entire post-breakout walk (`_walk_post_breakout`,
factored out below) and differs only in how a breakout is detected in the
first place: watching two trigger levels instead of one, and resolving
`match.direction`/`target_price`/`stop_price` to whichever side actually
broke rather than having them fixed by the caller up front.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from src.market_common.models import Direction
from src.patterns import volume as volume_mod
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternStatus


def _walk_post_breakout(
    df: pd.DataFrame,
    match: PatternMatch,
    *,
    breakout_bar: int,
    trigger_at: Callable[[int], float],
    volume: pd.Series,
    volume_sma_series: pd.Series,
    config: PatternConfig,
) -> PatternMatch:
    """Shared tail of both entry points below, once a breakout bar and its
    (now-fixed) `match.direction`/`match.target_price` are known: volume
    confirmation, then CONFIRMED / ACTIVE / HIT_TARGET /
    INVALIDATED_FAILED_BREAKOUT resolution. Caller must already have set
    `match.direction` and `match.target_price` before calling this."""
    is_bearish = match.direction == Direction.BEARISH
    buffer = config.breakout_buffer_pct
    n = len(df)
    closes = df["close"].to_numpy()

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


def _pending_deadline(
    formation_end_bar_index: int, formation_bars: int, config: PatternConfig, override: int | None,
) -> int:
    if override is not None:
        return override
    return formation_end_bar_index + int(config.expire_lifespan_mult * formation_bars)


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
    pending_deadline_bar_index: int | None = None,
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

    `pending_deadline_bar_index`, if given, overrides the standard
    `formation_end_bar_index + expire_lifespan_mult * formation_bars`
    deadline -- triangles/wedges (Phase 3) pass `min(that, apex_bar)`,
    since design doc §4.3 also expires a triangle that reaches its apex
    without breaking out, whichever deadline comes first. Omitted by every
    Phase 1/2 caller, preserving their exact prior behavior.
    """
    is_bearish = match.direction == Direction.BEARISH
    buffer = config.breakout_buffer_pct
    n = len(df)
    closes = df["close"].to_numpy()
    pending_deadline = _pending_deadline(formation_end_bar_index, formation_bars, config, pending_deadline_bar_index)

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

    return _walk_post_breakout(
        df, match, breakout_bar=breakout_bar, trigger_at=trigger_at,
        volume=volume, volume_sma_series=volume_sma_series, config=config,
    )


def apply_lifecycle_bidirectional(
    df: pd.DataFrame,
    match: PatternMatch,
    *,
    formation_end_bar_index: int,
    formation_bars: int,
    upper_trigger_at: Callable[[int], float],
    lower_trigger_at: Callable[[int], float],
    upper_target: float,
    lower_target: float,
    upper_stop: float,
    lower_stop: float,
    pre_breakout_invalidated_at: Callable[[int], bool],
    volume: pd.Series,
    volume_sma_series: pd.Series,
    config: PatternConfig,
    pending_deadline_bar_index: int | None = None,
) -> PatternMatch:
    """Bidirectional counterpart to `apply_lifecycle`, for patterns whose
    breakout side isn't fixed by the pattern's own geometry -- a triangle
    or wedge confirms on a close beyond *either* boundary, direction only
    known once it happens (design doc §4.3/§4.6, and explicitly for
    ascending/descending triangles: "note whether breakout direction
    matches the pattern's directional bias ... still tag it, don't
    discard" -- i.e. the "wrong-side" break is a real, valid outcome, not
    something to reject).

    Watches `upper_trigger_at`/`lower_trigger_at` each bar; whichever
    breaks first sets `match.direction` (BULLISH for an upward break,
    BEARISH for downward) and commits `match.target_price`/`stop_price` to
    that side's pre-computed values, then hands off to
    `_walk_post_breakout` -- the exact same post-breakout walk
    `apply_lifecycle` itself uses, not a reimplementation.

    `match.direction` going in should already hold the pattern's
    documented *bias* (e.g. ascending triangle -> BULLISH, symmetric ->
    NEUTRAL per `Direction.NEUTRAL`) -- purely informational unless/until a
    real breakout overwrites it; a PENDING/EXPIRED/INVALIDATED match never
    resolves and keeps that bias value.
    """
    buffer = config.breakout_buffer_pct
    n = len(df)
    closes = df["close"].to_numpy()
    pending_deadline = _pending_deadline(formation_end_bar_index, formation_bars, config, pending_deadline_bar_index)

    for i in range(formation_end_bar_index + 1, n):
        if i > pending_deadline:
            match.status = PatternStatus.EXPIRED
            return match

        close = float(closes[i])
        upper_level = upper_trigger_at(i)
        lower_level = lower_trigger_at(i)
        broke_up = close > upper_level * (1 + buffer)
        broke_down = close < lower_level * (1 - buffer)

        if broke_up or broke_down:
            if broke_up:
                match.direction = Direction.BULLISH
                match.target_price = upper_target
                match.stop_price = upper_stop
                resolved_trigger_at = upper_trigger_at
            else:
                match.direction = Direction.BEARISH
                match.target_price = lower_target
                match.stop_price = lower_stop
                resolved_trigger_at = lower_trigger_at
            return _walk_post_breakout(
                df, match, breakout_bar=i, trigger_at=resolved_trigger_at,
                volume=volume, volume_sma_series=volume_sma_series, config=config,
            )

        if pre_breakout_invalidated_at(i):
            match.status = PatternStatus.INVALIDATED
            return match

    match.status = PatternStatus.PENDING
    return match
