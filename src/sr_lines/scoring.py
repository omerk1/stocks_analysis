"""Weighted component scoring for a candidate line.

Each component is normalized to roughly [0, 1] before the weighted sum
(config.scoring_weights, which default to summing to 1.0). The full
per-component breakdown is always reported (ScoreBreakdown), not just the
final number -- required for tuning via the review chart and for a future
model consumer that might want the components individually.

`diagonal_penalty` is always 0.0 for horizontal lines; for diagonal lines
it's a fit-quality penalty (see `score_line`'s `diagonal_fit_penalty` param
and `candidates.DiagonalCandidate.fit_rms_atr_pct`).
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from src.sr_lines.config import SRConfig
from src.sr_lines.flip_status import break_and_flip_status, is_confirmation_event
from src.sr_lines.models import Event, EventType, ScoreBreakdown

_REACTION_CAP_ATR = 5.0
_WICK_FAKE_RESILIENCE = 0.15
_BODY_FAKE_RESILIENCE = 0.35
_BODY_FAKE_MIN_DECAY = 0.3
_RESILIENCE_CAP = 1.0
_PROXIMITY_ATR_SCALE = 5.0
_DIAGONAL_PENALTY_CAP = 0.3
# Volume weighting: a touch/wick-fake/body-fake reclaim on above-average
# volume is more convincing evidence (more participants defending the
# level) than the same interaction on thin volume -- a level "touched 4
# times on high volume" should score higher than one touched the same way
# on low volume, not just count touches. Graceful on both ends, matching
# the style of every other per-event factor here (reaction_atr capped,
# body-fake decay floored): never fully zeroes out a low-volume event
# (it's still real price action) and never lets volume alone dominate
# (capped boost). Neutral (1.0, no adjustment) when volume_ratio is
# missing (e.g. the first 20 bars of a detection window, before the
# rolling average warms up) rather than penalizing for absent data.
_VOLUME_RATIO_FLOOR = 0.7
_VOLUME_RATIO_CEILING = 1.3
_VOLUME_RATIO_CAP = 2.0
# Duration credit is judged against window_years/3, not the full detection
# window -- see _duration_score for why. Applied identically to horizontal
# and diagonal; at medium_term (window_years=3.0) this is exactly 1.0,
# reproducing the fixed 1-year reference diagonal alone used to get.
_DURATION_REFERENCE_FRACTION_OF_WINDOW = 1 / 3
# Below this many total events (of any type -- touch/wick/body/break), a
# line's span alone isn't enough to call it "mature" -- see _duration_score.
_MIN_EVENTS_FOR_FULL_DURATION_CREDIT = 4


def _decay_reference(events: list[Event], now: pd.Timestamp) -> pd.Timestamp:
    """A BROKEN (non-flipped) line is dead -- nothing more can happen to it,
    so for backtesting its historical strength shouldn't keep eroding just
    because more time passes on the calendar with nothing changing about the
    line itself. Its decay reference freezes at its last break. An ACTIVE or
    FLIPPED line is still in play and keeps decaying against the real
    reference date (`now`, i.e. as_of or the latest bar).

    Uses the same shared `flip_status.break_and_flip_status` lifecycle.py
    uses for state -- this must never disagree with lifecycle.py's state, or
    a line reported as FLIPPED could still have its score frozen as if dead.
    """
    status = break_and_flip_status(events)
    if status.saw_break and not status.is_flipped:
        return pd.Timestamp(status.broken_at)
    return now


def _volume_factor(volume_ratio: float | None) -> float:
    if volume_ratio is None:
        return 1.0
    vr = min(volume_ratio, _VOLUME_RATIO_CAP)
    return _VOLUME_RATIO_FLOOR + (_VOLUME_RATIO_CEILING - _VOLUME_RATIO_FLOOR) * (vr / _VOLUME_RATIO_CAP)


def _event_quality_score(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    """Sum of per-event evidence *strength* (not just count) x recency decay
    relative to `decay_reference`. TOUCH/BODY_TOUCH/WICK_FAKE use
    `reaction_atr` (how far price moved away afterward -- a real signal for
    all three, since a wick-fake's reclaim is scored the same way a touch's
    bounce is). A resolved BODY_FAKE has no `reaction_atr` of its own
    (events.py always sets it to 0.0 for body-fakes/breaks), so it uses the
    same reclaim-speed decay `_resilience` already computes for it instead --
    a quick reclaim is strong evidence, a slow one (up to the
    `fakeout_reclaim_bars` window) is weaker but still real, per the same
    "Undercut and Rally" grading used there.

    Also weighted by `_volume_factor(e.volume_ratio)` -- a touch on
    above-average volume is more convincing evidence (more participants
    defending the level) than the same interaction on thin volume, so a
    level touched 4 times on high volume should outscore one touched the
    same way on low volume, not just tie on count.

    Shared by `_touch_quality` (over TOUCH/BODY_TOUCH events) and
    `_role_reversal` (over confirming events after a break) so both measure
    strength, not raw count -- a handful of tiny, long-decayed, or
    barely-reclaimed events shouldn't score the same as a handful of strong,
    recent, cleanly-reclaimed ones just because the counts match.
    """
    half_life_days = half_life_years * 365.25
    total = 0.0
    for e in events:
        age_days = (decay_reference - pd.Timestamp(e.end)).days
        decay = 0.5 ** (max(age_days, 0) / half_life_days) if half_life_days > 0 else 1.0
        if e.type in (EventType.TOUCH, EventType.BODY_TOUCH, EventType.WICK_FAKE):
            quality = min(e.reaction_atr, _REACTION_CAP_ATR) / _REACTION_CAP_ATR
        elif e.type == EventType.BODY_FAKE and not e.pending:
            # bars_to_reclaim is always set for a resolved (non-pending)
            # BODY_FAKE -- see events.py's reclaim branch.
            fraction_of_window = (
                min(e.bars_to_reclaim / fakeout_reclaim_bars, 1.0) if fakeout_reclaim_bars > 0 else 1.0
            )
            quality = 1.0 - (1.0 - _BODY_FAKE_MIN_DECAY) * fraction_of_window
        else:
            continue
        total += quality * _volume_factor(e.volume_ratio) * decay
    return total


def _most_recent(events: list[Event], k: int) -> list[Event]:
    """The `k` most recent events, by end date.

    Recency decay alone doesn't stop `_event_quality_score`'s sum from
    growing without bound for a long-lived line: decay shrinks each event's
    *individual* contribution, but a real, non-chop line with events every
    few weeks for several years still has enough terms that the sum
    comfortably clears any fixed divisor -- confirmed on a real AAPL line
    with 46 genuine confirming events spread across a continuous ~4-year
    regime (no gap large enough to trigger `regime_start`, so `regime_start`
    alone doesn't help here): the raw quality-weighted sum came to ~11.7
    against a divisor of 3.0, saturating `role_reversal` to 1.0 alongside
    13-14 of 15 of AAPL's/PAAS's other real top-15 lines for `role_reversal`
    and `resilience` -- evidence that was real, but no longer discriminating
    between lines once nearly everything selected into the top-N saturates.
    `_touch_quality`'s and `_role_reversal`'s divisors were always named for
    a *recent* count ("6 strong recent touches", "3 strong recent
    confirmations") but the implementation only ever restricted *which
    events* by type, never by how many -- this closes that gap by actually
    windowing to the named count, not just decaying by age.
    """
    if len(events) <= k:
        return events
    return sorted(events, key=lambda e: (e.end, e.start))[-k:]


_TOUCH_QUALITY_TOUCHES_FOR_FULL_CREDIT = 6


def _touch_quality(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    touches = [e for e in events if e.type in (EventType.TOUCH, EventType.BODY_TOUCH)]
    if not touches:
        return 0.0
    touches = _most_recent(touches, _TOUCH_QUALITY_TOUCHES_FOR_FULL_CREDIT)
    total = _event_quality_score(touches, bars, decay_reference, half_life_years, fakeout_reclaim_bars)
    # Normalize against a generous ceiling of "6 strong recent touches" so a
    # single decent touch doesn't already saturate the component.
    return min(total / _TOUCH_QUALITY_TOUCHES_FOR_FULL_CREDIT, 1.0)


def _duration_score(events: list[Event], window_years: float) -> float:
    """How long has this line's evidence span been going, normalized against
    `window_years / 3` -- a fixed fraction of the detection window, applied
    identically to horizontal and diagonal.

    Originally normalized against the *full* detection window for
    horizontal but a fixed 1-year reference for diagonal. That fixed
    reference was itself a real fix (confirmed on real PAAS data: comparing
    a genuinely strong, recent ~1-year diagonal against the full 8-year
    long_term window crushed it to duration_density=0.089 purely for not
    spanning 8 years, while long multi-year diagonals got this component
    almost for free just by being long) -- but applying it only to
    diagonals created a new, equally real asymmetry the other way: *any*
    diagonal older than 1 year auto-maxes this component, while a
    horizontal needs to span the *entire* window to do the same. Confirmed
    on real PAAS data (long_term, `window_years=8`): a diagonal with sparse
    evidence (4 touches, 2 wick-fakes, 1 body-fake over 2.4 years) maxed at
    duration_density=1.000, while a horizontal with *more* evidence (9
    touches, 5 wick-fakes, 4 body-fakes over a similar span) sat at 0.628 --
    letting the sparser line outrank the better-evidenced one on strength.

    A survey of real span lengths across AAPL/PAAS/T/GEVO at both presets
    found real spans cluster consistently around `window_years / 3`
    regardless of kind (medium_term median ~0.6-0.7yr against a ~1yr
    natural reference; long_term median ~2.6-3.1yr against a ~2.7yr
    reference) -- window_years/3 keeps real discriminative spread at both
    presets, unlike a flat 1-year reference (which would collapse
    long_term's duration_density to a near-constant 1.0, since most
    long_term survivors already exceed 1 year). At medium_term
    (window_years=3.0) this is exactly 1.0, so diagonals there are
    unaffected by this change -- only horizontals move, from needing the
    full window down to a third of it.

    This is *maturity in time* only -- see `_in_play_fraction` for "does
    price actually track this line," which used to be multiplied in here
    but is now a separate multiplicative gate (see `score_line`).

    Scaled by a density factor (`len(events) / _MIN_EVENTS_FOR_FULL_DURATION_CREDIT`,
    capped at 1.0): the span alone (first event to last event) says nothing
    about how populated it actually was in between -- two events years
    apart get exactly the same span-based score as fifty events spread
    across the same years. Confirmed on a real 20-ticker random sample
    (not the usual AAPL/PAAS/T/GEVO four): 17 of 3,314 real lines had <=3
    total touch-type events yet still maxed duration_density=1.000 purely
    because their first and last event happened to be calendar-far-apart
    (e.g. a diagonal with exactly 2 touches, 4.75 years apart). Currently
    low-impact in practice (all 17 scored overall strength < 0.094,
    correctly suppressed by touch_quality's own count-based ceiling, which
    carries more weight) rather than a proven top-N-corrupting bug the way
    the horizontal/diagonal asymmetry above was -- added anyway since it's
    cheap and closes a real gap in what this component claims to measure.
    """
    if len(events) < 2:
        return 0.0
    first = pd.Timestamp(min(e.start for e in events))
    last = pd.Timestamp(max(e.end for e in events))
    span_days = max((last - first).days, 1)
    reference_years = window_years * _DURATION_REFERENCE_FRACTION_OF_WINDOW
    span_score = min(span_days / (reference_years * 365.25), 1.0)
    density_factor = min(len(events) / _MIN_EVENTS_FOR_FULL_DURATION_CREDIT, 1.0)
    return span_score * density_factor


def regime_start(
    events: list[Event], gap_years: float, since: pd.Timestamp | str | None = None
) -> pd.Timestamp:
    """The start of this line's *current* regime of engagement -- not
    necessarily its very first ever touch.

    A real level/trendline can go dormant for years (price simply wanders
    elsewhere) and then be legitimately retested -- that's normal market
    behavior, not evidence the line is spurious. But a flat measure over the
    line's *entire* [first_event, last_event] history can't tell that apart
    from a genuinely loose/coincidental fit that only crosses price by
    chance now and then, spread thin across years -- both look like "price
    was rarely near this line." The distinguishing signal isn't how much
    dead time there was, it's *when*: if the two look statistically
    identical, judge the line by whatever's currently happening, not by
    time that's already over.

    Walks events chronologically; whenever the gap since the previous
    event's end (or `since`, for the very first event) exceeds `gap_years`,
    everything before that gap is treated as an earlier, separate regime,
    and the current regime is reset to start there. `in_play_gate` and the
    rendered box (`plotting.py`) both use this instead of the full event
    span, so neither the score nor the chart penalizes/displays years of
    unrelated dead time before the current regime began.

    `since`, when given, is the line's actual founding date (its earliest
    *pivot*, i.e. `first_touch` -- events.py deliberately doesn't emit an
    event for the pivot bar itself, so without this the "current regime"
    would always start a few bars after the founding pivot, even with no
    real dormancy). Falls back to the first event's own start when `since`
    isn't given (used by `score_line`, which only sees events, not the
    candidate/pivots) or there's no gap that large either way.
    """
    ordered = sorted(events, key=lambda e: e.start)
    gap_days = gap_years * 365.25
    start = pd.Timestamp(since) if since is not None else pd.Timestamp(ordered[0].start)
    prev_end = start
    for e in ordered:
        event_start = pd.Timestamp(e.start)
        if (event_start - prev_end).days > gap_days:
            start = event_start
        prev_end = max(prev_end, pd.Timestamp(e.end))
    return start


def _in_play_fraction(
    events: list[Event],
    bars: pd.DataFrame,
    atr: pd.Series,
    center_at: Callable[[int], float],
    window_start: pd.Timestamp,
) -> float:
    """Fraction of bars, across [`window_start`, last_event], where price
    actually stayed within 3 ATR of the line -- as opposed to the line just
    extrapolating through empty space while real price action happened
    somewhere else entirely. `window_start` is `regime_start`, not
    necessarily the line's very first event -- see that function's
    docstring for why the window has to exclude old, already-over dormant
    periods rather than average across them.

    `center_at(bar_index)` is evaluated per bar, not once -- a horizontal
    candidate's center is constant so this is equivalent to a fixed-scalar
    version, but a diagonal candidate's center moves with its slope, and
    "how close did price stay to the level" has to be judged against
    wherever the trend actually was at each bar, not one snapshot value.

    Used as a multiplicative gate on the whole score (see `score_line`), not
    folded into the additive weighted components the way it used to be:
    a real AAPL run showed every line in the top-15 with
    touch_quality/resilience/role_reversal all saturated at/near 1.0 (a
    long-history line easily accumulates enough break/reclaim cycles to hit
    those caps), which diluted this signal into irrelevance at its former
    ~0.20-of-0.90 additive weight -- a line spending most of its life
    "hovering" away from real price (low in-play fraction) couldn't be
    meaningfully suppressed by one weighted term among several maxed-out
    ones. Same structural fix already applied to `proximity` for the same
    reason: some signals are prerequisites, not just one nice-to-have axis
    among many, and can't be bought back by being strong elsewhere.
    """
    if len(events) < 2:
        return 0.0
    last = pd.Timestamp(max(e.end for e in events))
    in_play = bars[(bars.index >= window_start) & (bars.index <= last)]
    if in_play.empty:
        return 0.0
    a = atr.reindex(in_play.index)
    bar_indices = bars.index.get_indexer(in_play.index)
    centers = pd.Series([center_at(int(i)) for i in bar_indices], index=in_play.index)
    distance_atr = (in_play["close"] - centers).abs() / a.replace(0, pd.NA)
    fraction = (distance_atr <= 3).mean()
    return 0.0 if pd.isna(fraction) else float(fraction)


_RECENT_EVENTS_FOR_FULL_CREDIT = 3


def _resilience(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    """Undercut-and-rally, graded, not flat: a WICK_FAKE is already same-bar
    (the reclaim is instant, within the same candle), so it keeps full
    per-event credit. A BODY_FAKE spans multiple bars -- the longer price
    sat on the wrong side before reclaiming, the less convincing the
    "defended" story, so its credit decays against how much of the
    `fakeout_reclaim_bars` window it used. Floored at `_BODY_FAKE_MIN_DECAY`
    rather than decaying to ~0 -- a slow reclaim right at the limit still
    genuinely recovered, just less cleanly than an instant one, and should
    keep meaningful credit for that. Also weighted by `_volume_factor` --
    a defense on above-average volume is more convincing than the same
    reclaim on thin volume.

    Also recency-decayed against `decay_reference`, same exponential
    half-life `_event_quality_score` already applies to touch_quality/
    role_reversal -- this was a real gap, not just a hypothetical
    inconsistency: without it, a handful of defenses from a decade ago stay
    permanently worth as much as ones from last month, and this component
    saturates at its 1.0 cap purely from long accumulated history regardless
    of whether any of it is still relevant. It's the same "some evidence
    components decay, some don't" gap that let resilience/role_reversal both
    sit maxed out in the original AAPL "hovering" case -- role_reversal was
    already fixed to decay; this closes the matching gap here.

    Restricted to the `_RECENT_EVENTS_FOR_FULL_CREDIT` most recent
    qualifying (WICK_FAKE/resolved BODY_FAKE) events, same reasoning as
    `_most_recent`'s docstring -- flat per-event credit means as few as 3
    body-fakes already reach the 1.0 cap, so a long-lived line with dozens
    of real defenses spread over years saturated just as easily as one with
    exactly 3 recent ones, decay notwithstanding.
    """
    qualifying = [e for e in events if e.type in (EventType.WICK_FAKE, EventType.BODY_FAKE) and not e.pending]
    qualifying = _most_recent(qualifying, _RECENT_EVENTS_FOR_FULL_CREDIT)
    half_life_days = half_life_years * 365.25
    total = 0.0
    for e in qualifying:
        vol = _volume_factor(e.volume_ratio)
        age_days = (decay_reference - pd.Timestamp(e.end)).days
        decay = 0.5 ** (max(age_days, 0) / half_life_days) if half_life_days > 0 else 1.0
        if e.type == EventType.WICK_FAKE:
            total += _WICK_FAKE_RESILIENCE * vol * decay
        else:
            # bars_to_reclaim is always set for a resolved (non-pending)
            # BODY_FAKE -- see events.py's reclaim branch.
            fraction_of_window = (
                min(e.bars_to_reclaim / fakeout_reclaim_bars, 1.0) if fakeout_reclaim_bars > 0 else 1.0
            )
            reclaim_decay = 1.0 - (1.0 - _BODY_FAKE_MIN_DECAY) * fraction_of_window
            total += _BODY_FAKE_RESILIENCE * reclaim_decay * vol * decay
    return min(total, _RESILIENCE_CAP)


def _role_reversal(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    """Proportional, not binary, *and* quality-weighted, not just counted.

    First fix (kept): a real AAPL run showed a single confirming touch right
    after a break getting the exact same full credit as a level retested
    repeatedly from the new side, which let barely-confirmed flips dominate
    the top-N purely from this one component. Scaled with the number of
    confirming events seen after *any* break (same
    `flip_status.is_confirmation_event` predicate lifecycle.py uses for its
    sticky "ever confirmed" definition of FLIPPED -- state stays a binary
    label, only the score contribution is graded).

    Second fix: counting confirmations *by raw count* wasn't enough either --
    a fresh AAPL smoke test after the first fix still showed a line with
    `touch_quality=0.011` (almost no real evidence) but `role_reversal=1.0`
    (exactly 3 confirming events, regardless of how weak) outranking a
    never-broken line with `touch_quality=0.205` (real evidence) and
    `role_reversal=0.0`. Now uses the same `_event_quality_score` weighting
    `_touch_quality` uses (reaction-strength/reclaim-speed x recency decay),
    applied to the confirming-event subset, normalized against
    `_RECENT_EVENTS_FOR_FULL_CREDIT` "strong recent confirmations" instead
    of a raw count -- a flip "confirmed" by 3 tiny, long-decayed touches
    (the same touches that keep that line's `touch_quality` near zero) now
    also scores low here, while a flip reconfirmed by several strong,
    recent touches still reaches full credit.

    Third fix: restricted to the `_RECENT_EVENTS_FOR_FULL_CREDIT` most
    recent confirming events, not *every* confirming event since the break
    -- see `_most_recent`'s docstring. Decay alone wasn't enough for a
    line with a long but *continuous* regime (no gap for `regime_start` to
    exclude): a real AAPL line had 46 genuine confirming events spread
    across ~4 years, and even meaningfully decayed, the sum still cleared
    the divisor by ~4x, saturating this component alongside 13-14 of 15 of
    AAPL's/PAAS's other real top-15 lines -- evidence that was real, but no
    longer discriminating between lines once nearly everything in the
    top-N saturates the same way.
    """
    ordered = sorted(events, key=lambda e: (e.start, e.end))
    saw_break = False
    confirming_events = []
    for e in ordered:
        if e.type == EventType.BREAK:
            saw_break = True
        elif saw_break and is_confirmation_event(e):
            confirming_events.append(e)
    if not confirming_events:
        return 0.0
    confirming_events = _most_recent(confirming_events, _RECENT_EVENTS_FOR_FULL_CREDIT)
    total = _event_quality_score(confirming_events, bars, decay_reference, half_life_years, fakeout_reclaim_bars)
    return min(total / _RECENT_EVENTS_FOR_FULL_CREDIT, 1.0)


_MIN_EVENTS_FOR_PENETRATION_TREND = 4
_PENETRATION_TREND_TYPES = (EventType.TOUCH, EventType.BODY_TOUCH, EventType.WICK_FAKE, EventType.BODY_FAKE)


def penetration_depth_trend(events: list[Event]) -> tuple[float | None, float | None, float | None]:
    """(avg_first_half, avg_second_half, trend) of `penetration_atr` over
    TOUCH/BODY_TOUCH/WICK_FAKE/BODY_FAKE events (BREAK excluded -- it's the
    terminal event, not a "test that reverted"), ordered chronologically and
    split by position. trend > 0: deepening (erosion/weakening); trend < 0:
    shallowing (fortification/strengthening). All None below
    `_MIN_EVENTS_FOR_PENETRATION_TREND` qualifying events, for a stable
    comparison. Data only -- not wired into `ScoreBreakdown`/`score_line`,
    left for a future weight-tuning pass to decide how (or whether) to use.
    """
    qualifying = sorted(
        (e for e in events if e.type in _PENETRATION_TREND_TYPES),
        key=lambda e: (e.start, e.end),
    )
    if len(qualifying) < _MIN_EVENTS_FOR_PENETRATION_TREND:
        return None, None, None
    mid = len(qualifying) // 2
    first, second = qualifying[:mid], qualifying[mid:]
    avg_first = sum(e.penetration_atr for e in first) / len(first)
    avg_second = sum(e.penetration_atr for e in second) / len(second)
    return avg_first, avg_second, avg_second - avg_first


def _proximity(current_price: float, candidate_center: float, atr_now: float) -> float:
    if pd.isna(atr_now) or atr_now == 0:
        return 0.0
    distance_atr = abs(current_price - candidate_center) / atr_now
    return 1.0 / (1.0 + distance_atr / _PROXIMITY_ATR_SCALE)


def _recency(last_event: pd.Timestamp | None, now: pd.Timestamp, half_life_years: float) -> float:
    """How long ago was this line last actually relevant (touched, wick/body-
    faked, or broken) -- unlike `_decay_reference`, this always measures
    against the real `now`, even for a dead (BROKEN) line. That's the point:
    an old level that hasn't mattered in years should fade out here
    regardless of how good its evidence looked when it was still active.
    """
    if last_event is None:
        return 1.0
    half_life_days = half_life_years * 365.25
    if half_life_days <= 0:
        return 1.0
    age_days = (now - last_event).days
    return 0.5 ** (max(age_days, 0) / half_life_days)


def score_line(
    events: list[Event],
    bars: pd.DataFrame,
    atr: pd.Series,
    candidate_center: float,
    config: SRConfig,
    diagonal: bool = False,
    center_at: Callable[[int], float] | None = None,
    diagonal_fit_penalty: float = 0.0,
) -> ScoreBreakdown:
    """`candidate_center` is the zone's center *at the current reference bar*
    -- used for `_proximity`, which only ever cares about "how far is price
    from the level right now." `center_at`, if given, is used by
    `_in_play_fraction` instead, which needs the center at every bar in its
    in-play window, not just one snapshot -- for a horizontal candidate
    that's the same constant either way, so it defaults to a closure
    returning `candidate_center` when not given. Diagonal callers should
    pass both: `candidate_center` evaluated at the reference bar, and
    `center_at` as the candidate's own per-bar center function.

    `diagonal_fit_penalty`, only applied when `diagonal=True`, is the
    candidate's own `DiagonalCandidate.fit_rms_atr_pct` -- how loosely its
    inliers scattered around the fitted line, capped at `_DIAGONAL_PENALTY_CAP`
    so one very sloppy fit can't push the score negative outright.

    `total` is gated by `relevance_gate` (proximity x recency -- is this
    line still relevant *right now*) and `in_play_gate` (fraction of the
    line's own *current regime* -- see `regime_start` -- price actually
    spent near it, was this ever a real, tracked trendline as opposed to
    one that mostly hovers through empty space) multiplicatively, on top of
    the additively-weighted inner components -- see `_in_play_fraction`'s
    docstring for why this can't be an additive term the way
    `duration_density` used to include it.

    `touch_quality`/`resilience`/`role_reversal` -- the three "evidence
    quality" components -- are computed only from events within the
    line's current regime (`regime_start` onward), not its whole history.
    A line that broke and reformed many times in a short, long-past window
    (chop -- price crossing back and forth, not a real level) can rack up
    a dozen-plus "confirming" events across that mess and saturate all
    three at their caps, while a tightly-fit line anchored at the actual
    defining peak, with just a handful of clean, well-spaced touches, does
    not -- confirmed on a real PAAS case where a loose (`fit_rms=0.4`)
    trendline with 8 breaks and 17 touches, mostly from one chaotic
    ~11-month stretch years ago, outscored a tightly-fit (`fit_rms=0.07`)
    line through the line's own actual highest peak. `duration_density`
    deliberately stays on the *full* event span (it measures maturity, not
    current evidence quality -- a level mattering across its whole history
    is meaningful regardless of whether it's chopping right now), and
    `regime_start`/`in_play_gate` are unaffected (already regime-scoped).
    """
    now = bars.index[-1]
    half_life = config.resolved_half_life_years()
    weights = config.scoring_weights
    if center_at is None:
        center_at = lambda _bar_index: candidate_center  # noqa: E731

    decay_reference = _decay_reference(events, now)
    regime_window_start = regime_start(events, config.regime_gap_years) if events else now
    current_regime_events = [e for e in events if pd.Timestamp(e.start) >= regime_window_start]
    touch_quality = _touch_quality(
        current_regime_events, bars, decay_reference, half_life, config.fakeout_reclaim_bars
    )
    duration_density = _duration_score(events, config.window_years)
    resilience = _resilience(
        current_regime_events, bars, decay_reference, half_life, config.fakeout_reclaim_bars
    )
    role_reversal = _role_reversal(
        current_regime_events, bars, decay_reference, half_life, config.fakeout_reclaim_bars
    )
    proximity = _proximity(bars["close"].iloc[-1], candidate_center, atr.iloc[-1])
    in_play_gate = _in_play_fraction(events, bars, atr, center_at, regime_window_start)

    last_event = pd.Timestamp(max((e.end for e in events), default=None)) if events else None
    recency = _recency(last_event, now, half_life)
    relevance_gate = proximity * recency

    diagonal_penalty = 0.0
    multiplier = 1.0
    if diagonal:
        multiplier = config.diagonal_score_multiplier
        diagonal_penalty = min(diagonal_fit_penalty, _DIAGONAL_PENALTY_CAP)

    # proximity no longer participates as a fifth additive term -- with 5
    # independent weighted terms, no single weight could suppress a level
    # that scored well on every other axis (a real AAPL level from 2020, now
    # ~5x below current price, still scored 0.37 this way). It's applied
    # instead as a multiplicative gate (with recency) on the *whole* score,
    # so old-and-far collapses toward 0 regardless of how strong the
    # historical evidence looked, while recent-and-nearby stays fully live.
    inner_weight_total = (
        weights.get("touch_quality", 0.0)
        + weights.get("duration_density", 0.0)
        + weights.get("resilience", 0.0)
        + weights.get("role_reversal", 0.0)
    )
    inner_weighted = (
        weights.get("touch_quality", 0.0) * touch_quality
        + weights.get("duration_density", 0.0) * duration_density
        + weights.get("resilience", 0.0) * resilience
        + weights.get("role_reversal", 0.0) * role_reversal
    )
    inner_score = inner_weighted / inner_weight_total if inner_weight_total > 0 else 0.0
    total = max(0.0, inner_score - diagonal_penalty) * multiplier * relevance_gate * in_play_gate

    return ScoreBreakdown(
        touch_quality=touch_quality,
        duration_density=duration_density,
        resilience=resilience,
        role_reversal=role_reversal,
        proximity=proximity,
        relevance_gate=relevance_gate,
        in_play_gate=in_play_gate,
        diagonal_penalty=diagonal_penalty,
        total=total,
    )
