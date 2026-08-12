"""Interaction tracking against an anchor's own AVWAP line.

`compute.anchored_vwap` already computes a full, zero-lookahead series --
previously the only thing ever read from it was `.iloc[-1]`, a bare
snapshot. This walks the same series against `bars["close"/"high"/"low"]`
from the anchor date onward, the same "how has price actually interacted
with this line" question `sr_lines/events.py` and `fibonacci/lifecycle.py`
already ask of a zone/level -- including the same "a zone/tolerance band,
not a bare price" discipline those two already apply. A cross is judged
against `config.distance_tolerance_atr`, the exact same tolerance used for
touch detection below, not a bare `close >= avwap` comparison: without a
band, a `close` chattering back and forth across the raw line every single
day would inflate `n_crosses` with noise indistinguishable from one real
crossover, the same failure mode a zoneless sr_lines/fibonacci would have.
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

    # A cross requires close to move from clearly established on one side
    # of the tolerance band to clearly established on the other -- a bar
    # still inside the band (including every bar before any side has ever
    # been established) inherits the last established side rather than
    # flipping the count on its own; `current_side is None` bars (only
    # possible while price has never yet cleared the band either way) fall
    # back to a bare sign comparison so pct_bars_above/below stay defined
    # from the very first bar.
    current_side: str | None = None
    n_crosses = 0
    last_cross_date: str | None = None
    above_flags: list[bool] = []
    reactions: list[float] = []

    for i in range(n):
        a = atr_vals[i]
        tolerance = config.distance_tolerance_atr * a if pd.notna(a) and a > 0 else 0.0
        diff = closes[i] - avwap_vals[i]

        if diff > tolerance:
            raw_side = "above"
        elif diff < -tolerance:
            raw_side = "below"
        else:
            raw_side = "inside"

        if raw_side != "inside":
            if current_side is not None and raw_side != current_side:
                n_crosses += 1
                last_cross_date = idx[i].isoformat()
            current_side = raw_side
        elif pd.notna(a) and a > 0:
            r = _reaction_atr(i, bool(current_side == "above" if current_side else diff >= 0))
            if r is not None:
                reactions.append(r)

        above_flags.append(current_side == "above" if current_side is not None else diff >= 0)

    pct_above = sum(above_flags) / n
    pct_below = 1.0 - pct_above

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
