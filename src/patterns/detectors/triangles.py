"""Ascending/Descending/Symmetric Triangle + Rising/Falling Wedge detector
-- design doc §4.3/§4.6. Phase 3: one detector for all five shapes, per
the doc's own module layout ("triangles.py -- ascending/descending/
symmetric + wedges, shared trendline logic") -- wedges are the same
convergence/classification math with a different slope-sign combination,
not a separate build.

New here vs. Phase 1/2 (see docs/features/chart_pattern_detection_design_
notes.md's Phase 3 section for the full narrative): a triangle's breakout
side isn't fixed by the pattern's own geometry the way H&S/double-top's
is -- a close beyond *either* boundary confirms, direction only known
once it happens. Uses `lifecycle.apply_lifecycle_bidirectional` rather
than `apply_lifecycle` for that reason.

Pivot window: `config.triangle_window_pivots` (default 6) *consecutive*
pivots, slid across the entire pivot history (one candidate per window
position) -- same generalization double_top_bottom/head_shoulders already
apply to their own "N most recent pivots" framing when scanning full
history, not just the trailing window.
"""

from __future__ import annotations

import math
import uuid

import numpy as np
import pandas as pd

from src.market_common import indicators
from src.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.patterns import lifecycle, scoring
from src.patterns import trendlines as tl
from src.patterns import volume as volume_mod
from src.patterns.base import PatternDetector
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternType

# Shape -> initial `direction` bias, purely informational until a real
# breakout (§4.3 point 7 / §6.1) overwrites it. Rising/falling wedges'
# *expected* resolution is counter to their own slope direction -- §4.6
# explicitly flags this as a common source of confusion vs. triangles.
_SHAPE_BIAS = {
    PatternType.ASCENDING_TRIANGLE: Direction.BULLISH,
    PatternType.DESCENDING_TRIANGLE: Direction.BEARISH,
    PatternType.SYMMETRIC_TRIANGLE: Direction.NEUTRAL,
    PatternType.RISING_WEDGE: Direction.BEARISH,
    PatternType.FALLING_WEDGE: Direction.BULLISH,
}


def _classify(upper_atr_slope: float, lower_atr_slope: float, flat: float) -> PatternType | None:
    upper_flat = abs(upper_atr_slope) < flat
    lower_flat = abs(lower_atr_slope) < flat
    if upper_flat and lower_atr_slope > flat:
        return PatternType.ASCENDING_TRIANGLE
    if lower_flat and upper_atr_slope < -flat:
        return PatternType.DESCENDING_TRIANGLE
    if upper_atr_slope < -flat and lower_atr_slope > flat:
        return PatternType.SYMMETRIC_TRIANGLE
    if upper_atr_slope > flat and lower_atr_slope > flat:
        return PatternType.RISING_WEDGE
    if upper_atr_slope < -flat and lower_atr_slope < -flat:
        return PatternType.FALLING_WEDGE
    return None


class TriangleWedgeDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        n_pivots = config.triangle_window_pivots
        if len(pivots) < n_pivots or len(df) < n_pivots:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)

        matches: list[PatternMatch] = []
        for start in range(len(pivots) - n_pivots + 1):
            window = pivots[start : start + n_pivots]
            match = self._try_window(df, atr, vol_sma, ticker, timeframe, config, window)
            if match is not None:
                matches.append(match)
        return matches

    def _try_window(self, df, atr, vol_sma, ticker, timeframe, config, window: list[Pivot]) -> PatternMatch | None:
        highs = [p for p in window if p.kind == PivotKind.HIGH]
        lows = [p for p in window if p.kind == PivotKind.LOW]
        if len(highs) < config.min_touches_per_line or len(lows) < config.min_touches_per_line:
            return None

        upper_slope, upper_intercept = tl.fit_line(
            np.array([p.bar_index for p in highs], dtype=float), np.array([p.price for p in highs], dtype=float),
        )
        lower_slope, lower_intercept = tl.fit_line(
            np.array([p.bar_index for p in lows], dtype=float), np.array([p.price for p in lows], dtype=float),
        )
        # Structural invariant (§6): the boundaries must actually
        # converge -- see trendlines.convergence_apex_bar's docstring for
        # why this one slope comparison is equivalent to the doc's own
        # "range_at_start > range_at_end" wording (and, as a side effect,
        # already rejects a same-sign slope pair that doesn't converge,
        # e.g. an "ascending"-looking upper line rising faster than the
        # lower one -- not a valid wedge).
        if upper_slope >= lower_slope:
            return None

        window_start_i, window_end_i = window[0].bar_index, window[-1].bar_index
        atr_ref = atr.iloc[window_end_i]
        if pd.isna(atr_ref) or atr_ref <= 0:
            return None

        pattern_type = _classify(upper_slope / atr_ref, lower_slope / atr_ref, config.triangle_flat_slope_atr_mult)
        if pattern_type is None:
            return None

        apex_bar = tl.convergence_apex_bar(upper_slope, upper_intercept, lower_slope, lower_intercept)
        if apex_bar is None or apex_bar <= window_end_i:
            return None

        def upper_at(i: int) -> float:
            return upper_slope * i + upper_intercept

        def lower_at(i: int) -> float:
            return lower_slope * i + lower_intercept

        window_df = df.iloc[window_start_i : window_end_i + 1]
        window_atr = atr.iloc[window_start_i : window_end_i + 1]
        n_upper_touches = tl.count_touches(
            window_df["high"], window_df["low"], window_atr,
            level_at=lambda i: upper_at(window_start_i + i),
            atr_mult=config.touch_tolerance_atr_mult, pct=config.touch_tolerance_pct,
        )
        n_lower_touches = tl.count_touches(
            window_df["high"], window_df["low"], window_atr,
            level_at=lambda i: lower_at(window_start_i + i),
            atr_mult=config.touch_tolerance_atr_mult, pct=config.touch_tolerance_pct,
        )
        # §4.3 point 4: "2 per trendline (4 total)" hard floor -- reuses
        # the generic min_touches_per_line knob (§3.2), same as every
        # other pattern's trendline-touch gating.
        if n_upper_touches < config.min_touches_per_line or n_lower_touches < config.min_touches_per_line:
            return None

        return self._build_match(
            df, atr, vol_sma, ticker, timeframe, config, pattern_type, window,
            upper_slope, upper_intercept, lower_slope, lower_intercept, apex_bar,
            n_upper_touches, n_lower_touches, highs, lows,
        )

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config, pattern_type, window,
        upper_slope, upper_intercept, lower_slope, lower_intercept, apex_bar,
        n_upper_touches, n_lower_touches, highs, lows,
    ) -> PatternMatch:
        window_start_i, window_end_i = window[0].bar_index, window[-1].bar_index

        def upper_at(i: int) -> float:
            return upper_slope * i + upper_intercept

        def lower_at(i: int) -> float:
            return lower_slope * i + lower_intercept

        # §3.6 measured-move height at the pattern's widest (leftmost)
        # point -- range is linear between two linear boundaries, and
        # strictly shrinking (per the convergence gate above), so the
        # window's own start is always that widest point.
        height = upper_at(window_start_i) - lower_at(window_start_i)
        upper_target = upper_at(window_end_i) + height
        lower_target = lower_at(window_end_i) - height
        # Stop: back through the *opposite* boundary invalidates whichever
        # breakout happened. No explicit doc convention for triangle stops
        # (unlike double top's max/min(p1,p2)) -- a reasonable default,
        # documented as our own choice, not the doc's.
        upper_stop = lower_at(window_end_i)
        lower_stop = upper_at(window_end_i)

        formation_bars = window_end_i - window_start_i
        # §4.3: EXPIRED either by the standard 2x-formation-duration
        # deadline or by reaching the apex without breaking out, whichever
        # comes first. `apex_bar` is a fractional bar index (the two
        # fitted lines cross between two whole bars, generally) -- ceil,
        # not floor/int: a candidate whose apex sits at e.g. 34.5
        # (window_end_i=34) must still get bar 35 as a real chance to
        # break out, since the apex is technically still ahead of it right
        # up to that bar. Flooring would set pending_deadline=34, expiring
        # the pattern on the very first loop iteration (i=35) before ever
        # checking its price -- discarding a legitimate breakout. Rounded
        # to 6dp before ceiling: np.polyfit's own floating-point noise can
        # push a "really" exact apex (e.g. a perfectly flat/linear
        # synthetic fixture, or real data that's genuinely this clean) to
        # something like 44.00000000000008 -- ceiling that raw would
        # overcorrect to 45 and grant a bar of "room" that was never
        # really there.
        pending_deadline = min(
            window_end_i + int(config.expire_lifespan_mult * formation_bars), math.ceil(round(apex_bar, 6)),
        )

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=_SHAPE_BIAS[pattern_type],
            pivots=list(window),
            key_levels={
                "upper_start": upper_at(window_start_i), "upper_end": upper_at(window_end_i),
                "lower_start": lower_at(window_start_i), "lower_end": lower_at(window_end_i),
                "apex_price": upper_at(apex_bar),
                "upper_target": upper_target, "lower_target": lower_target,
                "upper_stop": upper_stop, "lower_stop": lower_stop,
            },
            trendlines={"upper": (upper_slope, upper_intercept), "lower": (lower_slope, lower_intercept)},
            formation_start=window[0].timestamp,
            formation_end=window[-1].timestamp,
        )

        def pre_breakout_invalidated_at(_i: int) -> bool:
            # §4.3 invalidation: a wick-only trendline violation doesn't
            # invalidate (soft, scored elsewhere -- not modeled in this
            # first pass, see design notes); "reaching the apex without
            # breaking out" is EXPIRED, already handled via
            # pending_deadline above, not here. No other hard
            # pre-breakout invalidation condition is documented for this
            # pattern family.
            return False

        lifecycle.apply_lifecycle_bidirectional(
            df, match,
            formation_end_bar_index=window_end_i,
            formation_bars=formation_bars,
            upper_trigger_at=upper_at,
            lower_trigger_at=lower_at,
            upper_target=upper_target, lower_target=lower_target,
            upper_stop=upper_stop, lower_stop=lower_stop,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"], volume_sma_series=vol_sma,
            config=config,
            pending_deadline_bar_index=pending_deadline,
        )

        components = self._score_components(
            df, atr, vol_sma, config, match, window, upper_slope, upper_intercept,
            lower_slope, lower_intercept, apex_bar, n_upper_touches, n_lower_touches, highs, lows, formation_bars,
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(
        self, df, atr, vol_sma, config, match, window, upper_slope, upper_intercept,
        lower_slope, lower_intercept, apex_bar, n_upper_touches, n_lower_touches, highs, lows, formation_bars,
    ) -> dict[str, float]:
        window_start_i, window_end_i = window[0].bar_index, window[-1].bar_index

        # §6.1 pattern-agnostic metrics: trendline fit (R²) and point
        # count vs. minimum, averaged across both boundaries.
        upper_r2 = tl.r_squared(
            np.array([p.bar_index for p in highs], dtype=float), np.array([p.price for p in highs], dtype=float),
            upper_slope, upper_intercept,
        )
        lower_r2 = tl.r_squared(
            np.array([p.bar_index for p in lows], dtype=float), np.array([p.price for p in lows], dtype=float),
            lower_slope, lower_intercept,
        )
        avg_r2 = (max(0.0, min(1.0, upper_r2)) + max(0.0, min(1.0, lower_r2))) / 2
        touch_adequacy = (
            scoring.point_count_score(n_upper_touches, config.min_touches_per_line)
            + scoring.point_count_score(n_lower_touches, config.min_touches_per_line)
        ) / 2

        # §6.1 triangle-specific addition: convergence quality (range
        # monotonicity across the real, noisy pivot legs -- NOT the
        # fitted lines, which converge perfectly by construction and
        # would score 1.0 every time -- + apex proximity).
        leg_ranges = [abs(window[k + 1].price - window[k].price) for k in range(len(window) - 1)]
        convergence_quality = (
            scoring.range_monotonicity_score(leg_ranges)
            + scoring.apex_proximity_score(window_start_i, window_end_i, apex_bar)
        ) / 2

        # §6.1's own suggested 60% agnostic / 40% pattern-specific blend,
        # applied literally (avg_r2 40% + touch_adequacy 20% = 60%
        # agnostic; convergence_quality 40% pattern-specific).
        geometric_cleanliness = 0.4 * avg_r2 + 0.2 * touch_adequacy + 0.4 * convergence_quality

        duration = scoring.duration_fit(
            formation_bars, config.triangle_typical_min_bars, config.triangle_typical_max_bars,
        )

        # §4.3 names no prior-trend requirement for triangles/wedges
        # (unlike H&S/cup&handle's explicit §3.1 citation) -- measured
        # anyway as a soft input, per §6's universal weight table.
        # Direction-agnostic since a triangle's own eventual breakout
        # direction isn't known yet at this point: whichever of up/down
        # shows the larger prior move into the window.
        prior_up = tl.prior_trend_pct(df, window[0], config.prior_trend_min_bars, "up") or 0.0
        prior_down = tl.prior_trend_pct(df, window[0], config.prior_trend_min_bars, "down") or 0.0
        prior_trend_score = scoring.prior_trend_strength(max(prior_up, prior_down), config.prior_trend_score_cap_pct)

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
