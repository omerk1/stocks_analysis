"""PatternConfig -- tunable knobs shared across every pattern detector
(design doc §3: prior-trend qualification, trendline touch tolerance,
volume confirmation, breakout buffer, expiration). Same reasoning as
SRConfig/GapConfig/DivergenceConfig: a plain dataclass, not YAML, so the
CLI/plotting can drive it without touching detection code, and different
asset-class/timeframe profiles are `PRESETS` entries (see SRConfig.PRESETS)
rather than separate config files.

Deliberately thin for now -- only the §3 "common concepts" knobs that
Phase 0/1 (double top/bottom) actually need. Pattern-specific thresholds
(cup depth %, VCP contraction sequence, triangle apex/convergence knobs,
...) get added here alongside each pattern's own detector as later phases
land, not speculatively up front.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.market_common.models import Timeframe


def _default_scoring_weights() -> dict:
    # §6's example weight table. Sums to 1.0; score_pattern assumes callers
    # always supply exactly these five component keys (see scoring.py).
    return {
        "geometric_cleanliness": 0.30,
        "volume_signature": 0.25,
        "duration_fit": 0.15,
        "prior_trend": 0.15,
        "breakout_strength": 0.15,
    }


@dataclass
class PatternConfig:
    timeframe: Timeframe = Timeframe.DAILY
    atr_period: int = 14

    # Skip (ticker, timeframe) with fewer rows than this after filtering --
    # log a warning, don't attempt detection on too short a history. No
    # explicit figure in the design doc; a first-pass starting point giving
    # enough headroom for prior-trend lookback + formation + a real
    # post-formation window, same reasoning as DivergenceConfig.min_bars=150.
    min_bars: int = 100

    # Pivot detection (market_common.pivots.detect_pivots): reversal must
    # clear this x ATR to confirm a pivot. 2.5 is the design doc's own
    # recommended default (§2a) -- a starting point, not yet tuned against
    # real chart output the way sr_lines' pivot_atr_mult was.
    pivot_atr_mult: float = 2.5

    # §3.1 prior-trend qualification: a pattern's first pivot must be
    # preceded by a move of >= this %, over >= this many bars. Generic
    # defaults here match the design doc's H&S figures (15%, ~20 trading
    # days) -- other patterns pass their own thresholds directly to
    # `trendlines.has_prior_trend` rather than reading these (cup & handle
    # wants 30%+, per §4.4).
    prior_trend_min_pct: float = 15.0
    prior_trend_min_bars: int = 20

    # §3.2 trendline touch validation: a bar counts as "touching" a
    # trendline/neckline within max(touch_tolerance_atr_mult * ATR,
    # touch_tolerance_pct * price).
    touch_tolerance_atr_mult: float = 0.5
    touch_tolerance_pct: float = 0.005
    min_touches_per_line: int = 2

    # §3.3 volume confirmation: breakout bar's volume vs. its own trailing
    # SMA(volume, volume_sma_period) must reach at least this ratio to
    # count as volume-confirmed. 1.4 = the "~40% above average" figure
    # that recurs across VCP/cup-and-handle sources in the design doc.
    volume_sma_period: int = 50
    breakout_volume_mult: float = 1.4

    # §3.4 breakout/confirmation: a close must clear the trigger level by
    # at least this fraction to count as a real breakout (not a marginal
    # close), echoing O'Neil's cup & handle buffer convention.
    breakout_buffer_pct: float = 0.001

    # §3.5 EXPIRED: a still-PENDING pattern expires if no breakout occurs
    # within this multiple of the pattern's own formation duration
    # (breakout-level bar index minus first-pivot bar index).
    expire_lifespan_mult: float = 2.0
    # Post-breakout: a close back through the trigger level within this
    # many bars of the breakout counts as a failed breakout
    # (INVALIDATED_FAILED_BREAKOUT), not a genuine confirmed move -- same
    # default as sr_lines' fakeout_reclaim_bars. Shared by every detector's
    # lifecycle walk (see lifecycle.py), not pattern-specific.
    failed_breakout_reclaim_bars: int = 5

    # §6 confidence scoring. Sub-metric score caps: rel_volume of
    # `volume_score_cap_mult`+ maps to a full 1.0 volume_signature score
    # (1.0x = 0.0, per volume.rel_volume's own semantics of "no expansion
    # at all"); a breakout close `breakout_strength_cap_atr`+ ATR beyond
    # its trigger level maps to a full breakout_strength score;
    # `prior_trend_score_cap_pct`+ prior move maps to a full prior_trend
    # score. All starting points, not yet tuned against real chart output.
    scoring_weights: dict = field(default_factory=_default_scoring_weights)
    volume_score_cap_mult: float = 1.8
    breakout_strength_cap_atr: float = 1.0
    prior_trend_score_cap_pct: float = 30.0

    # §4.2 Double Top/Bottom. Symmetry is a soft-scored input (§6: only
    # true structural invariants hard-gate), but an unbounded search would
    # explode into noise without some outer bound -- this is that bound,
    # not the "typical ~3%" figure the design doc quotes for a *good*
    # instance (scoring.price_symmetry already scores a tight ~3% match
    # near 1.0 on its own). typical_min/max_bars feed scoring.duration_fit;
    # no explicit figure in the design doc for this pattern, so this is a
    # first-pass starting point (~2 weeks to ~6 months on daily bars).
    double_top_symmetry_hard_gate_pct: float = 8.0
    double_top_typical_min_bars: int = 10
    double_top_typical_max_bars: int = 120

    # §4.1 Head & Shoulders / Inverse. Same "hard outer bound, soft score
    # within it" reasoning as double_top_symmetry_hard_gate_pct -- the
    # design doc's own quoted "~10-15%" shoulder-symmetry tolerance is
    # treated as the hard gate (15, the top of that range), with
    # scoring.hs_price_symmetry providing the *soft*, continuous score.
    head_shoulders_symmetry_hard_gate_pct: float = 15.0
    # §4.1 point 6: "each leg >= 5 trading days" -- hard gate against a
    # 3-bar noise quintuple posing as a real 5-pivot formation.
    head_shoulders_min_leg_bars: int = 5
    # §4.1 point 5: neckline slope cap -- reject if the fitted T1->T2
    # neckline implies more than this % price change over its own span. No
    # explicit figure in the design doc ("cap slope... reject if... >X%
    # change"); a first-pass starting point, same unvalidated status as
    # every other knob here.
    head_shoulders_neckline_max_slope_pct: float = 10.0
    # duration_fit typical range -- wider than double top's (10/120) since
    # a 5-pivot H&S formation is structurally larger than a 3-pivot double
    # top. No explicit bar-count figure in the design doc; first-pass
    # starting point.
    head_shoulders_typical_min_bars: int = 20
    head_shoulders_typical_max_bars: int = 180

    # §4.3/§4.6 Triangles (asc/desc/symmetric) + Wedges. `min_touches_per_
    # line` (already defined above, §3.2) doubles as this pattern family's
    # own "2 per line, 4 total" hard floor -- no separate knob needed.
    # `triangle_window_pivots=6` -- the doc's own "5-6 pivots" convention;
    # picked the even end for a clean 3-highs/3-lows split against
    # detect_pivots' strict alternation. `triangle_flat_slope_atr_mult`
    # decides "flat/horizontal" for shape classification (ascending vs.
    # descending vs. symmetric vs. wedge) -- ATR-normalized rather than a
    # raw price-per-bar %, same reasoning sr_lines' own diagonal-slope
    # classification uses (Done #35's `slope_atr_per_bar`). Neither figure
    # is named explicitly in the design doc; first-pass starting points.
    triangle_window_pivots: int = 6
    triangle_flat_slope_atr_mult: float = 0.05
    # duration_fit typical range -- doc's own "several weeks to a few
    # months on daily charts" (point 6), treated as a *soft* score like
    # every other duration figure here (§6's weight table lists "Duration
    # within the typical range" as one of 5 universal soft components,
    # despite point 6's "reject" wording -- same soft-vs-hard resolution
    # double top/H&S already apply to their own duration figures).
    triangle_typical_min_bars: int = 15
    triangle_typical_max_bars: int = 90

    # §4.4 Cup & Handle + Inverse. `cup_prior_trend_min_pct=30.0` is the
    # doc's own explicit figure for this pattern (vs. the generic 15%) --
    # passed directly to `trendlines.prior_trend_pct`, same precedent H&S
    # already established for its own pattern-specific threshold.
    # `cup_rim_symmetry_max_pct=5.0` -- doc's own "~0-5%" tolerance for how
    # far short of the left rim the right rim is allowed to recover (no
    # upper bound: doc explicitly says a right rim *above* the left rim is
    # fine, "often bullish"). `cup_depth_hard_min/max_pct` are outer bounds
    # around the doc's own soft 12-50% depth range (same "hard floor
    # beneath an unbounded search" reasoning as double_top_symmetry_hard_
    # gate_pct); `cup_depth_typical_min/max_pct` are the doc's literal
    # "12-33% retracement" ideal range, soft-scored (reusing `duration_
    # fit`'s own ramp shape for "ideal middle, tolerated further out,
    # floors rather than zeroes") rather than hard-gated at 33%, matching
    # the doc's own "flag as lower-confidence rather than rejecting
    # outright" wording for the 33-50% band. `cup_roundedness_min_r2` gates
    # `curves.fit_roundedness` -- the doc's own primary "rounded not
    # V-shaped" operationalization (§4.4 point 3's first approach); the
    # doc's alternative "simpler heuristic" (multiple pivots per leg, no
    # single-bar-dominance) is deliberately not built alongside it -- one
    # principled mechanism, not two. `cup_max_span_pivots` bounds the
    # left-rim/right-rim pivot search (the doc gives no explicit pivot
    # count for "possibly several pivots" forming the rounding).
    # `cup_handle_max_retrace_pct=50.0` is the doc's own outer "up to 50%
    # in choppier tape" bound for how deep the handle retraces the cup's
    # total advance -- also functions as this detector's version of the
    # invalidation section's "handle depth exceeding ~50% of cup depth ->
    # structurally broken," treated as the same figure since "advance"
    # (right rim - cup extreme) and "depth" (left rim - cup extreme) are
    # already close given the rim-symmetry gate. `cup_typical_min/max_
    # bars` approximate the doc's separate cup (1-6 months) + handle (1-4
    # weeks) durations as one combined formation-length range, soft-scored
    # like every other pattern's duration figure. All first-pass starting
    # points except the two explicitly-named doc figures (30%, 5%).
    cup_prior_trend_min_pct: float = 30.0
    cup_rim_symmetry_max_pct: float = 5.0
    cup_depth_hard_min_pct: float = 5.0
    cup_depth_hard_max_pct: float = 60.0
    cup_depth_typical_min_pct: float = 12.0
    cup_depth_typical_max_pct: float = 33.0
    cup_roundedness_min_r2: float = 0.5
    cup_max_span_pivots: int = 12
    cup_handle_max_retrace_pct: float = 50.0
    cup_typical_min_bars: int = 25
    cup_typical_max_bars: int = 150

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["scoring_weights"] = dict(self.scoring_weights)
        return d


# Bar-count knobs (currently just prior_trend_min_bars) get a weekly value
# roughly daily/5, same unvalidated first-pass scaling SRConfig.PRESETS
# uses for its own weekly presets -- calendar-time/ratio knobs (the %s,
# ATR multiples, breakout_volume_mult, expire_lifespan_mult) are shared as-
# is between daily and weekly, same reasoning SRConfig documents for why
# its own scoring/decay knobs don't get weekly variants.
PRESETS: dict[str, PatternConfig] = {
    "daily": PatternConfig(timeframe=Timeframe.DAILY, prior_trend_min_bars=20),
    "weekly": PatternConfig(timeframe=Timeframe.WEEKLY, prior_trend_min_bars=4),
}


def get_preset(name: str) -> PatternConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    preset = PRESETS[name]
    return PatternConfig(**preset.to_dict())
