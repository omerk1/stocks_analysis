"""Per-line event classification: TOUCH, WICK_FAKE, BODY_FAKE, BREAK.

Walks bars chronologically against one candidate zone, tracking which side
of the zone price currently "belongs" to (its established role side) and
classifying each interaction:

- TOUCH: range intersects the zone, close snaps back to the established side
  without breaching the zone's far edge.
- WICK_FAKE: the wick breaches the zone's *far* edge (a deeper intrabar
  penetration than a touch) but the close still ends up back on the
  established side, same bar -- a failed break / stop hunt. Scores as a
  small positive (see scoring.py) since the level survived a harder test.
- BODY_FAKE: the close itself ends up on the *other* side of the zone, but
  reclaims (close back on the established side) within `fakeout_reclaim_bars`.
- BREAK: a body-close-beyond-zone that is *not* reclaimed within the window
  -- the established side flips, ending the candidate's prior phase.

A body-break still awaiting its K-bar reclaim window at the end of the
available data (or at `as_of`) is emitted as a BODY_FAKE with `pending=True`
rather than guessed either way -- this is required for as_of correctness and
is also just honest about the last few bars of any dataset.
"""

from __future__ import annotations

import pandas as pd

from src.sr_lines.candidates import Candidate
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Event, EventType

_MERGE_GAP_BARS = 3


def _close_side(close: float, zone_lo: float, zone_hi: float) -> str:
    if close > zone_hi:
        return "above"
    if close < zone_lo:
        return "below"
    return "inside"


