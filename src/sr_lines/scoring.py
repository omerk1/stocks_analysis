"""Weighted component scoring for a candidate line.

Each component is normalized to roughly [0, 1] before the weighted sum
(config.scoring_weights, which default to summing to 1.0). The full
per-component breakdown is always reported (ScoreBreakdown), not just the
final number -- required for tuning via the review chart and for a future
model consumer that might want the components individually.

Diagonal-specific penalties (component 6 in the spec) are a no-op until
milestone 5 -- `diagonal_penalty` is always 0.0 for horizontal lines.
"""

from __future__ import annotations

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


def _event_quality_score(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    """Sum of per-event evidence *strength* (not just count) x recency decay
    relative to `decay_reference`. TOUCH/WICK_FAKE use `reaction_atr` (how far
    price moved away afterward -- a real signal for both, since a wick-fake's
    reclaim is scored the same way a touch's bounce is). A resolved BODY_FAKE
    has no `reaction_atr` of its own (events.py always sets it to 0.0 for
    body-fakes/breaks), so it uses the same reclaim-speed decay `_resilience`
    already computes for it instead -- a quick reclaim is strong evidence, a
    slow one (up to the `fakeout_reclaim_bars` window) is weaker but still
    real, per the same "Undercut and Rally" grading used there.

    Shared by `_touch_quality` (over TOUCH events) and `_role_reversal` (over
    confirming events after a break) so both measure strength, not raw count
    -- a handful of tiny, long-decayed, or barely-reclaimed events shouldn't
    score the same as a handful of strong, recent, cleanly-reclaimed ones just
    because the counts match.
    """
    half_life_days = half_life_years * 365.25
    total = 0.0
    for e in events:
        age_days = (decay_reference - pd.Timestamp(e.end)).days
        decay = 0.5 ** (max(age_days, 0) / half_life_days) if half_life_days > 0 else 1.0
        if e.type in (EventType.TOUCH, EventType.WICK_FAKE):
            quality = min(e.reaction_atr, _REACTION_CAP_ATR) / _REACTION_CAP_ATR
        elif e.type == EventType.BODY_FAKE and not e.pending:
            bars_to_reclaim = _bars_between(bars, e.start, e.end)
            fraction_of_window = (
                min(bars_to_reclaim / fakeout_reclaim_bars, 1.0) if fakeout_reclaim_bars > 0 else 1.0
            )
            quality = 1.0 - (1.0 - _BODY_FAKE_MIN_DECAY) * fraction_of_window
        else:
            continue
        total += quality * decay
    return total


def _touch_quality(
    events: list[Event],
    bars: pd.DataFrame,
    decay_reference: pd.Timestamp,
    half_life_years: float,
    fakeout_reclaim_bars: int,
) -> float:
    touches = [e for e in events if e.type == EventType.TOUCH]
    if not touches:
        return 0.0
    total = _event_quality_score(touches, bars, decay_reference, half_life_years, fakeout_reclaim_bars)
    # Normalize against a generous ceiling of "6 strong recent touches" so a
    # single decent touch doesn't already saturate the component.
    return min(total / 6.0, 1.0)


def _duration_density(
    events: list[Event],
    bars: pd.DataFrame,
    atr: pd.Series,
    candidate_center: float,
    window_years: float,
) -> float:
    if len(events) < 2:
        return 0.0
    first = pd.Timestamp(min(e.start for e in events))
    last = pd.Timestamp(max(e.end for e in events))
    span_days = max((last - first).days, 1)
    span_score = min(span_days / (window_years * 365.25), 1.0)

    in_play = bars[(bars.index >= first) & (bars.index <= last)]
    if in_play.empty:
        return 0.0
    a = atr.reindex(in_play.index)
    distance_atr = (in_play["close"] - candidate_center).abs() / a.replace(0, pd.NA)
    fraction_in_play = (distance_atr <= 3).mean()
    if pd.isna(fraction_in_play):
        fraction_in_play = 0.0

    return span_score * float(fraction_in_play)


def _bars_between(bars: pd.DataFrame, start: str, end: str) -> int:
    return int(bars.index.get_loc(pd.Timestamp(end)) - bars.index.get_loc(pd.Timestamp(start)))


def _resilience(events: list[Event], bars: pd.DataFrame, fakeout_reclaim_bars: int) -> float:
    """Undercut-and-rally, graded, not flat: a WICK_FAKE is already same-bar
    (the reclaim is instant, within the same candle), so it keeps full
    per-event credit. A BODY_FAKE spans multiple bars -- the longer price
    sat on the wrong side before reclaiming, the less convincing the
    "defended" story, so its credit decays against how much of the
    `fakeout_reclaim_bars` window it used. Floored at `_BODY_FAKE_MIN_DECAY`
    rather than decaying to ~0 -- a slow reclaim right at the limit still
    genuinely recovered, just less cleanly than an instant one, and should
    keep meaningful credit for that.
    """
    total = 0.0
    for e in events:
        if e.type == EventType.WICK_FAKE:
            total += _WICK_FAKE_RESILIENCE
        elif e.type == EventType.BODY_FAKE and not e.pending:
            bars_to_reclaim = _bars_between(bars, e.start, e.end)
            fraction_of_window = (
                min(bars_to_reclaim / fakeout_reclaim_bars, 1.0) if fakeout_reclaim_bars > 0 else 1.0
            )
            decay = 1.0 - (1.0 - _BODY_FAKE_MIN_DECAY) * fraction_of_window
            total += _BODY_FAKE_RESILIENCE * decay
    return min(total, _RESILIENCE_CAP)


_ROLE_REVERSAL_CONFIRMATIONS_FOR_FULL_CREDIT = 3


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
    `_ROLE_REVERSAL_CONFIRMATIONS_FOR_FULL_CREDIT` "strong recent
    confirmations" instead of a raw count -- a flip "confirmed" by 3 tiny,
    long-decayed touches (the same touches that keep that line's
    `touch_quality` near zero) now also scores low here, while a flip
    reconfirmed by several strong, recent touches still reaches full credit.
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
    total = _event_quality_score(confirming_events, bars, decay_reference, half_life_years, fakeout_reclaim_bars)
    return min(total / _ROLE_REVERSAL_CONFIRMATIONS_FOR_FULL_CREDIT, 1.0)


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
) -> ScoreBreakdown:
    now = bars.index[-1]
    half_life = config.resolved_half_life_years()
    weights = config.scoring_weights

    decay_reference = _decay_reference(events, now)
    touch_quality = _touch_quality(events, bars, decay_reference, half_life, config.fakeout_reclaim_bars)
    duration_density = _duration_density(events, bars, atr, candidate_center, config.window_years)
    resilience = _resilience(events, bars, config.fakeout_reclaim_bars)
    role_reversal = _role_reversal(events, bars, decay_reference, half_life, config.fakeout_reclaim_bars)
    proximity = _proximity(bars["close"].iloc[-1], candidate_center, atr.iloc[-1])

    last_event = pd.Timestamp(max((e.end for e in events), default=None)) if events else None
    recency = _recency(last_event, now, half_life)
    relevance_gate = proximity * recency

    diagonal_penalty = 0.0
    multiplier = 1.0
    if diagonal:
        multiplier = config.diagonal_score_multiplier
        diagonal_penalty = 0.0  # slope penalty is milestone 5

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
    total = max(0.0, inner_score - diagonal_penalty) * multiplier * relevance_gate

    return ScoreBreakdown(
        touch_quality=touch_quality,
        duration_density=duration_density,
        resilience=resilience,
        role_reversal=role_reversal,
        proximity=proximity,
        relevance_gate=relevance_gate,
        diagonal_penalty=diagonal_penalty,
        total=total,
    )
