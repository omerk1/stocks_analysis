"""Cup & Handle / Inverse Cup & Handle / Rounding Bottom / Rounding Top
detector -- design doc §4.4 (Phase 4) and §4.8 (Phase 6). Reuses plain
`lifecycle.apply_lifecycle` (not the bidirectional entry point) -- unlike
a triangle, the breakout side here is always fixed by which pivot kind
matched, same as double_top_bottom.py.

One detector covers all four pattern types, same shape as
double_top_bottom: a HIGH...HIGH...LOW sequence (left rim, [any pivots
forming the rounding], right rim, handle low) is a cup & handle (bullish)
if the handle is valid, or a rounding bottom (bullish, no handle
requirement) if it isn't; a LOW...LOW...HIGH sequence mirrors both into
their bearish counterparts (inverse cup & handle / rounding top).

Rounding is "cup and handle without the handle" (§4.8: "reuse the cup's
quadratic-fit roundedness check; skip the handle-specific rules") -- per
the design doc's own §8 module layout, it lives in this same file rather
than a separate one. Implemented as the *fallback* classification for a
given (rim1, rim2) pair, not a second, independently-scanned candidate:
every rim/depth/prior-trend/roundedness gate is shared and checked once
(`_check_common_gates`); only afterward does `_handle_gates_pass` decide
whether the pivot right after rim2 forms a real handle (upper-half of the
base's range, retracing a bounded fraction of the advance) or not. A
valid handle produces a Cup & Handle match; no valid handle (including no
pivot there at all, i.e. rim2 is the window's last pivot) produces a
Rounding match instead, using a longer typical-duration range (§4.8:
"require a longer duration than a typical cup" -- soft-scored, same
convention as every other duration figure here, despite the doc's own
"require" wording). This keeps a base from generating two redundant,
near-duplicate matches for the same shape.

Unlike double top/H&S/triangles, the cup's own pivot count isn't fixed
(§4.4's pivot sequence: "LOW(cup bottom, *possibly several pivots*
forming the rounding)") -- the roundedness itself is checked against the
raw close-price path between the two rims (`curves.fit_quadratic`), not
against the intermediate pivots directly. Only three pivots are ever used
as this detector's own anchors: left rim, right rim, handle -- scanned as
(rim1_index, rim2_index) pairs across the pivot list, bounded by
`config.cup_max_span_pivots`.
"""

from __future__ import annotations

import uuid

import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Direction, Pivot, PivotKind, Timeframe
from src.signals.patterns import curves, lifecycle, scoring
from src.signals.patterns import trendlines as tl
from src.signals.patterns import volume as volume_mod
from src.signals.patterns.base import PatternDetector
from src.signals.patterns.config import PatternConfig
from src.signals.patterns.models import PatternMatch, PatternType


def _close_at(df: pd.DataFrame, pivot: Pivot) -> float:
    """This detector's rim/handle price: the pivot's own bar's *close*, not
    `pivot.price` (which is the intraday high/low the ZigZag tracked).

    Every other detector uses `pivot.price` and is right to -- but this one
    checks its shape against the close path between the rims
    (`curves.fit_quadratic`, `max_single_bar_move_frac`) and takes its cup
    extreme from that same close path. Mixing a wick-valued rim into
    close-valued geometry meant a single-bar capitulation low could anchor
    the rim, the cup depth and therefore the measured-move target while
    being structurally invisible to every gate meant to catch it (the
    close path never contains that wick). Measured across real matches: the
    rim's high/low sat a median 2.4% from its own close, 40% of rims were
    more than 3% away, and the worst was 19.5% -- which is how a
    post-IPO-dump wick came to anchor a "cup rim."

    That noise also landed directly on `cup_rim_divergence_max_pct`, whose
    input carried a mean 2.5 percentage points of wick error against a 10%
    budget -- roughly 25% noise on the gate's own measurement, so the
    threshold wasn't quite measuring what it was tuned to measure.

    Deliberately NOT done by re-running pivot detection on closes: that
    would shift every pivot position and change which candidates exist at
    all, making the change impossible to attribute. The candidate set stays
    exactly as it was; only its measurement is corrected. `match.pivots`
    likewise keeps its wick values -- a pivot marks where price actually
    turned, which is a different (and also correct) fact from where the
    tradeable level sits."""
    return float(df["close"].iloc[pivot.bar_index])


class CupAndHandleDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        if len(pivots) < 3 or len(df) < 4:
            return []

        atr = indicators.atr(df, config.atr_period)
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)
        max_span = config.cup_max_span_pivots

        matches: list[PatternMatch] = []
        for i, rim1 in enumerate(pivots):
            is_cup = rim1.kind == PivotKind.HIGH
            trend_direction = "up" if is_cup else "down"
            direction = Direction.BULLISH if is_cup else Direction.BEARISH

            # Right-rim candidates share rim1's own kind (strict
            # alternation), so they sit two pivots apart each step.
            # Rounding needs only rim2 itself to exist (no handle
            # requirement), unlike the old cup-only version of this loop.
            max_j = min(len(pivots) - 1, i + max_span)
            for j in range(i + 2, max_j + 1, 2):
                rim2 = pivots[j]
                common = self._check_common_gates(df, config, is_cup, trend_direction, rim1, rim2)
                if common is None:
                    continue
                extreme_price, prior_pct, r2, rim1_price, rim2_price = common

                handle = pivots[j + 1] if j + 1 < len(pivots) else None
                handle_price = _close_at(df, handle) if handle is not None else None
                if handle is not None and self._handle_gates_pass(
                    config, is_cup, rim2_price, extreme_price, handle_price
                ):
                    pattern_type = PatternType.CUP_AND_HANDLE if is_cup else PatternType.INVERSE_CUP_AND_HANDLE
                    match = self._build_match(
                        df, atr, vol_sma, ticker, timeframe, config,
                        pattern_type, direction, is_cup, rim1, rim1_price, rim2, rim2_price, extreme_price,
                        pivots[i : j + 2], prior_pct, r2,
                        formation_end_pivot=handle, extra_key_levels={"handle": handle_price},
                        duration_min_bars=config.cup_typical_min_bars, duration_max_bars=config.cup_typical_max_bars,
                    )
                else:
                    pattern_type = PatternType.ROUNDING_BOTTOM if is_cup else PatternType.ROUNDING_TOP
                    match = self._build_match(
                        df, atr, vol_sma, ticker, timeframe, config,
                        pattern_type, direction, is_cup, rim1, rim1_price, rim2, rim2_price, extreme_price,
                        pivots[i : j + 1], prior_pct, r2,
                        formation_end_pivot=rim2, extra_key_levels={},
                        duration_min_bars=config.rounding_typical_min_bars,
                        duration_max_bars=config.rounding_typical_max_bars,
                        # Rounding's formation ends on rim2, the same pivot
                        # its trigger level comes from -- so without a gap
                        # the breakout scan starts one bar after the level
                        # was defined. See config for the measured effect.
                        min_breakout_gap_bars=config.rounding_breakout_min_gap_bars,
                    )
                matches.append(match)
        return matches

    def _check_common_gates(
        self, df, config, is_cup: bool, trend_direction: str, rim1: Pivot, rim2: Pivot,
    ) -> tuple[float, float, float, float, float] | None:
        """Every gate shared by Cup & Handle and Rounding: rim divergence,
        cup depth, prior trend, roundedness. Returns `(extreme_price,
        prior_pct, r2, rim1_price, rim2_price)` on success -- what
        downstream needs regardless of which of the two pattern types this
        candidate ends up becoming. Rim prices are close-based (see
        `_close_at`), so they're returned rather than re-derived by each
        caller."""
        rim1_price = _close_at(df, rim1)
        rim2_price = _close_at(df, rim2)
        if rim1_price <= 0:
            return None

        # §4.4 point 4, bounded on BOTH sides. The doc's own wording ("a
        # right rim above the left rim is fine too and often bullish")
        # describes a one-sided tolerance, and reading it literally is what
        # broke the bearish variants: mirrored, "fine above" becomes "fine
        # arbitrarily far below," and a right rim 30-66% under the left rim
        # is not a cup's rim at all -- it's the far side of a bear leg. The
        # cup's two rims have to rhyme in *both* directions for the shape to
        # mean anything, and for `_build_match`'s dollar-denominated
        # measured move off rim2 to stay sane (see config's own note for the
        # negative-target failure this produced). Same test for both
        # variants, so there is no mirrored branch left to get wrong.
        if abs(rim2_price - rim1_price) / rim1_price * 100 > config.cup_rim_divergence_max_pct:
            return None

        close_path = df["close"].iloc[rim1.bar_index : rim2.bar_index + 1]
        if len(close_path) < 3:
            return None
        extreme_price = float(close_path.min()) if is_cup else float(close_path.max())

        # §4.4 point 2: cup depth as a % retracement from the left rim --
        # hard-bounded outside the doc's own soft 12-50% range (see
        # config's own comment for why these are wider than the "typical"
        # figures), scored within it.
        depth_pct = abs(rim1_price - extreme_price) / rim1_price * 100
        if not (config.cup_depth_hard_min_pct <= depth_pct <= config.cup_depth_hard_max_pct):
            return None

        prior_pct = tl.prior_trend_pct(df, rim1, config.prior_trend_min_bars, trend_direction)
        if prior_pct is None or prior_pct < config.cup_prior_trend_min_pct:
            return None

        # §4.4 point 3 / §6.1 roundedness -- four checks off one parabola
        # fit, not just its R². Most expensive block here, run last so every
        # cheaper structural gate above has first refusal. Computed once
        # regardless of handle validity, since both the Cup & Handle and
        # Rounding outcomes need the R² for scoring.
        path = close_path.to_numpy()
        fit = curves.fit_quadratic(path)
        if fit.r2 < config.cup_roundedness_min_r2:
            return None

        # The parabola must open the way this pattern requires. Nothing
        # checked this before (the R² alone is direction-agnostic), and 26%
        # of real matches fail it -- a "cup" whose best-fit parabola bulges
        # the wrong way is not the shape it claims to be.
        if (fit.curvature > 0) != is_cup:
            return None

        # ...and its vertex must fall inside the rim-to-rim window. A
        # monotone leg fits a parabola arm with a high R² but puts the
        # vertex well outside the window (measured: 2.16 and 4.37 window-
        # lengths out on invalid instances, against 0.45 dead-centre on the
        # valid one). NaN (degenerate fit) fails the comparison and rejects,
        # which is the intent.
        apex_min, apex_max = config.cup_apex_position_range
        if not (apex_min <= fit.apex_position <= apex_max):
            return None

        # No single bar may account for too much of the cup's depth -- the
        # doc's own alternative heuristic, catching one-day gaps posing as a
        # cup wall (an earnings cliff the R² check waved through).
        if curves.max_single_bar_move_frac(path) > config.cup_max_single_bar_move_frac:
            return None

        return extreme_price, prior_pct, fit.r2, rim1_price, rim2_price

    def _handle_gates_pass(
        self, config, is_cup: bool, rim2_price: float, extreme_price: float, handle_price: float
    ) -> bool:
        # §4.4 point 6: handle must sit in the upper half of the cup's own
        # range (mirrored for the inverse: closer to rim2/the breakout
        # level, not bounced back deep toward the rounding top). Close-based
        # like every other price here (see `_close_at`) -- a handle judged
        # on its wick could sit in the correct half intraday while closing
        # in the wrong one.
        midpoint = (rim2_price + extreme_price) / 2
        if is_cup:
            if handle_price < midpoint:
                return False
            advance = rim2_price - extreme_price
            handle_depth = rim2_price - handle_price
        else:
            if handle_price > midpoint:
                return False
            advance = extreme_price - rim2_price
            handle_depth = handle_price - rim2_price
        if advance <= 0:
            return False
        handle_retrace_pct = handle_depth / advance * 100
        return 0 <= handle_retrace_pct <= config.cup_handle_max_retrace_pct

    def _build_match(
        self, df, atr, vol_sma, ticker, timeframe, config,
        pattern_type, direction, is_cup, rim1, rim1_price, rim2, rim2_price, extreme_price,
        window_pivots, prior_pct, r2, formation_end_pivot, extra_key_levels,
        duration_min_bars, duration_max_bars, min_breakout_gap_bars: int = 0,
    ) -> PatternMatch:
        # §3.6 target = breakout_price + cup_depth, projected in the
        # breakout direction. The trigger level (rim2's close) is flat, so
        # -- unlike H&S/triangle's sloped/two-sided boundaries -- "breakout
        # price" and "the fixed trigger level" are the same number here,
        # no approximation needed. cup_depth measured against rim2 (the
        # same reference as the trigger), not rim1, so both the trigger
        # and the height share one anchor. Identical for Rounding -- §4.8
        # gives no separate target convention of its own.
        height = abs(rim2_price - extreme_price)
        target_price = rim2_price + height if is_cup else rim2_price - height
        stop_price = extreme_price
        formation_bars = formation_end_pivot.bar_index - rim1.bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=pattern_type,
            direction=direction,
            pivots=list(window_pivots),
            key_levels={
                "left_rim": rim1_price, "cup_extreme": extreme_price, "right_rim": rim2_price,
                # Reuses the "neckline" name double top/H&S already use
                # for their own flat/near-flat trigger level, so
                # plotting.py's existing key_levels["neckline"] fallback
                # draws this pattern's trigger line unchanged.
                "neckline": rim2_price,
                # Where that level came from. Necessary now that the level
                # is a close and `pivot.price` is a wick -- plotting can no
                # longer find the source pivot by matching the price.
                "neckline_bar": float(rim2.bar_index),
                **extra_key_levels,
            },
            target_price=target_price,
            stop_price=stop_price,
            formation_start=rim1.timestamp,
            formation_end=formation_end_pivot.timestamp,
        )

        def trigger_at(_i: int) -> float:
            return rim2_price

        def pre_breakout_invalidated_at(i: int) -> bool:
            # §4.4 invalidation: "a new low below the cup bottom at any
            # point after the cup is complete" (mirrored: a new high above
            # the rounding top) invalidates the base outright. Same for
            # Rounding -- §4.8 has no separate invalidation convention.
            return df["low"].iloc[i] < extreme_price if is_cup else df["high"].iloc[i] > extreme_price

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=formation_end_pivot.bar_index,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"], volume_sma_series=vol_sma,
            config=config,
            # Rounding only -- measured from rim2, the pivot that supplies
            # the trigger level. Cup & Handle passes 0 and is unaffected.
            min_breakout_bar_index=(
                rim2.bar_index + min_breakout_gap_bars if min_breakout_gap_bars else None
            ),
        )

        components = self._score_components(
            df, atr, vol_sma, config, match, rim1_price, rim2_price, r2, formation_bars, prior_pct,
            duration_min_bars, duration_max_bars,
        )
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(
        self, df, atr, vol_sma, config, match, rim1_price, rim2_price, r2, formation_bars, prior_pct,
        duration_min_bars, duration_max_bars,
    ) -> dict[str, float]:
        # §6.1: "use the quadratic-fit R² directly" as the primary
        # cleanliness metric, blended with rim price symmetry as a
        # secondary pattern-agnostic contributor (same idea as H&S's own
        # price+time symmetry blend, just one component here since there's
        # no second symmetric axis to measure for a cup).
        geometric_cleanliness = 0.7 * max(0.0, min(1.0, r2)) + 0.3 * scoring.price_symmetry(rim1_price, rim2_price)
        duration = scoring.duration_fit(formation_bars, duration_min_bars, duration_max_bars)
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, rim2_price, atr_at_breakout, match.direction, config.breakout_strength_cap_atr,
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
