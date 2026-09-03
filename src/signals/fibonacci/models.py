"""Output data model for multi-scale Fibonacci retracement/extension
detection -- plain, JSON-serializable dataclasses. Mirrors gaps.models'
separation: swings.py/levels.py/lifecycle.py build these, store.py/
plotting.py/cli.py are pure consumers.

`SwingDirection` is deliberately its own local enum, NOT a reuse of
`market_common.models.Direction` (bullish/bearish) -- that enum represents
a trading *signal* direction, a fibonacci swing's up/down is a geometric
description of which endpoint is the low and which is the high, a
different concept entirely (an "up" swing's retracement levels are a
bearish-leaning zone to watch, not a bullish signal). Conflating the two
would make call sites read backwards.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from src.foundation.market_common.models import Timeframe

__all__ = [
    "Timeframe",
    "SwingDirection",
    "FibLevelKind",
    "FibSetStatus",
    "FibSwing",
    "FibLevel",
    "FibSet",
]


class SwingDirection(str, Enum):
    UP = "up"
    DOWN = "down"


class FibLevelKind(str, Enum):
    RETRACEMENT = "retracement"
    EXTENSION = "extension"


class FibSetStatus(str, Enum):
    ACTIVE = "active"
    INVALIDATED = "invalidated"


@dataclass
class FibSwing:
    origin_date: str
    origin_price: float
    end_date: str
    end_price: float
    direction: SwingDirection
    scale_mult: float
    magnitude_atr: float
    duration_bars: int
    confirmed_at: str
    # Positional index (within the warmup-trimmed detection series) of the
    # origin/end pivot bars -- not part of the persisted schema (dates are
    # the durable identity), but needed internally for cross-scale dedup
    # ("within N *bars*" -- calendar-day gaps aren't equivalent across
    # weekends/holidays) and for the recency weight's bars_since_end.
    origin_bar_index: int = 0
    end_bar_index: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value
        return d


@dataclass
class FibLevel:
    id: str
    ratio: float
    kind: FibLevelKind
    price: float
    # Populated by lifecycle.evaluate_level_touches -- how price has
    # actually interacted with this level since the swing completed, not
    # just its static ratio->price mapping. All default to "never tested"
    # (0/None/False) for a level that's too new to have any bars after it.
    n_touches: int = 0
    n_violations: int = 0
    first_touch_date: str | None = None
    last_touch_date: str | None = None
    # ATR-normalized average forward-favorable-move across touches (does
    # price actually bounce off this level, not just brush it) -- same
    # mechanics as sr_lines.events._reaction_atr.
    avg_reaction_atr: float | None = None
    # Cheap derived summary (n_violations == 0 and n_touches > 0) so a model
    # can filter without recomputing from the raw counts.
    respected: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class FibSet:
    id: str
    ticker: str
    timeframe: Timeframe
    swing: FibSwing
    levels: list[FibLevel] = field(default_factory=list)
    weight: float = 0.0
    status: FibSetStatus = FibSetStatus.ACTIVE
    invalidated_date: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "timeframe": self.timeframe.value if isinstance(self.timeframe, Timeframe) else self.timeframe,
            "swing": self.swing.to_dict(),
            "levels": [lvl.to_dict() for lvl in self.levels],
            "weight": self.weight,
            "status": self.status.value,
            "invalidated_date": self.invalidated_date,
            "run_id": self.run_id,
        }
