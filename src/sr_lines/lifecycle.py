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


def _is_flipped(events: list[Event]) -> bool:
    ordered = sorted(events, key=lambda e: (e.start, e.end))
    saw_break = False
    for e in ordered:
        if e.type == EventType.BREAK:
            saw_break = True
        elif saw_break and e.type in (EventType.TOUCH, EventType.WICK_FAKE):
            return True
    return False


def build_line(
    line_id: str,
    candidate: HorizontalCandidate,
    events: list[Event],
    original_side: str | None,
    scores: ScoreBreakdown,
) -> Line:
    has_break = any(e.type == EventType.BREAK for e in events)
    flipped = has_break and _is_flipped(events)
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
    broken_at = None
    flipped_at = None
    for e in ordered:
        if e.type == EventType.BREAK:
            broken_at = e.start
            flipped_at = None
        elif broken_at is not None and e.type in (EventType.TOUCH, EventType.WICK_FAKE) and flipped_at is None:
            flipped_at = e.start
    if state != LineState.FLIPPED:
        flipped_at = None

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
