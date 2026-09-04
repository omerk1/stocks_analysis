# Chart pattern detection design notes

Running log of decisions and findings from building `src/patterns/`, in the
same spirit as `docs/features/sr_lines_design_notes.md`. Written so none of
this has to be re-derived when Phase 2 (H&S) and beyond start. Append to
this rather than rewriting it.

## Progress / build order

The full plan (module layout, why this order, what's stubbed vs. built)
was worked out interactively before any code was written and lives here,
not just in chat history — update the checkmarks below as phases land, add
a new phase entry rather than editing an old one's description after the
fact.

- [x] **Phase 0 — shared toolkit.** `src/patterns/{models,config,base,
  trendlines,volume,scoring}.py` + `market_common/trendline_fit.py`.
  Landed in PR #39 (`docs/done.md` #48).
- [x] **Phase 1 — Double Top/Bottom, first full vertical slice.**
  `detectors/double_top_bottom.py`, `lifecycle.py` (generic state machine,
  reusable as-is), `scanner.py`, `store.py`, `cli.py`, `plotting.py`,
  `backtest/labeler.py`. Landed in PR #39 (`docs/done.md` #48).
- [x] **Phase 2 — Head & Shoulders + Inverse.** Extends double-top's
  neckline/symmetry/target logic to 5 pivots; adds head-exceeded and
  failed-breakout invalidation; adds §6.1's price+time symmetry
  cleanliness metric. `detectors/head_shoulders.py`, `scanner.py`
  registration, `plotting.py` sloped-neckline support. Landed in PR #41
  (`docs/done.md` #49).
- [x] **Phase 3 — Triangles (asc/desc/symmetric) + Wedges.** New shared
  infra: convergence/apex math in `trendlines.py`, a bidirectional
  lifecycle entry point (breakout side isn't fixed by the pattern's
  geometry, unlike H&S/double-top). `detectors/triangles.py` covers all
  five shapes in one detector, per the design doc's own module layout.
  Landed in PR #42 (`docs/done.md` #50) -- see this file's own Phase 3
  section below for the full narrative.
- [x] **Phase 4 — Cup & Handle + Inverse.** New `curves.fit_roundedness`,
  isolated and independently tested before wiring into the detector, per
  this checklist's own original note. Scoped to Cup & Handle + Inverse
  only, not Rounding -- Phase 6's own description already deferred
  Rounding until after 1-5 are validated, superseding this line's title
  (a pre-existing inconsistency in the plan, resolved in favor of the
  more detailed Phase 6 wording, not a new deviation). Landed in PR #43
  (`docs/done.md` #51) -- see this file's own Phase 4 section below for
  the full narrative.
- [x] **Phase 5 — VCP.** Most novel logic (Trend Template gate, monotonic
  contraction sequence), least standardized in the source material,
  depends on none of the trendline/quadratic infra — sequenced last among
  primary patterns. The first detector to run its own, finer `detect_
  pivots` pass rather than the scanner's shared coarse one (anticipated
  since Phase 0/1, see base.py's own updated docstring). Landed in PR #44
  (`docs/done.md` #52) -- see this file's own Phase 5 section below for
  the full narrative, including a real-data calibration finding on the
  ATR-contraction ratio gate that was fixed before merge.
- [x] **Phase 6 (bonus) — Flags/Pennants, Rounding top/bottom.** Rounding
  landed inside `detectors/cup_and_handle.py` itself, per the design doc's
  own §8 module layout, as the fallback classification when a candidate's
  handle isn't valid -- reused Phase 4's quadratic fit directly, as
  anticipated. Flags/Pennants turned out to need its own finer pivot pass
  too (the second detector after VCP), a real finding from checking
  real data before shipping, not assumed from the "cheap given zigzag
  infra" framing. Landed in PR #45 (`docs/done.md` #53) -- see this
  file's own Phase 6 section below for the full narrative.

- [x] **Phase 7 — outcome-based backtest (§7.3).** New `backtest/
  evaluator.py`: for every match that actually broke out (`breakout_bar is
  not None`, i.e. any status in `{CONFIRMED, ACTIVE, HIT_TARGET,
  INVALIDATED_FAILED_BREAKOUT}`), computes forward returns at fixed bar
  horizons plus per-pattern-type target-hit/failed-breakout/still-open
  rates. Deliberately scoped to §7.3 only, not §7.2's precision/recall --
  `pattern_labels` (the labeler's own table) has zero rows, nobody has
  actually run `backtest/labeler.py` against real charts yet, and
  precision/recall against an empty label set can't be verified against
  anything real. Landed in PR #46 (`docs/done.md` #54) -- see this file's
  own Phase 7 section below for the full narrative.

Still open, deferred deliberately (see `docs/backlog.md` for the full
reasoning, not duplicated here): §7.2's precision/recall pass (blocked on
`backtest/labeler.py`'s label set actually having rows), throwback-rate
tracking (needs the actual target-hit bar, not just final status --
`evaluator.py`'s own docstring flags this as a real gap, not silently
folded into `failed_breakout_rate`), and any threshold tuning against real
chart review (every numeric knob added so far is an unvalidated first
pass, same status every sr_lines knob started at).

To resume cold: read this section, skim "Decisions resolved..." below for
the *why* behind the architecture, then `git log --oneline -- src/patterns`
for what's actually landed vs. this checklist's claims.

## Decisions resolved against existing repo convention, not the design doc's literal text

The design doc (`chart_pattern_detection_design.md`) was written as a
standalone brief and, in a few places, proposes conventions this repo
already solved differently. Deliberately followed repo precedent instead:

- **Pivot extraction (§2) is already built.** `market_common.pivots.
  detect_pivots` + `market_common.models.Pivot`/`PivotKind` *is* the doc's
  ATR-scaled ZigZag spec. No new pivot-extraction code -- detectors take an
  already-extracted `list[Pivot]`. PIP (§2b) stays unbuilt; the trigger to
  revisit it is if triangle/wedge §6.1 cleanliness scores look
  systematically off during real-data tuning (ZigZag pivots sparse/oddly
  placed for that specific geometry), not before.
- **Config is a plain dataclass (`PatternConfig`), not the doc's `config/
  pattern_thresholds.yaml`.** Every existing detection module (SRConfig,
  GapConfig, DivergenceConfig, FibConfig) does it this way; asset-class/
  timeframe profiles are `PRESETS` dict entries (daily/weekly here, mirroring
  SRConfig's medium_term/long_term/*_weekly), not separate config files. The
  repo does have a YAML+pydantic loader (`utils/config_loader.py`), but it's
  scoped to static infra paths (`configs/config.yaml`), not per-module
  tunable thresholds -- no precedent there for detection config.
- **Storage: one `pattern_matches` table, `pattern_type` discriminator
  column** -- confirmed by reading `sr_lines/store.py` that this is exactly
  how sr_lines already handles horizontal vs. diagonal (one table, `kind`
  column, geometry columns nullable per kind). Natural key: (ticker,
  timeframe, pattern_type, formation_start, formation_end).
- **Current-state-only, not a history table.** A later run's `ON CONFLICT
  ... DO UPDATE` overwrites an earlier run's mutable fields (confidence/
  status/etc.) on the same natural key -- same as gaps/divergences/sr_lines.
  Confirmed with the user this is fine for now; a dedicated backtest
  harness (re-running `scanner.detect(as_of=X)` fresh against raw bars,
  not reading this table's history) is deferred -- see `docs/backlog.md`.
- **Overlap handling (§9)**: adopted the doc's own recommendation --
  return every detector's matches independently, never force mutual
  exclusivity. Same principle sr_lines already applies to horizontal vs.
  diagonal lines coexisting.

## `sr_lines`/`patterns` trendline-fitting: what's shared, what isn't

User pushback ("core logic sounds around the same, what am I missing?")
was fair and worth recording precisely, not just asserting "they're
different." The one truly shared primitive -- least-squares line fit,
`np.polyfit(xs, ys, 1)` -- is now `market_common.trendline_fit.fit_line`,
used by both `sr_lines.candidates._fit_diagonal_candidates` (refactored to
call it, verified via `test_sr_lines_candidates.py` staying green) and
`patterns.trendlines.fit_line` (re-exported for Phase 3's triangle/wedge
detector). Everything *around* that call differs by design and is NOT
shared:

| | sr_lines diagonals | triangle/wedge (Phase 3) |
|---|---|---|
| Pivot selection | RANSAC search over a stock's *entire* history to discover which pivots form a good line | Already known -- the pattern matcher already picked the recent N pivots |
| Outlier handling | Needed (inlier/outlier separation) | Not needed -- every pivot in the fixed window is meant to be part of the shape |
| Price space | log-price (candidate lines can span a 5x price move over years) | plain price (a triangle lives weeks-to-months) |
| Dedup | Heavy (hundreds of near-duplicate fits) | Trivial/absent |

## Phase 1: Double Top/Bottom built first, not H&S

Simplest pivot sequence (3 pivots: H-L-H or L-H-L, guaranteed by
`detect_pivots`' strict alternation -- any 3 consecutive pivots already
have the right shape), reuses neckline/measured-move logic H&S also needs.
Built specifically to prove the full vertical slice (detector -> lifecycle
-> scanner -> store -> cli -> plotting -> labeler) end-to-end before
investing in the pricier detectors. H&S (Phase 2) should be a small
extension of this, not a first-of-its-kind build.

### `has_prior_trend` bug found while writing its own synthetic tests

First implementation searched the *entire* lookback window for whichever
extreme maximized the measured move, then separately checked that extreme
was >= `min_bars` away from the pivot (intended as "reject a 2-bar spike
dressed up as a trend"). Broke on a flat-plateau-then-spike fixture: a
20%-in-2-bars spike sitting at the end of a 10-bar flat plateau passed,
because the *plateau's own start* (not the spike) was the found extreme,
and it was trivially >10 bars back. The distance check was measuring the
wrong thing -- proximity of *whichever extreme the search happened to
find*, not whether the move itself took a plausible number of bars.

Root cause of the confusion: the design doc's §3.1 wording ("≥X% over
≥N bars") doesn't actually ask for anti-spike/monotonicity filtering --
that's a separate, pattern-specific concern the doc only raises for cup &
handle's own roundedness check (§4.4: "no single-bar move accounts for a
large fraction of the total cup depth"). Fixed by simplifying
`has_prior_trend`/`prior_trend_pct` to a plain magnitude-over-available-
history check, dropping the distance-from-extreme guard entirely, and
documenting explicitly that single-bar-dominance filtering is out of scope
here. If a future pattern needs that filtering (cup & handle will, per
§4.4), it should get its own dedicated check, not a generalization of this
helper.

### Real-data smoke test (AAPL, full history, daily)

`python -m src.signals.patterns.cli AAPL --timeframe daily --plot ...` ran clean
end-to-end: 105 patterns detected, status distribution `active=3,
expired=17, hit_target=19, invalidated=41, invalidated_failed_breakout=25`
-- spread across every terminal state, nothing degenerate (e.g. everything
landing in one bucket). Spot-checked geometry directly against the derived
DB: double_top rows have `target_price < stop_price` with `entry_price`
(breakout close) sitting between them and below the neckline, as expected
for a bearish breakout; double_bottom rows mirror that correctly upward.
`SELECT COUNT(*) WHERE confidence < 0 OR confidence > 1` returned 0 across
all 105 rows. Not yet reviewed chart-by-chart for whether individual
matches *look* like real double tops to a human eye -- that's what
`backtest/labeler.py` + a real precision/recall pass (§7.2, still not
built) is for, this was only a detection-pipeline sanity check.

## Config knobs added so far, unvalidated starting points (same caveat every SRConfig knob carries)

`pivot_atr_mult=2.5`, `prior_trend_min_pct=15.0`/`min_bars=20`,
`touch_tolerance_atr_mult=0.5`/`pct=0.005`, `breakout_volume_mult=1.4`,
`breakout_buffer_pct=0.001`, `expire_lifespan_mult=2.0`,
`failed_breakout_reclaim_bars=5`, §6 `scoring_weights` (30/25/15/15/15),
`double_top_symmetry_hard_gate_pct=8.0` (a hard outer bound so an
unbounded search doesn't explode into noise -- the doc's own "~3%" figure
is treated as a *soft*-scored target via `scoring.price_symmetry`, not a
hard gate, per §6's "only true structural invariants hard-gate" principle),
`double_top_typical_min/max_bars=10/120`. None of these have been tuned
against real chart review yet -- same status every sr_lines knob started
at before its own dedicated tuning rounds.

## Phase 2: Head & Shoulders + Inverse

Built as a close sibling of Phase 1's double top/bottom, not a fresh
design -- same sliding-window-over-strictly-alternating-pivots structure
(5 pivots instead of 3), same `lifecycle.py` state machine reused
completely unchanged, same score-component shape. The two genuinely new
pieces:

- **Sloped neckline.** Double top/bottom's neckline is a single trough
  point (trivially flat). H&S's neckline is fit (`trendlines.fit_line`,
  2 points -> exact line) through T1/T2, and can be sloped. `lifecycle.py`
  already accepted a `trigger_at(bar_index) -> float` callable rather than
  a flat constant specifically so this would need zero changes there --
  confirmed true, only the detector and `plotting.py` needed work.
- **Target computed at formation-end, not at breakout.** The design doc's
  literal formula is `neckline_price_at_breakout - head_height`, but
  `apply_lifecycle` needs one fixed `target_price` float *before* it walks
  forward to discover where the breakout even happens -- a constraint
  double top/bottom's flat neckline never surfaces, since "neckline at
  breakout" and "neckline at formation end" are the same number there by
  construction. Resolved by using the neckline's own value at the right
  shoulder's bar index as the stand-in for "neckline at breakout" -- a
  documented approximation, not the literal doc formula. Worth revisiting
  if real-data review shows this drifts meaningfully from the neckline's
  actual value at the real breakout bar (a steep-but-still-under-cap
  neckline slope over a long PENDING window is the scenario where this
  approximation would drift most).
- **Hard gates added, beyond double top/bottom's single symmetry gate:**
  `head_exceeds_shoulders` (strict -- also covers the doc's separate
  "right shoulder above head -> reject" case, since if RS > head then
  head > RS already fails), `head_shoulders_min_leg_bars=5` (doc's literal
  "each leg >= 5 trading days"), and a new
  `head_shoulders_neckline_max_slope_pct=10.0` gate (doc says "cap slope...
  reject if... >X% change" without naming X -- picked 10% as a first-pass
  figure, unvalidated like every other knob here). `stop_price` is set to
  the head itself, the same level `pre_breakout_invalidated_at` treats as
  the structural invalidation line -- unlike double top/bottom, where stop
  is `max/min(p1, p2)` since there's no third, more-extreme point to use.
- **§6.1 price+time symmetry**, per the doc's own explicit H&S formulas
  (`scoring.hs_price_symmetry`/`hs_time_symmetry`) -- distinct from double
  top/bottom's `price_symmetry` (normalized by `avg(a,b)`; H&S's own is
  normalized by head height, per §6.1's literal wording). Blended 50/50
  into `geometric_cleanliness`, replacing double top/bottom's price-only
  version (no second symmetric axis exists with only 3 pivots).
- **`plotting.py` generalized**, not H&S-specific-cased: `PatternMatch`
  already had a `trendlines` field (§5's data model) double top/bottom
  never populated. Now `render_pattern_chart` draws from
  `match.trendlines["neckline"]` (two endpoints off the fitted line,
  exact since it's linear) when present, falling back to the old flat
  `key_levels["neckline"]` line for patterns that don't set it -- covers
  triangle/wedge boundaries in later phases for free, no further plotting
  changes anticipated there.

### Real-data smoke test (AAPL, full history, daily)

`python -m src.signals.patterns.cli AAPL --timeframe daily --plot ...` with both
detectors registered: 118 patterns total (105 double top/bottom, unchanged
from Phase 1, + 13 new: 8 head_and_shoulders, 5
inverse_head_and_shoulders), status distribution spread across every
terminal state (`active`, `expired`, `hit_target`, `invalidated`,
`invalidated_failed_breakout`), nothing degenerate. Spot-checked H&S
geometry directly in the derived DB: every `head_and_shoulders` row has
`head > left_shoulder` and `head > right_shoulder`, `target_price <
stop_price(=head)`, and (when present) `entry_price` between them; every
`inverse_head_and_shoulders` row mirrors correctly upward (`head` is the
dominant lowest low, `target_price > stop_price`). `confidence` in [0, 1]
for all rows. Same caveat as Phase 1's own smoke test: this confirms the
detection *pipeline*, not yet whether individual matches look like real
head-and-shoulders to a human eye -- that's `backtest/labeler.py` +
§7.2's still-unbuilt precision/recall pass.

## Phase 3: Triangles (ascending/descending/symmetric) + Wedges

The one genuinely new architectural problem this phase introduces, not
present in Phase 1/2: **a triangle's breakout side isn't fixed by the
pattern's own geometry.** Double top/bottom is always bearish (breaks the
trough) or always bullish (breaks the peak); H&S is always bearish (breaks
the neckline down) or always bullish (inverse, up). A triangle confirms on
a close beyond *either* boundary -- direction is only known once it
happens, and per §4.3's own explicit wording for ascending/descending
("note whether breakout direction matches the pattern's directional
bias... still tag it, don't discard"), the "wrong-side" break is a real,
valid outcome that must be recorded, not rejected. `apply_lifecycle`
(Phase 1/2) can't express this at all -- it takes one fixed
`match.direction` and one `trigger_at` callable, decided by the caller
before the walk even starts.

Resolved with two coordinated additions rather than bolting something
awkward onto the existing function:

- **`Direction.NEUTRAL`** added to `market_common.models.Direction` (the
  shared enum `gaps`/`divergences` also use). A still-forming symmetric
  triangle genuinely has no directional bias -- `NEUTRAL` is its initial
  `PatternMatch.direction` until a real breakout resolves it one way or
  the other. Checked this was safe first: grepped every `gaps`/
  `divergences` use of `Direction` and confirmed neither ever constructs
  anything but `BULLISH`/`BEARISH`, so the addition is purely additive for
  both -- zero behavior change. `patterns.plotting`'s own
  `_DIRECTION_RGB` dict needed a `NEUTRAL` entry (neutral gray) to avoid a
  `KeyError` on a still-PENDING symmetric triangle.
- **`lifecycle.apply_lifecycle_bidirectional`**, a second entry point
  alongside `apply_lifecycle`. Refactored the post-breakout half of the
  original function out into a shared `_walk_post_breakout` first (target-
  hit / failed-breakout-reclaim / active resolution is identical either
  way) -- both entry points call it, so there's exactly one copy of that
  logic, not two drifting in parallel. The bidirectional version watches
  `upper_trigger_at`/`lower_trigger_at` each bar; whichever breaks first
  sets `match.direction`/`target_price`/`stop_price` to that side's
  pre-computed values (both sides' targets/stops are computed once at
  detection time, before either is known to be "the" real one -- possible
  because `PatternMatch.target_price`/`stop_price` are already `Optional`
  in the §5 data model, so a still-PENDING/unresolved match legitimately
  has both as `None` with no dataclass change needed). Verified the
  refactor changed nothing for Phase 1/2: reran their full test suites
  immediately after, before writing a single line of triangle code.
- Also added an optional `pending_deadline_bar_index` override to both
  entry points. §4.3 expires a triangle that reaches its apex without
  breaking out, on top of the standard `expire_lifespan_mult *
  formation_bars` deadline every pattern already has -- computed as
  `min(standard_deadline, apex_bar)` in the detector and passed straight
  through, no new expiry logic needed in `lifecycle.py` itself. Verified
  directly (both a dedicated `apply_lifecycle_bidirectional` unit test and
  a full detector-level test) that this actually fires *before* the
  standard 2x-formation deadline would have, not just that EXPIRED is
  reachable at all.

### Convergence/apex math (`trendlines.py`)

`convergence_apex_bar(upper_slope, upper_intercept, lower_slope,
lower_intercept)` solves where the two fitted boundaries intersect.
Noticed while writing it that the design doc's own "check `range_at_start
> range_at_end`" wording is redundant once both boundaries are linear:
`range(i) = upper_at(i) - lower_at(i)` is itself linear in `i`, so it's
strictly monotonic (or constant, if parallel) for *any* two points, not
just start/end -- `upper_slope < lower_slope` is the single condition
under which range shrinks as `i` increases, full stop. One comparison
replaces two evaluations. `r_squared(xs, ys, slope, intercept)` is the
§6.1 "trendline fit" cleanliness metric H&S's 2-point neckline never
needed (trivially 1.0 with only 2 points) -- now genuinely differentiates
with a triangle boundary's 3+ points.

### A metric that would have always scored 1.0 -- caught before shipping

First pass at §6.1's "how monotonically the range narrows leg-over-leg"
cleanliness metric evaluated the *fitted* boundary lines' own range at
each pivot's bar index. Since range between two linear boundaries is
itself perfectly linear (see above), and the convergence hard gate
already requires `upper_slope < lower_slope`, this would have scored
`1.0` for literally every triangle that passed the hard gate -- a
completely non-differentiating metric shipped as if it were real signal.
Caught during design, before writing the test that would have "confirmed"
it. Fixed by computing `range_monotonicity_score` off the **raw pivot-to-
pivot price legs** instead (`abs(window[k+1].price - window[k].price)`,
same idea as VCP's own §4.5 contraction-leg definition) -- real, noisy
zigzag data, not the smoothed regression fit, so it actually varies
per-candidate. `apex_proximity_score` (the other half of `§6.1`'s
convergence-quality addition, how close the window's last pivot sits to
the apex) has no equivalent degeneracy risk -- kept as originally
designed.

### Classification + gating order

One detector (`TriangleWedgeDetector`) covers all 5 shapes, per the
design doc's own module layout ("triangles.py -- ascending/descending/
symmetric + wedges, shared trendline logic"). Pivot window: the design
doc's "most recent 5-6 pivots" naturally generalizes to a full sliding
window (`config.triangle_window_pivots=6`, even so the 3/3 high/low split
is always balanced) across the *entire* pivot history when scanning full
history, same as Phase 1/2 already do with their own "N most recent"
framing.

Gate order, cheapest/most-structural first: (1) enough highs/lows on each
side for `min_touches_per_line` (reuses the existing generic §3.2 knob,
no new one needed -- the doc's own "2 per line, 4 total" hard floor); (2)
convergence (`upper_slope < lower_slope`, a true structural invariant per
§6); (3) shape classification via ATR-normalized slope vs.
`triangle_flat_slope_atr_mult` (same ATR-normalization reasoning as
sr_lines' own `slope_atr_per_bar`, Done #35) -- unclassifiable slope
combinations (e.g. upper rising with lower flat) are rejected here, though
in practice most of them already fail gate (2) first; (4) apex ahead of
the window's own last pivot, not already stale; (5) a real bar-by-bar
touch count (not just the defining pivots) against `min_touches_per_line`
again, now over the whole formation window. No prior-trend hard gate --
§4.3 doesn't cite one the way H&S/cup&handle cite §3.1 -- but it's still
*measured* as a soft scoring input (§6's universal weight table), taken as
whichever of up/down shows the larger prior move, since a triangle's own
eventual breakout direction isn't known at measurement time.

No hard pre-breakout invalidation condition beyond apex-expiry is
documented for this pattern family (§4.3's "wick-only trendline violation"
is explicitly soft/scored, not modeled in this first pass -- same kind of
deliberate deferral as Phase 0's PIP or the config-YAML decision).
`pre_breakout_invalidated_at` is a hard-coded `False` for every triangle/
wedge candidate.

### Target/stop, and why triangle stops point at the opposite boundary

Same constraint Phase 2 already hit with H&S's sloped neckline, doubled:
`upper_target`/`lower_target` are both computed once at detection time
using the window's own last-pivot boundary values (not "at breakout,"
unknown yet) plus the pattern's height at its widest point (the window's
first pivot, per §3.6's "widest point" convention -- always the leftmost
point here since range is provably monotonic once the convergence gate
passes). No doc-specified stop convention for triangles (unlike double
top's `max/min(p1,p2)`) -- `upper_stop`/`lower_stop` are each set to the
*opposite* boundary's own value at the window's end, our own reasonable
default: a break up that later falls back through the (still-live) lower
support has failed on its own terms, and vice versa.

### Apex-deadline off-by-one, caught in code review before merge

`pending_deadline`'s apex half used `int(apex_bar)` (floor) to turn the
fractional apex bar into a whole-bar deadline. A code review caught that
this silently discards a legitimate breakout whenever the true apex lands
inside the very first bar past the window's end (e.g. `apex_bar=34.5`,
`window_end_i=34`): flooring gives `pending_deadline=34`, and the walk's
first loop iteration is `i=35` -- `35 > 34` fires immediately, EXPIRED,
before that bar's actual close is ever checked. Reproduced directly
(swapped `ceil` back to `int` in a scratch run against a hand-built
fixture with exactly this apex, confirmed EXPIRED/`breakout_bar=None`
under the old code vs. a real resolved breakout under the fix) before
trusting the fix. Switching to `math.ceil` fixed the discard but
introduced a second, more subtle bug on the very same fixture: a
genuinely-should-be-exact apex (a perfectly flat/linear synthetic
triangle, `apex_bar` mathematically exactly `44.0`) came back as
`44.00000000000008` from `np.polyfit`'s own floating-point noise --
ceiling that *raw* overcorrects to `45`, granting a bar of "room" that
was never really there and silently changing the existing apex-deadline
test's expected outcome. Fixed by rounding to 6dp before ceiling
(`math.ceil(round(apex_bar, 6))`) -- eliminates float noise at that scale
while still preserving a genuinely fractional apex like `34.5`. Both
scenarios are now permanent regression tests (`test_expired_at_apex_
deadline_not_standard_deadline` for the original case,
`test_fractional_apex_still_gives_the_next_bar_a_real_breakout_chance`
for the off-by-one).

### Real-data smoke test (AAPL, full history, daily + weekly)

Daily, all three detectors registered: 226 total patterns (118 unchanged
from Phase 1/2 + 108 new triangle/wedge matches: 56 rising_wedge, 17
ascending_triangle, 14 descending_triangle, 14 falling_wedge, 7
symmetric_triangle), spread across every terminal status. The one thing
specifically worth checking for this phase -- bidirectional resolution
actually producing *both* outcomes for a biased shape, not just the
expected one -- confirmed directly: `ascending_triangle` shows both
`bullish` (6 hit_target + 3 failed-breakout) *and* `bearish` (4 hit_target
+ 2 failed-breakout + 2 active) rows; same true-both-ways pattern for
`descending_triangle`, `rising_wedge`, `falling_wedge`, and
`symmetric_triangle`. Zero rows persisted with `direction='neutral'`
(every symmetric triangle in AAPL's real history had already resolved one
way or the other by the run's cutoff -- expected given the long history,
not a gap). `target_price`/`stop_price` correctly ordered on the right
side of `direction` for all 108 resolved rows (0 failures on a query
checking exactly that), 0 out-of-range confidence values. Weekly run
(49 patterns) additionally surfaced a real EXPIRED row -- not a
triangle/wedge in this particular run (a double_top), so the apex-based
expiry path's real-data exercise so far comes from the unit tests, not
this smoke test; not a gap, just what the current data happened to
produce.

## Phase 4: Cup & Handle + Inverse

### Scope: Cup & Handle + Inverse only, not Rounding

This checklist's own Phase 4 title says "+ Rounding," but Phase 6's own
entry independently says Rounding is a bonus pattern deferred "only after
1-5 are validated" and "nearly free off Phase 4's quadratic fit" -- the
plan contradicts itself on when Rounding lands. Resolved in favor of
Phase 6's more detailed wording: built Cup & Handle + Inverse only here,
leaving Rounding as a genuinely cheap follow-up once `curves.
fit_roundedness` has a second real caller to prove it's actually generic
(right now it's only ever been exercised by one detector).

### No fixed pivot count, unlike every prior pattern

Double top (3 pivots), H&S (5), triangles (6 by config) all scan a
*fixed-size* sliding window. Cup & handle's own pivot sequence (§4.4)
explicitly can't be: "LOW(cup bottom, *possibly several pivots* forming
the rounding)" -- the rounding phase might be one clean pivot or a dozen,
depending on how choppy the base is. Resolved by decoupling the two
concerns the fixed-window patterns conflate: the *pivots* only anchor
three fixed points (left rim, right rim, handle), scanned as
`(rim1_index, rim2_index)` pairs bounded by `config.cup_max_span_pivots`
(the handle is always the very next pivot after rim2, guaranteed by
`detect_pivots`' strict alternation); the *roundedness* is checked
against the **raw close-price path** between the rims
(`curves.fit_roundedness`), independent of how many pivots happen to fall
inside that span. `match.pivots` still stores every intermediate pivot in
the window (`pivots[i:j+2]`) for an accurate polyline, even though only
three of them (rim1, rim2, handle) drive any actual geometry/gating.

### No approximation needed for target -- the trigger level is genuinely flat

H&S's sloped neckline and a triangle's two moving boundaries both forced
an explicit "value at formation end, not literal breakout" approximation
for `target_price` (documented in both of those phases' own sections).
Cup & handle's trigger level (`right_rim.price`) never moves -- it's the
same flat number at formation time and at the real breakout bar, the same
way double top/bottom's flat neckline already was. So `target = rim2.price
+ (rim2.price - cup_extreme)` is the design doc's literal §3.6 formula,
not an approximation of it. Deliberately anchored the height calculation
to `rim2` rather than `rim1` (the doc says "cup_high - cup_low" without
specifying which rim) so the trigger level and the height share one
reference point, not two independently-symmetric-but-not-identical rim
values.

### Roundedness alone doesn't distinguish a real cup from a plain V

Checked this directly before trusting the R² gate as the sole roundedness
mechanism: a plain, symmetric V-shape (equal-length straight decline then
straight recovery, same width/depth as a realistic cup) scores R²≈0.94
against a parabola -- comfortably above the default `cup_roundedness_
min_r2=0.5` floor, meaning the R² test alone would **not** reject an
obviously-sharp V. This matches the design doc's own framing (R² is
offered as one of "two practical approaches," not a claimed-perfect
discriminator) -- not a bug, but worth recording so a future reviewer
doesn't assume R² alone rules out V-shapes. The doc's alternative
"simpler heuristic" (multiple pivots per leg, no single-bar-dominance) was
deliberately not built alongside it, per the progress tracker's own
framing of `fit_roundedness` as *the* primitive to isolate -- one
principled mechanism, not two redundant ones. `min_r2=0.5` still does
real work: it catches genuinely degenerate/angular cases (a single-bar
spike straight to the bottom and back scores R²≈0.03), just not a
smooth-but-still-technically-sharp V. Revisit if real chart review shows
V-shaped false positives are common enough to matter.

### `plotting.py`'s neckline fallback assumed a fixed 3-pivot list -- caught by code review

`render_pattern_chart`'s `key_levels["neckline"]` fallback branch (used by
any pattern with no `trendlines` entry -- double top/bottom and now cup &
handle) started the drawn trigger line at `match.pivots[1]`. That's
correct for double top/bottom's fixed `[p1, trough, p2]` list (index 1 is
the trough, the pivot that actually set the neckline price) but wrong for
cup & handle's variable-length `[rim1, ..., rim2, handle]` list, where
index 1 is just whatever pivot happens to follow the left rim -- the cup's
own bottom in the shipped test fixture, not the right rim that actually
set the trigger level. The chart would have drawn the flat trigger line
starting from partway down the cup's decline leg instead of from the
right rim. The real invariant both patterns share is "second-to-last
pivot," not "index 1" -- they only coincide for double top/bottom because
its list happens to be exactly 3 long. Fixed (`pivot_x[1]` ->
`pivot_x[-2]`) and covered by a permanent regression test in `tests/
test_patterns_plotting.py`, confirmed to fail against the pre-fix code
before trusting it.

### Real-data smoke test (AAPL, full history, daily)

`python -m src.signals.patterns.cli AAPL --timeframe daily --plot ...` with all
four detectors registered: 299 total patterns (226 unchanged from Phase
1-3 + 73 new: 72 cup_and_handle, 1 inverse_cup_and_handle). The
72-vs-1 skew makes sense given AAPL's own history -- inverse cup & handle
requires a qualifying ≥30% *downtrend* into the left rim (§4.4's own
figure, distinct from the generic 15%), materially rarer across a
predominantly-uptrending mega-cap's full history than the ≥30% uptrend
the regular pattern needs. Spot-checked geometry directly in the derived
DB: 0 rows where `target_price`/`stop_price` land on the wrong side of
`direction`, `cup_extreme < left_rim`/`cup_extreme < right_rim` and
`handle` sitting between them (upper half) held on every sampled row, 0
out-of-range confidence values.

## Phase 5: VCP

### Its own, finer pivot pass -- the exception Phase 0/1 already anticipated

Every prior detector consumed the `pivots` argument `scan()` receives (the
scanner's one shared, coarse pass) unchanged. VCP is the first to ignore
it and call `detect_pivots` itself with `config.vcp_pivot_atr_mult=1.0`
(vs. the shared pass's 2.5) -- §2c explicitly calls for finer pivots here
to catch each individual contraction leg, and Phase 0/1's own design notes
already flagged this as the trigger for eventually building per-detector
granularity ("the fuller design wants different pivot granularity per
pattern... Phase 1's single detector doesn't need that yet... per-detector
granularity is a later-phase concern"). `base.py`'s `PatternDetector.scan`
docstring updated to document VCP as the exception, since it previously
stated flatly that "detectors never call detect_pivots themselves" --
keeping that claim accurate mattered more than leaving it alone.

### Trend Template as the prior-trend qualifier, not a separate check

§4.5 point 1 groups "require a prior uptrend" and "a Trend Template gate"
into one requirement, calling the pairing "closely tied to Minervini's
methodology." Treated literally: no separate `has_prior_trend` call the
way H&S/cup & handle each pass their own threshold to it. Price sitting
above rising 150/200-day MAs, with the 50-day MA stacked above both, near
its own 52-week high, already *is* the doc's own more specific stand-in
for "prior uptrend" here -- adding a redundant generic check on top would
just be re-testing a weaker version of the same thing.

### A straight linear ramp satisfies every Trend Template condition for free

Worth recording since it made the whole test suite tractable: on
perfectly linear price data, `SMA(N)` at bar `i` is just the price `N/2`
bars back (the average of an arithmetic sequence is its midpoint). For a
monotonically rising ramp, that means `SMA50 > SMA150 > SMA200` and both
the medium/long MAs "rising" over any lookback fall out automatically,
with zero risk of an off-by-one in constructing a fixture by hand -- no
need to hand-tune a specific shape the way, say, cup & handle's roundedness
check required. Every synthetic test fixture here uses a plain ramp as its
"already in a Stage-2 uptrend" prefix for exactly this reason.

### A real calibration finding, checked before shipping, not assumed away

Initial `vcp_atr_contraction_max_ratio` was 0.6 (already looser than the
doc's own "commonly cited ~1/3" figure for a textbook contraction). The
real-AAPL smoke test came back with **zero** VCP matches -- not a
plausible "this pattern is just rare" outcome by itself, so traced it
before accepting it: instrumented the gate funnel directly against AAPL's
real daily history. 2,458 bars passed the Trend Template gate and 393
candidates cleared both the monotonic-depth and higher-lows checks, but
every one of their `ATR(short)/ATR(long)` ratios sat between 0.68 and
1.81 (median ~1.03) -- literally none cleared 0.6. The real finding: a
shrinking *percentage* retracement (what points 4/5 check, off the pivot
prices) doesn't reliably predict a shrinking *ATR* (what point 7 checks,
off the bars' own true ranges) -- a leg can retrace a smaller % of price
while still being individually choppy. Raised the ceiling to 1.0 ("recent
volatility no higher than the longer-term baseline" -- a materially
weaker bar than the doc's textbook figure, but one that actually admits
real candidates) and re-verified: 167 real VCP matches on AAPL daily, 24
on weekly (confirming the weekly `PRESETS` overrides -- 10/30/40-week MAs,
ATR(2)/ATR(10) -- work too), spread across every terminal status.
`scoring.contraction_tightness_score` still rewards a tighter ratio
continuously within the new ceiling, so a genuinely textbook ~0.33
candidate still scores far higher than one just under 1.0 -- only the
hard gate moved, not what counts as "clean."

### Real-data smoke test (AAPL, full history, daily + weekly)

`python -m src.signals.patterns.cli AAPL --timeframe daily --plot ...` with all
five detectors registered: 466 total daily patterns (299 unchanged from
Phase 1-4 + 167 new VCP), spread across every terminal status
(`active=21, expired=22, hit_target=210, invalidated=76, invalidated_
failed_breakout=137`). Spot-checked geometry directly in the derived DB:
0 rows where `target_price <= stop_price` (every VCP match is bullish, so
this should never happen), several sampled rows show exactly one
non-shrinking contraction-depth pair -- confirmed this is the doc's own
explicit one-violation tolerance working as intended (§4.5 point 4), not
a bug, before treating it as expected rather than alarming. Weekly run:
107 total patterns including 24 VCP, confirming the weekly-preset MA/ATR
periods actually fire on real data, not just in unit tests. 0 out-of-range
confidence values in either run.

## Phase 6 (bonus): Flags/Pennants + Rounding

### Rounding: the fallback classification, not a second scan

§4.8 frames Rounding as "cup and handle without the handle," and §8's own
module layout says it lives in `cup_and_handle.py`, not a separate file --
followed both literally. Rather than running the rim-scan loop twice
(once requiring a handle, once not, producing two independent, often
near-duplicate matches for the same base), refactored the existing
detector to check every shared gate (rim symmetry, depth, prior trend,
roundedness -- computed once, since both outcomes need the same three
values) and only *afterward* decide: a valid handle right after rim2
produces a Cup & Handle match, no valid handle (including rim2 sitting at
the very end of the pivot list, i.e. no handle pivot at all) produces a
Rounding match instead, scored against a longer typical-duration range.
This is a genuine refactor of already-merged, already-tested Phase 4
code, not a bolt-on -- caught two of Phase 4's own existing tests that
needed updating (`test_handle_below_cup_midpoint_rejects_candidate` and
the retrace-gate equivalent both asserted "no match at all" for an
invalid handle; the correct new assertion is "falls through to Rounding
instead"), confirmed each rewritten test would have failed against the
old code before locking in the new expectation.

A second, more subtle regression from the same refactor was caught by
code review before merge: `plotting.py`'s `key_levels["neckline"]`
fallback branch (fixed in Phase 4, `docs/done.md` #51, to use
`pivots[-2]` after `pivots[1]` broke for cup & handle's variable-length
list) assumed "second-to-last" was the universal invariant for the
neckline pivot -- true for double top/bottom's trough and cup & handle's
right rim (both followed by one more pivot: `p2`/`handle`), but false for
Rounding, whose window ends *at* the right rim with nothing after it, so
it lands at index -1, not -2. The same class of bug the -2 fix itself
was written to replace, reintroduced by the very phase that added the
first pattern type without a trailing pivot. Fixed properly this time,
not with another guessed index: locate the actual neckline pivot by
*price* instead of position (every detector sets `key_levels["neckline"]`
from a pivot object that's also literally in `match.pivots`, so it's an
exact float match, not a fragile recomputed comparison), searched from
the end of the list since an earlier pivot can legitimately share the
same exact price (a cup/rounding's rim1 and rim2, gated to be close, are
sometimes exactly equal -- confirmed this collision for real in the
existing shared test fixture, which is exactly why the fix searches
backward, not forward). Covered by a new regression test, confirmed to
fail against the pre-fix code first, same as the original -2 fix's own
regression test.

### Flags/Pennants: the second detector to need its own finer pivot pass

Initially built against the scanner's shared coarse pivot pass, on the
strength of §4.7's own "cheap given zigzag infra" framing -- assumed this
meant "no new pivot-extraction work needed," not "works with whatever
granularity happens to already exist." The real-AAPL smoke test came back
with **zero** flag/pennant matches, the same kind of result VCP's own
Phase 5 taught not to accept at face value. Traced it the same way:
the coarse pass's *median* gap between consecutive pivots is 11 bars, so
a 4-pivot consolidation window built from it spans ~35-85 bars in
practice -- nowhere near "much shorter than the patterns above" (§4.7's
own defining trait), and looser than even triangles' own typical range.
Loosening `flag_consolidation_max_bars` to match would have erased the
one thing that makes a flag a flag rather than just a small triangle, so
instead this became the second detector (after VCP) to run its own,
finer `detect_pivots` pass (`flag_pivot_atr_mult=1.5`, between the shared
pass's 2.5 and VCP's own 1.0 -- checked directly: brings the median gap
down to 4 bars). `base.py`'s own docstring updated again to describe two
exceptions instead of one.

Fixing the pivot granularity wasn't the whole story -- re-running against
real AAPL still returned zero matches, now bottlenecked entirely on
`flag_consolidation_max_range_ratio` (an initial "textbook" 0.5 ceiling on
how large the consolidation's own amplitude could be relative to the
pole). The small sample of real candidates that cleared every earlier
gate had ratios between 0.64 and 1.15 -- none under 0.5. Same finding, same
fix pattern as VCP's own ATR-contraction ratio: raised to 1.0, re-verified
real matches on both timeframes. Two independent "checked before shipping,
found the textbook figure doesn't survive contact with real data" findings
in one detector -- worth noting as a pattern of its own: a first-pass
threshold literally quoted from or closely modeled on the design doc's own
"textbook" language (§4.5's "~1/3," §4.7's implicit "tight" consolidation)
has now needed real-data loosening in both of the two detectors built
against such a figure, while thresholds this project derived from other
detectors' own established conventions (rim symmetry, handle retrace,
etc.) haven't shown the same pattern yet.

### Pivot-confirmation mechanics that made synthetic fixtures genuinely hard to build

Building test fixtures for a detector with its own internal `detect_pivots`
call (VCP, and now this one) means the fixture is a real price path whose
*own* zigzag output has to happen to match the intended pole+consolidation
shape -- unlike every hand-built-pivot-list detector's tests, there's no
way to just assert the pivots directly. Two mechanics fought the first few
attempts at this, both worth recording since they'll recur for any future
detector needing its own pivot pass:

1. A pivot's confirmation threshold uses ATR *at that pivot's own bar
   index*, not the current scanning position or a decaying value. Right at
   a sharp pole's peak, that ATR is itself elevated by the pole's own huge
   bars -- so the pole's peak needs a *proportionally large* reversal to
   confirm as a pivot at all, and a flat (zero-true-range) lead-in before
   the pole never confirms a starting LOW pivot, since it never reverses
   anything. Fixed by giving the pole a real prior downtrend to rise out
   of, not a flat plateau.
2. A consolidation pivot only confirms once a *later* bar reverses far
   enough away from it. The bull-flag fixture's 4th consolidation pivot
   needed a 5th price point purely to supply that confirming reversal --
   that 5th point is therefore part of the *fixed* shared prefix every
   lifecycle-variant test reuses, not a "tail" bar appended per test. A
   first attempt at reusing "the same prefix, different tails" without
   accounting for this produced a consolidation pivot that silently failed
   to confirm at all under some tails (the tail's own first value, being
   higher than the intended 4th pivot, just extended the still-open
   candidate instead of confirming it) -- caught by comparing actual
   detector output against hand-derived expectations before trusting any
   of these fixtures, the same discipline applied throughout every prior
   phase.

### Real-data smoke test (AAPL, full history, daily + weekly)

Daily, all six detectors registered: 516 total patterns (466 unchanged
from Phase 1-5 + 50 new: 46 rounding_bottom, 1 rounding_top, 1 bull_flag,
1 bear_flag, 1 pennant). The rounding/flag skew mirrors what's already
been seen for other direction-asymmetric patterns here (e.g. cup & handle
Phase 4's own 72-vs-1 skew) -- AAPL's predominantly-uptrending history
naturally produces far more bullish continuation/basing setups than
bearish ones, and flags/pennants' own tight structural gates (a fast,
large pole *and* a genuinely tight follow-on consolidation) are
inherently rare even before that skew. Spot-checked geometry directly in
the derived DB: 0 rows with `target_price`/`stop_price` on the wrong side
of `direction` across rounding and flags/pennants combined, 0
out-of-range confidence values. Weekly run: 131 total patterns (up from
107 pre-Phase-6), confirming both new pattern families fire on both
timeframes, not just daily.

## Phase 7: outcome-based backtest (§7.3)

All six pattern families from the design doc's §4 are now landed (Phases
1-6) -- there's no further detector phase in the plan. The design doc's
own §7 validation methodology has two halves that were both deferred
until "enough labeled data / detectors exist to make backtesting
worthwhile" (`docs/backlog.md`): §7.2 precision/recall against a hand-
labeled ground-truth set, and §7.3 an outcome-based backtest (forward
returns, target-hit rate, failure rate) measured against real subsequent
price action. Only §7.3 turned out to be buildable now -- checked `data/
derived/analysis.sqlite`'s `pattern_labels` table directly before
starting: zero rows. `backtest/labeler.py` (Phase 1) is human-in-the-loop
and nobody has actually run it against real charts since it landed, so
there's no ground truth to compute precision/recall against, and nothing
in this module ships a metric it can't check against something real.
§7.3 needs no labels at all -- just real historical price data, which
already exists -- so that's the whole scope of this phase.

**The backtest/evaluator harness turned out to need no new re-run
infrastructure.** `docs/backlog.md`'s original framing was that
`pattern_matches` is current-state-only (`ON CONFLICT ... DO UPDATE`
overwrites an earlier run's `status` on the same natural key), so
"what did detection believe on day D" can't be reconstructed after day
D+5's rerun -- implying a dedicated harness that re-runs `scanner.detect(
as_of=X)` per historical date would be needed. That gap is real, but only
matters for §7.2 (auditing a specific past belief against a label made at
that date) -- not for §7.3. `lifecycle.apply_lifecycle`'s post-breakout
walk (`_walk_post_breakout`) already resolves a match's *final* status by
walking forward through every bar visible to it at scan time; scanning
with the full available history (`scan_bars` with no `as_of` truncation,
unlike `scanner.detect`'s point-in-time mode) makes that final status
*already* the realized, real-world outcome -- HIT_TARGET/
INVALIDATED_FAILED_BREAKOUT are genuine terminal states, not detector
guesses. New `backtest/evaluator.py` therefore just re-scans full history
per ticker directly (deliberately not reading `pattern_matches` itself,
since that table may reflect a different `as_of`/config than what's being
backtested) and reads off `match.status`/`match.breakout_bar`/
`match.entry_price` -- no new lifecycle logic, no new persistence.

**Scope boundary: `breakout_bar is not None` is the exact predicate for
"had an outcome to measure."** `match.breakout_bar` is only ever set
inside `lifecycle._walk_post_breakout`, which only runs once a breakout
has actually been found -- confirmed by reading `apply_lifecycle`/
`apply_lifecycle_bidirectional` directly rather than assumed: every path
that reaches PENDING/INVALIDATED/EXPIRED returns *before* calling
`_walk_post_breakout`, so those three statuses always carry
`breakout_bar=None` and the other four (CONFIRMED/ACTIVE/HIT_TARGET/
INVALIDATED_FAILED_BREAKOUT) always carry a real one. `compute_outcomes`
uses exactly this set as its filter -- a pattern that never triggered has
no trade to measure and is skipped entirely, not scored as a zero/failed
outcome (that would conflate "never happened" with "happened and lost").

**Forward-return sign convention.** `forward_return_pct` reports the
*trade's* return, not the raw price return: a BEARISH match (short) is
profitable when price falls, so its raw `(close - entry) / entry` is
negated before reporting. Verified with a hand-built step fixture (flat
at 100.0 through the breakout bar, then a flat 90.0 for every later bar)
rather than trusted by inspection -- a bearish match on that fixture
reports `+0.10`, a bullish one `-0.10`, both asserted directly in
`tests/test_patterns_evaluator.py`.

**Right-censoring, not zero-filling.** A horizon past the end of
available bars (`breakout_bar + horizon_bars >= len(bars)`) returns
`None` from `forward_return_pct`, and `summarize` reports both a mean
over only the resolved subset *and* `n_resolved_{h}b` alongside it --
deliberately two numbers, not one, so a thin horizon's mean (e.g. 2 of 50
matches actually old enough to measure at 60 bars) isn't read as being on
equal footing with a well-populated one. `still_open_rate` (CONFIRMED/
ACTIVE) is the same right-censoring idea applied to pattern status
directly rather than to a specific horizon.

**Throwback rate, named but not built.** The design doc's §7.3 also
names Bulkowski's throwback-rate benchmark (price revisits the breakout
level *without* reversing through it, then continues to target -- distinct
from `INVALIDATED_FAILED_BREAKOUT`, which is a genuine reversal). Building
it needs the actual bar index where price later hits `target_price`, not
just the final status `_walk_post_breakout` leaves behind -- nothing here
computes that today. Left out rather than half-built, and the module
docstring says so explicitly so `failed_breakout_rate` isn't later
mistaken for already covering it.

### Real-data smoke test (AAPL, full daily history)

`python -m src.signals.patterns.backtest.evaluator AAPL --timeframe daily`
against real AAPL history produces a per-pattern-type table across all 14
pattern types with at least one breakout on record, matching Bulkowski-
style shape sanity-checked by eye rather than assumed correct just
because it ran: `cup_and_handle` (n=71) 62% hit-target / 38% failed-
breakout, `rounding_bottom` (n=26) 73% hit-target -- both broadly in
Bulkowski's documented range for bullish base patterns; `double_top`
(n=35) is the clear outlier at 26% hit-target / 66% failed-breakout with
negative mean forward returns at every horizon, which reads as a real
finding about AAPL's own predominantly-uptrending history rather than a
bug -- a bearish reversal pattern is expected to underperform in a market
regime that mostly doesn't reverse. One coincidence investigated rather
than assumed benign: `inverse_cup_and_handle` and `rounding_top` (both
n=1) report identical forward returns; traced directly against the
scanner output rather than shrugged off -- confirmed to be two genuinely
distinct real matches (different `id`, different `pattern_type`) that
happen to share the same `breakout_bar` (1600) and `entry_price` because
their formation windows both terminate at essentially the same right-rim
pivot in AAPL's 2015-08 to 2016-01 range, not a deduplication bug.

A real bug caught by code review before merge: `run_backtest`'s own
docstring claimed "continue-on-error per ticker, same as `cli.py main()`'s
own per-ticker try/except" -- but the per-ticker loop body had no
`try`/`except` at all, so one bad ticker would abort the entire run,
silently discarding every other ticker's already-computed outcomes too
(not just skipping the bad one). Reproduced first with a mocked
`load_and_validate` raising on the middle ticker of a three-ticker list,
confirmed the whole call crashed and the third ticker was never even
attempted, then wrapped the per-ticker body in a real `try`/`except
Exception`, printing and continuing -- matching the docstring's own
claimed behavior instead of rewriting the claim to match the bug. New
regression test confirmed to fail against the pre-fix code first; the
real AAPL smoke test above reproduces byte-identical output post-fix,
confirming the fix changed nothing on the non-error path.

## Detection-quality fix batch: dedup, rim gate, roundedness, resolution horizon

Four bugs found by running the §7.3 outcome backtest across the full
universe for the first time and chasing the one result that looked wrong.
Worth recording as a group because three of the four were only visible
*because* of the fourth, and because the investigation route -- notice an
implausible statistic, read the sign conventions, then look at rendered
charts -- worked better than any of them would have alone.

The trigger: `inverse_cup_and_handle` came back with a 0.084 target-hit
rate and a -16.4% mean 60-bar return on the first (5-ticker) sample. Too
lopsided to be a weak edge; a pattern with no predictive power lands near
a coin flip with noisy-but-centred returns.

**Not a flipped sign.** First hypothesis was the obvious one -- a bearish
variant derived by mirroring the bullish one, with a comparison left
pointing the wrong way. Checked every one (breakout test, target-hit test,
failed-breakout reclaim, `extreme_price`, target formula, invalidation,
handle gates) and they were all correctly mirrored. Recording this because
the *absence* of the expected bug is what forced looking at the data
instead of the code.

**1. The rim gate was an unbounded mirror.** §4.4 says the right rim should
recover to within ~0-5% of the left rim, and that "a right rim above the
left rim is fine too and often bullish" -- a deliberately one-sided
tolerance. Mirroring it faithfully for the bearish variants turned "fine
above" into "fine arbitrarily far below." Measured: the inverse variants'
right rim sat a median 29.8% (min 66.0%) *below* the left rim, which is not
a cup rim at all but the far side of a bear leg. Because the measured move
is computed in absolute dollars off the right rim, that drove targets
through zero: 16.3% of bearish matches had a **negative target price**,
unreachable by construction, and the median implied target was a -78.7%
move. The lesson generalizes past this detector: a mirror that is
geometrically faithful is not necessarily faithful in price space, which is
bounded at zero going down and unbounded going up. The bullish side had the
identical defect (right rim up to +234% above the left rim) and it stayed
invisible only because an inflated bullish target is still positive and
reachable. Fixed with a symmetric `cup_rim_divergence_max_pct = 10.0`.

**2. Quadratic R2 is a poor roundedness discriminator, and raising it makes
things worse.** §4.4 point 3 offers two operationalizations of "rounded not
V-shaped"; only the R2 one was built, on the reasoning that one principled
mechanism beats two. That call was wrong -- they are complementary. A
*monotone* price path fits a parabola arm almost perfectly, so R2 actively
rewards the shape the check exists to exclude. Across six hand-audited
instances the single confirmed-valid cup scored the **lowest** R2 of the
group (0.677) while four invalid ones scored higher (up to 0.879).
Tightening the threshold would have rejected the good instance first. Fixed
by keeping `cup_roundedness_min_r2` at 0.5 and adding three gates off the
same fit: curvature sign (must open the way the pattern requires -- 26% of
real matches failed this, and nothing checked it because
`curves.fit_roundedness` is direction-agnostic by design), apex position
inside the rim-to-rim window (a monotone leg puts the vertex 2-4 window
lengths outside), and the doc's own never-built "no single-bar move
accounts for a large fraction of the total cup depth" heuristic (catches an
earnings cliff at 0.491 of total depth that R2 waved through).

**3. `scanner.py` never implemented the dedup §5 specifies.** Each cup
detector scans (rim1, rim2) pairs and emits one match per plausible left
rim, so a single base with three left rims became three matches sharing one
right rim, one breakout bar, and near-identical outcomes. Every `n` in
every backtest result was inflated (measured: 2832 -> 2040, 28.0% of
output, max group size 6) and one real trade was counted up to six times.
The instructive part is the key: window-overlap ratio, the obvious choice,
**fails** -- at Jaccard >= 0.7 it merges 153 of 178 true duplicates while
wrongly merging 1145 genuinely distinct pairs, because distinct patterns on
one ticker routinely share most of their window. The duplicates are not
"overlapping," they are the same structure found from different starting
pivots, so the identity key is the pattern's *terminal* pivot -- what
actually fixes its trigger level and breakout.

**4. `HIT_TARGET` had no time horizon.** `_walk_post_breakout` walked to the
end of available history, so the status meant "target reached at any point
in the rest of recorded history." One audited instance was credited a hit
~2 years after its breakout, which is not comparable to the
weeks-to-months Bulkowski benchmarks §7.3 measures against. Added
`target_horizon_mult`, deliberately reusing `expire_lifespan_mult`'s exact
convention and value (a pattern's own duration sets its timescale,
pre-breakout and post-breakout alike) rather than inventing a second notion
of relevance, clamped to [20, 252] bars. New `EXPIRED_UNRESOLVED` status
keeps "ran its full horizon and resolved to nothing" (a decided non-hit)
separate from `ACTIVE` ("horizon hasn't elapsed in the data we have" --
right-censored), the same distinction `INVALIDATED_FAILED_BREAKOUT` already
draws against plain `INVALIDATED`. The pre-fix baseline's implausible
still-open rates (0.416 for inverse cup & handle against 0.095 for its
bullish twin) were this bug and bug 1 compounding.

**Validation of the batch.** Against the six hand-audited instances, the
fixed detector rejects all five invalid ones and keeps the one valid one.
Cup-family matches with a non-positive target: 22 -> 0. Median implied
target for inverse cup & handle: -78.7% -> -40.0%.

**Two doc corrections made alongside.** §8's `config/pattern_thresholds.yaml`
was never built and should not be -- `PatternConfig` + `PRESETS` is the
right architecture and matches every sibling module; §8 now documents the
real one. §8's `evaluator.py` line promising precision/recall was removed
(see §7.1/§7.2 -- no labeled set in v1).

**Still open, deliberately not touched in this batch:** `falling_wedge`
posts +21.0% at 60 bars while sitting at -0.5%/-0.0% at 10 and 20 bars
across 72k pre-fix samples. A return that materializes only at the longest
horizon, from nothing, looks like a measurement artifact rather than edge.
Investigate *after* the post-fix rerun -- the resolution horizon above may
explain or partly resolve it, and report before proposing a fix.

## Spike-low rims: pivot prices are wicks, cup geometry is closes

Follow-up to the fix batch above, surfaced by eyeballing the surviving
`inverse_cup_and_handle` matches across the full universe. Two of five
sampled survivors had a rim anchored on a single-bar wick -- an IPO-dump low
in one case -- and the shape gates were structurally incapable of noticing.

The mismatch: `detect_pivots` runs on the `high`/`low` series, so
`pivot.price` is an intraday extreme, but this detector checks its shape
against the *close* path between the rims (`fit_quadratic`,
`max_single_bar_move_frac`) and takes `extreme_price` from that same close
path. A wick-valued rim therefore set the cup depth and the measured-move
target while never appearing in any series the gates read. Every other
detector uses `pivot.price` and is right to -- this one is the only place
where rim values and shape checks come from different series.

Scale, measured across real matches: the rim's high/low sat a **median 2.4%
from its own close**, 40% of rims were more than 3% away, worst 19.5%.

**The second-order finding is the more interesting one.** That wick error
lands directly on `cup_rim_divergence_max_pct`'s own input: mean absolute
difference between wick-space and close-space rim divergence was **2.5
percentage points against a 10% budget** -- roughly 25% noise on the
measurement the gate is thresholding. The rim gate added in the batch above
was not quite measuring the thing it was tuned to measure. Worth
generalizing: when a threshold is tuned against a measurement, check what
noise the measurement itself carries before concluding the threshold is
wrong.

**Rejected fix: validate the rim's wick against its own close.** The obvious
guard (reject when `|pivot.price - close| / close` exceeds some bound) does
not discriminate. The single confirmed-valid instance has a **10.78%** wick
gap -- larger than every weak-or-poor instance except the worst one. Any
threshold catching the bad ones also rejects the known-good one. Same shape
of failure as raising the roundedness R2: the metric doesn't separate the
classes, so tuning it only trades false positives for false negatives. A
legitimate capitulation low that forms a real rim often *has* a long wick;
the wick isn't the defect, using it as the measured-move anchor is.

**Fix taken: source rim/handle prices from the close series** (`_close_at`),
leaving `match.pivots` wick-valued. Rim divergence, cup depth, handle gates,
height/target/stop, `key_levels` and the breakout trigger all now live in
close space, consistent with `extreme_price`, which was already close-based.
No new config knob -- the existing 10% rim gate does the rejecting, now on a
clean input. Deliberately *not* done by re-running pivot detection on
closes: that would shift every pivot position and change which candidates
exist at all, making the change impossible to attribute against the
previous baseline.

Rim pivots stay wick-valued on the match on purpose. A pivot marks where
price actually turned; a key level marks where the tradeable boundary sits.
Those are different facts and unifying them would lose one.

**Plotting ripple, fixed as part of this.** `plotting.py` located a flat
neckline's starting pivot by exact float equality against
`key_levels["neckline"]`. Once the neckline is a close and `pivot.price` is
a wick, that match never succeeds and it silently falls back to a positional
`-2` index -- wrong for Rounding patterns, and the exact bug that file's own
docstring records having already fixed once. Detectors now store
`key_levels["neckline_bar"]` and plotting reads that; the float-match path
survives only as a fallback for pre-existing stored rows and hand-built test
fixtures.

**Two tests had to be rebuilt, and the reason is worth recording.**
`test_rim_symmetry_gate_rejects_weak_recovery` and
`test_handle_below_cup_midpoint_falls_through_to_rounding` constructed their
scenarios by overriding a *pivot's price* while leaving the bars unchanged
-- a pivot claiming 120 whose bar closes at 140. They passed before only
because the detector trusted `pivot.price`, i.e. they encoded the bug. Both
now build the intended price into the bars. The rim test also gained a
control (`..._is_what_rejects_it_and_nothing_else`) that widens the rim
bound and asserts the candidate returns, so the rejection is attributable to
the rim gate rather than to some other gate the new fixture happens to trip.

## Failed breakout vs. throwback: deciding at the horizon, not mid-flight

`_walk_post_breakout` used to resolve INVALIDATED_FAILED_BREAKOUT the moment
price closed back through the trigger level, provided that happened inside a
fixed `failed_breakout_reclaim_bars` window (default 5). The bug isn't the
value of that constant -- it's that no value can be right.

At the instant of a reclaim, a **throwback** (Bulkowski: revisits the
breakout level, then continues on to target -- a pattern that *worked*) and a
**false breakout** are indistinguishable. Only what happens afterward
separates them. A fixed window therefore isn't a threshold, it's a choice
about which error to make. Measured across 28,514 real breakouts:

```
window  catches of all reclaims   genuine target-reaching matches mislabelled
   5            66.7%                            2.4%
  10            79.5%                           14.1%
  20            89.6%                           24.7%
  40            95.7%                           32.0%
```

Reclaims are heavily front-loaded (median 3 bars, p75 8, p90 21), so a
*wider* window catches more real failures -- and converts one in seven
genuine winners into a "failure" by bar 10. Widening was the obvious fix and
it is not an improvement, just a different error.

**Fix: the reclaim no longer ends the walk.** It's recorded, the walk
continues to the resolution horizon, and target-hit always wins. A match that
reclaims and then reaches target is a throwback and stays HIT_TARGET.
INVALIDATED_FAILED_BREAKOUT is now only reachable at the end of the horizon
-- reclaimed at some point *and* never reached target -- so it states a
resolved outcome instead of guessing at one mid-flight. EXPIRED_UNRESOLVED
keeps its meaning as the other non-hit: never gave the level back, simply
went nowhere.

`failed_breakout_reclaim_bars` was **removed**, not retuned. With the
decision moved to the horizon there is no window left to configure, and a
knob that looks tunable while affecting nothing is worse than no knob --
someone would eventually sweep it in §7.4 and conclude it had no effect.

**What actually happened to the rates, against what was predicted.** The
prediction written here beforehand was that `failed_breakout_rate` would rise
sharply, `unresolved_rate` fall, and `hit_target_rate` rise modestly. Two of
those three were wrong, and the reason is worth keeping:

- `hit_target_rate` rose for **17/17** pattern types, mean **+15.6 points**
  (cup & handle +24, rounding bottom +26). Not "modest." The reclaim
  distribution was the clue and it was misread: median reclaim is 3 bars,
  p25 is 1 bar, so more than half of all reclaims were landing *inside* the
  old 5-bar window and terminating the walk before the pattern had any
  chance to work.
- `failed_breakout_rate` **rose for 8 types and fell for 9** -- not a sharp
  rise. Two opposing flows cancel to different net effects per pattern:
  matches reclaiming *outside* the old window that never hit target move
  UNRESOLVED -> FAILED (pushes up), while matches reclaiming *inside* it that
  then reached target move FAILED -> HIT_TARGET (pushes down). Given the
  front-loaded reclaim distribution the second flow is the larger one for
  most patterns.
- `unresolved_rate` fell everywhere, as predicted -- to near zero in several
  cases (cup & handle 0.153 -> 0.003), since ~75% of breakouts reclaim at
  some point and now resolve as FAILED rather than UNRESOLVED.
- `throwback_rate` rose for **17/17**, mean +29.6 points. This was not
  predicted at all, and it is the most important of the four -- see the
  Bulkowski entry below.

**Six tests asserted the old semantics and all six needed real fixtures, not
just renaming.** Every one broke the level, reclaimed, and then ended a few
bars later -- which under the old rule resolved immediately, and under the
new one leaves the match ACTIVE (right-censored: the horizon hasn't elapsed
in the data provided). Two were fixed by extending the tail past the horizon;
four needed the horizon pinned short in their config instead, because the
horizon scales with each pattern's own formation length and a cup's or VCP
base's horizon outruns any reasonable fixture tail. All six were renamed from
`..._reclaim_within_window_flags_...` to
`test_reclaim_without_reaching_target_flags_failed_breakout`, since there is
no window any more. Four new lifecycle tests cover the cases the redesign
exists for: reclaim-then-target is a hit; reclaim-without-target is a
failure; no-reclaim-without-target is unresolved; and reclaim with data
running out inside the horizon stays ACTIVE.

**Cost to note:** the walk no longer short-circuits on reclaim, so it visits
every bar to the horizon. The test suite went from ~34s to ~92s and the
full-universe backtest gets correspondingly slower. The reclaim check itself
stops after the first hit, but the target check cannot.

## ⭐ First external validation: throwback rate matches Bulkowski

**This is the only number in this module that has been checked against an
independent source and agreed with it.** Recording it separately so it stays
easy to find.

Design doc §7.3 names Bulkowski's documented **~62% throwback rate for cup
and handle** as a benchmark worth comparing detector output against. After
the reclaim redesign:

```
  cup_and_handle throwback_rate    pre-fix   0.395
                                   POST-FIX  0.650
                                   Bulkowski ~0.62
```

Within ~3 points, across 17,868 breakout outcomes, on a metric nothing in
this codebase was tuned toward.

**Why it was wrong before, and why that matters more than the agreement
itself.** Throwback is by definition "price came back to the breakout level,
then went on to target." The old lifecycle resolved a match to
INVALIDATED_FAILED_BREAKOUT the moment it reclaimed inside the 5-bar window,
which removed it from the HIT_TARGET pool entirely -- and `throwback_rate`'s
denominator is HIT_TARGET matches. So the metric's denominator
*systematically excluded the exact population the metric measures*. It could
only ever observe throwbacks that happened after bar 5, and reported 0.395
for something the literature puts at 0.62.

That failure mode is worth generalising: a metric can be individually
correct at every step and still be structurally blind, because an *upstream*
state machine decided which rows it gets to see. The bug was not in
`had_throwback`, which was right the whole time.

Caveats, stated so this isn't over-read: it is one benchmark on one pattern
type. Bulkowski's sample, era, and pattern-identification criteria are not
this detector's, so exact agreement would be suspicious rather than
reassuring -- proximity is the signal. The other §7.3 benchmark quoted
alongside it (cup & handle's ~5% break-even failure rate) is **not** the same
thing as `failed_breakout_rate` (0.383) and should not be read as a
contradiction: break-even failure is about trades that fail to clear a profit
threshold, not about breakouts that reverse. No comparable published figure
has been checked for the other pattern types yet.

## Mean forward return is the wrong statistic, for every pattern type

`falling_wedge` posted +21.04% mean 60-bar return across the universe while
sitting at -0.49%/-0.03% at 10 and 20 bars -- flagged as an anomaly to
investigate. It is not an anomaly and it is not edge. It is the arithmetic
mean behaving exactly as it must on this data.

Measured over 5,553 falling-wedge outcomes across 353 random tickers:

```
  mean                 +0.61%       median               -1.22%
  5-95% trimmed mean   -1.57%       mean minus top 10    -1.00%
                                    mean minus top 1%    -2.47%
```

**One outcome of 5,553 supplied 90% of the mean** (a sub-dollar stock at
+3,080% over 60 bars). The top 5 outcomes -- 0.09% of the sample --
contributed more than the entire mean. Median return is negative at all
three horizons.

The mechanism is entry price, and it is structural, not a data error: equity
percentage returns are unbounded above and floored at -100%, so low-priced
names produce enormously skewed distributions.

```
  entry <$1     n=188   mean +40.35%   median -1.64%     <- mean is 25x median
  entry $1-5    n=1085  mean  +0.36%   median -4.81%
  entry $5-20   n=1944  mean  +0.88%   median +0.26%
  entry $20-100 n=1726  mean  -1.44%   median -0.96%
  entry >$100   n=610   mean  -6.20%   median -4.65%
```

**This is not a falling_wedge property.** `rising_wedge` in the same sample:
mean -1.91%, median -1.63%, max +405%. Same distribution shape, different
draw. Every `mean_return_*` figure in every baseline recorded before this
change is tail-dominated; falling wedge only stood out because it happened to
catch the largest single ticket. Which pattern looks best on mean return is
substantially a lottery.

**Fix:** `summarize` now reports `median_return_{h}b` and `wins_return_{h}b`
(mean after winsorizing each tail at `WINSOR_LIMIT`, default 1%) beside the
raw `mean_return_{h}b`. Winsorized rather than trimmed so `n_resolved` stays
the true sample size -- observations are capped, not discarded. The raw mean
is deliberately *kept* rather than replaced: the gap between mean and median
is itself the diagnostic, and hiding it would make the next such distortion
harder to notice.

A minimum-entry-price filter would also suppress this, and is deliberately
**not** bundled here: winsorizing corrects a statistical distortion in how
results are summarised, whereas a price floor is a decision about which
universe the module covers. Different question, separate call.

## Formation completion: Rounding's breakout level comes from the pivot its formation ends on

A third hypothesis class, and deliberately filed apart from the two before
it. The fix batch above was **measurement** bugs -- the wrong price fed into
otherwise-correct math (wick where a close belonged, no time horizon, no
dedup). This one is neither that nor a price-space problem at all. Every
number going into the rounding breakout test is the number it should be.
The defect is *when* the test is allowed to run.

**The structure.** Rounding and Cup & Handle are the same code path
(`detectors/cup_and_handle.py`) -- same shape gates, same rim2 trigger, same
measured move, same invalidation. The only branch between them is whether
pivot `j+1` exists and passes `_handle_gates_pass`. Rounding is the residual
bucket: candidates that cleared every shape gate but had no valid handle.

That branch has a consequence nobody designed. For Rounding,
`formation_end_pivot` **is** rim2 -- the pivot that supplies the trigger
level -- so `apply_lifecycle`'s scan (`range(formation_end_bar_index + 1,
n)`) starts hunting for a break of that level one bar after the level was
defined. Cup & Handle's formation ends on the *handle*, strictly later than
rim2, so its scan can never start adjacent to its own trigger pivot. The
handle is not adding predictive signal here; it is incidentally enforcing a
separation Rounding never had.

Compounding it: after the spike-low rim fix above, the trigger level is
rim2's **close**, while rim2 itself is a wick-defined pivot. So for a bar or
two afterwards price can re-close through that level without the swing high
ever being touched. That is not a breakout, it is the same swing.

**Measured, full universe:**

```
                        n     gap<=5    median 60b            throwback
                                        near      far         near   far
  rounding_bottom     10021   50.5%    -9.42%   +0.87%        0.842  0.621
  rounding_top         3090   55.2%   -16.39%   -2.02%        0.874  0.606
  cup_and_handle      17868   13.1%    +2.84%   +1.80%          --     --
  inverse_cup_&_h      4738   11.7%    +0.21%   -1.61%          --     --
```

Over half of all rounding matches "broke out" within five bars of their own
right rim, and that slice carried the *entire* return deficit of both types.
Throwback rate in it runs 0.84-0.87 -- near-certain retracement, the
signature of a level that was never really cleared. Cup & Handle sits at
~13% near-rim with its near slice slightly *better* than its far slice, in
both directions: the opposite sign, which is independent evidence the gate
belongs to Rounding alone rather than to the shared path.

**A hypothesis this falsified along the way.** The first mechanism proposed
was that breakouts failing to clear the pivot's wick extreme underperform,
and split by `cleared_rim_extreme` it looked convincing. It was a proxy.
Holding the temporal gap fixed, clearing the extreme adds almost nothing --
in the 1-2 bar bucket `cleared=True` has n=2 and n=1, because a break that
close to the pivot essentially never clears it. The two variables are nearly
collinear there and the gap is the causal one. What exposed this was the
`cup_and_handle` row: it showed no split at all, and any mechanism resting on
the shared trigger code had to explain that. The temporal one does; the
price-space one could not.

**Fix.** `apply_lifecycle` takes an optional `min_breakout_bar_index`;
Rounding passes `rim2.bar_index + rounding_breakout_min_gap_bars` (6) and
Cup & Handle passes nothing. Deliberately narrow: it gates the breakout
comparison **alone**. `pre_breakout_invalidated_at` keeps being evaluated on
every bar of the window, because a base that breaks below its own floor
while we are waiting is dead regardless of why we were waiting -- suppressing
that too would let the gap silently rescue patterns that should have been
invalidated. A break inside the window is *ignored*, not disqualifying: those
bars are not evidence against the shape, only too close to the defining
pivot to be evidence for a breakout.

**Why 6.** Sweep at full n, gate applied to rounding only:

```
  gap   rounding_bottom          rounding_top
        kept%   median 60b       kept%   median 60b
    0   100.0%    -4.61%         100.0%    -9.66%
    4    54.6%    +0.03%          51.1%    -2.40%
    6    49.5%    +0.87%          44.8%    -2.02%
    8    46.1%    +1.11%          40.9%    -1.35%
   11    41.8%    +1.41%          36.9%    -1.20%
   21    29.4%    +1.80%          25.1%    -0.86%
```

The structural gains are concentrated at gaps 2-4 (+2.37, +1.68, +0.59
points for rounding_bottom), which is what a noise-re-crossing mechanism
predicts: the noise resolves within a few bars and everything past it is
curve-fitting. 6 captures 85% of rounding_bottom's total available
improvement and 84% of rounding_top's while keeping ~half the population;
6 -> 11 costs ~8 points of kept-n for +0.54/+0.82 return points. The tell
that past ~8 is noise: **10 -> 11 moves the median +0.01 points for both
types**, buying nothing for real sample size.

**Not claimed:** `rounding_top` never reaches positive anywhere in the sweep
(best -0.61% at gap 15). The gate converts it from badly broken to roughly
break-even; it does not make it a profitable pattern. Whether a near-zero-edge
bearish pattern is worth keeping is a separate call and is not folded in here.

**Open design question, deliberately deferred rather than resolved.** A flat
6-bar constant, chosen by sweeping one historical universe, is a strange fit
for what the mechanism actually is -- and it's inconsistent with this same
module's own convention elsewhere: `resolution_horizon_bars` (the
post-breakout time limit) deliberately scales with `formation_bars` rather
than using a flat constant, on the reasoning that a pattern's own duration
sets its timescale. Rounding bases range 150-400 bars by config; a 400-bar
base plausibly has a wider settling band around its rim than a 150-bar one,
and a flat 6 can't express that. There's also a more direct per-instance
signal already sitting unused: `rim_gap_frac`/`cleared_rim_extreme` measure
the actual close-vs-wick divergence at each specific rim, rather than a
population-level bar count standing in for it -- a price-based gate ("close
must clear rim2's own wick extreme, or clear it by some buffer") would be
self-calibrating per match instead of one number tuned once. Kept flat for
now because it's simple and already verified; worth revisiting if this
pattern's economics matter enough to justify the extra complexity. See
`config.py`'s own note on `rounding_breakout_min_gap_bars` for the same
caveat, kept next to the knob it concerns.

**Before / after, full universe (all other pattern types byte-identical --
verified column-by-column, 0 delta on every one):**

```
                    n before/after   hit_target%   median 60b     throwback%
  rounding_bottom  10021 -> 7630     46.0 -> 55.2   -2.91 -> -0.20   70.8 -> 62.2
  rounding_top      3090 -> 2180     29.3 -> 37.4  -14.14 -> -3.29   72.4 -> 61.5
```

`n` drops because ~24-30% of prior matches never actually broke out at all
under the corrected window -- they were noise re-crossings of the rim,
correctly reclassified as still-forming or invalidated rather than resolved
trades. `hit_target_rate` rises (fewer false starts diluting the
denominator) while `throwback_rate` *falls* -- consistent with the removed
population being exactly the "broke out, immediately threw back" cases that
were inflating it. `rounding_bottom` crosses to essentially flat on median;
`rounding_top` improves sharply but, as noted above, does not cross zero.

## §7.4: pivot-extraction sensitivity sweep

Design doc item 4, the last item in §7 and the last item of this module's
initial investigation arc: sweep `config.pivot_atr_mult` -- the ATR
multiple every detector's pivots come from (`detect_pivots(..., threshold_fn
= config.pivot_atr_mult * atr)`) -- and report stability rather than picking
one value and moving on. Swept `[1.5, 2.0, 2.5, 3.0, 4.0]` (default 2.5)
against a fixed 400-ticker sample, full §7.3 outcome backtest per value.

**Match count is exactly as sensitive as the doc predicted, and the shape
of that sensitivity splits pattern families in two.** Triangle/wedge/
double-top-bottom/cup-family types thin out *monotonically* as the
multiple widens (coarser pivots -> fewer candidate windows) -- `n(1.5) /
n(4.0)` ranges from 2.1x (rounding) to a striking **43.8x for
symmetric_triangle** (4,775 -> 109 matches). Four types are completely
flat across the whole sweep -- `vcp`, `bull_flag`, `bear_flag`, `pennant`
-- because they use their own dedicated `vcp_pivot_atr_mult`/
`flag_pivot_atr_mult`, not the shared parameter this sweep varies; they
were included as an implicit negative control and behaved exactly as
expected (bit-identical `n` at every value).

**Head & Shoulders and its inverse are the one family that does NOT thin
out monotonically -- they peak near the current default and fall off on
*both* sides:**

```
                    1.5    2.0    2.5    3.0    4.0
head_and_shoulders   205    548    722    702    452
inverse_h_and_s      172    388    541    498    357
```

This makes structural sense in a way the monotonic families don't: H&S
needs a specific five-pivot alternation (shoulder-head-shoulder-two
troughs) to survive intact. Pivots too fine (low mult) inject noise that
breaks the exact sequence before it forms; pivots too coarse (high mult)
leave too few pivots overall for the sequence to appear at all. The
current default of 2.5 sits close to the empirical peak for both -- not
by design (this knob predates any H&S-specific tuning), but it is not a
bad accident either.

**Outcome quality (hit_target_rate, median_60b) is reasonably stable
across a roughly half-to-double range around the default for most types,
and least stable for exactly the types whose sample also collapses most --
which makes the two hard to fully disentangle with one 400-ticker sample.**
Two notable exceptions worth flagging on their own:

```
                 hit_target_rate                    median_60b
                 1.5     2.5     4.0                 1.5      2.5      4.0
rounding_top     0.413   0.373   0.318               -0.035   -0.028   -0.086
falling_wedge    0.449   0.414   0.298                0.000   -0.004   -0.059
```

Both degrade steadily as the multiple widens, and `n` for both is already
thin at the high end (rounding_top: 184 -> 88; falling_wedge: 14,052 ->
1,050 -- still a large sample, so this one reads as more than pure noise).
Whether this is the pivot threshold changing which *real* structures get
found, or coarser pivots systematically admitting worse-quality candidates
at the margin, isn't something this sweep alone can separate -- flagging
as read, not concluding.

**Not claimed:** this sweep doesn't identify a "better" value than 2.5 --
that was never its purpose (per the doc's own framing, the point is
reporting stability, not re-tuning). No change made to `pivot_atr_mult` or
any other config value as a result of this sweep.

This closes out the initial investigation arc opened by the full-universe
outcome backtest: dedup, rim/roundedness fixes, resolution horizon, the
reclaim redesign, the rounding formation-completion fix, the mean/median
distortion fix, and now this sensitivity check. `docs/backlog.md` (or
wherever future work gets tracked) is the right place for anything raised
here that warrants deeper follow-up -- the H&S sweet-spot shape and the
rounding_top/falling_wedge degradation at wide multiples both seem like
reasonable candidates.
