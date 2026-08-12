"""FibConfig -- every tunable knob for multi-scale fib detection, mirroring
sr_lines.config's SRConfig precedent (one dataclass, plot/CLI can override
fields without touching detection code).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_weight_components() -> dict:
    return {"magnitude": 0.5, "duration": 0.2, "recency": 0.3}


def _default_scales() -> list[float]:
    return [2.0, 4.0, 8.0]


def _default_retracement_ratios() -> list[float]:
    return [0.236, 0.382, 0.5, 0.618, 0.786]


def _default_extension_ratios() -> list[float]:
    return [1.272, 1.618, 2.0, 2.618]


@dataclass
class FibConfig:
    # Pivot detection -- run once per scale, independently (see swings.py's
    # module docstring for why this is deliberate, not something to
    # collapse into a single pass).
    scales: list[float] = field(default_factory=_default_scales)
    # Not in the original spec table -- ATR(14) is this project's standing
    # default lookback (sr_lines.config.SRConfig.atr_period), reused here
    # rather than inventing a second "idiomatic" period.
    atr_period: int = 14

    min_swing_atr: float = 8.0
    max_sets: int = 6

    retracement_ratios: list[float] = field(default_factory=_default_retracement_ratios)
    extension_ratios: list[float] = field(default_factory=_default_extension_ratios)

    # "linear" or "log" -- interpolation mode for level prices.
    price_scale: str = "linear"

    dedup_bar_tolerance: int = 3
    recency_half_life_bars: int = 250
    weight_components: dict = field(default_factory=_default_weight_components)
    # Normalization caps for the magnitude/duration weight components --
    # a swing at or above this magnitude_atr/duration_bars maps to that
    # component's full [0, 1] weight. Exposed alongside recency_half_life_bars
    # (the third component's own knob) rather than left as fixed divisors.
    magnitude_atr_cap: float = 40.0
    duration_bars_cap: int = 250

    min_bars: int = 150
    warmup_bars: int = 50

    # Level touch/respect tracking (see lifecycle.evaluate_level_touches).
    # Full-width ATR-dollar tolerance band around a level's exact price --
    # smaller than sr_lines.SRConfig.zone_width_atr's 0.4 (a level here is a
    # single computed price, not a pre-clustered zone of real pivots, so a
    # tighter band is the more honest starting point). Starting point, not
    # validated -- needs the same real-chart tuning pass every new knob in
    # this project gets.
    level_touch_atr_tolerance: float = 0.3
    # How many bars a close that crossed a level's tolerance band gets to
    # close back on the original side before the interaction counts as a
    # violation instead of a (weaker, still-respected) touch -- same
    # reasoning as SRConfig.fakeout_reclaim_bars, just level-scoped.
    level_violation_reclaim_bars: int = 5
    # Forward window (bars) for measuring how far price moved away after a
    # touch, ATR-normalized -- mirrors SRConfig.touch_reaction_window_bars.
    touch_reaction_window_bars: int = 10

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["scales"] = list(self.scales)
        d["retracement_ratios"] = list(self.retracement_ratios)
        d["extension_ratios"] = list(self.extension_ratios)
        d["weight_components"] = dict(self.weight_components)
        return d
