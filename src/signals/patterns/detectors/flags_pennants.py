"""Flag / Pennant detector -- design doc §4.7. Phase 6 (bonus): a sharp,
near-vertical "flagpole" leg followed by a brief, tight consolidation --
a small parallel channel (flag) or small symmetric triangle (pennant) --
then continuation in the flagpole's own direction.

Unlike a triangle, direction here is *fixed* by the pole from the start
(a flag/pennant is a continuation pattern, not a reversal one) -- uses
plain `lifecycle.apply_lifecycle`, not the bidirectional entry point,
same as double_top_bottom/H&S/cup&handle. The pennant variant reuses
triangle's own convergence math (`trendlines.fit_line`/
`convergence_apex_bar`) directly, per §4.6's own precedent of treating a
pennant as "a small symmetric triangle" -- flag vs. pennant is purely
"do the two consolidation boundaries converge or not," the same test
`detectors/triangles.py` already uses as its own hard gate, used here as
a classifier instead (both outcomes are valid, unlike a triangle where
non-convergence is rejected outright).

Consolidation window: a *fixed* `config.flag_consolidation_pivots` (4 --
2 highs + 2 lows) immediately after the pole, not a sliding range like
triangles'/VCP's own variable pivot counts -- see config.py's own comment
for why. Pole + consolidation together are always 6 consecutive pivots
(2 for the pole, 4 for the consolidation), scanned as a single sliding
window.

Checked directly against real data before shipping, same as VCP's own
calibration finding: the scanner's shared coarse pivot pass (2.5x ATR) is
too sparse in *time* for this pattern -- its median gap between
consecutive pivots is well past what "much shorter than the patterns
above" (§4.7) can tolerate for a 4-pivot consolidation window. This is
the second detector (after VCP) to run its own, finer `detect_pivots`
pass (`config.flag_pivot_atr_mult=1.5`) rather than the `pivots` argument
`scan()` receives -- see base.py's own docstring and config.py's own
comment for the real numbers behind the choice.
"""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.foundation.market_common.pivots import detect_pivots
from src.signals.patterns import lifecycle, scoring
from src.signals.patterns import trendlines as tl
from src.signals.patterns import volume as volume_mod
from src.signals.patterns.base import PatternDetector
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.models import PatternMatch, PatternType


class FlagPennantDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        n_consolidation = config.flag_consolidation_pivots
        window_size = 2 + n_consolidation
        if len(df) < window_size:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)
        fine_pivots = detect_pivots(
            df["high"], df["low"], threshold_fn=lambda i: config.flag_pivot_atr_mult * atr.iloc[i]
        )
        if len(fine_pivots) < window_size:
            return []

        matches: list[PatternMatch] = []
        for i in range(len(fine_pivots) - window_size + 1):
            pole_start, pole_end = fine_pivots[i], fine_pivots[i + 1]
            consolidation = fine_pivots[i + 2 : i + window_size]
            match = self._try_window(
                df, atr, vol_sma, ticker, timeframe, config, pole_start, pole_end, consolidation,
            )
            if match is not None:
                matches.append(match)
        return matches

    def _try_window(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pole_start: Pivot, pole_end: Pivot, consolidation: list[Pivot],
    ) -> PatternMatch | None:
        if pole_start.price <= 0:
            return None

        # §4.7: "a sharp, near-vertical prior move ... large % move in
        # few bars" -- the pole's own defining shape, a structural
        # invariant of this pattern (not a soft duration figure).
        pole_bars = pole_end.bar_index - pole_start.bar_index
        if pole_bars > config.flag_pole_max_bars:
            return None
        pole_pct = abs(pole_end.price - pole_start.price) / pole_start.price * 100
        if pole_pct < config.flag_pole_min_pct:
            return None
        is_bullish = pole_end.price > pole_start.price
        pole_height = abs(pole_end.price - pole_start.price)

        # §4.7: consolidation "typically days to a few weeks -- much
        # shorter than the patterns above" -- structural, hard-gated
        # (unlike every soft duration figure elsewhere in this module,
        # see config.py's own comment for why).
        consolidation_bars = consolidation[-1].bar_index - consolidation[0].bar_index
        if consolidation_bars > config.flag_consolidation_max_bars:
            return None

        highs = [p for p in consolidation if p.kind == PivotKind.HIGH]
        lows = [p for p in consolidation if p.kind == PivotKind.LOW]
        if len(highs) < config.min_touches_per_line or len(lows) < config.min_touches_per_line:
            return None

        # §4.7 point (c): "retraces a limited fraction of the flagpole
        # (commonly under ~50%)".
        if is_bullish:
            consolidation_extreme = min(p.price for p in lows)
            retrace_pct = (pole_end.price - consolidation_extreme) / pole_height * 100
        else:
            consolidation_extreme = max(p.price for p in highs)
            retrace_pct = (consolidation_extreme - pole_end.price) / pole_height * 100
        if retrace_pct < 0 or retrace_pct > config.flag_max_retrace_pct:
            return None

        # §4.7 point (b): "low-volatility relative to the flagpole" --
        # direct amplitude ratio, no separate ATR machinery needed.
        consolidation_range = max(p.price for p in consolidation) - min(p.price for p in consolidation)
        range_ratio = consolidation_range / pole_height
        if range_ratio > config.flag_consolidation_max_range_ratio:
            return None

        upper_slope, upper_intercept = tl.fit_line(
            np.array([p.bar_index for p in highs], dtype=float), np.array([p.price for p in highs], dtype=float),
        )
        lower_slope, lower_intercept = tl.fit_line(
            np.array([p.bar_index for p in lows], dtype=float), np.array([p.price for p in lows], dtype=float),
        )

        return self._build_match(
            df, atr, vol_sma, ticker, timeframe, config, pole_start, pole_end, consolidation,
            is_bullish, pole_pct, pole_height, range_ratio,
            upper_slope, upper_intercept, lower_slope, lower_intercept, highs, lows,
        )

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config, pole_start, pole_end, consolidation,
        is_bullish, pole_pct, pole_height, range_ratio,
        upper_slope, upper_intercept, lower_slope, lower_intercept, highs, lows,
    ) -> PatternMatch:
        def upper_at(i: float) -> float:
            return upper_slope * i + upper_intercept

        def lower_at(i: float) -> float:
            return lower_slope * i + lower_intercept

        # §4.6's own precedent for a wedge applies just as well to a
        # pennant: reuse the triangle convergence test as a *classifier*
        # here (both outcomes are valid), not a hard gate. A pennant
        # whose apex already sits behind the consolidation's own last
        # pivot is treated as a flag instead of rejected outright --
        # more lenient than triangles' own hard apex-ahead requirement,
        # since a flag is this pattern's natural fallback shape.
        apex_bar = tl.convergence_apex_bar(upper_slope, upper_intercept, lower_slope, lower_intercept)
        formation_end_i = consolidation[-1].bar_index
        is_pennant = upper_slope < lower_slope and apex_bar is not None and apex_bar > formation_end_i

        if is_pennant:
            pattern_type = PatternType.PENNANT
        else:
            pattern_type = PatternType.BULL_FLAG if is_bullish else PatternType.BEAR_FLAG
        direction = Direction.BULLISH if is_bullish else Direction.BEARISH

        trigger_at = upper_at if is_bullish else lower_at
        opposite_at = lower_at if is_bullish else upper_at

        # §3.6: flagpole length projected from the breakout. The trigger
        # boundary is sloped (like H&S's neckline/a triangle's own
        # boundaries), so target/stop use its value at formation end, not
        # literal breakout time -- the same documented approximation
        # every sloped-boundary detector here already makes.
        trigger_at_formation_end = trigger_at(formation_end_i)
        target_price = trigger_at_formation_end + pole_height if is_bullish else trigger_at_formation_end - pole_height
        stop_price = opposite_at(formation_end_i)
        formation_bars = formation_end_i - pole_start.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=[pole_start, pole_end, *consolidation],
            key_levels={
                "pole_start": pole_start.price, "pole_end": pole_end.price,
                "upper_start": upper_at(consolidation[0].bar_index), "upper_end": upper_at(formation_end_i),
                "lower_start": lower_at(consolidation[0].bar_index), "lower_end": lower_at(formation_end_i),
            },
            trendlines={"upper": (upper_slope, upper_intercept), "lower": (lower_slope, lower_intercept)},
            target_price=target_price,
            stop_price=stop_price,
            formation_start=pole_start.timestamp,
            formation_end=consolidation[-1].timestamp,
        )

        # §4.7 has no documented invalidation convention of its own --
        # reuses the same retrace threshold that already gates detection,
        # applied as an ongoing check: price giving back more of the pole
        # than the pattern ever allowed, before any breakout, is a
        # structural break of the same premise cup & handle's own
        # handle-depth figure already treats this way.
        retrace_violation_level = (
            pole_end.price - pole_height * config.flag_max_retrace_pct / 100 if is_bullish
            else pole_end.price + pole_height * config.flag_max_retrace_pct / 100
        )

        def pre_breakout_invalidated_at(i: int) -> bool:
            return df["low"].iloc[i] < retrace_violation_level if is_bullish else df["high"].iloc[i] > retrace_violation_level

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=formation_end_i,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"], volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_components(
            df, atr, vol_sma, config, match, pole_pct, range_ratio,
            consolidation[-1].bar_index - consolidation[0].bar_index, highs, lows,
            upper_slope, upper_intercept, lower_slope, lower_intercept,
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(
        self, df, atr, vol_sma, config, match, pole_pct, range_ratio, consolidation_bars, highs, lows,
        upper_slope, upper_intercept, lower_slope, lower_intercept,
    ) -> dict[str, float]:
        upper_r2 = tl.r_squared(
            np.array([p.bar_index for p in highs], dtype=float), np.array([p.price for p in highs], dtype=float),
            upper_slope, upper_intercept,
        )
        lower_r2 = tl.r_squared(
            np.array([p.bar_index for p in lows], dtype=float), np.array([p.price for p in lows], dtype=float),
            lower_slope, lower_intercept,
        )
        avg_r2 = (max(0.0, min(1.0, upper_r2)) + max(0.0, min(1.0, lower_r2))) / 2
        # §6.1 pattern-agnostic R² + a flag-specific tightness score
        # (reusing the exact same "ratio relative to its own gate
        # ceiling" shape VCP's contraction_tightness_score already
        # provides -- the two are the same underlying idea: a hard-gated
        # ratio scored continuously within its own ceiling).
        tightness = scoring.contraction_tightness_score(range_ratio, config.flag_consolidation_max_range_ratio)
        geometric_cleanliness = 0.5 * avg_r2 + 0.5 * tightness

        duration = scoring.duration_fit(consolidation_bars, config.flag_typical_min_bars, config.flag_typical_max_bars)
        # The pole itself *is* the prior trend for this pattern -- no
        # separate lookback needed, unlike every other detector's own
        # `trendlines.prior_trend_pct` call.
        prior_trend_score = scoring.prior_trend_strength(pole_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            resolved_slope, resolved_intercept = match.trendlines[
                "upper" if match.direction == Direction.BULLISH else "lower"
            ]
            level_price = resolved_slope * match.breakout_bar + resolved_intercept
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, level_price, atr_at_breakout, match.direction, config.breakout_strength_cap_atr,
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
