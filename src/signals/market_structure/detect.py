"""Break of Structure (BOS) / Change of Character (CHoCH) trend-regime
tracking -- pivot breakout validation design doc §1
(docs/features/pivot_breakout_validation_design.md). Detects the moment
price closes past the "line in the sand" -- the most recent structural
pivot holding the current trend -- and emits a CHOCH event flipping the
regime, or a BOS event confirming continuation past the most recent
same-direction pivot.

Deliberately does NOT rewrite market_common.pivots.detect_pivots (design
doc "Code Modification Rules": "do not rewrite our core pivot detection
algorithms") -- this is a state machine layered entirely on top of an
already-computed pivot sequence plus raw closes, same division of labor
as patterns.lifecycle sits on top of each pattern detector's own geometry.

Break condition is close-only, never a wick pierce ("Sharpened Break
Condition" in the design doc) -- there is no `break_confirmation_type`
param here at all (see design doc §4/§5: a literal wick-based mode was
considered and discarded, not defaulted off, since nothing in this
codebase treats a same-bar wick beyond a level as a real break).
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date

import pandas as pd

from src.foundation.market_common import data as data_mod
from src.foundation.market_common import indicators
from src.foundation.market_common.models import DataQualityReport, Pivot, PivotKind, Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.signals.market_structure.config import MarketStructureConfig
from src.signals.market_structure.models import Direction, StructureEvent, TrendState

logger = logging.getLogger(__name__)


def _confirmed_bar_index(bars: pd.DataFrame, pivot: Pivot) -> int:
    """A pivot isn't *knowable* until its confirming reversal happens --
    using its own `bar_index` instead of `confirmed_at` would let the walk
    below react to a swing point before it actually existed as far as a
    real-time observer could tell (the same lookahead-safety discipline
    every as_of-aware module in this codebase already applies)."""
    return bars.index.get_loc(pd.Timestamp(pivot.confirmed_at))


def _volume_confirmed(bars: pd.DataFrame, vol_sma: pd.Series, i: int, config: MarketStructureConfig) -> bool:
    sma_at_i = vol_sma.iloc[i]
    if pd.isna(sma_at_i) or sma_at_i <= 0:
        return False
    return float(bars["volume"].iloc[i]) / float(sma_at_i) >= config.breakout_volume_mult


def track_market_structure(
    bars: pd.DataFrame,
    pivots: list[Pivot],
    config: MarketStructureConfig,
    ticker: str,
    timeframe: Timeframe,
) -> list[TrendState]:
    """Pure function over an already-loaded bars frame and an already-
    extracted pivot sequence (market_common.pivots.detect_pivots) -- no DB
    access, no as_of handling, so synthetic tests can hand-build both
    directly (same shape as patterns.base.PatternDetector.scan /
    divergences.detect_for_indicator).

    Bootstraps the initial regime from the first two pivots: pivots
    strictly alternate HIGH/LOW (market_common.pivots' own guarantee), so
    a LOW-then-HIGH opening pair reads as an up-leg (initial direction
    BULLISH, the LOW is the line in the sand), and HIGH-then-LOW reads as
    a down-leg (BEARISH, the HIGH is the line in the sand). First-pass
    convention, not something the design doc specifies explicitly -- there
    is no prior regime to inherit from before any pivots exist at all.

    Every subsequent bar's close is tested against two levels, kept
    current as new pivots confirm:
      - the *opposite*-direction pivot most recently confirmed (the "line
        in the sand") -- a close past it is CHOCH, the regime flips.
      - the *same*-direction pivot most recently confirmed -- a close past
        it is BOS, confirming the regime without flipping it.
    Each of those two levels only fires once per pivot (a `*_broken` flag,
    reset whenever a newer pivot of that kind confirms) -- otherwise a BOS
    would refire on every single subsequent bar for as long as price stays
    beyond an already-broken level. Same "stays broken until a genuine new
    event" discipline sr_lines.flip_status already applies to its own
    break/flip state. This applies across a CHOCH too: the pivot that just
    triggered a CHOCH is marked broken like any other, so a regime that
    just flipped bearish on breaking the last low doesn't immediately
    re-fire a BOS against that same, already-spent level one bar later --
    the new regime's own BOS reference only becomes live again once a
    genuinely new pivot of that kind confirms.
    """
    if len(pivots) < 2 or len(bars) < 2:
        return []

    vol_sma = indicators.sma(bars["volume"], config.volume_sma_period)

    if pivots[0].kind == PivotKind.LOW:
        direction = Direction.BULLISH
        last_low, last_low_broken = pivots[0], False
        last_high, last_high_broken = pivots[1], False
    else:
        direction = Direction.BEARISH
        last_high, last_high_broken = pivots[0], False
        last_low, last_low_broken = pivots[1], False

    next_pivot_idx = 2
    start_bar = _confirmed_bar_index(bars, pivots[1]) + 1
    n = len(bars)
    closes = bars["close"].to_numpy()

    events: list[TrendState] = []

    for i in range(start_bar, n):
        while next_pivot_idx < len(pivots) and _confirmed_bar_index(bars, pivots[next_pivot_idx]) <= i:
            p = pivots[next_pivot_idx]
            if p.kind == PivotKind.HIGH:
                last_high, last_high_broken = p, False
            else:
                last_low, last_low_broken = p, False
            next_pivot_idx += 1

        close = float(closes[i])
        vc = _volume_confirmed(bars, vol_sma, i, config)
        volume_ok = vc or not config.require_volume_surge

        if direction == Direction.BULLISH:
            structural, structural_broken = last_low, last_low_broken
            choch = not structural_broken and close < structural.value
        else:
            structural, structural_broken = last_high, last_high_broken
            choch = not structural_broken and close > structural.value

        if choch and volume_ok:
            if structural is last_low:
                last_low_broken = True
            else:
                last_high_broken = True
            direction = Direction.BEARISH if direction == Direction.BULLISH else Direction.BULLISH
            events.append(TrendState(
                id=str(uuid.uuid4()), ticker=ticker, timeframe=Timeframe(timeframe),
                event=StructureEvent.CHOCH, direction=direction, broken_pivot=structural,
                broken_at=bars.index[i].isoformat(), close=close, volume_confirmed=vc,
            ))
            continue

        if direction == Direction.BULLISH:
            trend, trend_broken = last_high, last_high_broken
            bos = not trend_broken and close > trend.value
        else:
            trend, trend_broken = last_low, last_low_broken
            bos = not trend_broken and close < trend.value

        if bos and volume_ok:
            if trend is last_high:
                last_high_broken = True
            else:
                last_low_broken = True
            events.append(TrendState(
                id=str(uuid.uuid4()), ticker=ticker, timeframe=Timeframe(timeframe),
                event=StructureEvent.BOS, direction=direction, broken_pivot=trend,
                broken_at=bars.index[i].isoformat(), close=close, volume_confirmed=vc,
            ))

    return events


def detect(
    conn: sqlite3.Connection,
    ticker: str,
    timeframe: Timeframe | str,
    config: MarketStructureConfig,
    as_of: str | pd.Timestamp | date | None = None,
) -> tuple[list[TrendState], DataQualityReport, str | None]:
    """Load+validate bars for (ticker, timeframe) up to `as_of`, track
    market structure. Returns (events, quality_report, skip_reason) --
    skip_reason is None on success, otherwise events is [] and
    quality_report still reflects what was loaded, same contract as
    patterns.scanner.detect / divergences.detect.
    """
    timeframe = Timeframe(timeframe)
    bars, report = data_mod.load_and_validate(conn, ticker, timeframe, as_of=as_of)

    if len(bars) < config.min_bars:
        reason = f"only {len(bars)} bars available (< min_bars={config.min_bars})"
        logger.warning("%s/%s: skipping market-structure tracking -- %s", ticker, timeframe.value, reason)
        return [], report, reason

    atr = indicators.atr(bars, config.atr_period)
    pivots = detect_pivots(bars["high"], bars["low"], threshold_fn=lambda i: config.pivot_atr_mult * atr.iloc[i])
    events = track_market_structure(bars, pivots, config, ticker, timeframe)

    if as_of is not None:
        as_of_ts = pd.Timestamp(as_of)
        events = [e for e in events if pd.Timestamp(e.broken_at) <= as_of_ts]

    return events, report, None
