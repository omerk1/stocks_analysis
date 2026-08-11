"""Forward walk from a gap's creation bar to the last available bar,
computing its fill percentage and status over time.

Pure function of (bars, gaps) -- no DB, no as_of handling. The caller
(`detect.detect`) is responsible for handing this the *same* as_of-truncated
bars frame it detected gaps from; a gap walked against a longer frame than
it was detected on would see bars its own detection never had.
"""

from __future__ import annotations

import numpy as np
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


def _walk(
    idx: pd.DatetimeIndex, price_by_direction: dict[Direction, "np.ndarray"], gap: Gap, config: GapConfig
) -> None:
    """Vectorized mirror of `_penetration_pct`'s exact formula/clamping,
    computed for every bar in the gap's active window at once (numpy) rather
    than one `.iloc[i]` row-construction + function call per bar -- see
    `apply_lifecycle`'s docstring for why. Any change to `_penetration_pct`'s
    price-selection or formula must be mirrored here."""
    try:
        created_pos = idx.get_loc(pd.Timestamp(gap.created_at))
    except KeyError:
        # The bars frame this gap was detected on isn't the one it's being
        # walked against (e.g. mismatched test fixtures) -- nothing sound
        # to walk; leave the gap at its dataclass defaults (OPEN, no dates).
        return

    start = created_pos + 1
    height = gap.zone_top - gap.zone_bottom
    if start >= len(idx) or height <= 0:
        gap.max_fill_pct = 0.0
        gap.status = _status_for(0.0, config.soft_close_pct)
        return

    price = price_by_direction[gap.direction][start:]
    if gap.direction == Direction.BULLISH:
        pct = (gap.zone_top - price) / height * 100.0
    else:
        pct = (price - gap.zone_bottom) / height * 100.0
    pct = np.clip(pct, 0.0, 100.0)
    cummax = np.maximum.accumulate(pct)

    def _date_at(mask) -> str | None:
        hit = np.flatnonzero(mask)
        return idx[start + hit[0]].isoformat() if hit.size else None

    max_fill = float(cummax[-1])
    gap.max_fill_pct = max_fill
    gap.first_touch_date = _date_at(pct > 0.0)
    gap.soft_closed_date = _date_at(cummax >= config.soft_close_pct)
    gap.closed_date = _date_at(cummax >= 100.0)
    gap.status = _status_for(max_fill, config.soft_close_pct)


def apply_lifecycle(bars: pd.DataFrame, gaps: list[Gap], config: GapConfig) -> list[Gap]:
    """Mutates and returns `gaps` with status/max_fill_pct/*_date fields
    populated by walking `bars` forward from each gap's own creation bar.

    The fill-by-wick vs fill-by-body price series (open/high/low/close never
    change per-gap, only each gap's own zone/direction do) are computed once
    here, shared across every gap in `gaps`, rather than every gap
    re-deriving its own per-bar prices independently.
    """
    open_arr = bars["open"].to_numpy()
    high_arr = bars["high"].to_numpy()
    low_arr = bars["low"].to_numpy()
    close_arr = bars["close"].to_numpy()

    if config.fill_by == "wick":
        price_by_direction = {Direction.BULLISH: low_arr, Direction.BEARISH: high_arr}
    else:
        price_by_direction = {
            Direction.BULLISH: np.minimum(open_arr, close_arr),
            Direction.BEARISH: np.maximum(open_arr, close_arr),
        }

    for gap in gaps:
        _walk(bars.index, price_by_direction, gap, config)
    return gaps
