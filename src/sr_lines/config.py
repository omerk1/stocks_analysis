"""SRConfig -- every tunable knob for the S/R engine lives here, so the
review chart (plotting.py/cli.py) can drive weight-tuning by visual
inspection without touching detection code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_scoring_weights() -> dict:
    return {
        "touch_quality": 0.35,
        "duration_density": 0.20,
        "resilience": 0.15,
        "role_reversal": 0.20,
        "proximity": 0.10,
    }


@dataclass
class SRConfig:
    # Data window
    window_years: float = 3.0

    # Pivot detection
    pivot_atr_mult: float = 2.0
    atr_period: int = 14

    # Candidate zones
    zone_width_atr: float = 0.4
    min_pivots_per_cluster: int = 2

    # Diagonal (unused until milestone 5; kept here so the config shape is
    # stable across the milestone-4 review checkpoint)
    diagonal_enabled: bool = False
    diagonal_score_multiplier: float = 0.65
    max_diagonal_slope_atr_per_bar: float = 0.05
    diagonal_min_pivot_separation_bars: int = 20
    diagonal_min_inliers: int = 3
    diagonal_max_candidates: int = 30

    # Events
    fakeout_reclaim_bars: int = 5
    touch_reaction_window_bars: int = 10

    # Scoring
    recency_half_life_years: float | None = None  # None -> window_years * 0.25
    scoring_weights: dict = field(default_factory=_default_scoring_weights)

    # Lifecycle / selection
    top_n: int = 10
    dedup_overlap_threshold: float = 0.6

    # Data quality
    corruption_warning_threshold: float = 0.005  # 0.5%

    def resolved_half_life_years(self) -> float:
        if self.recency_half_life_years is not None:
            return self.recency_half_life_years
        return self.window_years * 0.25

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["scoring_weights"] = dict(self.scoring_weights)
        return d


PRESETS: dict[str, SRConfig] = {
    "medium_term": SRConfig(window_years=3.0, pivot_atr_mult=2.0),
    "long_term": SRConfig(window_years=8.0, pivot_atr_mult=3.0),
}


def get_preset(name: str) -> SRConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    # Return a fresh copy so callers mutating fields don't corrupt the shared preset.
    preset = PRESETS[name]
    return SRConfig(**preset.to_dict())
