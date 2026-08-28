"""Output data model for chart-pattern detection -- plain, JSON-serializable
dataclass. Mirrors gaps.models'/divergences.models' separation: detectors
build these, lifecycle.py mutates the mutable fields in place, store.py/
plotting.py/cli.py are pure consumers.

One `PatternMatch` shape covers every pattern type via the `pattern_type`
discriminator, same as sr_lines' single `sr_lines` table covers both
horizontal and diagonal lines via its `kind` column -- most fields
(confidence, status, target/stop, notes) mean the same thing across every
pattern; only `key_levels`/`trendlines` differ in which named entries they
carry per type (documented per-detector, not fixed by this dataclass).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

from src.market_common.models import Direction, Pivot, Timeframe

__all__ = ["Direction", "Timeframe", "PatternType", "PatternStatus", "PatternMatch"]


class PatternType(str, Enum):
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    SYMMETRIC_TRIANGLE = "symmetric_triangle"
    RISING_WEDGE = "rising_wedge"
    FALLING_WEDGE = "falling_wedge"
    CUP_AND_HANDLE = "cup_and_handle"
    INVERSE_CUP_AND_HANDLE = "inverse_cup_and_handle"
    ROUNDING_BOTTOM = "rounding_bottom"
    ROUNDING_TOP = "rounding_top"
    VCP = "vcp"
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    PENNANT = "pennant"


class PatternStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    HIT_TARGET = "hit_target"
    INVALIDATED = "invalidated"
    # Distinct from plain INVALIDATED per design-doc §3.5/§7.5 -- a breakout
    # happened and then failed, not "never broke out at all." Tracked
    # explicitly (never collapsed into INVALIDATED or silently dropped) since
    # the false-breakout rate is itself a useful output, not noise.
    INVALIDATED_FAILED_BREAKOUT = "invalidated_failed_breakout"
    EXPIRED = "expired"
    # Broke out, then ran out the §7.3 resolution horizon
    # (config.target_horizon_mult) without hitting target or being reclaimed
    # through the trigger. Kept distinct from plain EXPIRED -- which is
    # strictly pre-breakout, "never triggered at all" -- for the same reason
    # INVALIDATED_FAILED_BREAKOUT is kept distinct from INVALIDATED: a
    # breakout that went nowhere within the pattern's own relevant timescale
    # is a different, separately-countable outcome from one that never
    # happened, and collapsing them would hide it. Distinct from ACTIVE too:
    # ACTIVE now means "still inside its horizon with data still running
    # out," a genuinely unresolved right-censored case, rather than
    # doubling as "resolved to nothing."
    EXPIRED_UNRESOLVED = "expired_unresolved"


@dataclass
class PatternMatch:
    id: str
    ticker: str
    timeframe: Timeframe
    pattern_type: PatternType
    direction: Direction
    pivots: list[Pivot]
    # Named price levels specific to this pattern instance, e.g.
    # {"neckline_start": .., "neckline_end": .., "head": ..} for H&S,
    # {"pivot_price": .., "base_low": ..} for VCP. Keys documented per
    # detector, not fixed here -- see each detectors/*.py module.
    key_levels: dict[str, float] = field(default_factory=dict)
    # Named (slope, intercept) trendlines, e.g. {"upper": (s, i), "lower":
    # (s, i)} for a triangle -- slope/intercept in (bar_index, price) space,
    # NOT log-price (see market_common.trendline_fit's docstring for why
    # patterns doesn't need sr_lines' log-space convention).
    trendlines: dict[str, tuple[float, float]] = field(default_factory=dict)
    status: PatternStatus = PatternStatus.PENDING
    breakout_bar: int | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    # 0-1, see scoring.py. Mutable -- re-evaluated (and overwritten in the
    # DB, see store.py) on every detection run, same as sr_lines' Line
    # scores or gaps' status/max_fill_pct. Not a historical record of what
    # confidence was on some earlier run.
    confidence: float = 0.0
    volume_confirmed: bool = False
    formation_start: str = ""
    formation_end: str = ""
    # Human-readable reasons for the score/status, e.g.
    # "symmetry: 0.91, touch_tightness: 0.62" -- see scoring.py's
    # docstring for why this matters during threshold tuning.
    notes: list[str] = field(default_factory=list)
    run_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timeframe"] = self.timeframe.value
        d["pattern_type"] = self.pattern_type.value
        d["direction"] = self.direction.value
        d["status"] = self.status.value
        d["pivots"] = [p.to_dict() for p in self.pivots]
        return d
