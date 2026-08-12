"""Invalidation tracking for a fib swing.

A set is invalidated the first time price closes beyond its swing's
ORIGIN (not its END): an up-swing (origin=low, end=high) invalidates on a
close below the origin low; a down-swing invalidates on a close above the
origin high. Crossing beyond the END is expected, ongoing behavior for an
active swing (that's precisely when its extension levels become
relevant), not invalidation.

No bar between origin_date and end_date can breach the origin: by
`detect_pivots`' own construction, origin is the running extreme of its
stretch right up until the reversal that produces end, so it's safe (and
simplest) to scan forward from end_date only, not origin_date.

Once invalidated, status is terminal -- searching for only the *first*
breach and never re-examining afterward already guarantees a later close
back inside the range can't revert it.
"""

from __future__ import annotations

import pandas as pd

from src.fibonacci.config import FibConfig
from src.fibonacci.models import FibLevel, FibSwing, FibSetStatus, SwingDirection


def evaluate_lifecycle(swing: FibSwing, close: pd.Series) -> tuple[FibSetStatus, str | None]:
    """`close` should already be trimmed to whatever `as_of` cutoff is in
    effect -- invalidation is judged only against bars the caller allows
    this evaluation to see, so as_of's "no lookahead" guarantee is the
    caller's responsibility (engine.py loads bars via `load_bars(...,
    as_of=as_of)` before any of this runs), not re-enforced here.
    """
    after = close[close.index > pd.Timestamp(swing.end_date)]
    if swing.direction == SwingDirection.UP:
        breaches = after[after < swing.origin_price]
    else:
        breaches = after[after > swing.origin_price]

    if breaches.empty:
        return FibSetStatus.ACTIVE, None
    return FibSetStatus.INVALIDATED, breaches.index[0].isoformat()


def evaluate_level_touches(
    levels: list[FibLevel], bars: pd.DataFrame, atr: pd.Series, swing: FibSwing, config: FibConfig,
) -> list[FibLevel]:
    """Bar-by-bar walk against each level's own price, starting right after
    the swing completes -- levels aren't meaningful before then, same
    `after = ... > swing.end_date` cutoff `evaluate_lifecycle` already uses
    (and the same *untrimmed* `bars`/`atr` that function's own `close`
    argument comes from at the call site, not the warmup-trimmed series
    used for swing/pivot detection).

    Classifies each level's own touch/violation history similarly to how
    `sr_lines/events.py` classifies TOUCH/BREAK against a zone, simplified
    since a level has no wick/body distinction to track (not asked for at
    this granularity): a touch is a bar whose range enters the level's
    tolerance band while its close stays on the already-established side; a
    violation is a close that crosses to the other side and isn't reclaimed
    within `config.level_violation_reclaim_bars` bars (a reclaimed cross
    still counts as a touch -- the same "Undercut and Rally" leniency
    sr_lines gives a reclaimed BODY_FAKE). The very first bar that
    establishes which side price approaches from doesn't itself count as an
    event, same reasoning as `sr_lines/events.py`'s own bootstrap bar.

    Mutates and returns `levels` in place. Intended to be called only for
    a swing's *selected* (top-`max_sets`) levels, not every candidate --
    this is a real per-bar walk per level, wasted work for a swing that
    gets discarded by ranking anyway.
    """
    after = bars[bars.index > pd.Timestamp(swing.end_date)]
    if after.empty:
        return levels

    idx = after.index
    highs = after["high"].to_numpy()
    lows = after["low"].to_numpy()
    closes = after["close"].to_numpy()
    atr_after = atr.reindex(idx).to_numpy()
    n = len(after)

    def _reaction_atr(i: int, side: str) -> float:
        window_end = min(i + 1 + config.touch_reaction_window_bars, n)
        if i + 1 >= window_end:
            return 0.0
        a = atr_after[i]
        if pd.isna(a) or a == 0:
            return 0.0
        if side == "above":
            favorable = highs[i + 1 : window_end].max() - closes[i]
        else:
            favorable = closes[i] - lows[i + 1 : window_end].min()
        return max(0.0, float(favorable / a))

    for level in levels:
        current_side: str | None = None
        pending: dict | None = None
        reactions: list[float] = []

        for i in range(n):
            a = atr_after[i]
            tolerance = config.level_touch_atr_tolerance * a if pd.notna(a) and a > 0 else 0.0
            zone_lo, zone_hi = level.price - tolerance / 2, level.price + tolerance / 2

            if closes[i] > zone_hi:
                close_side = "above"
            elif closes[i] < zone_lo:
                close_side = "below"
            else:
                close_side = "inside"

            if pending is not None:
                if close_side == pending["origin_side"]:
                    level.n_touches += 1
                    level.last_touch_date = idx[i].isoformat()
                    if level.first_touch_date is None:
                        level.first_touch_date = pending["start"]
                    reactions.append(_reaction_atr(pending["start_i"], pending["origin_side"]))
                    current_side = pending["origin_side"]
                    pending = None
                    continue
                elif i - pending["start_i"] >= config.level_violation_reclaim_bars:
                    level.n_violations += 1
                    current_side = pending["violation_side"]
                    pending = None
                    continue
                else:
                    continue

            if current_side is None:
                if close_side != "inside":
                    current_side = close_side
                continue

            if close_side == "inside":
                continue

            if close_side == current_side:
                intersects = lows[i] <= zone_hi and highs[i] >= zone_lo
                if not intersects:
                    continue
                level.n_touches += 1
                level.last_touch_date = idx[i].isoformat()
                if level.first_touch_date is None:
                    level.first_touch_date = idx[i].isoformat()
                reactions.append(_reaction_atr(i, current_side))
            else:
                pending = {
                    "start": idx[i].isoformat(), "start_i": i,
                    "origin_side": current_side, "violation_side": close_side,
                }

        level.avg_reaction_atr = (sum(reactions) / len(reactions)) if reactions else None
        level.respected = level.n_violations == 0 and level.n_touches > 0

    return levels
