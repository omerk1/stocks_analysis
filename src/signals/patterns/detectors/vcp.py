"""Volatility Contraction Pattern (VCP) detector -- design doc §4.5.
Phase 5: bullish continuation base of 2-6 successive pullback legs, each
shallower than the last, ending in a low-volatility "pivot" that breaks
out on volume. Bullish-only -- the design doc frames VCP purely as a
Minervini-style bullish continuation setup, no inverse variant is
described (unlike every earlier pattern here).

The most architecturally novel detector so far, in two ways:

1. **Its own, finer pivot pass.** Every prior detector consumed the
   `pivots` argument `scan()` receives (the scanner's one shared,
   coarse-granularity pass). §2c explicitly calls for finer pivots here
   to catch each individual contraction leg -- `scan()` ignores the
   passed-in `pivots` and calls `detect_pivots` itself with
   `config.vcp_pivot_atr_mult` (1.0, vs. the shared pass's 2.5). See
   base.py's own updated docstring.
2. **A Trend Template regime gate before any base geometry is even
   examined** (§4.5 point 1: "Require prior uptrend and a Trend Template
   gate... this is closely tied to Minervini's methodology"). Treated as
   *the* prior-trend qualifier for this pattern -- no separate
   `has_prior_trend` call, since price sitting above rising 150/200-day
   MAs near its 52-week high already is the doc's own stand-in for "prior
   uptrend," more specific than the generic §3.1 check every other
   detector uses.
"""

from __future__ import annotations

import uuid

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


def _is_in_stage2_uptrend(
    i: int, df: pd.DataFrame, sma_short: pd.Series, sma_medium: pd.Series, sma_long: pd.Series,
    high_lookback: pd.Series, config: PatternConfig,
) -> bool:
    """§4.5 point 1's Trend Template, evaluated at bar `i`: price above
    rising medium/long MAs, the short MA stacked above both, and price
    within `config.vcp_pct_from_52w_high_max`% of its own trailing high.
    All-NaN-safe (returns False, not an error, during warmup -- `pd.isna`
    comparisons are never accidentally True)."""
    close = df["close"].iloc[i]
    s_short, s_medium, s_long = sma_short.iloc[i], sma_medium.iloc[i], sma_long.iloc[i]
    if pd.isna(s_short) or pd.isna(s_medium) or pd.isna(s_long):
        return False

    lookback = config.vcp_ma_rising_lookback_bars
    if i - lookback < 0:
        return False
    s_medium_prior, s_long_prior = sma_medium.iloc[i - lookback], sma_long.iloc[i - lookback]
    if pd.isna(s_medium_prior) or pd.isna(s_long_prior):
        return False

    rising = s_medium > s_medium_prior and s_long > s_long_prior
    above_mas = close > s_medium and close > s_long
    ma_stack = s_short > s_medium and s_short > s_long

    trailing_high = high_lookback.iloc[i]
    if pd.isna(trailing_high) or trailing_high <= 0:
        return False
    near_high = (trailing_high - close) / trailing_high * 100 <= config.vcp_pct_from_52w_high_max

    return rising and above_mas and ma_stack and near_high


