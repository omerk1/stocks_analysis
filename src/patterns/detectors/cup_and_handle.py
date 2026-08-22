"""Cup & Handle / Inverse Cup & Handle detector -- design doc §4.4. Phase
4: rounded U-shaped (or, inverted, an upward bulge) base recovering to
roughly the prior rim, followed by a small, tighter handle pullback, then
a flat breakout through the right rim. Reuses plain `lifecycle.
apply_lifecycle` (not the bidirectional entry point) -- unlike a triangle,
the breakout side here is always fixed by which pivot kind matched, same
as double_top_bottom.py.

One detector covers both directions, same shape as double_top_bottom: a
HIGH...HIGH...LOW sequence (left rim, [any pivots forming the rounding],
right rim, handle low) is a cup & handle (bullish, breaks up through the
right rim); a LOW...LOW...HIGH sequence is the inverse (bearish, mirrored
-- a rounded top with a small upward handle bounce, breaking down).

Unlike double top/H&S/triangles, the cup's own pivot count isn't fixed
(§4.4's pivot sequence: "LOW(cup bottom, *possibly several pivots*
forming the rounding)") -- the roundedness itself is checked against the
raw close-price path between the two rims (`curves.fit_roundedness`), not
against the intermediate pivots directly. Only three pivots are used as
this detector's own anchors: left rim, right rim, handle -- scanned as
(rim1_index, rim2_index) pairs across the pivot list, bounded by
`config.cup_max_span_pivots`, with the handle always the pivot
immediately after rim2 (guaranteed to be the opposite kind by
`detect_pivots`' strict alternation).
"""

from __future__ import annotations

import uuid

import pandas as pd

from src.market_common import indicators
from src.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.patterns import curves, lifecycle, scoring
from src.patterns import trendlines as tl
from src.patterns import volume as volume_mod
from src.patterns.base import PatternDetector
from src.patterns.config import PatternConfig
from src.patterns.models import PatternMatch, PatternType


class CupAndHandleDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        if len(pivots) < 4 or len(df) < 4:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)
        max_span = config.cup_max_span_pivots

        matches: list[PatternMatch] = []
        for i, rim1 in enumerate(pivots):
            is_cup = rim1.kind == PivotKind.HIGH
            pattern_type = PatternType.CUP_AND_HANDLE if is_cup else PatternType.INVERSE_CUP_AND_HANDLE
            direction = Direction.BULLISH if is_cup else Direction.BEARISH
            trend_direction = "up" if is_cup else "down"

            # Right-rim candidates share rim1's own kind (strict
            # alternation), so they sit two pivots apart each step; +1 so
            # the handle pivot (right after rim2) still exists.
            max_j = min(len(pivots) - 2, i + max_span)
            for j in range(i + 2, max_j + 1, 2):
                rim2 = pivots[j]
                handle = pivots[j + 1]
                match = self._try_candidate(
                    df, atr, vol_sma, ticker, timeframe, config,
                    pattern_type, direction, trend_direction, is_cup,
                    rim1, rim2, handle, pivots[i : j + 2],
                )
                if match is not None:
                    matches.append(match)
        return matches

    def _try_candidate(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, trend_direction, is_cup,
        rim1: Pivot, rim2: Pivot, handle: Pivot, window_pivots: list[Pivot],
    ) -> PatternMatch | None:
        if rim1.price <= 0:
            return None

        # §4.4 point 4: right rim recovering too weakly relative to the
        # left rim rejects; recovering to or past the left rim never does
        # (doc: "a right rim above the left rim is fine too and often
        # bullish").
        if is_cup:
            if rim2.price < rim1.price * (1 - config.cup_rim_symmetry_max_pct / 100):
                return None
        else:
            if rim2.price > rim1.price * (1 + config.cup_rim_symmetry_max_pct / 100):
                return None

        close_path = df["close"].iloc[rim1.bar_index : rim2.bar_index + 1]
        if len(close_path) < 3:
            return None
        extreme_price = float(close_path.min()) if is_cup else float(close_path.max())

        # §4.4 point 2: cup depth as a % retracement from the left rim --
        # hard-bounded outside the doc's own soft 12-50% range (see
        # config's own comment for why these are wider than the "typical"
        # figures), scored within it.
        depth_pct = abs(rim1.price - extreme_price) / rim1.price * 100
        if not (config.cup_depth_hard_min_pct <= depth_pct <= config.cup_depth_hard_max_pct):
            return None

        # §4.4 point 6: handle must sit in the upper half of the cup's own
        # range (mirrored for the inverse: closer to rim2/the breakout
        # level, not bounced back deep toward the rounding top).
        midpoint = (rim2.price + extreme_price) / 2
        if is_cup:
            if handle.price < midpoint:
                return None
            advance = rim2.price - extreme_price
            handle_depth = rim2.price - handle.price
        else:
            if handle.price > midpoint:
                return None
            advance = extreme_price - rim2.price
            handle_depth = handle.price - rim2.price
        if advance <= 0:
            return None
        handle_retrace_pct = handle_depth / advance * 100
        if handle_retrace_pct < 0 or handle_retrace_pct > config.cup_handle_max_retrace_pct:
            return None

        prior_pct = tl.prior_trend_pct(df, rim1, config.prior_trend_min_bars, trend_direction)
        if prior_pct is None or prior_pct < config.cup_prior_trend_min_pct:
            return None

        # §4.4 point 3 / §6.1: the doc's primary roundedness
        # operationalization -- most expensive check here, run last so
        # every cheaper structural gate above has first refusal.
        r2 = curves.fit_roundedness(close_path.to_numpy())
        if r2 < config.cup_roundedness_min_r2:
            return None

        return self._build_match(
            df, atr, vol_sma, ticker, timeframe, config,
            pattern_type, direction, is_cup, rim1, rim2, handle, extreme_price,
            window_pivots, prior_pct, r2,
        )

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, is_cup, rim1, rim2, handle, extreme_price,
        window_pivots, prior_pct, r2,
    ) -> PatternMatch:
        # §3.6 target = breakout_price + cup_depth, projected in the
        # breakout direction. The trigger level (rim2.price) is flat, so
        # -- unlike H&S/triangle's sloped/two-sided boundaries -- "breakout
        # price" and "the fixed trigger level" are the same number here,
        # no approximation needed. cup_depth measured against rim2 (the
        # same reference as the trigger), not rim1, so both the trigger
        # and the height share one anchor.
        height = abs(rim2.price - extreme_price)
        target_price = rim2.price + height if is_cup else rim2.price - height
        stop_price = extreme_price
        formation_bars = handle.bar_index - rim1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=list(window_pivots),
            key_levels={
                "left_rim": rim1.price, "cup_extreme": extreme_price, "right_rim": rim2.price,
                "handle": handle.price,
                # Reuses the "neckline" name double top/H&S already use
                # for their own flat/near-flat trigger level, so
                # plotting.py's existing key_levels["neckline"] fallback
                # draws this pattern's trigger line unchanged.
                "neckline": rim2.price,
            },
            target_price=target_price,
            stop_price=stop_price,
            formation_start=rim1.timestamp,
            formation_end=handle.timestamp,
        )

        def trigger_at(_i: int) -> float:
            return rim2.price

        def pre_breakout_invalidated_at(i: int) -> bool:
            # §4.4 invalidation: "a new low below the cup bottom at any
            # point after the cup is complete" (mirrored: a new high above
            # the rounding top) invalidates the base outright.
            return df["low"].iloc[i] < extreme_price if is_cup else df["high"].iloc[i] > extreme_price

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=handle.bar_index,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"], volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_components(
            df, atr, vol_sma, config, match, rim1, rim2, r2, formation_bars, prior_pct,
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(self, df, atr, vol_sma, config, match, rim1, rim2, r2, formation_bars, prior_pct) -> dict[str, float]:
        # §6.1: "use the quadratic-fit R² directly" as the primary
        # cleanliness metric, blended with rim price symmetry as a
        # secondary pattern-agnostic contributor (same idea as H&S's own
        # price+time symmetry blend, just one component here since there's
        # no second symmetric axis to measure for a cup).
        geometric_cleanliness = 0.7 * max(0.0, min(1.0, r2)) + 0.3 * scoring.price_symmetry(rim1.price, rim2.price)
        duration = scoring.duration_fit(formation_bars, config.cup_typical_min_bars, config.cup_typical_max_bars)
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, rim2.price, atr_at_breakout, match.direction, config.breakout_strength_cap_atr,
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
