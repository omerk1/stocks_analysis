"""Line states, role/state determination, dedup, and top-N selection.

States: ACTIVE, BROKEN(date), FLIPPED(date). A broken line is never
silently deleted -- it persists as BROKEN unless later respected from the
other side, at which point it becomes FLIPPED with the same event stream
continuing on the same Line object.
"""

from __future__ import annotations

import math

import pandas as pd

from src.sr_lines import scoring
from src.sr_lines.candidates import Candidate, DiagonalCandidate, slopes_are_similar
from src.sr_lines.config import SRConfig
from src.sr_lines.flip_status import break_and_flip_status
from src.sr_lines.models import Event, EventType, Line, LineKind, LineRole, LineState, ScoreBreakdown


def build_line(
    line_id: str,
    candidate: Candidate,
    events: list[Event],
    original_side: str | None,
    scores: ScoreBreakdown,
) -> Line:
    status = break_and_flip_status(events)
    has_break, flipped, broken_at, flipped_at = (
        status.saw_break, status.is_flipped, status.broken_at, status.flipped_at,
    )
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

    # The zone starts when its defining pivots occurred, not at the first
    # classified event -- events.py's walk deliberately doesn't emit an event
    # for the bar it uses to bootstrap which side price is on, so using
    # "earliest event" instead of "earliest pivot" here silently skipped the
    # very peak/trough that established the level. candidate.pivots isn't
    # sorted by time (candidates.py sorts by price for clustering), so this
    # must take the min explicitly rather than assuming pivots[0].
    first_touch = min(p.timestamp for p in candidate.pivots)
    last_event = max((e.end for e in events), default=first_touch)

    is_diagonal = isinstance(candidate, DiagonalCandidate)

    return Line(
        id=line_id,
        kind=LineKind.DIAGONAL if is_diagonal else LineKind.HORIZONTAL,
        role=role,
        state=state,
        center=None if is_diagonal else candidate.center,
        half_width=candidate.half_width,
        slope=candidate.slope if is_diagonal else None,
        intercept=candidate.intercept if is_diagonal else None,
        origin_index=candidate.origin_index if is_diagonal else None,
        first_touch=first_touch,
        last_event=last_event,
        events=ordered,
        scores=scores,
        strength=scores.total,
        proximity=scores.proximity,
        diagonal_fit_penalty=candidate.fit_rms_atr_pct if is_diagonal else 0.0,
        n_touches=sum(1 for e in events if e.type == EventType.TOUCH),
        n_wick_fakes=sum(1 for e in events if e.type == EventType.WICK_FAKE),
        n_body_fakes=sum(1 for e in events if e.type == EventType.BODY_FAKE),
        n_breaks=sum(1 for e in events if e.type == EventType.BREAK),
        broken_at=broken_at,
        flipped_at=flipped_at,
    )


