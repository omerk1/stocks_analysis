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

from src.foundation.market_common.models import Timeframe


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
    # (There was a `failed_breakout_reclaim_bars` knob here -- a fixed window
    # after the breakout inside which a reclaim was treated as a failed
    # breakout. Removed rather than retuned: a reclaim is indistinguishable
    # from a throwback at the moment it happens, so the window length only
    # chose which error to make, and no value resolves that. `lifecycle.
    # _walk_post_breakout` now records the reclaim, keeps walking, and
    # decides at the end of the resolution horizon -- see its docstring.)

    # §7.3 resolution horizon: how long after a breakout the measured-move
    # target stays live before the match resolves EXPIRED_UNRESOLVED
    # instead of being left to walk to the end of available history. Without
    # this, `lifecycle._walk_post_breakout` scanned every remaining bar, so
    # HIT_TARGET meant "ever, eventually" -- one audited instance recorded a
    # hit ~2 years after its breakout, which is not comparable to any of the
    # Bulkowski-style benchmarks §7.3 measures against (those are horizons
    # of weeks to months). Expressed as a multiple of the pattern's own
    # `formation_bars`, reusing `expire_lifespan_mult`'s exact convention
    # and value rather than introducing a second, unrelated notion of "how
    # long is this pattern relevant for" -- a pattern's own duration sets
    # its timescale, pre-breakout and post-breakout alike. Clamped: the
    # floor keeps a days-long flag/pennant from getting a ~6-bar window, the
    # cap (one trading year) keeps a multi-year rounding base from getting a
    # decade.
    target_horizon_mult: float = 2.0
    target_horizon_min_bars: int = 20
    target_horizon_max_bars: int = 252

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
    # `cup_rim_divergence_max_pct=10.0` -- SYMMETRIC bound on how far the
    # right rim may sit from the left rim, in either direction. Replaces an
    # earlier one-sided `cup_rim_symmetry_max_pct=5.0` that bounded only the
    # "recovers short of the left rim" side, mirroring the doc's "a right
    # rim *above* the left rim is fine, often bullish" literally. That
    # mirror is geometrically faithful but wrong in price space, which is
    # bounded at zero going down and unbounded going up: mirrored for the
    # bearish variants it let the right rim sit arbitrarily far *below* the
    # left rim (measured: median -29.8%, min -66.0%), which is not a cup at
    # all but a rounded top followed by a bear leg. Since the measured move
    # is computed in absolute dollars from the right rim (`height =
    # |rim2 - extreme|`), that drove targets through zero -- 16.3% of
    # bearish matches had a *negative* target price, unreachable by
    # construction, and the median implied target was a -78.7% move. 10.0
    # rather than the doc's literal 5.0 because a symmetric bound still has
    # to accommodate the legitimate "right rim slightly above" case the doc
    # calls out; it is the doc's figure doubled, not a new invention.
    # Survival across five tickers: 5%->152 matches, 10%->244, 15%->338 (of
    # 999); at 5% only 22 bearish matches survive, too thin to measure.
    # A §7.4 sensitivity candidate -- sweep 8/10/12/15 against the rerun
    # baseline, don't re-guess it here.
    # `cup_depth_hard_min/max_pct` are outer bounds
    # around the doc's own soft 12-50% depth range (same "hard floor
    # beneath an unbounded search" reasoning as double_top_symmetry_hard_
    # gate_pct); `cup_depth_typical_min/max_pct` are the doc's literal
    # "12-33% retracement" ideal range, soft-scored (reusing `duration_
    # fit`'s own ramp shape for "ideal middle, tolerated further out,
    # floors rather than zeroes") rather than hard-gated at 33%, matching
    # the doc's own "flag as lower-confidence rather than rejecting
    # outright" wording for the 33-50% band.
    #
    # Roundedness is gated by FOUR checks, not one. `cup_roundedness_min_r2`
    # (§4.4 point 3's first approach) stays at 0.5 deliberately: measured
    # against six hand-audited instances, a quadratic R2 turned out to be a
    # near-useless discriminator for "rounded vs. V-shaped" -- the single
    # confirmed-VALID cup scored the *lowest* R2 of the six (0.677) while
    # four invalid ones scored higher (up to 0.879), because a monotone
    # bear leg fits a parabola arm better than a real cup does. Raising the
    # cutoff would reject the good instance first. The other three gates do
    # the work R2 cannot, and are the doc's own second approach (point 3's
    # "simpler heuristic"), which was previously left unbuilt on the
    # reasoning that one principled mechanism beat two -- that call was
    # wrong, and the two approaches turn out to be complementary rather
    # than redundant:
    #   - curvature sign: the fitted parabola must open the way the pattern
    #     requires (a > 0 for a cup/rounding bottom, a < 0 for their
    #     inverses). The R² alone is deliberately direction-agnostic, so
    #     nothing checked this before; 26% of real matches fail it. No
    #     threshold to tune -- it's a sign test.
    #   - `cup_apex_position_range`: the parabola's vertex must fall inside
    #     the rim-to-rim window, expressed as a 0-1 position across it. A
    #     monotone path puts the vertex far outside (measured: 2.159 and
    #     4.365 on two invalid instances, vs. 0.445 dead-centre on the
    #     valid one). Bounds are deliberately loose -- there is exactly one
    #     confirmed-valid example to calibrate against, and tuning tightly
    #     against n=1 would be overfitting.
    #   - `cup_max_single_bar_move_frac`: the doc's literal "no single-bar
    #     move accounts for a large fraction of the total cup depth."
    #     Catches one-day gaps posing as a cup wall (an earnings cliff at
    #     0.491 of total depth) while clearing the valid instance (0.231);
    #     population median 0.244, p75 0.340.
    # `cup_max_span_pivots` bounds the
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
    cup_rim_divergence_max_pct: float = 10.0
    cup_depth_hard_min_pct: float = 5.0
    cup_depth_hard_max_pct: float = 60.0
    cup_depth_typical_min_pct: float = 12.0
    cup_depth_typical_max_pct: float = 33.0
    cup_roundedness_min_r2: float = 0.5
    cup_apex_position_range: tuple[float, float] = (0.20, 0.80)
    cup_max_single_bar_move_frac: float = 0.35
    cup_max_span_pivots: int = 12
    cup_handle_max_retrace_pct: float = 50.0
    cup_typical_min_bars: int = 25
    cup_typical_max_bars: int = 150

    # §4.8 Rounding Bottom/Top (Phase 6) -- "cup and handle without the
    # handle," sharing every gate above (rim symmetry, depth, prior
    # trend, roundedness) except the handle-specific ones. Only its own
    # knob: a duration range operationalizing the doc's "require a longer
    # duration than a typical cup" as "at or beyond a typical cup's own
    # upper bound," soft-scored like every duration figure here despite
    # the doc's "require" wording.
    rounding_typical_min_bars: int = 150
    rounding_typical_max_bars: int = 400
    # How many bars must separate the right rim from a breakout before the
    # breakout counts. Rounding is the ONE pattern whose formation ends on
    # the same pivot that supplies its trigger level, and that level is the
    # rim's *close* while the rim itself is a wick -- so for a bar or two
    # afterwards price can re-close above the level without the swing high
    # ever being touched. Measured full-universe (5,314 tickers): 50.5% of
    # rounding bottoms and 55.2% of rounding tops "broke out" within 5 bars
    # of their own right rim, and that slice carried the entire deficit
    # (60-bar median -9.42% / -16.39%, against +0.87% / -2.02% for
    # everything else, throwback 0.84-0.87 vs 0.61-0.62 -- levels that were
    # never really cleared). Cup & Handle is structurally immune and gets
    # no gate here: its handle pushes formation end to a LATER pivot than
    # the rim, so its scan can never start adjacent to the trigger pivot
    # (13% near-rim, near slice slightly *better* than far in both
    # directions -- the opposite sign to Rounding).
    #
    # 6 is a flat bar count, picked from a full-universe sweep (2->0.85 of
    # the achievable median-return gain per pattern; 10->11 moves the
    # median +0.01 points for ~1 point of kept-n, i.e. noise past ~8). Two
    # more principled alternatives were raised and deliberately deferred,
    # not rejected:
    #   (a) scale with formation_bars, the way `resolution_horizon_bars`
    #       already does for the post-breakout time limit -- a 400-bar
    #       rounding base plausibly needs a wider settling window than a
    #       150-bar one, and a flat constant can't express that.
    #   (b) gate on price instead of time: require the breakout close to
    #       clear rim2's own wick extreme (or clear it by some buffer),
    #       using the already-measured `rim_gap_frac`/`cleared_rim_extreme`
    #       per-instance rather than a population-level bar count standing
    #       in for it.
    # Revisit if this pattern's economics matter enough to justify the
    # extra complexity; flat 6 is the simple, verified floor in the
    # meantime.
    rounding_breakout_min_gap_bars: int = 6

    # §4.5 VCP. The one pattern needing its own bar-count-scaled knobs
    # baked directly into `PatternConfig` rather than left to `PRESETS`'
    # usual "just prior_trend_min_bars differs" convention -- VCP's
    # Trend Template gate is inherently tied to specific daily-bar MA
    # windows (50/150/200-day, from the methodology itself), so its
    # weekly equivalents (10/30/40-week) need their own PRESETS overrides
    # below, not a /5 scaling of the same field.
    #
    # `vcp_pivot_atr_mult=1.0` -- finer than the shared coarse pass's 2.5
    # (§2c: "VCP wants fine-grained pivots to catch each contraction leg")
    # -- VCP is the first detector to actually need this, so it runs its
    # own `detect_pivots` call rather than using the `pivots` argument
    # `scan()` receives (see base.py's updated docstring).
    # `vcp_min/max_contractions=2/6` -- the doc's own explicit range.
    # `vcp_contraction_violations_allowed=1` -- the doc's own explicit
    # "allow one minor tolerance violation, don't require perfect
    # monotonicity." Higher-lows (point 5) gets no such tolerance in the
    # doc's own text, so that check stays strict (zero violations).
    # `vcp_atr_contraction_max_ratio=1.0` -- the doc cites "commonly ~1/3"
    # as what a *textbook* contraction looks like, and an initial 0.6
    # ceiling (already looser than that) was checked directly against
    # real AAPL history before shipping: 393 candidates cleared the
    # monotonic-depth/higher-lows gates, but their ATR(short)/ATR(long)
    # ratios clustered at a median of ~1.03 (range 0.68-1.81) -- literally
    # zero cleared 0.6, meaning the pivot-depth-based contraction checks
    # (points 4/5) don't reliably correlate with real ATR-based
    # contraction (a shrinking % retracement doesn't guarantee the bars
    # composing it are individually calmer). Raised to 1.0 -- "short-term
    # volatility no higher than the longer-term baseline," a materially
    # weaker bar than the doc's own textbook figure, but one that actually
    # admits real candidates rather than gating out every single one on
    # real data. `scoring.contraction_tightness_score` still rewards a
    # tighter ratio continuously within that ceiling, so a genuinely
    # textbook ~0.33 candidate still scores far higher than one just
    # under 1.0.
    # `vcp_sma_*_period`/`vcp_ma_rising_lookback_bars`/`vcp_pct_from_52w_
    # high_max`/`vcp_52w_high_lookback_bars` -- the doc's own Trend
    # Template checklist (§4.5 point 1); 25% off the 52-week high is a
    # commonly-cited figure associated with the methodology, not itself
    # quoted in this design doc's text -- flagged as such, not
    # doc-sourced like the 2/6 contraction range is.
    vcp_pivot_atr_mult: float = 1.0
    vcp_min_contractions: int = 2
    vcp_max_contractions: int = 6
    vcp_contraction_violations_allowed: int = 1
    vcp_atr_contraction_max_ratio: float = 1.0
    vcp_atr_short_period: int = 10
    vcp_atr_long_period: int = 50
    vcp_sma_short_period: int = 50
    vcp_sma_medium_period: int = 150
    vcp_sma_long_period: int = 200
    vcp_ma_rising_lookback_bars: int = 20
    vcp_pct_from_52w_high_max: float = 25.0
    vcp_52w_high_lookback_bars: int = 252
    vcp_typical_min_bars: int = 15
    vcp_typical_max_bars: int = 90

    # §4.7 Flags/Pennants (Phase 6, bonus). The one pattern family using a
    # *fixed* consolidation pivot count rather than a sliding range
    # (triangles' 2-6 contractions, VCP's 2-6 legs) -- the doc doesn't
    # name a variable range for flags the way it does for those, and
    # `flag_consolidation_pivots=4` is already the minimum for 2 touches
    # per boundary (§3.2's own floor), so a fixed size is the more
    # doc-faithful choice here, not a corner cut. `flag_pole_min_pct`/
    # `flag_pole_max_bars` operationalize "large % move in few bars";
    # `flag_consolidation_max_bars` is a hard ceiling (unlike every other
    # duration figure here) since "much shorter than the patterns above"
    # is closer to this pattern's own structural definition than a
    # tunable quality signal -- a consolidation that ran for months
    # wouldn't be a flag, it'd just be whatever triangle/wedge it turned
    # into, already a separate detector. `flag_max_retrace_pct=50.0` is
    # the doc's own "commonly under ~50%" figure, doing double duty as
    # both the detection-time gate and (via the same threshold) an
    # ongoing pre-breakout invalidation check, same pattern cup & handle's
    # own handle-depth figure already established. `flag_consolidation_
    # max_range_ratio` operationalizes "low-volatility relative to the
    # flagpole" as a direct amplitude ratio, no new ATR machinery needed
    # -- checked directly against real AAPL history before shipping, same
    # discipline as VCP's own calibration finding: an initial "textbook"
    # 0.5 ceiling produced zero real matches even after fixing the pivot-
    # granularity issue below -- the (small, n=4) sample of candidates
    # that passed every earlier gate had range_ratio between 0.64 and
    # 1.15, all above 0.5. Raised to 1.0 (admits 3 of those 4) -- a
    # consolidation's amplitude no larger than the pole's own height is
    # still a real, meaningful "low volatility relative to the flagpole"
    # bar, just a materially weaker one than the doc's own implicit
    # textbook picture.
    #
    # `flag_pivot_atr_mult=1.5` -- checked directly against real AAPL
    # history before shipping (same discipline as VCP's own calibration
    # finding): the scanner's shared coarse pass (2.5x ATR) has a *median*
    # gap of 11 bars between consecutive pivots, so a 4-pivot
    # consolidation window built from it spans ~35-85 bars in practice --
    # nowhere close to "much shorter than the patterns above" (point (a)
    # of §4.7's own definition), and looser than even triangles' own
    # typical range. Rather than loosen flag_consolidation_max_bars to
    # match (which would erase the thing that makes a flag a flag, not
    # just a small triangle), this is the second detector (after VCP) to
    # run its own, finer `detect_pivots` pass -- see base.py's docstring.
    # 1.5x ATR (between the shared pass's 2.5 and VCP's own 1.0) brings
    # the median gap down to 4 bars, comfortably inside the 20-bar
    # ceiling below.
    flag_pivot_atr_mult: float = 1.5
    flag_pole_min_pct: float = 15.0
    flag_pole_max_bars: int = 10
    flag_consolidation_pivots: int = 4
    flag_consolidation_max_bars: int = 20
    flag_max_retrace_pct: float = 50.0
    flag_consolidation_max_range_ratio: float = 1.0
    flag_typical_min_bars: int = 3
    flag_typical_max_bars: int = 20

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["scoring_weights"] = dict(self.scoring_weights)
        return d


