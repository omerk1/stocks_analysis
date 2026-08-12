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
from src.market_common import indicators


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


def _apply_reaction(
    idx: pd.DatetimeIndex,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    atr_arr: np.ndarray,
    gap: Gap,
    config: GapConfig,
) -> None:
    """Only called once `gap.status == GapStatus.CLOSED` (see `_walk`).
    ATR-normalized max favorable move *back in the gap's original
    direction* within `config.reaction_window_bars` bars after
    `closed_date` -- the classic "fill then reverse" check, same
    forward-window mechanics as `sr_lines.events._reaction_atr`/
    `fibonacci.lifecycle.evaluate_level_touches`/
    `avwap.lifecycle.apply_interaction_tracking`, anchored at the bar
    where the gap first fully closed rather than at a touch/level/line
    interaction.
    """
    closed_pos = idx.get_loc(pd.Timestamp(gap.closed_date))
    window_end = min(closed_pos + 1 + config.reaction_window_bars, len(idx))
    if closed_pos + 1 >= window_end:
        return

    ref_close = close_arr[closed_pos]
    max_favorable = 0.0
    bars_to_peak: int | None = None
    any_valid = False

    for j in range(closed_pos + 1, window_end):
        a = atr_arr[j]
        if pd.isna(a) or a == 0:
            continue
        any_valid = True
        if gap.direction == Direction.BULLISH:
            favorable = max(0.0, (high_arr[j] - ref_close) / a)
        else:
            favorable = max(0.0, (ref_close - low_arr[j]) / a)
        if favorable > max_favorable:
            max_favorable = favorable
            bars_to_peak = j - closed_pos

    if any_valid:
        gap.reaction_atr_after_close = max_favorable
        gap.bars_to_reaction_peak = bars_to_peak


def _walk(
    idx: pd.DatetimeIndex,
    price_by_direction: dict[Direction, "np.ndarray"],
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    close_arr: np.ndarray,
    vol_arr: np.ndarray,
    vol_avg20_arr: np.ndarray,
    atr_arr: np.ndarray,
    gap: Gap,
    config: GapConfig,
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

    # Independent of whether there are any bars *after* creation -- the
    # creation bar itself always exists.
    avg = vol_avg20_arr[created_pos]
    if pd.notna(avg) and avg > 0:
        gap.volume_ratio_at_creation = float(vol_arr[created_pos] / avg)

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

    # Distinct approach events: rising edges of "currently touching the
    # zone" -- the running cummax above answers "how deep has price ever
    # gotten," this answers "how many separate times did price come back,"
    # neither recoverable from the other (a gap touched once for 40 bars
    # straight and one touched 10 times briefly can share the same
    # max_fill_pct/first_touch_date but tell very different stories).
    touching = pct > 0.0
    rising = touching & ~np.concatenate(([False], touching[:-1]))
    gap.n_approaches = int(rising.sum())

    def _milestone(mask) -> tuple[str | None, int | None]:
        hit = np.flatnonzero(mask)
        if not hit.size:
            return None, None
        # +1 so "1 bar later" means the very next bar after creation
        # (created_at itself is bar 0), matching how a human would count it.
        bars_since_creation = int(hit[0]) + 1
        return idx[start + hit[0]].isoformat(), bars_since_creation

    max_fill = float(cummax[-1])
    gap.max_fill_pct = max_fill
    gap.first_touch_date, gap.bars_to_first_touch = _milestone(pct > 0.0)
    gap.soft_closed_date, gap.bars_to_soft_closed = _milestone(cummax >= config.soft_close_pct)
    gap.closed_date, gap.bars_to_closed = _milestone(cummax >= 100.0)
    gap.status = _status_for(max_fill, config.soft_close_pct)

    if gap.status == GapStatus.CLOSED:
        _apply_reaction(idx, high_arr, low_arr, close_arr, atr_arr, gap, config)


def apply_lifecycle(bars: pd.DataFrame, gaps: list[Gap], config: GapConfig) -> list[Gap]:
    """Mutates and returns `gaps` with status/max_fill_pct/*_date/
    n_approaches/volume_ratio_at_creation/reaction_atr_after_close fields
    populated by walking `bars` forward from each gap's own creation bar.

    The fill-by-wick vs fill-by-body price series (open/high/low/close never
    change per-gap, only each gap's own zone/direction do), the rolling
    volume-ratio series, and the ATR series are all computed once here,
    shared across every gap in `gaps`, rather than every gap re-deriving
    its own per-bar prices independently.
    """
    open_arr = bars["open"].to_numpy()
    high_arr = bars["high"].to_numpy()
    low_arr = bars["low"].to_numpy()
    close_arr = bars["close"].to_numpy()
    vol_arr = bars["volume"].to_numpy()
    vol_avg20_arr = bars["volume"].rolling(20).mean().to_numpy()
    atr_arr = indicators.atr(bars, config.atr_period).to_numpy()

    if config.fill_by == "wick":
        price_by_direction = {Direction.BULLISH: low_arr, Direction.BEARISH: high_arr}
    else:
        price_by_direction = {
            Direction.BULLISH: np.minimum(open_arr, close_arr),
            Direction.BEARISH: np.maximum(open_arr, close_arr),
        }

    for gap in gaps:
        _walk(
            bars.index, price_by_direction, high_arr, low_arr, close_arr,
            vol_arr, vol_avg20_arr, atr_arr, gap, config,
        )
    return gaps
