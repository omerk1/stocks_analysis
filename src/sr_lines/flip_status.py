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

from src.sr_lines.models import Event, EventType

_CONFIRMATION_TYPES = (EventType.TOUCH, EventType.WICK_FAKE)


def is_confirmation_event(event: Event) -> bool:
    """Does this event count as evidence the line's *current* side is being
    respected -- i.e. as a flip-confirmation when it follows a break?
    TOUCH and WICK_FAKE always qualify. A non-pending BODY_FAKE also
    qualifies: it's the same "undercut and rally" evidence resilience.py
    already grades as weaker-but-real proof of respect (see
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
