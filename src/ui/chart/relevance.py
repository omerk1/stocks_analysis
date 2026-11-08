"""Which overlays are drawn by default: "relevant now" (`docs/features/chart_ui_design.md`,
"Default selection").

1. Alive as of the last bar (each module's own lifecycle, `Overlay.alive`).
2. In reach: the distance from the last close to the item, in ATRs, is at most
   `reach_atr`. A zone counts from its nearer edge, and is 0 when the close is inside it.
3. Score = `weight x proximity + (1 - weight) x strength`, proximity = 1 - distance / reach,
   strength = the item's mid-rank percentile among its family's alive items. A family
   with no strength is scored on proximity alone.
4. The best `per_family` of each family, then the best `total` of those.

Events (divergences) aren't at a price: in reach means confirmed at most `reach_bars`
bars ago (per timeframe), and proximity is recency, 1 - age / reach_bars. Events with the same
`same_key` (one pivot, several indicators) take one slot.

Display rules only: none of these numbers is tuned against anything, and none may be
tuned against returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Timeframe
from src.ui.chart.config import RelevanceConfig
from src.ui.chart.overlays import Overlay


@dataclass(frozen=True, eq=False)
class Ranked:
    overlay: Overlay
    distance_atr: float
    in_reach: bool
    strength_pct: float | None  # None: the family has no strength
    score: float | None  # None: dead or out of reach, never picked by default


def distance_atr(lo: float, hi: float, close: float, atr: float) -> float:
    """Distance from `close` to the nearer edge of [lo, hi], in ATRs; 0 inside it,
    inf when the ATR isn't defined."""
    if not np.isfinite(atr) or atr <= 0 or not (np.isfinite(lo) and np.isfinite(hi)):
        return float("inf")
    if lo <= close <= hi:
        return 0.0
    return min(abs(lo - close), abs(hi - close)) / atr


def _mid_rank_pct(values: list[float]) -> list[float]:
    """Each value's mid-rank percentile in (0, 1): ties share their average rank, and
    a lone value gets 0.5, not 1."""
    if not values:
        return []
    ranks = pd.Series(values).rank(method="average").to_numpy()
    return list((ranks - 0.5) / len(values))


def rank(overlays: list[Overlay], close: float, atr: float, config: RelevanceConfig,
         weight: float | None = None, timeframe: Timeframe = Timeframe.DAILY) -> list[Ranked]:
    """Every overlay with its distance, reach and score, best first: scored items by
    score, then the rest alive before dead, nearest (or most recent) first. An event's
    `distance_atr` is inf: it isn't at a price."""
    w = config.weight if weight is None else min(max(float(weight), 0.0), 1.0)
    reach_bars = config.reach_bars[timeframe]
    strength_pct: dict[int, float] = {}
    by_family: dict[str, list[Overlay]] = {}
    for o in overlays:
        if o.alive and o.strength is not None and np.isfinite(o.strength):
            by_family.setdefault(o.family, []).append(o)
    for items in by_family.values():
        for o, pct in zip(items, _mid_rank_pct([o.strength for o in items])):
            strength_pct[id(o)] = pct

    ranked = []
    for o in overlays:
        if o.age_bars is None:
            d = distance_atr(o.lo, o.hi, close, atr)
            reach, proximity = d <= config.reach_atr, 1.0 - d / config.reach_atr
        else:  # an event: how recent it is takes the place of how close
            d = float("inf")
            reach, proximity = o.age_bars <= reach_bars, 1.0 - o.age_bars / reach_bars
        pct = strength_pct.get(id(o))
        score = None
        if o.alive and reach:
            score = proximity if pct is None else w * proximity + (1.0 - w) * pct
        ranked.append(Ranked(o, d, reach, pct, score))
    ranked.sort(key=lambda r: (r.score is None, -(r.score or 0.0), not r.overlay.alive, _nearness(r)))
    return ranked


def _nearness(r: Ranked) -> float:
    """Unscored items' order within a family: nearest level, or most recent event,
    first. (A family is all levels or all events, so the units never meet in a list.)"""
    return r.distance_atr if r.overlay.age_bars is None else float(r.overlay.age_bars)


def nearest_alive(ranked: list[Ranked], family: str, config: RelevanceConfig,
                  atr: float = float("nan")) -> list[str]:
    """What ticking a family picks when nothing of it is in reach: its `per_family`
    nearest (or most recent) alive items, one per level or event, as `family_defaults`."""
    tolerance = config.same_level_atr * atr if np.isfinite(atr) and atr > 0 else 0.0
    alive = sorted((r for r in ranked if r.overlay.family == family and r.overlay.alive), key=_nearness)
    kept: list[Overlay] = []
    for r in alive:
        if len(kept) == config.per_family:
            break
        if not any(_same(r.overlay, k, tolerance) for k in kept):
            kept.append(r.overlay)
    return [o.item_id for o in kept]


def family_defaults(ranked: list[Ranked], config: RelevanceConfig, atr: float = float("nan")) -> dict[str, list[str]]:
    """{family: item ids picked by default when that family is ticked}: its best
    `per_family` scored items. An item overlapping one already picked in its family,
    or within `same_level_atr` ATRs of it (a classic gap and an FVG over the same zone,
    the same S/R level from both presets, AVWAPs anchored days apart), is skipped, so
    one level doesn't take two slots."""
    tolerance = config.same_level_atr * atr if np.isfinite(atr) and atr > 0 else 0.0
    out: dict[str, list[str]] = {}
    taken: dict[str, list[Overlay]] = {}
    for r in ranked:
        if r.score is None:
            continue
        o = r.overlay
        ids, kept = out.setdefault(o.family, []), taken.setdefault(o.family, [])
        if len(ids) < config.per_family and not any(_same(o, k, tolerance) for k in kept):
            ids.append(o.item_id)
            kept.append(o)
    return out


def _same(a: Overlay, b: Overlay, tolerance: float) -> bool:
    """One event (same `same_key`), or for levels, overlapping prices."""
    if a.same_key is not None or b.same_key is not None:
        return a.same_key == b.same_key
    return overlaps(a.lo, a.hi, b.lo, b.hi, tolerance)


def overlaps(lo1: float, hi1: float, lo2: float, hi2: float, tolerance: float = 0.0) -> bool:
    """Two price ranges share a point, or are within `tolerance` of each other."""
    return lo1 <= hi2 + tolerance and lo2 <= hi1 + tolerance


def default_selection(ranked: list[Ranked], config: RelevanceConfig, atr: float = float("nan"),
                      per_family: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """{family: item ids} drawn when the chart opens: the families' defaults
    (`per_family`, from `family_defaults`; computed when not given), then the best
    `total` of those across families."""
    if per_family is None:
        per_family = family_defaults(ranked, config, atr)
    picked = {(f, i) for f, ids in per_family.items() for i in ids}
    best = [r for r in ranked if (r.overlay.family, r.overlay.item_id) in picked][: config.total]
    out: dict[str, list[str]] = {}
    for r in best:
        out.setdefault(r.overlay.family, []).append(r.overlay.item_id)
    return out


def last_atr(bars: pd.DataFrame, period: int) -> float:
    """ATR(`period`) at the last bar, NaN when there are too few bars."""
    if len(bars) <= period:
        return float("nan")
    return float(indicators.atr(bars, period).iloc[-1])
