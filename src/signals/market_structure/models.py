"""Output data model for market-structure (trend-regime) tracking -- Break
of Structure (BOS) / Change of Character (CHoCH), pivot breakout
validation design doc §1 (docs/features/pivot_breakout_validation_design.md).

Unlike patterns.PatternMatch (a bounded formation with its own target/
stop/lifecycle), this tracks a single ongoing trend-direction *state*,
updated by discrete break events as price closes past a structural pivot
-- closer in shape to divergences.Divergence (a stream of dated events)
than to a pattern with a resolution horizon. See detect.py for the break-
classification rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from src.foundation.market_common.models import Direction, Pivot, Timeframe

__all__ = ["Direction", "Timeframe", "StructureEvent", "TrendState"]


class StructureEvent(str, Enum):
    # A close beyond the pivot that was containing the *opposite* side of
    # the prevailing trend (the "line in the sand") -- the regime flips
    # (BULLISH<->BEARISH).
    CHOCH = "choch"
    # A close beyond the most recent same-direction pivot -- the
    # prevailing trend just confirmed a new higher high (bullish) / lower
    # low (bearish) without the regime itself changing.
    BOS = "bos"


@dataclass
class TrendState:
    id: str
    ticker: str
    timeframe: Timeframe
    event: StructureEvent
    # Direction AFTER this event resolves -- for a CHOCH this is the newly
    # flipped regime; for a BOS it's unchanged from the direction already
    # in effect (this event just confirmed it).
    direction: Direction
    # The structural pivot whose close-break triggered this event -- the
    # "line in the sand" for CHOCH, the most recent same-direction pivot
    # for BOS.
    broken_pivot: Pivot
    broken_at: str
    close: float
    volume_confirmed: bool
    run_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timeframe"] = self.timeframe.value
        d["event"] = self.event.value
        d["direction"] = self.direction.value
        return d
