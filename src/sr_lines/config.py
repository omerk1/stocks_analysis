"""SRConfig -- every tunable knob for the S/R engine lives here, so the
review chart (plotting.py/cli.py) can drive weight-tuning by visual
inspection without touching detection code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_scoring_weights() -> dict:
    # proximity is not in this dict -- it's applied as a multiplicative
    # relevance gate (with recency) on the whole score, not an additive
    # term. See scoring.py's score_line for why.
    return {
        "touch_quality": 0.35,
        "duration_density": 0.20,
        "resilience": 0.15,
        "role_reversal": 0.20,
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

    # Diagonal (milestone 5)
    diagonal_enabled: bool = False
    diagonal_score_multiplier: float = 0.65
    max_diagonal_slope_atr_per_bar: float = 0.05
    diagonal_min_pivot_separation_bars: int = 20
    diagonal_min_inliers: int = 3
    # A candidate must move more than its own half_width (in log-price) over
    # the span between its own first and last inlier, or it's rejected --
    # otherwise its price never actually leaves its own noise band across its
    # entire claimed lifetime, which makes it indistinguishable from a flat
    # horizontal zone (already covered by generate_horizontal_candidates)
    # wearing a slope. Confirmed on real GEVO/T data: several kept diagonals
    # had slopes of -0.000002 to -0.000005/bar (total drift/half_width ratio
    # 0.16-0.95) sitting in the exact same price band as several of that same
    # run's top horizontal lines -- the same level rendered twice, once as a
    # box, once as an indistinguishable near-flat streak, since horizontal
    # and diagonal candidates are never deduped against each other (a sloped
    # and a flat line are usually genuinely different claims, so that's
    # deliberate -- see lifecycle.dedup_lines). Real trend lines on the same
    # runs sat at ratio >= 1.4, with most well above 2 -- 1.0 is a
    # conservative floor that only rejects candidates whose own fitted
    # geometry never clears their own tolerance band, not merely gentle ones.
    diagonal_min_drift_to_half_width: float = 1.0
    # 30 was too aggressive: a real AAPL run had 255 genuinely distinct
    # candidates after proper (slope-aware) dedup, and ranking the survivors
    # by raw pivot count before capping systematically favored long,
    # low-precision multi-year lines over short, tight, recent ones --
    # discarding a visually obvious 3-touch descending trendline before
    # scoring ever got a chance to rank it. 300 comfortably covers real
    # long_term windows (255/228 candidates seen on AAPL/T) so candidate
    # generation stops pre-filtering by "most pivots" and leaves ranking to
    # scoring's actual relevance/quality machinery, at the cost of a slower
    # detection run (~8-10s vs ~1s on a long_term window).
    diagonal_max_candidates: int = 300

    # Events
    fakeout_reclaim_bars: int = 5
    touch_reaction_window_bars: int = 10

    # Scoring
    recency_half_life_years: float | None = None  # None -> window_years * 0.25
    scoring_weights: dict = field(default_factory=_default_scoring_weights)
    # A line's events can have a real, multi-year gap in the middle -- price
    # simply wandered elsewhere for a while, then came back to legitimately
    # retest the level -- and that's normal market behavior, not evidence the
    # line is spurious. If the gap between two consecutive events exceeds
    # this, `scoring.regime_start` treats everything before it as an earlier,
    # separate regime: `in_play_gate` and the rendered box both then judge
    # the line only from its *current* regime onward, instead of averaging/
    # spanning across dead time from years ago. Confirmed on a real PAAS
    # trendline: a genuine, tightly-fit (fit_rms=0.07) descending resistance
    # with a real ~3-year dormant gap before a decisive 2024 breakout scored
    # 0.032 (buried) under the old flat full-history in_play_gate, vs. 0.177
    # (top-ranked) once judged from the start of its current regime.
    regime_gap_years: float = 1.0

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
