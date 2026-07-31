"""Line states, role/state determination, dedup, and top-N selection.

States: ACTIVE, BROKEN(date), FLIPPED(date). A broken line is never
silently deleted -- it persists as BROKEN unless later respected from the
other side, at which point it becomes FLIPPED with the same event stream
continuing on the same Line object.
"""

from __future__ import annotations

from src.sr_lines.candidates import HorizontalCandidate
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Event, EventType, Line, LineKind, LineRole, LineState, ScoreBreakdown


def _break_and_flip_status(events: list[Event]) -> tuple[bool, bool, str | None, str | None]:
    """Single source of truth for break/flip status, shared by state
    determination and broken_at/flipped_at -- these must never disagree.

    "Flipped" is sticky: once *any* break has ever been followed by a
    respecting touch/wick-fake, the line counts as flipped permanently, even
    if it breaks again later without a further reclaim (there's no separate
    LineState for "flipped, then broken again" -- see the module docstring).
    broken_at/flipped_at report the *first* break and its confirming event,
    i.e. the pair that actually caused the flip.
    """
    ordered = sorted(events, key=lambda e: (e.start, e.end))
    saw_break = False
    is_flipped = False
    first_break_at: str | None = None
    first_flip_confirmation_at: str | None = None
    last_break_at: str | None = None
    for e in ordered:
        if e.type == EventType.BREAK:
            saw_break = True
            last_break_at = e.start
            if first_break_at is None:
                first_break_at = e.start
        elif saw_break and e.type in (EventType.TOUCH, EventType.WICK_FAKE) and not is_flipped:
            is_flipped = True
            first_flip_confirmation_at = e.start
    broken_at = last_break_at if saw_break else None
    flipped_at = first_flip_confirmation_at if is_flipped else None
    return saw_break, is_flipped, broken_at, flipped_at


def build_line(
    line_id: str,
    candidate: HorizontalCandidate,
    events: list[Event],
    original_side: str | None,
    scores: ScoreBreakdown,
) -> Line:
    has_break, flipped, broken_at, flipped_at = _break_and_flip_status(events)
    state = LineState.FLIPPED if flipped else (LineState.BROKEN if has_break else LineState.ACTIVE)

    if state == LineState.FLIPPED:
        role = LineRole.FLIPPED
    elif original_side == "above":
        role = LineRole.SUPPORT
    elif original_side == "below":
        role = LineRole.RESISTANCE
    else:
        role = LineRole.SUPPORT

    ordered = sorted(events, key=lambda e: (e.start, e.end))

    fallback_ts = candidate.pivots[0].timestamp
    first_touch = min((e.start for e in events), default=fallback_ts)
    last_event = max((e.end for e in events), default=fallback_ts)

    return Line(
        id=line_id,
        kind=LineKind.HORIZONTAL,
        role=role,
        state=state,
        center=candidate.center,
        half_width=candidate.half_width,
        slope=None,
        intercept=None,
        origin_index=None,
        first_touch=first_touch,
        last_event=last_event,
        events=ordered,
        scores=scores,
        strength=scores.total,
        proximity=scores.proximity,
        n_touches=sum(1 for e in events if e.type == EventType.TOUCH),
        n_wick_fakes=sum(1 for e in events if e.type == EventType.WICK_FAKE),
        n_body_fakes=sum(1 for e in events if e.type == EventType.BODY_FAKE),
        n_breaks=sum(1 for e in events if e.type == EventType.BREAK),
        broken_at=broken_at,
        flipped_at=flipped_at,
    )


def dedup_lines(lines: list[Line], config: SRConfig) -> list[Line]:
    """Merge lines whose zones overlap more than `dedup_overlap_threshold`
    (as a fraction of the narrower zone) -- keeps the better-scoring
    geometry, unions events. Diagonal dedup is deferred to milestone 5.
    """
    kept: list[Line] = []
    for line in sorted(lines, key=lambda l: -l.strength):
        merged_into = None
        if line.kind == LineKind.HORIZONTAL:
            for k in kept:
                if k.kind != LineKind.HORIZONTAL:
                    continue
                lo1, hi1 = line.center - line.half_width, line.center + line.half_width
                lo2, hi2 = k.center - k.half_width, k.center + k.half_width
                overlap = max(0.0, min(hi1, hi2) - max(lo1, lo2))
                narrower = min(hi1 - lo1, hi2 - lo2)
                if narrower > 0 and overlap / narrower > config.dedup_overlap_threshold:
                    merged_into = k
                    break
        if merged_into is not None:
            merged_into.events = sorted(merged_into.events + line.events, key=lambda e: (e.start, e.end))
        else:
            kept.append(line)
    return kept


def select_lines(lines: list[Line], config: SRConfig, strength_floor: float | None = None) -> list[Line]:
    ranked = sorted(lines, key=lambda l: -l.strength)
    if strength_floor is not None:
        return [line for line in ranked if line.strength >= strength_floor]
    return ranked[: config.top_n]
