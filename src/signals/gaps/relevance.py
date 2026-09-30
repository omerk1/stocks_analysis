"""Gap state and relevance as of any date -- for point-in-time consumers
(the LRP model, docs/modeling/LRP.md) and for the stored snapshot.

Two separate facts about a gap:

- Its lifecycle -- open / partial / soft_closed / closed, and how deep it
  has been filled. That stays a plain historical fact: a 1982 gap that
  never filled *is* still open.
- Whether it's *relevant* on a date: `in_reach` is False when the gap's
  midpoint is more than `GapConfig.reach_factor` x away from that date's
  close (either direction) -- the same test anchors use
  (`AnchorConfig.regime_reach_factor`). AAPL's 1982 gaps sit ~8,600x below
  today's price; in a 2026-09 sample of 393 tickers, 73% of open gaps were
  out of reach at 2x, leaving ~9 relevant open gaps per ticker, median age
  8 months. Consumers filter on it; nothing is deleted.

Why this module exists: the stored `gaps` rows are current-state -- their
`status`/`max_fill_pct` are as of the last run, so reading them for an
earlier date leaks later fills (a gap that filled in 2024 would already
look closed in 2020). Two properties make a cheap exact reconstruction
possible instead of re-running detection per date:

1. Detection only uses bars up to each gap's creation bar (ATR at t,
   highs/lows at t-2..t), so a full-history run finds exactly the gaps an
   as_of run would, for every gap created on or before as_of.
2. A gap's fill as of a date depends only on bars from its creation to
   that date -- the same running maximum `lifecycle._walk` takes, just
   stopped at the date.

`gap_states` therefore takes gaps detected once on the full history and
returns each one's state on each requested date, using only bars up to
that date. Tested equal to `detect(as_of=...)` for status and fill.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.signals.gaps.config import GapConfig
from src.signals.gaps.lifecycle import _status_for
from src.signals.gaps.models import Direction, Gap

STATE_COLUMNS = [
    "date", "gap_id", "created_at", "kind", "direction", "zone_bottom", "zone_top", "size_atr",
    "volume_ratio_at_creation", "age_bars", "max_fill_pct", "status",
    "close", "distance_x", "distance_atr", "in_reach",
]


def _fill_price(bars: pd.DataFrame, direction: Direction, fill_by: str) -> np.ndarray:
    if fill_by == "wick":
        col = "low" if direction == Direction.BULLISH else "high"
        return bars[col].to_numpy(dtype=float)
    o, c = bars["open"].to_numpy(dtype=float), bars["close"].to_numpy(dtype=float)
    return np.minimum(o, c) if direction == Direction.BULLISH else np.maximum(o, c)


def distance_x(zone_bottom: float, zone_top: float, close: float) -> float:
    """How many times away the gap's midpoint is from `close`, either
    direction (>= 1)."""
    mid = (zone_bottom + zone_top) / 2.0
    if mid <= 0 or close <= 0:
        return float("inf")
    return max(mid / close, close / mid)


def gap_states(
    bars: pd.DataFrame, gaps: list[Gap], dates, config: GapConfig, include_closed: bool = False,
) -> pd.DataFrame:
    """Each gap's state on each of `dates` (only gaps created on or before
    the date), computed from bars up to that date only. Long format, one
    row per (date, gap), columns STATE_COLUMNS. `dates` not in the bar
    index are snapped back to the last bar on or before them.

    Fully closed gaps are left out by default -- fill only ever grows, so a
    closed gap never comes back, and consumers like LRP drop them anyway
    (they'd otherwise be most of the rows: ~95% of gaps close).
    `include_closed=True` keeps them.
    """
    idx = bars.index
    if not len(idx) or not gaps:
        return pd.DataFrame(columns=STATE_COLUMNS)
    req = idx.searchsorted(pd.DatetimeIndex(pd.to_datetime(list(dates))), side="right") - 1
    positions = np.unique(req[req >= 0])
    if not len(positions):
        return pd.DataFrame(columns=STATE_COLUMNS)
    closes = bars["close"].to_numpy(dtype=float)
    atr = indicators.atr(bars, config.atr_period).to_numpy(dtype=float)
    price = {d: _fill_price(bars, d, config.fill_by) for d in Direction}

    parts = []
    for g in gaps:
        try:
            created = idx.get_loc(pd.Timestamp(g.created_at))
        except KeyError:
            continue
        wanted = positions[positions >= created]
        if not len(wanted):
            continue
        height = g.zone_top - g.zone_bottom
        # Running max fill from the bar after creation, same formula and
        # clamping as lifecycle._walk; cummax[k] = fill through bar created+1+k.
        seg = price[g.direction][created + 1: wanted[-1] + 1]
        if height > 0 and len(seg):
            pct = (g.zone_top - seg) / height if g.direction == Direction.BULLISH else (seg - g.zone_bottom) / height
            cummax = np.maximum.accumulate(np.clip(pct * 100.0, 0.0, 100.0))
        else:
            cummax = np.zeros(len(seg))
        after = wanted > created
        fill = np.zeros(len(wanted))
        fill[after] = cummax[wanted[after] - created - 1]
        if not include_closed:
            keep = fill < 100.0
            wanted, fill = wanted[keep], fill[keep]
            if not len(wanted):
                continue
        close = closes[wanted]
        mid = (g.zone_bottom + g.zone_top) / 2.0
        with np.errstate(divide="ignore", invalid="ignore"):
            dx = np.where((mid > 0) & (close > 0), np.maximum(mid / close, close / mid), np.inf)
            edge = np.where((close >= g.zone_bottom) & (close <= g.zone_top), 0.0,
                            np.minimum(np.abs(g.zone_top - close), np.abs(g.zone_bottom - close)))
            a = atr[wanted]
            dist_atr = np.where(a > 0, edge / a, np.nan)
        n = len(wanted)
        parts.append(pd.DataFrame({
            "date": idx[wanted], "gap_id": g.id, "created_at": g.created_at, "kind": g.kind.value,
            "direction": g.direction.value, "zone_bottom": g.zone_bottom, "zone_top": g.zone_top,
            "size_atr": g.size_atr, "volume_ratio_at_creation": g.volume_ratio_at_creation,
            "age_bars": wanted - created, "max_fill_pct": fill,
            "status": [_status_for(f, config.soft_close_pct).value for f in fill],
            "close": close, "distance_x": dx, "distance_atr": dist_atr,
            "in_reach": dx <= config.reach_factor,
        }, index=range(n)))
    if not parts:
        return pd.DataFrame(columns=STATE_COLUMNS)
    out = pd.concat(parts, ignore_index=True)[STATE_COLUMNS]
    return out.sort_values(["date", "created_at"], kind="stable").reset_index(drop=True)


def gaps_as_of(
    bars: pd.DataFrame, gaps: list[Gap], as_of, config: GapConfig, include_closed: bool = False,
) -> pd.DataFrame:
    """`gap_states` for a single date."""
    return gap_states(bars, gaps, [as_of], config, include_closed=include_closed)


def apply_snapshot_relevance(bars: pd.DataFrame, gaps: list[Gap], config: GapConfig) -> list[Gap]:
    """Sets `distance_x`/`in_reach` on each gap against the frame's last
    close -- the stored snapshot's view, alongside its status/fill."""
    if bars.empty:
        return gaps
    close = float(bars["close"].iloc[-1])
    for g in gaps:
        g.distance_x = distance_x(g.zone_bottom, g.zone_top, close)
        g.in_reach = g.distance_x <= config.reach_factor
    return gaps
