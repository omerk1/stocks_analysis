"""Output data model for gap/FVG detection -- plain, JSON-serializable
dataclass. Mirrors sr_lines.models' separation: detect.py/lifecycle.py build
these, store.py/plotting.py/cli.py are pure consumers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from src.market_common.models import Direction, Timeframe

__all__ = ["Direction", "Timeframe", "GapKind", "GapStatus", "Gap"]


class GapKind(str, Enum):
    CLASSIC = "classic"
    FVG = "fvg"


class GapStatus(str, Enum):
    OPEN = "open"
    PARTIAL = "partial"
    SOFT_CLOSED = "soft_closed"
    CLOSED = "closed"


@dataclass
class Gap:
    id: str
    ticker: str
    timeframe: Timeframe
    kind: GapKind
    direction: Direction
    created_at: str
    zone_top: float
    zone_bottom: float
    size_atr: float
    status: GapStatus = GapStatus.OPEN
    max_fill_pct: float = 0.0
    first_touch_date: str | None = None
    soft_closed_date: str | None = None
    closed_date: str | None = None
    # Bar-count companions to the three dates above -- the exact same
    # milestones, in "bars since created_at" rather than calendar dates, so
    # a consumer doesn't have to re-join against bars_1d just to convert.
    # None wherever the corresponding date is None (milestone never reached).
    bars_to_first_touch: int | None = None
    bars_to_soft_closed: int | None = None
    bars_to_closed: int | None = None
    # Set only on an FVG row whose same-bar, same-direction classic gap was
    # also detected (see detect.py) -- the classic row's own related_id
    # always stays None, so the link is one-directional (FVG -> classic).
    related_id: str | None = None
    # Populated by lifecycle.apply_lifecycle -- insight that was already
    # being computed bar-by-bar but previously collapsed straight to
    # max_fill_pct/status without being kept. n_approaches: distinct times
    # price entered the zone and receded, not just the single running-max
    # fill curve (a gap can be approached repeatedly without ever fully
    # filling). volume_ratio_at_creation: rolling-20-bar ratio at the
    # creation bar, same calc as sr_lines.events._vol_ratio -- was a gap
    # created on unusually high volume. reaction_atr_after_close/
    # bars_to_reaction_peak: once status reaches CLOSED, the ATR-normalized
    # best move *back in the gap's original direction* within
    # config.reaction_window_bars -- the classic "fill then reverse" check.
    # None/0 ("not yet applicable") while still open or too near the data's
    # edge for a full reaction window.
    n_approaches: int = 0
    volume_ratio_at_creation: float | None = None
    reaction_atr_after_close: float | None = None
    bars_to_reaction_peak: int | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timeframe"] = self.timeframe.value
        d["kind"] = self.kind.value
        d["direction"] = self.direction.value
        d["status"] = self.status.value
        return d
