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
    # "1d" or "1w" -- mirrors the DB's own bars_1d/bars_1w table naming.
    # "1w" bars are resampled live from bars_1d (see data.py), not read from
    # the separately-ingested bars_1w table directly, which is incomplete
    # for several tickers (e.g. T and GEVO both have zero bars_1w rows
    # despite a fully backfilled bars_1d). Don't set this directly on a
    # daily config and expect it to behave like a weekly one -- three other
    # fields below are bar-count-denominated and need rescaling too; use
    # `get_preset("<name>_weekly")` instead, which bundles both correctly
    # (see PRESETS below).
    bar_interval: str = "1d"

    # Pivot detection
    pivot_atr_mult: float = 2.0
    atr_period: int = 14

    # Candidate zones
    zone_width_atr: float = 0.4
    min_pivots_per_cluster: int = 2

    # Diagonal (milestone 5)
    diagonal_enabled: bool = False
    diagonal_score_multiplier: float = 0.65
    # ATR-normalized (see candidates.slope_atr_per_bar): roughly "how many
    # ATRs of real price movement per bar, along the trend." Real trendline
    # slopes are documented elsewhere in this file as ~0.0001-0.001 raw
    # log-price/bar; at a typical daily-equity ATR% (~2%, price/ATR~=50)
    # that normalizes to roughly 0.005-0.05 ATR/bar. 0.35 keeps the same
    # "generous, rarely binding" character the old raw cap (0.05, applied
    # directly to log-slope with no ATR normalization at all) had -- but
    # unlike that one, now means the same thing for every ticker regardless
    # of its own price/ATR% regime, rather than being inconsistently loose
    # for low-ATR%/mega-caps and comparatively tight for high-ATR%/small-caps.
    # A starting point, not a final answer -- needs the same real-chart
    # tuning pass every other knob here already went through.
    max_diagonal_slope_atr_per_bar: float = 0.35
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
    # scoring ever got a chance to rank it. Raising the number to 300 turned
    # out not to be the real fix, just a bigger version of the same one: a
    # real GEVO run produced 1,144 raw same-kind fits from LOW pivots alone
    # (804 genuinely distinct after dedup), so a 3-inlier short trendline
    # could still lose its turn to hundreds of higher-touch-count long lines
    # before the cap ever saw it. `_dedupe_diagonal_candidates` now applies
    # this cap *after* dedup finishes (not mid-loop) and truncates by
    # `fit_rms_atr_pct` -- fit tightness, not touch count -- so candidate
    # generation actually leaves ranking to quality rather than raw pivot
    # count, at the cost of a slower
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


# Each preset is written out in full, independently of every other one --
# no preset is derived from, or overwrites fields on, another. The
# `_weekly` presets duplicate `window_years`/`pivot_atr_mult` from their
# daily counterpart rather than building on top of it, on purpose: this
# project has already gotten burned once by a config field silently ending
# up in an inconsistent combination (regime_start, an earlier round --
# see design notes), and a value here is either right for that preset or
# it isn't, regardless of what some other preset happens to say. The three
# bar-count-denominated fields that actually differ between a daily and
# weekly preset of the same span (fakeout_reclaim_bars,
# touch_reaction_window_bars, diagonal_min_pivot_separation_bars) are a
# first-pass starting point (same real-world span the daily default
# covered, divided by ~5 and rounded), NOT an empirically validated
# calibration -- every other bar-count knob in this project (zone_width_atr,
# dedup_overlap_threshold, the diagonal candidate cap, etc.) got its own
# dedicated real-chart review round after its mechanism landed, and these
# should get the same treatment as separate, deliberately-scoped follow-up
# work. `atr_period` is deliberately the same 14 in both -- an idiomatic
# ATR lookback regardless of timeframe (ATR(14) is standard on weekly
# charts too), not actually coupled to daily-ness the way the other three
# are. Everything else (including all of scoring.py's decay/regime
# machinery -- `recency_half_life_years`, `regime_gap_years`, `window_years`
# itself) already operates in real calendar time, not bar counts, so daily
# and weekly genuinely share the same right answer there.
#
# `max_diagonal_slope_atr_per_bar` is also bar-count-denominated (it's a
# rate *per bar*), but scales the *opposite* direction from the other three:
# those are "how many bars until X" thresholds, which shrink under weekly
# since fewer, longer bars are needed to span the same calendar time; slope
# is "movement per bar", which grows under weekly since each bar now spans
# ~5x the calendar time (and therefore accumulates ~5x the price movement)
# of a daily bar for the same real-world trend. Same "divide/multiply
# daily's default by ~5" unvalidated first pass as the other three, just in
# the opposite direction.
PRESETS: dict[str, SRConfig] = {
    "medium_term": SRConfig(
        window_years=3.0, pivot_atr_mult=2.0, bar_interval="1d",
        fakeout_reclaim_bars=5, touch_reaction_window_bars=10, diagonal_min_pivot_separation_bars=20,
    ),
    "long_term": SRConfig(
        window_years=8.0, pivot_atr_mult=3.0, bar_interval="1d",
        fakeout_reclaim_bars=5, touch_reaction_window_bars=10, diagonal_min_pivot_separation_bars=20,
    ),
    "medium_term_weekly": SRConfig(
        window_years=3.0, pivot_atr_mult=2.0, bar_interval="1w",
        fakeout_reclaim_bars=1, touch_reaction_window_bars=2, diagonal_min_pivot_separation_bars=4,
        max_diagonal_slope_atr_per_bar=1.75,
    ),
    "long_term_weekly": SRConfig(
        window_years=8.0, pivot_atr_mult=3.0, bar_interval="1w",
        fakeout_reclaim_bars=1, touch_reaction_window_bars=2, diagonal_min_pivot_separation_bars=4,
        max_diagonal_slope_atr_per_bar=1.75,
    ),
}


def get_preset(name: str) -> SRConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    # Return a fresh copy so callers mutating fields don't corrupt the shared preset.
    preset = PRESETS[name]
    return SRConfig(**preset.to_dict())
