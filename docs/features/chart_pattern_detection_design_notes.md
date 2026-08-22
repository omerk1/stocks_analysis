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
- [ ] **Phase 6 (bonus) — Flags/Pennants, Rounding top/bottom.** Only
  after 1–5 are validated. Rounding is nearly free off Phase 4's quadratic
  fit.

Also still open, deferred deliberately (see `docs/backlog.md` for the full
reasoning, not duplicated here): the backtest/evaluator harness (§7.2/7.3),
a real precision/recall pass via `backtest/labeler.py`'s growing label set,
and any threshold tuning against real chart review (every numeric knob
added so far is an unvalidated first pass, same status every sr_lines knob
started at).

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

`python -m src.patterns.cli AAPL --timeframe daily --plot ...` ran clean
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

`python -m src.patterns.cli AAPL --timeframe daily --plot ...` with both
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

`python -m src.patterns.cli AAPL --timeframe daily --plot ...` with all
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

`python -m src.patterns.cli AAPL --timeframe daily --plot ...` with all
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
