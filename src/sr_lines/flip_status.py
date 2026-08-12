"""Single source of truth for a line's break/flip status from its event
stream -- shared by lifecycle.py (state, broken_at/flipped_at) and
scoring.py (decay reference freezing, role_reversal confirmation counting)
so they can never independently drift out of sync the way they did once
before (a real AAPL line with 6 breaks had state=FLIPPED but
flipped_at=None because two separate loops disagreed on what counted).

"Flipped" is sticky: once a break has ever been followed by a confirming
event, the line counts as flipped permanently, even if it breaks again
later without a further reclaim -- there's no separate LineState for
"flipped, then broken again."
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.sr_lines.bar_math import bars_between
from src.sr_lines.models import Event, EventType

_CONFIRMATION_TYPES = (EventType.TOUCH, EventType.BODY_TOUCH, EventType.WICK_FAKE)


def is_confirmation_event(event: Event) -> bool:
    """Does this event count as evidence the line's *current* side is being
    respected -- i.e. as a flip-confirmation when it follows a break?
    TOUCH, BODY_TOUCH, and WICK_FAKE always qualify -- a body-touch is at
    least as strong "level respected" evidence as a wick-only touch (price
    actually traded inside the zone and still snapped back). A non-pending
    BODY_FAKE also qualifies: it's the same "undercut and rally" evidence
    resilience.py already grades as weaker-but-real proof of respect (see
    docs/sr_lines_design_notes.md) -- price tried to fall back through the
    zone toward the old side and failed, closing back on the new side. A
    *pending* BODY_FAKE hasn't resolved yet and must not count.
    """
    return event.type in _CONFIRMATION_TYPES or (event.type == EventType.BODY_FAKE and not event.pending)


@dataclass
class BreakFlipStatus:
    saw_break: bool
    is_flipped: bool
    broken_at: str | None  # last break's start, if any
    flipped_at: str | None  # first confirming event's start, if flipped


@dataclass
class BreakReclaim:
    break_event: Event
    reclaimed: bool
    reclaimed_at: str | None
    bars_to_reclaim: int | None


def pair_break_reclaims(events: list[Event], bars: pd.DataFrame) -> list[BreakReclaim]:
    """Per-break (not sticky-line-level) pairing: for each BREAK, the first
    later `is_confirmation_event` is *that break's own* reclaim -- distinct
    from `break_and_flip_status`'s sticky "ever confirmed" line-level
    definition, which never resets per break. A later BREAK is NOT itself
    treated as a reclaim of an earlier one (`is_confirmation_event` never
    includes BREAK) -- a break immediately followed by an opposite-direction
    re-break with no intervening confirming event is conservatively reported
    as "never reclaimed" for the first break, rather than inventing a new
    confirmation rule. `bars_to_reclaim` is measured from the break's own
    `start` (the bar price first closed beyond the zone), matching
    BODY_FAKE's own reclaim-duration convention.

    Pure function -- does not mutate `events`; the caller (lifecycle.py)
    attaches the results back onto the actual Event objects.
    """
    ordered = sorted(events, key=lambda e: (e.start, e.end))
    results: list[BreakReclaim] = []
    outstanding: BreakReclaim | None = None
    for e in ordered:
        if e.type == EventType.BREAK:
            if outstanding is not None:
                results.append(outstanding)
            outstanding = BreakReclaim(break_event=e, reclaimed=False, reclaimed_at=None, bars_to_reclaim=None)
        elif outstanding is not None and is_confirmation_event(e):
            outstanding.reclaimed = True
            outstanding.reclaimed_at = e.start
            outstanding.bars_to_reclaim = bars_between(bars, outstanding.break_event.start, e.start)
            results.append(outstanding)
            outstanding = None
    if outstanding is not None:
        results.append(outstanding)
    return results


def break_and_flip_status(events: list[Event]) -> BreakFlipStatus:
    ordered = sorted(events, key=lambda e: (e.start, e.end))
    saw_break = False
    is_flipped = False
    first_flip_confirmation_at: str | None = None
    last_break_at: str | None = None

    for e in ordered:
        if e.type == EventType.BREAK:
            saw_break = True
            last_break_at = e.start
        elif saw_break and not is_flipped and is_confirmation_event(e):
            is_flipped = True
            first_flip_confirmation_at = e.start

    return BreakFlipStatus(
        saw_break=saw_break,
        is_flipped=is_flipped,
        broken_at=last_break_at if saw_break else None,
        flipped_at=first_flip_confirmation_at if is_flipped else None,
    )
