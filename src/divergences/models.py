"""Output data model for divergence detection -- plain, JSON-serializable
dataclass. Mirrors gaps.models' separation: detect.py builds these,
store.py/plotting.py/cli.py are pure consumers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from src.market_common.models import Direction, Timeframe

__all__ = ["Direction", "Timeframe", "IndicatorKind", "Divergence"]


class IndicatorKind(str, Enum):
    RSI = "rsi"
    MACD_HIST = "macd_hist"
    OBV = "obv"
    VOLUME = "volume"


@dataclass
class Divergence:
    id: str
    ticker: str
    timeframe: Timeframe
    indicator: IndicatorKind
    direction: Direction
    # The two price pivots that make up the divergence (p1 = earlier/first
    # of the pair, p2 = later -- p2 is the one whose confirmation actually
    # completes the divergence, see detect.py).
    p1_date: str
    p2_date: str
    p1_price: float
    p2_price: float
    # The paired indicator pivots' own values (not necessarily on the exact
    # same bar as p1/p2 -- see detect.py's pairing_window).
    i1_value: float
    i2_value: float
    strength: float
    # The raw, unclipped inputs strength is built from (see detect.py's
    # _evaluate_pairs) -- strength itself caps each component to [0, 1]
    # before weighting, which is the right behavior for a bounded display
    # score but throws away real magnitude information above the cap (an
    # 8x-ATR move and a 50x-ATR move both read as 1.0). Kept here
    # unclipped for anyone using these as model features rather than a
    # display label. duration_bars = p2.bar_index - p1.bar_index;
    # price_move_atr = |p2.value - p1.value| / ATR at p2's bar;
    # indicator_gap_raw = |ip2.value - ip1.value| / the indicator's own
    # magnitude at p2's bar.
    duration_bars: int
    price_move_atr: float
    appeared_at: str
    confirmed_at: str
    # None when the indicator's own magnitude at p2's bar couldn't be
    # computed reliably -- see detect.py's scale_consistent guard (the same
    # case that makes the clipped `indicator_gap` component fall back to 0.0).
    indicator_gap_raw: float | None = None
    # Populated by lifecycle.apply_outcome -- did the divergence's implied
    # reversal actually happen, walking forward from confirmed_at for up to
    # config.outcome_window_bars. All None/False ("not yet resolved") when
    # there are no bars past confirmed_at yet (a divergence confirmed on the
    # data's very last available bar).
    max_favorable_move_atr: float | None = None  # ATR-normalized best move in the implied direction
    bars_to_max_favorable_move: int | None = None
    # True if price ever moved beyond p2's own extreme (a new lower low for
    # a bullish divergence, a new higher high for a bearish one) within the
    # outcome window -- the pattern's own "price makes a higher low/lower
    # high" thesis failed, independent of whether a favorable move also
    # happened at some other point in the same window.
    invalidated: bool = False
    invalidated_at: str | None = None
    # Last bar this row's outcome fields actually reflect -- None if no
    # bars past confirmed_at were available to walk at all.
    outcome_computed_through: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timeframe"] = self.timeframe.value
        d["indicator"] = self.indicator.value
        d["direction"] = self.direction.value
        return d
