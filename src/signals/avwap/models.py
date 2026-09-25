"""Output data model for anchored-VWAP anchor discovery -- plain,
JSON-serializable dataclass. Mirrors gaps.models' separation: anchors.py
builds these, store.py/plotting.py/cli.py are pure consumers.
"""

from __future__ import annotations

from dataclasses import dataclass

# AnchorType/AnchorStatus/seniority helpers live in market_common.anchors
# (shared with volume_profile) -- re-exported here so existing
# `avwap.models` imports keep working.
from src.foundation.market_common.anchors import (
    CYCLE_ROLES, SENIORITY, AnchorStatus, AnchorType, is_pure_cycle, primary_role,
)
from src.foundation.market_common.models import Timeframe

__all__ = [
    "Timeframe", "AnchorType", "AnchorStatus", "AnchoredVwap",
    "CYCLE_ROLES", "is_pure_cycle", "primary_role", "SENIORITY",
]


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
    # Populated by lifecycle.apply_interaction_tracking -- how price has
    # actually interacted with this AVWAP line since it was anchored, not
    # just where the line sits right now. All default to "no history yet"
    # (0/None) for a freshly-anchored line with no bars after it.
    distance_atr: float | None = None  # (current close - current_value) / atr, signed
    n_crosses: int = 0
    pct_bars_above: float | None = None
    pct_bars_below: float | None = None
    last_cross_date: str | None = None
    # ATR-normalized average forward-favorable-move on bars where price
    # traded within config.distance_tolerance_atr of the line -- does price
    # actually bounce off this AVWAP, same mechanics as
    # sr_lines.events._reaction_atr / fibonacci's avg_reaction_atr.
    avg_reaction_atr_on_touch: float | None = None
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
            "distance_atr": self.distance_atr,
            "n_crosses": self.n_crosses,
            "pct_bars_above": self.pct_bars_above,
            "pct_bars_below": self.pct_bars_below,
            "last_cross_date": self.last_cross_date,
            "avg_reaction_atr_on_touch": self.avg_reaction_atr_on_touch,
            "run_id": self.run_id,
        }
