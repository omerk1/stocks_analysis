"""Output data model for the anchored volume profile -- plain,
JSON-serializable dataclass. Mirrors avwap.models: the full per-row
histogram is never stored, only this snapshot of what it implies (POC/VAH/
VAL and how the latest close sits against them). compute.build_profile
recomputes the histogram on demand; persisting it would be a second,
staleness-prone copy of the same data.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.foundation.market_common.anchors import AnchorStatus, AnchorType
from src.foundation.market_common.models import Timeframe

__all__ = ["Timeframe", "AnchorType", "AnchorStatus", "AnchoredVolumeProfile"]


@dataclass
class AnchoredVolumeProfile:
    id: str
    ticker: str
    timeframe: Timeframe
    anchor_date: str
    anchor_types: frozenset[AnchorType]
    status: AnchorStatus = AnchorStatus.ACTIVE
    # Snapshot at the last available bar (or as_of) -- left None for an
    # anchor whose window has no volume yet.
    poc: float | None = None  # mid-price of the max-volume row
    vah: float | None = None  # upper edge of the value area's top row
    val: float | None = None  # lower edge of the value area's bottom row
    total_volume: float | None = None
    up_volume: float | None = None  # bars with close >= open
    down_volume: float | None = None
    poc_up_volume: float | None = None
    poc_down_volume: float | None = None
    n_bars: int = 0  # bars from anchor_date through updated_through, inclusive
    current_close: float | None = None
    distance_to_poc_atr: float | None = None  # (close - poc) / atr, signed
    # "above" / "inside" / "below" the [val, vah] value area.
    value_area_position: str | None = None
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
            "poc": self.poc,
            "vah": self.vah,
            "val": self.val,
            "total_volume": self.total_volume,
            "up_volume": self.up_volume,
            "down_volume": self.down_volume,
            "poc_up_volume": self.poc_up_volume,
            "poc_down_volume": self.poc_down_volume,
            "n_bars": self.n_bars,
            "current_close": self.current_close,
            "distance_to_poc_atr": self.distance_to_poc_atr,
            "value_area_position": self.value_area_position,
            "updated_through": self.updated_through,
            "run_id": self.run_id,
        }
