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
- [ ] **Phase 3 — Triangles (asc/desc/symmetric) + Wedges.** New shared
  infra: convergence/apex math in `trendlines.py`. Wedges near-free once
  triangle fitting exists.
- [ ] **Phase 4 — Cup & Handle + Inverse + Rounding.** Isolate the
  quadratic roundedness fit (`fit_roundedness(prices) -> r_squared`) as
  its own tested primitive before wiring into the full detector.
- [ ] **Phase 5 — VCP.** Most novel logic (Trend Template gate, monotonic
  contraction sequence), least standardized in the source material,
  depends on none of the trendline/quadratic infra — sequenced last among
  primary patterns.
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
detectors). Everything *around* that call differs by design and is NOT
shared:

| | sr_lines diagonals | triangle/wedge (Phase 3, not yet built) |
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
