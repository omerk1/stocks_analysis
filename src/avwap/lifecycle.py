"""Interaction tracking against an anchor's own AVWAP line.

`compute.anchored_vwap` already computes a full, zero-lookahead series --
previously the only thing ever read from it was `.iloc[-1]`, a bare
snapshot. This walks the same series against `bars["close"/"high"/"low"]`
from the anchor date onward, the same "how has price actually interacted
with this line" question `sr_lines/events.py` and `fibonacci/lifecycle.py`
already ask of a zone/level, adapted to a single continuously-moving line
(no band/zone to track a "side" bootstrap against -- `close >= avwap` at
the very first bar already tells you which side price starts on).
"""

from __future__ import annotations

import pandas as pd

from src.avwap import compute
from src.avwap.config import AvwapConfig
from src.avwap.models import AnchoredVwap


def apply_interaction_tracking(
    bars: pd.DataFrame, atr: pd.Series, anchor: AnchoredVwap, config: AvwapConfig,
) -> AnchoredVwap:
    """Mutates and returns `anchor` with `current_value`/`updated_through`
    (same snapshot the old code set) plus `distance_atr`/`n_crosses`/
    `pct_bars_above`/`pct_bars_below`/`last_cross_date`/
    `avg_reaction_atr_on_touch`.
    """
    series = compute.anchored_vwap(bars, anchor.anchor_date, config.price_source)
    on_or_after = bars.index >= pd.Timestamp(anchor.anchor_date)
    mask = on_or_after & series.notna() & bars["close"].notna()
    sub = bars[mask]

    if sub.empty:
        anchor.current_value = None
        anchor.updated_through = bars.index[-1].isoformat() if not bars.empty else None
        return anchor

    idx = sub.index
    closes = sub["close"].to_numpy()
    highs = sub["high"].to_numpy()
    lows = sub["low"].to_numpy()
    avwap_vals = series.reindex(idx).to_numpy()
    atr_vals = atr.reindex(idx).to_numpy()
    n = len(sub)

    # Ties (close == avwap) count as "above" -- an arbitrary but consistent
    # convention, same spirit as sr_lines._close_side treating the exact
    # boundary as belonging to one side rather than a third "on the line"
    # state that would otherwise need its own handling everywhere below.
    side_above = closes >= avwap_vals

    n_crosses = 0
    last_cross_date: str | None = None
    for i in range(1, n):
        if side_above[i] != side_above[i - 1]:
            n_crosses += 1
            last_cross_date = idx[i].isoformat()

    pct_above = float(side_above.mean())
    pct_below = 1.0 - pct_above

    def _reaction_atr(i: int, side_is_above: bool) -> float | None:
        window_end = min(i + 1 + config.touch_reaction_window_bars, n)
        if i + 1 >= window_end:
            return None
        a = atr_vals[i]
        if pd.isna(a) or a == 0:
            return None
        if side_is_above:
            favorable = highs[i + 1 : window_end].max() - closes[i]
        else:
            favorable = closes[i] - lows[i + 1 : window_end].min()
        return max(0.0, float(favorable / a))

    reactions: list[float] = []
    for i in range(n):
        a = atr_vals[i]
        if pd.isna(a) or a == 0:
            continue
        distance = abs(closes[i] - avwap_vals[i]) / a
        if distance <= config.distance_tolerance_atr:
            r = _reaction_atr(i, bool(side_above[i]))
            if r is not None:
                reactions.append(r)

    now_atr = atr_vals[-1]
    distance_atr = (
        float((closes[-1] - avwap_vals[-1]) / now_atr) if pd.notna(now_atr) and now_atr != 0 else None
    )

    anchor.current_value = float(avwap_vals[-1]) if pd.notna(avwap_vals[-1]) else None
    anchor.updated_through = idx[-1].isoformat()
    anchor.distance_atr = distance_atr
    anchor.n_crosses = n_crosses
    anchor.pct_bars_above = pct_above
    anchor.pct_bars_below = pct_below
    anchor.last_cross_date = last_cross_date
    anchor.avg_reaction_atr_on_touch = (sum(reactions) / len(reactions)) if reactions else None

    return anchor
