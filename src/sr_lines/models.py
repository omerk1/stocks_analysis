"""Output data model for the S/R detection engine -- plain, JSON-serializable
dataclasses. This is the contract between engine.py (which builds these) and
everything downstream (plotting.py, a future model consumer): no Plotly, no
pandas objects, no engine internals leak through here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum


class LineKind(str, Enum):
    HORIZONTAL = "horizontal"
    DIAGONAL = "diagonal"


class LineRole(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    FLIPPED = "flipped"


class LineState(str, Enum):
    ACTIVE = "active"
    BROKEN = "broken"
    FLIPPED = "flipped"


class EventType(str, Enum):
    TOUCH = "touch"
    WICK_FAKE = "wick_fake"
    BODY_FAKE = "body_fake"
    BREAK = "break"


class PivotKind(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class Pivot:
    kind: PivotKind
    timestamp: str
    price: float
    confirmed_at: str
    atr_at_pivot: float
    # Integer position in the detection window's bar index -- the x-axis
    # diagonal trendline fitting needs (log-price vs. bar-index, not
    # price-only like horizontal clustering). Defaults to 0 so tests that
    # construct a Pivot without a real bars context don't need to supply one.
    bar_index: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    type: EventType
    start: str
    end: str
    penetration_atr: float
    reaction_atr: float
    volume_ratio: float | None = None
    # BODY_FAKE only: set once the K-bar reclaim window has been observed.
    # None while a candidate body-break is still within its reclaim window
    # and hasn't yet been classified as BODY_FAKE or BREAK (as_of mode).
    pending: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class ScoreBreakdown:
    touch_quality: float = 0.0
    duration_density: float = 0.0
    resilience: float = 0.0
    role_reversal: float = 0.0
    proximity: float = 0.0
    # Multiplicative gate (proximity x recency) applied to the weighted sum
    # of the other four components -- an old, far-from-price level can't be
    # "saved" by strong historical evidence the way it could when proximity
    # was just another additive term. 1.0 = fully relevant, ~0 = stale/far.
    relevance_gate: float = 1.0
    # Second multiplicative gate: fraction of this line's *current regime*
    # (see scoring.regime_start) that price actually spent near it, as
    # opposed to the line extrapolating through empty space while real
    # price action happened elsewhere. Same reasoning as relevance_gate --
    # couldn't be an additive term without letting a line saturated on
    # touch_quality/resilience/role_reversal "buy back" a low in-play
    # fraction. 1.0 = price tracked it throughout its current regime, ~0 =
    # mostly hovering away from real price.
    in_play_gate: float = 1.0
    diagonal_penalty: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Line:
    id: str
    kind: LineKind
    role: LineRole
    state: LineState
    # Horizontal: center +/- half_width is the zone. Diagonal: slope/intercept
    # are in log-price-per-bar-index space, half_width is the log-space band.
    center: float | None
    half_width: float
    slope: float | None
    intercept: float | None
    origin_index: int | None
    first_touch: str
    last_event: str
    # Start of this line's *current* regime of engagement (see
    # scoring.regime_start) -- may be well after first_touch if there was a
    # real multi-year dormant gap before the line's current relevance began.
    # None for lines not built through lifecycle.build_line (e.g. hand-built
    # in tests), in which case consumers fall back to first_touch -- the old,
    # pre-regime-concept behavior.
    regime_start: str | None = None
    events: list[Event] = field(default_factory=list)
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    strength: float = 0.0
    proximity: float = 0.0
    n_touches: int = 0
    n_wick_fakes: int = 0
    n_body_fakes: int = 0
    n_breaks: int = 0
    # Diagonal only: the fitted line's own fit-quality measure (see
    # candidates.DiagonalCandidate.fit_rms_atr_pct), carried onto the built
    # Line so lifecycle.dedup_lines can rescore a merged survivor with its
    # own diagonal_penalty preserved rather than losing it after a merge.
    diagonal_fit_penalty: float = 0.0
    broken_at: str | None = None
    flipped_at: str | None = None

    def price_at(self, bar_index: int) -> float:
        """Zone center price at a given integer bar index. For horizontal
        lines this is constant; for diagonal lines it follows the fitted
        log-linear trend from origin_index."""
        if self.kind == LineKind.HORIZONTAL:
            return self.center
        return math.exp(self.intercept + self.slope * (bar_index - self.origin_index))

    def zone_at(self, bar_index: int) -> tuple[float, float]:
        """(lo, hi) band at a given bar index -- constant width for
        horizontal, multiplicative (via `half_width`'s log-space band around
        `price_at`) for diagonal, so the real-dollar width scales with price
        along the trend the same way `candidates.DiagonalCandidate.zone_at`
        does (reused here rather than reimplemented a third time)."""
        if self.kind == LineKind.HORIZONTAL:
            return self.center - self.half_width, self.center + self.half_width
        center = self.price_at(bar_index)
        return center * math.exp(-self.half_width), center * math.exp(self.half_width)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "role": self.role.value,
            "state": self.state.value,
            "center": self.center,
            "half_width": self.half_width,
            "slope": self.slope,
            "intercept": self.intercept,
            "origin_index": self.origin_index,
            "first_touch": self.first_touch,
            "regime_start": self.regime_start,
            "last_event": self.last_event,
            "events": [e.to_dict() for e in self.events],
            "scores": self.scores.to_dict(),
            "strength": self.strength,
            "proximity": self.proximity,
            "n_touches": self.n_touches,
            "n_wick_fakes": self.n_wick_fakes,
            "n_body_fakes": self.n_body_fakes,
            "n_breaks": self.n_breaks,
            "diagonal_fit_penalty": self.diagonal_fit_penalty,
            "broken_at": self.broken_at,
            "flipped_at": self.flipped_at,
        }


@dataclass
class DataQualityReport:
    ticker: str
    rows_loaded: int
    rows_dropped: int
    drop_rate: float
    suspicious_jump_dates: list[str] = field(default_factory=list)
    unreliable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DetectionResult:
    ticker: str
    source: str
    as_of: str | None
    config_snapshot: dict
    data_quality: DataQualityReport
    lines: list[Line] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "source": self.source,
            "as_of": self.as_of,
            "config_snapshot": self.config_snapshot,
            "data_quality": self.data_quality.to_dict(),
            "lines": [line.to_dict() for line in self.lines],
        }
