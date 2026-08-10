"""Forward walk from a gap's creation bar to the last available bar,
computing its fill percentage and status over time.

Pure function of (bars, gaps) -- no DB, no as_of handling. The caller
(`detect.detect`) is responsible for handing this the *same* as_of-truncated
bars frame it detected gaps from; a gap walked against a longer frame than
it was detected on would see bars its own detection never had.
"""

from __future__ import annotations

import pandas as pd

from src.gaps.config import GapConfig
from src.gaps.models import Direction, Gap, GapStatus


def _penetration_pct(
    direction: Direction, zone_top: float, zone_bottom: float, bar: pd.Series, fill_by: str
) -> float:
    """How far this single bar reached from the gap's open edge toward its
    far edge, as a % of zone height, clamped to [0, 100] -- not cumulative,
    that's the caller's job (`_walk`'s running `max_fill`).

    Bullish gaps gapped *up*, so the open edge (closer to current price) is
    zone_top and future fill comes from price falling back down toward
    zone_bottom; bearish is the mirror image.
    """
    height = zone_top - zone_bottom
    if height <= 0:
        return 0.0
    if direction == Direction.BULLISH:
        price = bar["low"] if fill_by == "wick" else min(bar["open"], bar["close"])
        pct = (zone_top - price) / height * 100.0
    else:
        price = bar["high"] if fill_by == "wick" else max(bar["open"], bar["close"])
        pct = (price - zone_bottom) / height * 100.0
    return max(0.0, min(100.0, pct))


def _status_for(max_fill_pct: float, soft_close_pct: float) -> GapStatus:
    if max_fill_pct >= 100.0:
        return GapStatus.CLOSED
    if max_fill_pct >= soft_close_pct:
        return GapStatus.SOFT_CLOSED
    if max_fill_pct > 0.0:
        return GapStatus.PARTIAL
    return GapStatus.OPEN


def _walk(bars: pd.DataFrame, gap: Gap, config: GapConfig) -> None:
    created_ts = pd.Timestamp(gap.created_at)
    try:
        created_pos = bars.index.get_loc(created_ts)
    except KeyError:
        # The bars frame this gap was detected on isn't the one it's being
        # walked against (e.g. mismatched test fixtures) -- nothing sound
        # to walk; leave the gap at its dataclass defaults (OPEN, no dates).
        return

    max_fill = 0.0
    first_touch: str | None = None
    soft_closed: str | None = None
    closed: str | None = None

    for i in range(created_pos + 1, len(bars)):
        bar = bars.iloc[i]
        pct = _penetration_pct(gap.direction, gap.zone_top, gap.zone_bottom, bar, config.fill_by)
        bar_date = bars.index[i].isoformat()

        if pct > 0.0 and first_touch is None:
            first_touch = bar_date
        if pct > max_fill:
            max_fill = pct
        if max_fill >= config.soft_close_pct and soft_closed is None:
            soft_closed = bar_date
        if max_fill >= 100.0 and closed is None:
            closed = bar_date
            break  # CLOSED is terminal -- later re-entries change nothing

    gap.max_fill_pct = max_fill
    gap.first_touch_date = first_touch
    gap.soft_closed_date = soft_closed
    gap.closed_date = closed
    gap.status = _status_for(max_fill, config.soft_close_pct)


def apply_lifecycle(bars: pd.DataFrame, gaps: list[Gap], config: GapConfig) -> list[Gap]:
    """Mutates and returns `gaps` with status/max_fill_pct/*_date fields
    populated by walking `bars` forward from each gap's own creation bar."""
    for gap in gaps:
        _walk(bars, gap, config)
    return gaps