# Bar-count knobs get a weekly value roughly daily/5, same unvalidated
# first-pass scaling SRConfig.PRESETS uses for its own weekly presets --
# calendar-time/ratio knobs (the %s, ATR multiples, breakout_volume_mult,
# expire_lifespan_mult) are shared as-is between daily and weekly, same
# reasoning SRConfig documents for why its own scoring/decay knobs don't
# get weekly variants. VCP's own MA-period knobs are the one exception --
# 50/150/200-*day* and ATR(10)/ATR(50) are specific, named daily-bar
# windows from the methodology itself, not a generic bar-count needing a
# blanket /5 scale, so their weekly equivalents (10/30/40-week,
# ATR(2)/ATR(10)) are set explicitly below rather than derived.
PRESETS: dict[str, PatternConfig] = {
    "daily": PatternConfig(timeframe=Timeframe.DAILY, prior_trend_min_bars=20),
    "weekly": PatternConfig(
        timeframe=Timeframe.WEEKLY, prior_trend_min_bars=4,
        vcp_sma_short_period=10, vcp_sma_medium_period=30, vcp_sma_long_period=40,
        vcp_atr_short_period=2, vcp_atr_long_period=10,
        vcp_ma_rising_lookback_bars=4, vcp_52w_high_lookback_bars=52,
    ),
}


def get_preset(name: str) -> PatternConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown preset {name!r}. Available: {sorted(PRESETS)}")
    preset = PRESETS[name]
    return PatternConfig(**preset.to_dict())
