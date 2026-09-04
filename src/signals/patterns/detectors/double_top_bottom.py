"""Double Top / Double Bottom detector -- design doc §4.2. Built first
(Phase 1), specifically to prove the full vertical slice (detector ->
lifecycle -> scanner -> store -> cli -> plotting) end-to-end before
investing in the pricier H&S/triangle/cup&handle/VCP detectors. See
docs/features/chart_pattern_detection_design_notes.md for the build-order
reasoning.

One detector covers both directions: a HIGH-LOW-HIGH pivot triple is a
double top (bearish, breaks down through the trough "neckline"); a
LOW-HIGH-LOW triple is a double bottom (bullish, mirrored). Both come from
the same sliding-window scan since market_common.pivots.detect_pivots
already guarantees strict HIGH/LOW alternation -- any 3 consecutive pivots
automatically have the right shape, keyed off which kind the first one is.

Also covers Triple Top/Bottom (pivot breakout validation design doc,
docs/features/pivot_breakout_validation_design.md §2/§5 decision 3): the
same detector, not a separate file, since it's the direct 5-pivot
generalization of the same window/trigger/invalidation shape -- see
`_scan_triples`/`_build_triple_match` below.
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


class DoubleTopBottomDetector(PatternDetector):
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
        matches.extend(self._scan_doubles(df, pivots, atr, vol_sma, ticker, timeframe, config))
        if len(pivots) >= 5:
            matches.extend(self._scan_triples(df, pivots, atr, vol_sma, ticker, timeframe, config))
        return matches

    def _scan_doubles(self, df, pivots, atr, vol_sma, ticker, timeframe, config) -> list[PatternMatch]:
        matches: list[PatternMatch] = []
        for p1, t, p2 in zip(pivots, pivots[1:], pivots[2:]):
            if p1.kind == PivotKind.HIGH:
                pattern_type = PatternType.DOUBLE_TOP
                direction = Direction.BEARISH
                trend_direction = "up"
            else:
                pattern_type = PatternType.DOUBLE_BOTTOM
                direction = Direction.BULLISH
                trend_direction = "down"

            if p1.price <= 0:
                continue
            symmetry_pct = abs(p1.price - p2.price) / p1.price * 100
            if symmetry_pct > config.double_top_symmetry_hard_gate_pct:
                continue

            prior_pct = tl.prior_trend_pct(df, p1, config.prior_trend_min_bars, trend_direction)
            if prior_pct is None or prior_pct < config.prior_trend_min_pct:
                continue

            match = self._build_match(
                df, atr, vol_sma, ticker, timeframe, config,
                pattern_type, direction, trend_direction, p1, t, p2, prior_pct,
            )
            matches.append(match)

        return matches

    def _scan_triples(self, df, pivots, atr, vol_sma, ticker, timeframe, config) -> list[PatternMatch]:
        """Triple Top/Bottom: a HIGH-LOW-HIGH-LOW-HIGH (or mirrored
        LOW-HIGH-LOW-HIGH-LOW) window with 3 comparable extremes. The
        trigger/neckline is `t2` -- the second trough/peak, the level price
        is actually testing right as the pattern completes -- same role
        the lone trough plays in `_scan_doubles`. `t1` is kept in
        `pivots`/`key_levels` for reference (plotting, audit) but doesn't
        set the trigger.
        """
        matches: list[PatternMatch] = []
        for e1, t1, e2, t2, e3 in zip(pivots, pivots[1:], pivots[2:], pivots[3:], pivots[4:]):
            if e1.kind == PivotKind.HIGH:
                pattern_type = PatternType.TRIPLE_TOP
                direction = Direction.BEARISH
                trend_direction = "up"
            else:
                pattern_type = PatternType.TRIPLE_BOTTOM
                direction = Direction.BULLISH
                trend_direction = "down"

            if e1.price <= 0:
                continue
            extremes = (e1.price, e2.price, e3.price)
            symmetry_pct = (max(extremes) - min(extremes)) / e1.price * 100
            if symmetry_pct > config.triple_top_symmetry_hard_gate_pct:
                continue

            prior_pct = tl.prior_trend_pct(df, e1, config.prior_trend_min_bars, trend_direction)
            if prior_pct is None or prior_pct < config.prior_trend_min_pct:
                continue

            match = self._build_triple_match(
                df, atr, vol_sma, ticker, timeframe, config,
                pattern_type, direction, trend_direction, e1, t1, e2, t2, e3, prior_pct,
            )
            matches.append(match)

        return matches

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, trend_direction, p1, t, p2, prior_pct,
    ) -> PatternMatch:
        is_top = direction == Direction.BEARISH
        neckline = t.price
        avg_extreme = (p1.price + p2.price) / 2
        target_price = (
            neckline - (avg_extreme - neckline) if is_top else neckline + (neckline - avg_extreme)
        )
        stop_price = max(p1.price, p2.price) if is_top else min(p1.price, p2.price)
        formation_bars = p2.bar_index - p1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=[p1, t, p2],
            # `neckline_bar` is where the neckline level was taken from, so
            # plotting can start the line at the right bar without having to
            # recover it by matching float prices back to a pivot.
            key_levels={"p1": p1.price, "neckline": neckline, "neckline_bar": float(t.bar_index), "p2": p2.price},
            target_price=target_price,
            stop_price=stop_price,
            formation_start=p1.timestamp,
            formation_end=p2.timestamp,
        )

        def trigger_at(_i: int) -> float:
            return neckline

        def pre_breakout_invalidated_at(i: int) -> bool:
            if is_top:
                return df["high"].iloc[i] > max(p1.price, p2.price)
            return df["low"].iloc[i] < min(p1.price, p2.price)

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=p2.bar_index,
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
        # Geometric cleanliness kept minimal for this first detector (just
        # price symmetry -- there's no fitted trendline here, a single
        # trough point, so §6.1's R²/touch-tightness machinery doesn't
        # apply yet). Richer, pattern-specific cleanliness lands with H&S
        # (needs price+time symmetry combined) and beyond.
        geometric_cleanliness = scoring.price_symmetry(p1.price, p2.price)
        duration = scoring.duration_fit(formation_bars, config.double_top_typical_min_bars, config.double_top_typical_max_bars)
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, match.key_levels["neckline"], atr_at_breakout,
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

    def _build_triple_match(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, trend_direction, e1, t1, e2, t2, e3, prior_pct,
    ) -> PatternMatch:
        is_top = direction == Direction.BEARISH
        neckline = t2.price
        avg_extreme = (e1.price + e2.price + e3.price) / 3
        target_price = (
            neckline - (avg_extreme - neckline) if is_top else neckline + (neckline - avg_extreme)
        )
        stop_price = max(e1.price, e2.price, e3.price) if is_top else min(e1.price, e2.price, e3.price)
        formation_bars = e3.bar_index - e1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=[e1, t1, e2, t2, e3],
            key_levels={
                "p1": e1.price, "trough1": t1.price, "p2": e2.price,
                "neckline": neckline, "neckline_bar": float(t2.bar_index), "p3": e3.price,
            },
            target_price=target_price,
            stop_price=stop_price,
            formation_start=e1.timestamp,
            formation_end=e3.timestamp,
        )

        def trigger_at(_i: int) -> float:
            return neckline

        def pre_breakout_invalidated_at(i: int) -> bool:
            if is_top:
                return df["high"].iloc[i] > max(e1.price, e2.price, e3.price)
            return df["low"].iloc[i] < min(e1.price, e2.price, e3.price)

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=e3.bar_index,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"],
            volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_triple_components(
            df, atr, vol_sma, config, match, e1, e2, e3, formation_bars, prior_pct
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_triple_components(self, df, atr, vol_sma, config, match, e1, e2, e3, formation_bars, prior_pct) -> dict[str, float]:
        # Average pairwise symmetry (each extreme vs. e1, same normalizer
        # the hard gate itself uses) -- a direct 3-point generalization of
        # price_symmetry's own 2-point formula, not a new scoring.py
        # primitive.
        geometric_cleanliness = (
            scoring.price_symmetry(e1.price, e2.price) + scoring.price_symmetry(e1.price, e3.price)
        ) / 2
        duration = scoring.duration_fit(
            formation_bars, config.triple_top_typical_min_bars, config.triple_top_typical_max_bars
        )
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, match.key_levels["neckline"], atr_at_breakout,
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
