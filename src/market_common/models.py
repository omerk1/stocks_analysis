"""Shared dataclasses/enums used across sr_lines and the gaps/divergences/
fibonacci/avwap modules. Plain, JSON-serializable -- no pandas objects, no
plotting/DB coupling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Timeframe(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


class Direction(str, Enum):
    """Bullish/bearish signal direction -- shared by gaps and divergences.
    NOT used for a fibonacci swing's up/down geometric direction, which is
    a different concept with its own local enum in fibonacci/models.py."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    # patterns-only (design doc §5's own PatternMatch.direction type):
    # a still-forming symmetric triangle has no directional bias until it
    # actually breaks out either way. gaps/divergences never produce this
    # -- purely additive, doesn't change either module's exhaustive
    # BULLISH/BEARISH keyed lookups (e.g. their own plotting.py color
    # dicts).
    NEUTRAL = "neutral"


class PivotKind(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class Pivot:
    kind: PivotKind
    timestamp: str
    # The series value at this pivot -- a price for price pivots, an RSI/
    # MACD-histogram/OBV value for indicator pivots.
    value: float
    confirmed_at: str
    # The reversal-confirmation magnitude in effect at this pivot's own bar
    # (what `pivots.detect_pivots`'s `magnitude_fn` returned for it, NOT
    # necessarily the same number used to actually confirm the reversal --
    # see `pivots.detect_pivots`'s docstring for why those two can differ).
    threshold_at_pivot: float
    # Integer position in the detection window's bar index -- the x-axis
    # diagonal trendline fitting needs (log-price vs. bar-index, not
    # price-only like horizontal clustering). Defaults to 0 so tests that
    # construct a Pivot without a real bars context don't need to supply one.
    bar_index: int = 0

    # sr_lines predates this shared module and reads `.price`/`.atr_at_pivot`
    # throughout (candidates.py's clustering and diagonal fitting, at
    # minimum) -- these are read-only aliases so every existing sr_lines
    # call site keeps working unchanged, while new code gets the more
    # accurate names (a `.price` on an RSI pivot would be misleading).
    @property
    def price(self) -> float:
        return self.value

    @property
    def atr_at_pivot(self) -> float:
        return self.threshold_at_pivot

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DataQualityReport:
    ticker: str
    rows_loaded: int
    rows_dropped: int
    drop_rate: float
    suspicious_jump_dates: list[str] = field(default_factory=list)
    # Bars whose intraday range (high - low) is anomalously large relative
    # to that ticker's own recent ATR, even when the close-to-close move
    # looks completely normal -- catches a same-day spike-and-round-trip
    # that `suspicious_jump_dates` (close-based) can't see. See
    # `validate_bars`'s docstring for the exact ratio/threshold. Soft flag,
    # same as `suspicious_jump_dates` -- not a row drop.
    suspicious_intraday_range_dates: list[str] = field(default_factory=list)
    unreliable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
