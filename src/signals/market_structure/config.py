"""MarketStructureConfig -- tunable knobs for Break of Structure (BOS) /
Change of Character (CHoCH) trend-regime tracking. Same reasoning as
DivergenceConfig/PatternConfig: a plain dataclass so the CLI can drive it
without touching detection code.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.foundation.market_common.models import Timeframe


@dataclass
class MarketStructureConfig:
    timeframe: Timeframe = Timeframe.DAILY
    atr_period: int = 14

    # Pivot detection (market_common.pivots.detect_pivots): reversal must
    # clear this x ATR to confirm a pivot -- same default as
    # PatternConfig.pivot_atr_mult / sr_lines' own pivot_atr_mult.
    pivot_atr_mult: float = 2.5

    # Skip (ticker, timeframe) with fewer rows than this -- needs at least
    # 2 confirmed pivots to even bootstrap a starting regime (see
    # detect.track_market_structure), same reasoning as every other
    # module's min_bars gate.
    min_bars: int = 60

    # Pivot breakout validation design doc's "Code Modification Rules":
    # optional volume-surge gate on every break. Reuses
    # breakout_volume_mult/volume_sma_period as the single shared
    # threshold rather than a second, duplicate knob -- same design
    # decision as PatternConfig.require_volume_surge (see
    # docs/features/pivot_breakout_validation_design.md §4). Off by
    # default: a close-only break is already the "sharpened" requirement
    # the design doc asks for; volume confirmation is an additional,
    # optional filter on top. Note `break_confirmation_type` ("wick" vs.
    # "close") was discarded entirely rather than added as a param here --
    # see the design doc's §4/§5 for why.
    require_volume_surge: bool = False
    volume_sma_period: int = 50
    breakout_volume_mult: float = 1.4

    def to_dict(self) -> dict:
        return dict(self.__dict__)


PRESETS: dict[str, MarketStructureConfig] = {
    "daily": MarketStructureConfig(timeframe=Timeframe.DAILY),
    "weekly": MarketStructureConfig(timeframe=Timeframe.WEEKLY, min_bars=20),
}


def get_preset(name: str) -> MarketStructureConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    preset = PRESETS[name]
    return MarketStructureConfig(**preset.to_dict())