def dedup_lines(lines: list[Line], bars: pd.DataFrame, atr: pd.Series, config: SRConfig) -> list[Line]:
    """Merge lines whose zones are close relative to their own width -- not
    just zones that literally overlap. A real run showed candidates.py's
    clustering producing several genuinely-separate (non-overlapping)
    adjacent zones that read as one cluttered area on a chart, and the old
    overlap-only check let every one of them survive untouched since none
    of their ranges actually intersected.

    Uses signed distance between the two zones (negative = already
    overlapping by that much, positive = separated by that much) against
    `dedup_overlap_threshold` as a fraction of their average width -- so the
    same knob covers "deep overlap" and "close enough to be the same area"
    with one rule. Keeps the better-scoring geometry, unions events -- and
    rescores/re-derives state from that union (see `_absorb`): a merged-in
    line's events used to just get appended to `.events` for display while
    `state`/`broken_at`/`flipped_at`/counts/`scores`/`strength` silently kept
    reflecting only the survivor's own pre-merge events. That let a merged
    zone render as e.g. ACTIVE (solid border, no break annotation) while a
    BREAK marker from the absorbed line sat right on it, and meant top-N
    selection never actually benefited from the "more complete evidence"
    a merge is supposed to represent. `bars`/`atr` are needed here (not just
    at build_line time) purely to support that rescoring.

    Diagonal-diagonal merges (v1, not a fully-reasoned final answer -- worth
    tuning against real charts the same way `dedup_overlap_threshold` was):
    same gap-based rule, but evaluated at the *current* reference bar (i.e.
    compare where both bands actually sit right now, via `Line.price_at`)
    rather than across their whole span, and gated by a slope-similarity
    check first -- two trendlines can cross near "now" while diverging
    everywhere else, and merging those would misrepresent both. Horizontal
    and diagonal lines never merge with each other.
    """
    now_bar_index = len(bars) - 1
    kept: list[Line] = []
    for line in sorted(lines, key=lambda l: -l.strength):
        merged_into = None
        for k in kept:
            if k.kind != line.kind:
                continue
            if line.kind == LineKind.HORIZONTAL:
                lo1, hi1 = line.center - line.half_width, line.center + line.half_width
                lo2, hi2 = k.center - k.half_width, k.center + k.half_width
            else:
                if not slopes_are_similar(line.slope, k.slope):
                    continue
                c1, c2 = line.price_at(now_bar_index), k.price_at(now_bar_index)
                lo1, hi1 = c1 * math.exp(-line.half_width), c1 * math.exp(line.half_width)
                lo2, hi2 = c2 * math.exp(-k.half_width), c2 * math.exp(k.half_width)
            gap = max(lo1, lo2) - min(hi1, hi2)  # negative means overlapping
            avg_width = ((hi1 - lo1) + (hi2 - lo2)) / 2
            if avg_width > 0 and gap < config.dedup_overlap_threshold * avg_width:
                merged_into = k
                break
        if merged_into is not None:
            _absorb(merged_into, line, bars, atr, config)
        else:
            kept.append(line)
    return kept


def _absorb(survivor: Line, absorbed: Line, bars: pd.DataFrame, atr: pd.Series, config: SRConfig) -> None:
    """Merge `absorbed`'s events into `survivor` in place and recompute every
    field derived from the event stream, so a merged line's state/score
    reflect the *union* of evidence, not just whichever candidate happened to
    keep its own geometry."""
    survivor.events = sorted(survivor.events + absorbed.events, key=lambda e: (e.start, e.end))
    survivor.first_touch = min(survivor.first_touch, absorbed.first_touch)
    survivor.last_event = max((e.end for e in survivor.events), default=survivor.first_touch)

    status = break_and_flip_status(survivor.events)
    survivor.state = (
        LineState.FLIPPED if status.is_flipped
        else (LineState.BROKEN if status.saw_break else LineState.ACTIVE)
    )
    if survivor.state == LineState.FLIPPED:
        survivor.role = LineRole.FLIPPED
    survivor.broken_at = status.broken_at
    survivor.flipped_at = status.flipped_at

    survivor.n_touches = sum(1 for e in survivor.events if e.type == EventType.TOUCH)
    survivor.n_wick_fakes = sum(1 for e in survivor.events if e.type == EventType.WICK_FAKE)
    survivor.n_body_fakes = sum(1 for e in survivor.events if e.type == EventType.BODY_FAKE)
    survivor.n_breaks = sum(1 for e in survivor.events if e.type == EventType.BREAK)

    is_diagonal = survivor.kind == LineKind.DIAGONAL
    now_bar_index = len(bars) - 1
    candidate_center = survivor.price_at(now_bar_index) if is_diagonal else survivor.center
    center_at = survivor.price_at if is_diagonal else None

    survivor.scores = scoring.score_line(
        survivor.events, bars, atr, candidate_center, config, diagonal=is_diagonal, center_at=center_at,
        diagonal_fit_penalty=survivor.diagonal_fit_penalty,
    )
    survivor.strength = survivor.scores.total
    survivor.proximity = survivor.scores.proximity


def select_lines(lines: list[Line], config: SRConfig, strength_floor: float | None = None) -> list[Line]:
    ranked = sorted(lines, key=lambda l: -l.strength)
    if strength_floor is not None:
        return [line for line in ranked if line.strength >= strength_floor]
    return ranked[: config.top_n]
