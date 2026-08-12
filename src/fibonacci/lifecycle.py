"""Invalidation tracking for a fib swing.

A set is invalidated the first time price closes beyond its swing's
ORIGIN (not its END): an up-swing (origin=low, end=high) invalidates on a
close below the origin low; a down-swing invalidates on a close above the
origin high. Crossing beyond the END is expected, ongoing behavior for an
active swing (that's precisely when its extension levels become
relevant), not invalidation.

No bar between origin_date and end_date can breach the origin: by
`detect_pivots`' own construction, origin is the running extreme of its
stretch right up until the reversal that produces end, so it's safe (and
simplest) to scan forward from end_date only, not origin_date.

Once invalidated, status is terminal -- searching for only the *first*
breach and never re-examining afterward already guarantees a later close
back inside the range can't revert it.
"""

from __future__ import annotations

import pandas as pd

from src.fibonacci.models import FibSwing, FibSetStatus, SwingDirection


def evaluate_lifecycle(swing: FibSwing, close: pd.Series) -> tuple[FibSetStatus, str | None]:
    """`close` should already be trimmed to whatever `as_of` cutoff is in
    effect -- invalidation is judged only against bars the caller allows
    this evaluation to see, so as_of's "no lookahead" guarantee is the
    caller's responsibility (engine.py loads bars via `load_bars(...,
    as_of=as_of)` before any of this runs), not re-enforced here.
    """
    after = close[close.index > pd.Timestamp(swing.end_date)]
    if swing.direction == SwingDirection.UP:
        breaches = after[after < swing.origin_price]
    else:
        breaches = after[after > swing.origin_price]

    if breaches.empty:
        return FibSetStatus.ACTIVE, None
    return FibSetStatus.INVALIDATED, breaches.index[0].isoformat()
