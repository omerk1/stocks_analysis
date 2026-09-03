"""AvwapConfig -- every tunable knob for anchor discovery, kept in one
place so the CLI can drive it without touching detection code (same
reasoning as sr_lines.config.SRConfig / gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AvwapConfig:
    # "hlc3" or "close" -- passed straight through to compute.anchored_vwap.
    price_source: str = "hlc3"

    # Trailing lookback (in bars of the running timeframe) used to find the
    # 52w_high/52w_low anchor candidates -- keyed by Timeframe.value so
    # daily and weekly each get their own window instead of one shared
    # bar-count that would mean very different calendar spans.
    trailing_window_bars: dict[str, int] = field(
        default_factory=lambda: {"daily": 252, "weekly": 52}
    )

    # ATR multiplier for market_common.pivots.detect_pivots when finding
    # cycle_high/cycle_low anchor candidates -- much wider than sr_lines'
    # own pivot detection (which looks for local S/R turning points): an
    # AVWAP anchor should mark a genuine cycle swing, not routine noise.
    cycle_scale_mult: float = 8.0

    # ATR lookback period feeding cycle_scale_mult above -- same default
    # gaps.config.GapConfig.atr_period/fibonacci.config.FibConfig.atr_period
    # use, but exposed here too (rather than a fixed module constant) so
    # every module's ATR period is tunable the same way.
    cycle_atr_period: int = 14

    # Most recent N confirmed cycle pivots (highs+lows combined, ranked by
    # date) become cycle_high/cycle_low anchor candidates.
    max_cycle_anchors: int = 4

    # Hard cap on total stored anchors per (ticker, timeframe) -- see
    # anchors._apply_cap for the trim-oldest-pure-cycle-first rule.
    max_anchors_total: int = 8

    # Skip (ticker, timeframe) with fewer rows than this, log a warning, no
    # detection at all.
    min_bars: int = 150

    # Skip this many leading bars of each series for cycle-pivot detection
    # only -- guarantees the ATR feeding detect_pivots' reversal threshold
    # is fully formed. ath/atl/52w_high/52w_low don't depend on ATR and are
    # deliberately searched over the *full* available history regardless of
    # this setting (see anchors.py).
    warmup_bars: int = 50

    # Interaction tracking (see lifecycle.apply_interaction_tracking).
    # ATR-normalized "how close does close need to be to the AVWAP line to
    # count as a touch" -- same tolerance concept as
    # fibonacci.FibConfig.level_touch_atr_tolerance, reused here at the
    # same default since an AVWAP line and a fib level are both "a single
    # price series price interacts with." Starting point, not validated.
    distance_tolerance_atr: float = 0.3
    # Forward window (bars) for measuring how far price moved away after a
    # touch, ATR-normalized -- mirrors SRConfig.touch_reaction_window_bars /
    # FibConfig's field of the same name.
    touch_reaction_window_bars: int = 10
