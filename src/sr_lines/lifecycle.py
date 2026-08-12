"""Line states, role/state determination, dedup, and top-N selection.

States: ACTIVE, BROKEN(date), FLIPPED(date). A broken line is never
silently deleted -- it persists as BROKEN unless later respected from the
other side, at which point it becomes FLIPPED with the same event stream
continuing on the same Line object.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.sr_lines import events as events_mod
from src.sr_lines import flip_status
from src.sr_lines import scoring
from src.sr_lines.candidates import Candidate, DiagonalCandidate, slope_atr_per_bar, slopes_are_similar
from src.sr_lines.config import SRConfig
from src.sr_lines.flip_status import BreakFlipStatus, break_and_flip_status
from src.sr_lines.models import (
    Event, EventType, Line, LineKind, LineRole, LineState, ScoreBreakdown, TouchCounts,
)

_REACTION_EVENT_TYPES = (EventType.TOUCH, EventType.BODY_TOUCH, EventType.WICK_FAKE)


@dataclass
class _EventDerivedFields:
    status: BreakFlipStatus
    state: LineState
    regime_start: str
    last_event: str
    touch_counts: TouchCounts
    avg_penetration_first_half: float | None
    avg_penetration_second_half: float | None
    penetration_trend: float | None
    avg_reaction_atr_touch: float | None
    avg_volume_ratio_touch: float | None
    avg_volume_ratio_break: float | None
    age_days_total: int
    age_days_regime: int
    days_since_last_event: int


def _derive_event_fields(
    events: list[Event], bars: pd.DataFrame, config: SRConfig, first_touch: str,
) -> _EventDerivedFields:
    """Everything `build_line`/`_absorb` derive purely from a line's own
    event stream (plus `bars`, for age/reference-bar math) -- factored out
    of both so the growing pile of counts/aggregates below has exactly one
    home instead of drifting into a second, third, ... copy every time a
    new one is added (this already happened once, pre-session, with
    `break_and_flip_status`/`regime_start` themselves being computed
    independently in `build_line` and `_absorb`).

    `touch_counts` covers the line's *whole* documented history (`events`,
    not regime-scoped) -- matching the pre-existing n_touches/n_wick_fakes/
    n_body_fakes/n_breaks convention this replaces. These are raw counts,
    not "current evidence quality" the way touch_quality/resilience/
    role_reversal are (scoring.py deliberately regime-scopes those), and
    `duration_density` already establishes the "full history is the right
    scope for how much has ever happened here" precedent this follows.

    Penetration-trend and reaction/volume averages, by contrast, *are*
    regime-scoped (current-regime events only) -- same reasoning
    `scoring.score_line` already applies to touch_quality/resilience/
    role_reversal: a line's current regime is what's actually relevant to
    "is this level behaving differently lately," not diluted by a long-past,
    possibly-unrelated dormant stretch.
    """
    status = break_and_flip_status(events)
    state = (
        LineState.FLIPPED if status.is_flipped
        else (LineState.BROKEN if status.saw_break else LineState.ACTIVE)
    )
    last_event = max((e.end for e in events), default=first_touch)
    regime_start_ts = (
        scoring.regime_start(events, config.regime_gap_years, since=first_touch)
        if events else pd.Timestamp(first_touch)
    )
    regime_start_str = regime_start_ts.isoformat() if events else first_touch

    wick = sum(1 for e in events if e.type == EventType.TOUCH)
    body = sum(1 for e in events if e.type == EventType.BODY_TOUCH)
    wick_fake = sum(1 for e in events if e.type == EventType.WICK_FAKE)
    ur_events = [e for e in events if e.type == EventType.BODY_FAKE and not e.pending]
    undercut_and_rally = len(ur_events)
    ur_durations = [e.bars_to_reclaim for e in ur_events if e.bars_to_reclaim is not None]
    avg_bars_to_reclaim_ur = (sum(ur_durations) / len(ur_durations)) if ur_durations else None

    break_reclaims = flip_status.pair_break_reclaims(events, bars)
    # Attach the pairing result back onto the actual Event objects -- Event
    # isn't frozen, so this in-place mutation is safe and requires no
    # rebuilding of `events`.
    for br in break_reclaims:
        br.break_event.reclaimed = br.reclaimed
        br.break_event.reclaimed_at = br.reclaimed_at
        br.break_event.bars_to_reclaim = br.bars_to_reclaim
    breaks_reclaimed = sum(1 for br in break_reclaims if br.reclaimed)
    break_durations = [br.bars_to_reclaim for br in break_reclaims if br.reclaimed]

    touch_counts = TouchCounts(
        wick=wick, body=body, wick_fake=wick_fake, undercut_and_rally=undercut_and_rally,
        total=wick + body + wick_fake + undercut_and_rally,
        avg_bars_to_reclaim_ur=avg_bars_to_reclaim_ur,
        breaks=len(break_reclaims), breaks_reclaimed=breaks_reclaimed,
        avg_bars_to_reclaim_break=(sum(break_durations) / len(break_durations)) if break_durations else None,
        bars_to_reclaim_last_break=break_reclaims[-1].bars_to_reclaim if break_reclaims else None,
    )

    regime_events = [e for e in events if pd.Timestamp(e.start) >= regime_start_ts]
    avg_first, avg_second, trend = scoring.penetration_depth_trend(regime_events)

    reaction_events = [e for e in regime_events if e.type in _REACTION_EVENT_TYPES]
    avg_reaction_atr_touch = (
        sum(e.reaction_atr for e in reaction_events) / len(reaction_events) if reaction_events else None
    )
    touch_volumes = [e.volume_ratio for e in reaction_events if e.volume_ratio is not None]
    avg_volume_ratio_touch = (sum(touch_volumes) / len(touch_volumes)) if touch_volumes else None
    break_events_regime = [e for e in regime_events if e.type == EventType.BREAK]
    break_volumes = [e.volume_ratio for e in break_events_regime if e.volume_ratio is not None]
    avg_volume_ratio_break = (sum(break_volumes) / len(break_volumes)) if break_volumes else None

    now = bars.index[-1]
    age_days_total = (now - pd.Timestamp(first_touch)).days
    age_days_regime = (now - regime_start_ts).days
    days_since_last_event = (now - pd.Timestamp(last_event)).days

    return _EventDerivedFields(
        status=status, state=state, regime_start=regime_start_str, last_event=last_event,
        touch_counts=touch_counts,
        avg_penetration_first_half=avg_first, avg_penetration_second_half=avg_second, penetration_trend=trend,
        avg_reaction_atr_touch=avg_reaction_atr_touch,
        avg_volume_ratio_touch=avg_volume_ratio_touch,
        avg_volume_ratio_break=avg_volume_ratio_break,
        age_days_total=age_days_total, age_days_regime=age_days_regime,
        days_since_last_event=days_since_last_event,
    )


def build_line(
    line_id: str,
    candidate: Candidate,
    events: list[Event],
    original_side: str | None,
    scores: ScoreBreakdown,
    config: SRConfig,
    bars: pd.DataFrame,
    atr: pd.Series,
) -> Line:
    if original_side == "above":
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

    derived = _derive_event_fields(ordered, bars, config, first_touch)
    if derived.state == LineState.FLIPPED:
        role = LineRole.FLIPPED

    is_diagonal = isinstance(candidate, DiagonalCandidate)
    now_bar_index = len(bars) - 1
    slope_atr = (
        slope_atr_per_bar(candidate.slope, candidate.center_at(now_bar_index), atr.iloc[-1])
        if is_diagonal else None
    )

    return Line(
        id=line_id,
        kind=LineKind.DIAGONAL if is_diagonal else LineKind.HORIZONTAL,
        role=role,
        state=derived.state,
        center=None if is_diagonal else candidate.center,
        half_width=candidate.half_width,
        slope=candidate.slope if is_diagonal else None,
        intercept=candidate.intercept if is_diagonal else None,
        origin_index=candidate.origin_index if is_diagonal else None,
        first_touch=first_touch,
        regime_start=derived.regime_start,
        last_event=derived.last_event,
        events=ordered,
        scores=scores,
        strength=scores.total,
        proximity=scores.proximity,
        diagonal_fit_penalty=candidate.fit_rms_atr_pct if is_diagonal else 0.0,
        broken_at=derived.status.broken_at,
        flipped_at=derived.status.flipped_at,
        origin_side=original_side,
        slope_atr_per_bar=slope_atr,
        touch_counts=derived.touch_counts,
        avg_penetration_first_half=derived.avg_penetration_first_half,
        avg_penetration_second_half=derived.avg_penetration_second_half,
        penetration_trend=derived.penetration_trend,
        avg_reaction_atr_touch=derived.avg_reaction_atr_touch,
        avg_volume_ratio_touch=derived.avg_volume_ratio_touch,
        avg_volume_ratio_break=derived.avg_volume_ratio_break,
        age_days_total=derived.age_days_total,
        age_days_regime=derived.age_days_regime,
        days_since_last_event=derived.days_since_last_event,
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
    """Merge `absorbed` into `survivor` in place and recompute every field
    derived from the event stream, so a merged line's state/score reflect
    the *union* of evidence, not just whichever candidate happened to keep
    its own geometry.

    Horizontal: `absorbed`'s events are unioned directly into `survivor`'s
    -- safe, since a horizontal zone's bounds are a constant (lo, hi), so if
    two zones were close enough to merge, they were close *everywhere*, not
    just at the points dedup happened to check.

    Diagonal: a band's bounds move with its slope, and the dedup proximity
    check (`candidates._candidates_are_duplicate`) only samples 2 points --
    two candidates can pass that check while diverging elsewhere along
    their span. Blindly unioning pre-computed events (each validated
    against its *own* candidate's zone) would attach events to a final
    geometry they don't actually match -- confirmed on a real T line: a
    ~0.5%-wide band with dozens of "touch"/"break" events whose close price
    sat 5-15% away from it, physically impossible for a genuine interaction
    with that zone. Instead, re-classify from scratch against the
    survivor's own kept geometry, so every event is always consistent with
    what's actually rendered, regardless of how the merge happened.

    `first_touch` is extended back to `absorbed`'s (if earlier) for
    horizontal only, never for diagonal. For horizontal that's always valid
    -- the zone's bounds are a constant, so "this same level was touched
    earlier too" holds regardless of when. For diagonal it isn't: the
    survivor keeps its *own* slope/intercept (a merge never changes them),
    so pulling the displayed start back past the survivor's own earliest
    defining pivot would render the box across a period its fitted geometry
    was never actually fit against or validated for -- confirmed on a real
    AAPL line whose `first_touch` got pulled back to 2018-09 from an
    absorbed candidate, while every one of its own 5 defining pivots was
    2020-07 through 2026-02; the fitted line at 2018-09-10 (~$68) had no
    relationship to the real price that day (~$52), a pure unvalidated
    backward extrapolation. The dedup check that allowed the merge only
    verifies proximity from the *later* of the two candidates' starts
    onward, never before it, so the pre-2020 period was never actually
    checked for geometric agreement in the first place.

    Every field `_derive_event_fields` computes (state, regime_start,
    last_event, touch_counts, penetration/reaction/volume aggregates, age
    fields) is likewise recomputed from the final event set on every merge,
    for both kinds -- all of it is a pure function of the event timeline,
    not something a merge can leave stale the way a naive event union
    could. `origin_side` is the one exception, deliberately: it's the
    line's founding identity, frozen at `build_line` time, and a merge
    enriches evidence without redefining what founded it.
    """
    if survivor.kind == LineKind.DIAGONAL:
        survivor.events, _ = events_mod.classify_events(
            bars, survivor, atr, config, start_ts=pd.Timestamp(survivor.first_touch),
        )
    else:
        survivor.first_touch = min(survivor.first_touch, absorbed.first_touch)
        survivor.events = sorted(survivor.events + absorbed.events, key=lambda e: (e.start, e.end))

    derived = _derive_event_fields(survivor.events, bars, config, survivor.first_touch)
    survivor.state = derived.state
    survivor.regime_start = derived.regime_start
    survivor.last_event = derived.last_event
    survivor.touch_counts = derived.touch_counts
    survivor.avg_penetration_first_half = derived.avg_penetration_first_half
    survivor.avg_penetration_second_half = derived.avg_penetration_second_half
    survivor.penetration_trend = derived.penetration_trend
    survivor.avg_reaction_atr_touch = derived.avg_reaction_atr_touch
    survivor.avg_volume_ratio_touch = derived.avg_volume_ratio_touch
    survivor.avg_volume_ratio_break = derived.avg_volume_ratio_break
    survivor.age_days_total = derived.age_days_total
    survivor.age_days_regime = derived.age_days_regime
    survivor.days_since_last_event = derived.days_since_last_event

    if survivor.state == LineState.FLIPPED:
        survivor.role = LineRole.FLIPPED
    survivor.broken_at = derived.status.broken_at
    survivor.flipped_at = derived.status.flipped_at

    is_diagonal = survivor.kind == LineKind.DIAGONAL
    now_bar_index = len(bars) - 1
    candidate_center = survivor.price_at(now_bar_index) if is_diagonal else survivor.center
    center_at = survivor.price_at if is_diagonal else None

    if is_diagonal:
        survivor.slope_atr_per_bar = slope_atr_per_bar(survivor.slope, candidate_center, atr.iloc[-1])

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