class VCPDetector(PatternDetector):
    def scan(
        self,
        df: pd.DataFrame,
        pivots: list[Pivot],
        ticker: str,
        timeframe: Timeframe,
        config: PatternConfig,
    ) -> list[PatternMatch]:
        if len(df) < config.min_bars:
            return []

        atr_main = indicators.atr(df, config.atr_period)
        atr_short = indicators.atr(df, config.vcp_atr_short_period)
        atr_long = indicators.atr(df, config.vcp_atr_long_period)
        sma_short = indicators.sma(df["close"], config.vcp_sma_short_period)
        sma_medium = indicators.sma(df["close"], config.vcp_sma_medium_period)
        sma_long = indicators.sma(df["close"], config.vcp_sma_long_period)
        high_lookback = df["high"].rolling(config.vcp_52w_high_lookback_bars).max()
        vol_sma = volume_mod.volume_sma(df["volume"], config.volume_sma_period)

        fine_pivots = detect_pivots(
            df["high"], df["low"], threshold_fn=lambda i: config.vcp_pivot_atr_mult * atr_main.iloc[i]
        )

        matches: list[PatternMatch] = []
        for i, p in enumerate(fine_pivots):
            if p.kind != PivotKind.HIGH:
                continue
            for n in range(config.vcp_min_contractions, config.vcp_max_contractions + 1):
                window = fine_pivots[i : i + 2 * n]
                if len(window) < 2 * n:
                    break  # not enough pivots left for this or any larger n from this start
                match = self._try_window(
                    df, atr_main, atr_short, atr_long, sma_short, sma_medium, sma_long, high_lookback, vol_sma,
                    ticker, timeframe, config, window,
                )
                if match is not None:
                    matches.append(match)
        return matches

    def _try_window(
        self, df, atr_main, atr_short, atr_long, sma_short, sma_medium, sma_long, high_lookback, vol_sma,
        ticker, timeframe, config, window: list[Pivot],
    ) -> PatternMatch | None:
        highs = window[0::2]
        lows = window[1::2]

        base_start_i = highs[0].bar_index
        if not _is_in_stage2_uptrend(base_start_i, df, sma_short, sma_medium, sma_long, high_lookback, config):
            return None

        depths = [(h.price - l.price) / h.price * 100 if h.price > 0 else 0.0 for h, l in zip(highs, lows)]
        if any(d <= 0 for d in depths):
            return None

        # §4.5 point 4: monotonically shallower contractions, with the
        # doc's own explicit one-violation tolerance.
        violations = sum(1 for a, b in zip(depths, depths[1:]) if b >= a)
        if violations > config.vcp_contraction_violations_allowed:
            return None

        # §4.5 point 5: higher lows within the base -- no tolerance
        # granted for this one in the doc's own text, unlike point 4.
        if any(lows[k + 1].price <= lows[k].price for k in range(len(lows) - 1)):
            return None

        final_low_i = lows[-1].bar_index
        long_atr = atr_long.iloc[final_low_i]
        if pd.isna(long_atr) or long_atr <= 0:
            return None
        ratio = float(atr_short.iloc[final_low_i]) / float(long_atr)
        if ratio > config.vcp_atr_contraction_max_ratio:
            return None

        base_low = min(l.price for l in lows)
        pivot_price = highs[-1].price

        return self._build_match(
            df, atr_main, sma_medium, vol_sma, ticker, timeframe, config, window, highs, lows,
            depths, ratio, base_low, pivot_price,
        )

    def _build_match(
        self, df, atr_main, sma_medium, vol_sma, ticker, timeframe, config, window, highs, lows,
        depths, ratio, base_low, pivot_price,
    ) -> PatternMatch:
        height = pivot_price - base_low
        target_price = pivot_price + height
        stop_price = base_low
        formation_bars = lows[-1].bar_index - highs[0].bar_index

        match = PatternMatch(
            id=str(uuid.uuid4()),
            ticker=ticker,
            timeframe=Timeframe(timeframe),
            pattern_type=PatternType.VCP,
            direction=Direction.BULLISH,
            pivots=list(window),
            key_levels={
                "pivot_price": pivot_price, "base_low": base_low,
                **{f"contraction_{k}_depth_pct": d for k, d in enumerate(depths)},
            },
            target_price=target_price,
            stop_price=stop_price,
            formation_start=highs[0].timestamp,
            formation_end=lows[-1].timestamp,
        )

        def trigger_at(_i: int) -> float:
            return pivot_price

        def pre_breakout_invalidated_at(i: int) -> bool:
            # §4.5 invalidation: a fresh low below the base's own overall
            # low, or a close back below the (rising) medium-term MA --
            # either breaks the Stage-2-uptrend precondition the whole
            # base was gated on.
            return df["low"].iloc[i] < base_low or df["close"].iloc[i] < sma_medium.iloc[i]

        lifecycle.apply_lifecycle(
            df, match,
            formation_end_bar_index=lows[-1].bar_index,
            formation_bars=formation_bars,
            trigger_at=trigger_at,
            pre_breakout_invalidated_at=pre_breakout_invalidated_at,
            volume=df["volume"], volume_sma_series=vol_sma,
            config=config,
        )

        components = self._score_components(df, atr_main, vol_sma, config, match, depths, ratio, formation_bars, highs)
        confidence, notes = scoring.score_pattern(components, config)
        match.confidence = confidence
        match.notes = notes
        return match

    def _score_components(
        self, df, atr_main, vol_sma, config, match, depths, ratio, formation_bars, highs,
    ) -> dict[str, float]:
        # §6.1 VCP-specific addition: contraction-monotonicity
        # *strictness* (continuous, unlike the hard gate's one-violation
        # floor -- a textbook 25->12->5->2 sequence scores near 1.0, a
        # noisy sequence that only barely avoids violating it scores much
        # lower) blended with how tight the final ATR-contraction ratio
        # actually is within the hard gate's own ceiling.
        contraction_strictness = scoring.range_monotonicity_score(depths)
        contraction_tightness = scoring.contraction_tightness_score(ratio, config.vcp_atr_contraction_max_ratio)
        geometric_cleanliness = 0.5 * contraction_strictness + 0.5 * contraction_tightness

        duration = scoring.duration_fit(formation_bars, config.vcp_typical_min_bars, config.vcp_typical_max_bars)

        # The Trend Template gate already qualifies "prior uptrend" as a
        # hard precondition -- this soft component still measures its
        # magnitude, same generic mechanism every other detector uses,
        # rather than inventing a VCP-specific substitute.
        prior_pct = tl.prior_trend_pct(df, highs[0], config.prior_trend_min_bars, "up") or 0.0
        prior_trend_score = scoring.prior_trend_strength(prior_pct, config.prior_trend_score_cap_pct)

        if match.breakout_bar is not None:
            breakout_close = float(df["close"].iloc[match.breakout_bar])
            atr_at_breakout = atr_main.iloc[match.breakout_bar]
            atr_at_breakout = None if pd.isna(atr_at_breakout) else float(atr_at_breakout)
            breakout_strength = scoring.breakout_close_strength(
                breakout_close, match.key_levels["pivot_price"], atr_at_breakout,
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
