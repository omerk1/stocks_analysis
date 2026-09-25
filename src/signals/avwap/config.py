"""AvwapConfig -- every tunable knob for AVWAP (anchor discovery included,
via AnchorConfig), kept in one place so the CLI can drive it without
touching detection code (same reasoning as sr_lines.config.SRConfig /
gaps.config.GapConfig).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.foundation.market_common.anchors import AnchorConfig


@dataclass
class AvwapConfig(AnchorConfig):
    # Anchor-discovery knobs (trailing_window_bars, cycle_scale_mult,
    # cycle_atr_period, max_cycle_anchors, max_anchors_total, min_bars,
    # warmup_bars) are inherited from market_common.anchors.AnchorConfig --
    # shared with volume_profile, which anchors on the exact same dates.

    # "hlc3" or "close" -- passed straight through to compute.anchored_vwap.
    price_source: str = "hlc3"

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

    # Std-band multipliers k for the volume-weighted bands `avwap +/- k *
    # std` (see compute.anchored_vwap_std). Drawn by plotting.py; the stored
    # `AnchoredVwap.distance_std` is continuous, so research can threshold
    # it anywhere without depending on this setting. 1 and 2 are the common
    # convention (TradingView's VWAP bands default to 1/2/3); 3 is left out
    # because on an anchor more than a few weeks old the std keeps widening
    # and price rarely reaches 3x it. Price isn't normally distributed
    # around the AVWAP, so "1 std ~ 68% of bars" doesn't hold literally --
    # these are conventional distances, not calibrated probabilities.
    band_multipliers: tuple[float, ...] = (1.0, 2.0)
