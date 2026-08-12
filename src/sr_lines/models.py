"""Output data model for the S/R detection engine -- plain, JSON-serializable
dataclasses. This is the contract between engine.py (which builds these) and
everything downstream (plotting.py, a future model consumer): no Plotly, no
pandas objects, no engine internals leak through here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum

from src.market_common.models import DataQualityReport, Pivot, PivotKind

__all__ = [
    "DataQualityReport", "Pivot", "PivotKind",
    "LineKind", "LineRole", "LineState", "EventType",
    "Event", "TouchCounts", "ScoreBreakdown", "Line", "DetectionResult",
]


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
    BODY_TOUCH = "body_touch"
    WICK_FAKE = "wick_fake"
    BODY_FAKE = "body_fake"
    BREAK = "break"


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
    # Set for BODY_FAKE and BREAK -- the two event types that represent a
    # close-beyond-zone. None (all three fields) for TOUCH/BODY_TOUCH/
    # WICK_FAKE (never applicable -- those never crossed in the first
    # place). For BODY_FAKE, set directly at classification time in
    # events.py: it's already, by definition, a close-beyond-zone that
    # reclaimed within `fakeout_reclaim_bars` -- that reclaim IS what makes
    # it a BODY_FAKE rather than a BREAK, so `reclaimed` is always True and
    # `bars_to_reclaim` always <= fakeout_reclaim_bars for one. For BREAK,
    # left None at classification time and filled in later (possibly
    # never) by `flip_status.pair_break_reclaims` -- a break can be
    # reclaimed long after the fakeout window that would have made it a
    # BODY_FAKE instead, which is exactly the slower, second-chance "did
    # the market change its mind" question these fields answer for a
    # BREAK specifically. `reclaimed` is bool|None (not plain bool) so
    # "not applicable" stays distinguishable from "did cross, never
    # reclaimed" (False).
    reclaimed: bool | None = None
    reclaimed_at: str | None = None
    bars_to_reclaim: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d


@dataclass
class TouchCounts:
    """Every classified interaction between price and a line, bucketed by
    how the level held (or didn't). `wick`, `body`, `wick_fake`, and
    `undercut_and_rally` are the four "held" flavors -- different depths/
    conviction, but in every one of them the level was tested and still
    respected -- and all four roll into `total`. A resolved BODY_FAKE
    ("Undercut and Rally", this codebase's own established term -- see
    docs/sr_lines_design_notes.md -- a close-beyond-zone that reclaimed
    within `fakeout_reclaim_bars`) genuinely counts as a touch here: the
    level ultimately held, just via a slower, weaker path than a same-bar
    touch or wick-fake. `breaks` is tracked on its own axis (the level did
    NOT hold within its own event) -- a break that's later reclaimed
    (`breaks_reclaimed`, via flip_status.pair_break_reclaims, a longer,
    separate horizon than U&R's bounded window) is still a break event; it
    doesn't retroactively move into `total`.
    """
    wick: int = 0                  # EventType.TOUCH -- wick-only, body never entered zone
    body: int = 0                  # EventType.BODY_TOUCH -- body entered zone, held
    wick_fake: int = 0             # EventType.WICK_FAKE -- wick breached far edge, held
    undercut_and_rally: int = 0    # EventType.BODY_FAKE, resolved (not pending) -- "U&R"
    total: int = 0                 # wick + body + wick_fake + undercut_and_rally
    avg_bars_to_reclaim_ur: float | None = None  # mean Event.bars_to_reclaim over undercut_and_rally
    breaks: int = 0                # EventType.BREAK -- level did NOT hold
    breaks_reclaimed: int = 0      # of `breaks`, how many were later reclaimed (pair_break_reclaims)
    avg_bars_to_reclaim_break: float | None = None
    bars_to_reclaim_last_break: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


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
    # Diagonal only: the fitted line's own fit-quality measure (see
    # candidates.DiagonalCandidate.fit_rms_atr_pct), carried onto the built
    # Line so lifecycle.dedup_lines can rescore a merged survivor with its
    # own diagonal_penalty preserved rather than losing it after a merge.
    diagonal_fit_penalty: float = 0.0
    broken_at: str | None = None
    flipped_at: str | None = None
    # Founding side ("above"/"below"), frozen at build_line time, never
    # touched by _absorb (a merge enriches evidence, must not redefine
    # founding identity -- same reasoning already applied to diagonal
    # first_touch/slope survival on merge). Used by store.py's natural key.
    origin_side: str | None = None
    # Diagonal only: ATR-normalized slope (see candidates.slope_atr_per_bar),
    # evaluated at "now" (bars.index[-1]). None for horizontal.
    slope_atr_per_bar: float | None = None
    touch_counts: TouchCounts = field(default_factory=TouchCounts)
    # First-half vs second-half avg penetration_atr over current-regime
    # TOUCH/BODY_TOUCH/WICK_FAKE/BODY_FAKE events (BREAK excluded --
    # terminal, not "a test that reverted"). trend = second - first; >0 =
    # deepening (erosion/weakening), <0 = shallowing (fortification/
    # strengthening). None (all 3) if <4 qualifying events. Data only --
    # deliberately NOT wired into ScoreBreakdown/score_line.
    avg_penetration_first_half: float | None = None
    avg_penetration_second_half: float | None = None
    penetration_trend: float | None = None
    avg_reaction_atr_touch: float | None = None   # over TOUCH+BODY_TOUCH+WICK_FAKE
    avg_volume_ratio_touch: float | None = None   # over TOUCH+BODY_TOUCH+WICK_FAKE
    avg_volume_ratio_break: float | None = None   # over BREAK events
    # "How long has this area been valid" -- calendar days, evaluated
    # against `now` (bars.index[-1]) at build time.
    age_days_total: int = 0        # now - first_touch
    age_days_regime: int = 0       # now - regime_start; primary "how long valid"
    days_since_last_event: int = 0 # now - last_event (recency)

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
            "diagonal_fit_penalty": self.diagonal_fit_penalty,
            "broken_at": self.broken_at,
            "flipped_at": self.flipped_at,
            "origin_side": self.origin_side,
            "slope_atr_per_bar": self.slope_atr_per_bar,
            "touch_counts": self.touch_counts.to_dict(),
            "avg_penetration_first_half": self.avg_penetration_first_half,
            "avg_penetration_second_half": self.avg_penetration_second_half,
            "penetration_trend": self.penetration_trend,
            "avg_reaction_atr_touch": self.avg_reaction_atr_touch,
            "avg_volume_ratio_touch": self.avg_volume_ratio_touch,
            "avg_volume_ratio_break": self.avg_volume_ratio_break,
            "age_days_total": self.age_days_total,
            "age_days_regime": self.age_days_regime,
            "days_since_last_event": self.days_since_last_event,
        }


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
