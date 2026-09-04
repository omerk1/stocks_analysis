"""Head & Shoulders / Inverse Head & Shoulders detector -- design doc §4.1.
Phase 2: extends double_top_bottom.py's neckline/symmetry/measured-move
logic from 3 pivots to 5 -- see
docs/features/chart_pattern_detection_design_notes.md's Phase 2 entry for
what's new here vs. reused as-is. `lifecycle.py`'s state machine is reused
completely unchanged; the neckline here can be sloped (fit through two
trough/peak pivots), not just flat like double top/bottom's single trough.

One detector covers both directions, same pattern as double_top_bottom: a
HIGH-LOW-HIGH-LOW-HIGH pivot quintuple is a (top) Head & Shoulders
(bearish, breaks down through the T1-T2 neckline); a LOW-HIGH-LOW-HIGH-LOW
quintuple is Inverse H&S (bullish, mirrored). Both come from the same
sliding window since market_common.pivots.detect_pivots already guarantees
strict HIGH/LOW alternation -- any 5 consecutive pivots automatically have
the right shape, keyed off which kind the first one is.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns import lifecycle, scoring
from src.signals.patterns import trendlines as tl
from src.signals.patterns import volume as volume_mod
from src.signals.patterns.base import PatternDetector
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.models import PatternMatch, PatternType


class HeadShouldersDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        if len(pivots) < 5 or len(df) < 5:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)

        matches: list[PatternMatch] = []
        for p1, t1, head, t2, p2 in zip(pivots, pivots[1:], pivots[2:], pivots[3:], pivots[4:]):
            if p1.kind == PivotKind.HIGH:
                pattern_type = PatternType.HEAD_AND_SHOULDERS
                direction = Direction.BEARISH
                trend_direction = "up"
                # §4.1 point 3 + "right shoulder above head -> not H&S at
                # all, reject" -- both covered by this one strict check.
                head_exceeds_shoulders = head.price > p1.price and head.price > p2.price
            else:
                pattern_type = PatternType.INVERSE_HEAD_AND_SHOULDERS
                direction = Direction.BULLISH
                trend_direction = "down"
                head_exceeds_shoulders = head.price < p1.price and head.price < p2.price

            if not head_exceeds_shoulders or head.price <= 0:
                continue

            symmetry_pct = abs(p1.price - p2.price) / head.price * 100
            if symmetry_pct > config.head_shoulders_symmetry_hard_gate_pct:
                continue

            legs = (
                t1.bar_index - p1.bar_index, head.bar_index - t1.bar_index,
                t2.bar_index - head.bar_index, p2.bar_index - t2.bar_index,
            )
            if min(legs) < config.head_shoulders_min_leg_bars:
                continue

            prior_pct = tl.prior_trend_pct(df, p1, config.prior_trend_min_bars, trend_direction)
            if prior_pct is None or prior_pct < config.prior_trend_min_pct:
                continue

            neck_slope, neck_intercept = tl.fit_line(
                np.array([t1.bar_index, t2.bar_index], dtype=float),
                np.array([t1.price, t2.price], dtype=float),
            )
            neckline_at_t1 = neck_slope * t1.bar_index + neck_intercept
            if neckline_at_t1 <= 0:
                continue
            neckline_span_pct = abs(neck_slope * (t2.bar_index - t1.bar_index)) / neckline_at_t1 * 100
            if neckline_span_pct > config.head_shoulders_neckline_max_slope_pct:
                continue

            match = self._build_match(
                df, atr, vol_sma, ticker, timeframe, config,
                pattern_type, direction, p1, t1, head, t2, p2,
                neck_slope, neck_intercept, prior_pct,
            )
            matches.append(match)

        return matches

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, p1, t1, head, t2, p2,
        neck_slope, neck_intercept, prior_pct,
    ) -> PatternMatch:
        is_top = direction == Direction.BEARISH

        def neckline_at(i: int) -> float:
            return neck_slope * i + neck_intercept

        # Target/stop, per §3.6/§4.1: measured-move height at the head,
        # projected from the neckline's own value at the pattern's last
        # known formation point (the right shoulder). The design doc's
        # literal formula measures from "neckline at breakout," but
        # breakout_bar isn't known yet at construction time, and
        # lifecycle.apply_lifecycle needs one fixed target float up front
        # (a constraint double top/bottom's flat neckline never has to
        # confront, since there "neckline at breakout" and "neckline at
        # formation end" are the same number by construction). Using the
        # right-shoulder-time neckline value is a documented approximation,
        # not the literal doc formula. Stop is the head itself -- the same
        # level `pre_breakout_invalidated_at` below treats as the
        # structural invalidation line.
        neckline_at_p2 = neckline_at(p2.bar_index)
        head_height = abs(head.price - neckline_at(head.bar_index))
        target_price = neckline_at_p2 - head_height if is_top else neckline_at_p2 + head_height
        stop_price = head.price
        formation_bars = p2.bar_index - p1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=[p1, t1, head, t2, p2],
            key_levels={
                "left_shoulder": p1.price, "neckline_t1": t1.price, "head": head.price,
                "neckline_t2": t2.price, "right_shoulder": p2.price,
            },
            trendlines={"neckline": (neck_slope, neck_intercept)},
            target_price=target_price,
            stop_price=stop_price,
            formation_start=p1.timestamp,
            formation_end=p2.timestamp,
        )

        def pre_breakout_invalidated_at(i: int) -> bool:
            # §4.1 invalidation: any pivot after the head that exceeds the
            # head (before a valid neckline break) invalidates -- checked
            # against every bar's high/low, not just pivots, same
            # generous-but-well-defined convention double_top_bottom's own
            # "new high beyond both peaks" check uses.
            return df["high"].iloc[i] > head.price if is_top else df["low"].iloc[i] < head.price

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=p2.bar_index,
            formation_bars=formation_bars,
            trigger_at=neckline_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"],
            volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_components(
            df, atr, vol_sma, config, match, p1, head, p2, formation_bars, prior_pct,
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(self, df, atr, vol_sma, config, match, p1, head, p2, formation_bars, prior_pct) -> dict[str, float]:
        # §6.1 H&S-specific cleanliness: price+time symmetry blended
        # evenly, replacing double top/bottom's price-only
        # geometric_cleanliness (there's no second symmetric axis to
        # measure with only 3 pivots).
        price_sym = scoring.hs_price_symmetry(p1.price, p2.price, head.price)
        time_sym = scoring.hs_time_symmetry(
            head.bar_index - p1.bar_index, p2.bar_index - head.bar_index, formation_bars,
        )
        geometric_cleanliness = (price_sym + time_sym) / 2
        duration = scoring.duration_fit(
            formation_bars, config.head_shoulders_typical_min_bars, config.head_shoulders_typical_max_bars,
        )
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            neck_slope, neck_intercept = match.trendlines["neckline"]
            neckline_at_breakout = neck_slope * match.breakout_bar + neck_intercept
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, neckline_at_breakout, atr_at_breakout,
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
