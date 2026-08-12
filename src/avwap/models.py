"""Output data model for anchored-VWAP anchor discovery -- plain,
JSON-serializable dataclass. Mirrors gaps.models' separation: anchors.py
builds these, store.py/plotting.py/cli.py are pure consumers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.market_common.models import Timeframe

__all__ = [
    "Timeframe", "AnchorType", "AnchorStatus", "AnchoredVwap",
    "CYCLE_ROLES", "is_pure_cycle", "primary_role", "SENIORITY",
]


class AnchorType(str, Enum):
    ATH = "ath"
    ATL = "atl"
    WEEK_52_HIGH = "52w_high"
    WEEK_52_LOW = "52w_low"
    CYCLE_HIGH = "cycle_high"
    CYCLE_LOW = "cycle_low"


class AnchorStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"


CYCLE_ROLES = frozenset({AnchorType.CYCLE_HIGH, AnchorType.CYCLE_LOW})

# Shared by anchors.py (cap-trimming only ever removes pure-cycle anchors,
# never ath/atl/52w_*) and plotting.py (color/saturation keyed off the most
# senior role present) -- one ranking, not two independently-maintained
# copies that could drift.
SENIORITY = {
    AnchorType.ATH: 0, AnchorType.ATL: 0,
    AnchorType.WEEK_52_HIGH: 1, AnchorType.WEEK_52_LOW: 1,
    AnchorType.CYCLE_HIGH: 2, AnchorType.CYCLE_LOW: 2,
}


def is_pure_cycle(types) -> bool:
    types = frozenset(types)
    return bool(types) and types <= CYCLE_ROLES


def primary_role(types) -> AnchorType:
    return min(types, key=lambda t: SENIORITY[t])


@dataclass
class AnchoredVwap:
    id: str
    ticker: str
    timeframe: Timeframe
    anchor_date: str
    anchor_types: frozenset[AnchorType]
    status: AnchorStatus = AnchorStatus.ACTIVE
    # The AVWAP series itself is never stored -- only this snapshot value,
    # computed by compute.anchored_vwap at the last available bar (or
    # as_of). The full series is cheap enough to recompute on demand
    # (that's what compute.py's pure function is for) that persisting it
    # would just be a second, staleness-prone copy of the same data.
    current_value: float | None = None
    updated_through: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "timeframe": self.timeframe.value,
            "anchor_date": self.anchor_date,
            "anchor_types": sorted(t.value for t in self.anchor_types),
            "status": self.status.value,
            "current_value": self.current_value,
            "updated_through": self.updated_through,
            "run_id": self.run_id,
        }