def classify_events(
    bars: pd.DataFrame,
    candidate: Candidate,
    atr: pd.Series,
    config: SRConfig,
    start_ts: pd.Timestamp | None = None,
) -> tuple[list[Event], str | None]:
    """Returns (events, original_side) -- `original_side` ("above"/"below",
    or None if the zone was never clearly approached from either side) is
    the side price first established relative to the zone, used by
    lifecycle.py to determine the line's role (support vs. resistance)
    independent of any later break/flip.

    Zone bounds are evaluated *per bar* via `candidate.zone_at(bar_index)` --
    constant for a `HorizontalCandidate`, but a diagonal candidate's band
    moves with its slope, so "did price reclaim the established side" must
    be checked against where the band actually is at each bar, not a single
    fixed value. `bar_index` is the position in the *full* `bars` passed
    here (matching `Pivot.bar_index`/`DiagonalCandidate.origin_index`'s
    scale) -- not `sub`'s own local position, since `sub` is a suffix slice.

    `start_ts`, if given, overrides deriving it from `candidate.pivots` --
    used by `lifecycle._absorb` to re-classify a merged diagonal survivor
    (a `Line`, which has no `.pivots`) against its own kept geometry from
    its own `first_touch` instead.
    """
    if start_ts is None:
        start_ts = min(pd.Timestamp(p.timestamp) for p in candidate.pivots)
    sub = bars[bars.index >= start_ts]
    sub_atr = atr.reindex(sub.index)
    if len(sub) < 2:
        return [], None

    global_offset = bars.index.get_loc(sub.index[0])
    idx = sub.index
    highs = sub["high"].to_numpy()
    lows = sub["low"].to_numpy()
    closes = sub["close"].to_numpy()
    vol_avg20 = sub["volume"].rolling(20).mean().to_numpy()
    volumes = sub["volume"].to_numpy()
    n = len(sub)

    raw_events: list[Event] = []
    current_side: str | None = None
    original_side: str | None = None
    pending_break: dict | None = None

    def _vol_ratio(i: int) -> float | None:
        avg = vol_avg20[i]
        if pd.isna(avg) or avg == 0:
            return None
        return float(volumes[i] / avg)

    def _reaction_atr(i: int, side: str) -> float:
        window_end = min(i + 1 + config.touch_reaction_window_bars, n)
        if i + 1 >= window_end:
            return 0.0
        a = sub_atr.iloc[i]
        if pd.isna(a) or a == 0:
            return 0.0
        if side == "above":
            favorable = highs[i + 1 : window_end].max() - closes[i]
        else:
            favorable = closes[i] - lows[i + 1 : window_end].min()
        return max(0.0, float(favorable / a))

    for i in range(n):
        zone_lo, zone_hi = candidate.zone_at(global_offset + i)
        close_side = _close_side(closes[i], zone_lo, zone_hi)
        a = sub_atr.iloc[i]

        if pending_break is not None:
            if close_side == pending_break["origin_side"]:
                raw_events.append(
                    Event(
                        type=EventType.BODY_FAKE,
                        start=pending_break["start_ts"].isoformat(),
                        end=idx[i].isoformat(),
                        penetration_atr=pending_break["penetration_atr"],
                        reaction_atr=0.0,
                        volume_ratio=pending_break["volume_ratio"],
                        pending=False,
                    )
                )
                current_side = pending_break["origin_side"]
                pending_break = None
                continue
            elif i - pending_break["start_i"] >= config.fakeout_reclaim_bars:
                raw_events.append(
                    Event(
                        type=EventType.BREAK,
                        start=pending_break["start_ts"].isoformat(),
                        end=idx[i].isoformat(),
                        penetration_atr=pending_break["penetration_atr"],
                        reaction_atr=0.0,
                        volume_ratio=pending_break["volume_ratio"],
                        pending=False,
                    )
                )
                current_side = pending_break["break_side"]
                pending_break = None
                continue
            else:
                continue

        if current_side is None:
            if close_side != "inside":
                current_side = close_side
                original_side = close_side
            continue

        if close_side == "inside":
            continue

        if close_side == current_side:
            intersects = lows[i] <= zone_hi and highs[i] >= zone_lo
            if not intersects:
                continue
            if current_side == "above":
                breached_far = lows[i] < zone_lo
                depth = (zone_lo - lows[i]) if breached_far else (zone_hi - lows[i])
            else:
                breached_far = highs[i] > zone_hi
                depth = (highs[i] - zone_hi) if breached_far else (highs[i] - zone_lo)
            penetration_atr = float(depth / a) if pd.notna(a) and a != 0 else 0.0
            event_type = EventType.WICK_FAKE if breached_far else EventType.TOUCH
            raw_events.append(
                Event(
                    type=event_type,
                    start=idx[i].isoformat(),
                    end=idx[i].isoformat(),
                    penetration_atr=penetration_atr,
                    reaction_atr=_reaction_atr(i, current_side),
                    volume_ratio=_vol_ratio(i),
                )
            )
        else:
            depth = (closes[i] - zone_hi) if close_side == "above" else (zone_lo - closes[i])
            pending_break = {
                "start_ts": idx[i],
                "start_i": i,
                "origin_side": current_side,
                "break_side": close_side,
                "penetration_atr": float(depth / a) if pd.notna(a) and a != 0 else 0.0,
                "volume_ratio": _vol_ratio(i),
            }

    if pending_break is not None:
        raw_events.append(
            Event(
                type=EventType.BODY_FAKE,
                start=pending_break["start_ts"].isoformat(),
                end=idx[-1].isoformat(),
                penetration_atr=pending_break["penetration_atr"],
                reaction_atr=0.0,
                volume_ratio=pending_break["volume_ratio"],
                pending=True,
            )
        )

    return _merge_adjacent(raw_events, bars.index), original_side


def _merge_adjacent(events: list[Event], full_index: pd.DatetimeIndex) -> list[Event]:
    """Merge consecutive same-type events within `_MERGE_GAP_BARS` bars into
    one, keeping the max penetration/reaction seen across the merged group."""
    if not events:
        return []

    pos = {ts: i for i, ts in enumerate(full_index)}
    merged: list[Event] = [events[0]]

    for ev in events[1:]:
        prev = merged[-1]
        gap = pos.get(pd.Timestamp(ev.start), 0) - pos.get(pd.Timestamp(prev.end), 0)
        if ev.type == prev.type and gap <= _MERGE_GAP_BARS:
            merged[-1] = Event(
                type=prev.type,
                start=prev.start,
                end=ev.end,
                penetration_atr=max(prev.penetration_atr, ev.penetration_atr),
                reaction_atr=max(prev.reaction_atr, ev.reaction_atr),
                volume_ratio=ev.volume_ratio if ev.volume_ratio is not None else prev.volume_ratio,
                pending=ev.pending,
            )
        else:
            merged.append(ev)

    return merged
