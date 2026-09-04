"""1-2-3 Reversal detector -- pivot breakout validation design doc
(docs/features/pivot_breakout_validation_design.md §3): tracks three
consecutive structural points (Point 1: trend high/low, Point 2:
retracement peak/valley, Point 3: higher low / lower high), triggering the
moment a candle closes past Point 2's exact price.

Same 3-pivot HIGH-LOW-HIGH / LOW-HIGH-LOW window as double_top_bottom.py
(and hence the same trigger role for the middle pivot -- Point 2 IS the
neckline), but two structural differences instead of double top/bottom's
symmetry gate:
  - Point 3 must be a genuine higher low (bullish) / lower high (bearish)
    relative to Point 1 -- not a comparable, near-equal extreme the way
    double top/bottom's two peaks/troughs are required to be. This is the
    pattern's actual defining shape, so it's a hard structural gate, not a
    soft score. (Point 3 being strictly closer to Point 2 than to Point 1
    is already guaranteed by market_common.pivots.detect_pivots itself --
    a pivot only confirms after reversing far enough from the running
    extreme -- so this gate alone is enough to bound Point 3 between them.)
  - Invalidation only watches Point 1 (design doc: "If the price breaches
    Point 1 before breaching Point 2, invalidate the sequence and reset
    the tracker") -- unlike double top/bottom, which invalidates on a
    breach past EITHER extreme. A fresh 1-2-3 starting at the next pivot
    is found automatically on the next scan (this is a pure function over
    the whole pivot list every call, not a stateful tracker), which is
    what "reset the tracker" amounts to here -- no separate reset plumbing
    needed beyond marking the invalidated match INVALIDATED like every
    other detector (see lifecycle.apply_lifecycle).
"""

from __future__ import annotations

import uuid

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns import lifecycle, scoring
from src.signals.patterns import trendlines as tl
from src.signals.patterns import volume as volume_mod
from src.signals.patterns.base import PatternDetector
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.models import PatternMatch, PatternType


class Reversal123Detector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        if len(pivots) < 3 or len(df) < 3:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)

        matches: list[PatternMatch] = []
        for p1, p2, p3 in zip(pivots, pivots[1:], pivots[2:]):
            if p1.kind == PivotKind.LOW:
                # LOW(P1) -> HIGH(P2) -> LOW(P3): bottoming reversal, P3
                # must be a genuine higher low.
                direction = Direction.BULLISH
                trend_direction = "down"
                if p3.price <= p1.price:
                    continue
            else:
                # HIGH(P1) -> LOW(P2) -> HIGH(P3): topping reversal, P3
                # must be a genuine lower high.
                direction = Direction.BEARISH
                trend_direction = "up"
                if p3.price >= p1.price:
                    continue

            prior_pct = tl.prior_trend_pct(df, p1, config.prior_trend_min_bars, trend_direction)
            if prior_pct is None or prior_pct < config.prior_trend_min_pct:
                continue

            match = self._build_match(
                df, atr, vol_sma, ticker, timeframe, config, direction, p1, p2, p3, prior_pct,
            )
            matches.append(match)

        return matches

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config, direction, p1, p2, p3, prior_pct,
    ) -> PatternMatch:
        is_bullish = direction == Direction.BULLISH
        trigger = p2.price
        # Measured move: project the P1->P2 leg's own height beyond the
        # breakout, the standard 1-2-3 reversal target -- there's no second
        # comparable extreme here to average against the way double
        # top/bottom's target does (see module docstring for why).
        leg = abs(p2.price - p1.price)
        target_price = trigger + leg if is_bullish else trigger - leg
        stop_price = p1.price
        formation_bars = p3.bar_index - p1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=PatternType.REVERSAL_123,
            direction=direction,
            pivots=[p1, p2, p3],
            key_levels={
                "point1": p1.price, "point2": trigger, "point2_bar": float(p2.bar_index), "point3": p3.price,
            },
            target_price=target_price,
            stop_price=stop_price,
            formation_start=p1.timestamp,
            formation_end=p3.timestamp,
        )

        def trigger_at(_i: int) -> float:
            return trigger

        def pre_breakout_invalidated_at(i: int) -> bool:
            # Design doc: only Point 1 invalidates, never Point 3.
            if is_bullish:
                return df["low"].iloc[i] < p1.price
            return df["high"].iloc[i] > p1.price

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=p3.bar_index,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"],
            volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_components(df, atr, vol_sma, config, match, p1, p2, formation_bars, prior_pct)
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(self, df, atr, vol_sma, config, match, p1, p2, formation_bars, prior_pct) -> dict[str, float]:
        # Geometric cleanliness: how "textbook" Point 3's retracement of
        # the P1->P2 leg is. A healthy pullback holds in the classic
        # 38%-62% retracement zone (peaks at 50%); too shallow (barely off
        # P2) or too deep (near Point 1, on the edge of invalidation) both
        # score lower. Computed inline rather than added to scoring.py --
        # a single-use triangular ramp, not a general cleanliness
        # primitive shared across detectors.
        p3 = match.pivots[2]
        leg = p2.price - p1.price
        retrace_pct = abs(p2.price - p3.price) / abs(leg) if leg != 0 else 1.0
        geometric_cleanliness = max(0.0, 1.0 - abs(retrace_pct - 0.5) / 0.5)

        duration = scoring.duration_fit(
            formation_bars, config.reversal_123_typical_min_bars, config.reversal_123_typical_max_bars
        )
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, match.key_levels["point2"], atr_at_breakout,
                match.direction, config.breakout_strength_cap_atr,
            )
            rel_vol = volume_mod.rel_volume(
                float(df["volume"].iloc[match.breakout_bar]), float(vol_sma.iloc[match.breakout_bar])
            )
            volume_signature = scoring.volume_signature_score(rel_vol, config.volume_score_cap_mult)
        else:
            breakout_strength = 0.0
            volume_signature = 0.0

        return {
            "geometric_cleanliness": geometric_cleanliness,
            "volume_signature": volume_signature,
            "duration_fit": duration,
            "prior_trend": prior_trend_score,
            "breakout_strength": breakout_strength,
        }
