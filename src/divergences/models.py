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
    appeared_at: str
    confirmed_at: str
    run_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timeframe"] = self.timeframe.value
        d["indicator"] = self.indicator.value
        d["direction"] = self.direction.value
        return d
