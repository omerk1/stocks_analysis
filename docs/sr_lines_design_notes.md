# sr_lines design notes

Running log of design decisions, findings, and open questions from building
the horizontal S/R engine (milestone 4 + review-round fixes). Written so
none of this has to be re-derived when milestone 5 (diagonals) starts --
nearly everything here applies in log-price/slope space too, not just flat
horizontal zones. Append to this rather than rewriting it.

## Backtesting / `as_of` semantics

- **Detection must never see the future.** `engine.detect(conn, ticker, config, as_of=X)` loads bars only through X. This already gives correct
  lookahead-safety for free: a pivot can't appear unless its confirming
  reversal was observed within the visible window, and an in-progress
  body-break correctly lands as `pending=True` if there aren't enough bars
  left within the window to resolve fakeout vs. break.
- **Visual review needs the opposite.** For manually checking "did this zone
  drawn at X actually hold up," the *chart* should show real price action
  past X even though the *detection* stayed blind to it. `cli.py` now loads
  two bar sets when `--as-of` is given: bounded bars feed `engine.detect()`,
  extended bars (same start, through whatever's latest available) feed the
  chart. `render_review_chart()` takes a `reference_date` so zone extents
  use the detection cutoff, not the (longer) displayed range, plus a dotted
  vertical line marking exactly where the cutoff falls.
- **Zones always render to the reference date regardless of state.** A zone
  detected as of X should show in full as of X whether or not it later broke
  or flipped -- state is a label/color (dash style, break/flip annotations),
  not something that should shorten the box. (Diagonal equivalent: the band
  should extend the same way; slope doesn't change this.)
- **Decay must freeze on death, not keep eroding with wall-clock time.**
  `touch_quality`'s recency decay uses a `decay_reference` that's frozen at
  a `BROKEN` (dead, never-flipped) line's last break, not `now` -- nothing
  more can happen to a dead line, so its historical strength shouldn't keep
  fading just because more calendar time passes. `ACTIVE`/`FLIPPED` lines
  (still in play) decay against the real reference date. This must stay in
  sync with the line's "flipped is sticky" state determination (see below)
  -- a line reported as FLIPPED must never have its score frozen as if dead.
  **Resolved**: `scoring._decay_reference` and `lifecycle.build_line` used to
  be two independent implementations of "is this actually flipped" and had
  already drifted out of sync once (see below). Factored into one shared
  `flip_status.break_and_flip_status()` (plus `flip_status.is_confirmation_event()`
  for the one-event predicate `_role_reversal` also needs) -- both
  `lifecycle.py` and `scoring.py` now call the same function, so they
  structurally can't disagree again.

## Zone geometry: two different knobs, easy to conflate

- **`zone_width_atr`** (config) is the tolerance used *during clustering* --
  how close two pivots' prices need to be (in ATR terms) to be considered
  the same level in the first place. This is the more fundamental lever.
- **`dedup_overlap_threshold`** (config, exposed as `--dedup-threshold`) is
  applied *after* clustering, in `lifecycle.dedup_lines` -- merges zones
  whose gap (not just literal overlap) is small relative to their average
  width.
- **Real finding (T, 8yr window)**: candidates.py's clustering produced 5
  separate narrow zones in the $17-19 range that a human reads as one broad
  area. Raising `dedup_overlap_threshold` from 0.6 to 2.0 barely touched this
  cluster (it's about *initial* cluster width, not post-hoc merging).
  Raising `zone_width_atr` from 0.4 to 3.0 collapsed it into **one** zone
  (absorbing 11 pivots) and cut the ticker's total candidate count from 28
  to 9. **When several pivots that should read as one area keep showing up
  as separate zones, reach for `zone_width_atr` first, not the dedup
  threshold.**
- Neither knob has a validated "right" default -- both are exposed on the
  CLI (`--zone-width-atr`, `--dedup-threshold`) specifically so they can be
  tuned by eyeballing real charts, not guessed.
- **`zone_width_atr=1.5` breadth-checked across 6 tickers** (T, AAPL, GME,
  KO, JPM, XOM; long_term preset): consistently reduced total candidate
  count 25-40% vs. the 0.4 default, in every ticker regardless of volatility
  profile. Direction is consistent -- reasonable evidence it generalizes as
  a *default* -- but this is a breadth check, not per-ticker visual
  validation; only T and AAPL got the detailed "does this actually look
  right" review.
- **Clustering thresholds now use ATR% of price, not raw dollar ATR.**
  Raw-dollar ATR is *locally* computed per cluster, so it partly
  self-normalizes across a single stock's own price history (a $50-era
  cluster gets a smaller dollar threshold than a $300-era cluster of the
  same stock) -- but that's incidental to using local ATR, not a real
  price-relative guarantee, and does nothing for comparing the same
  `zone_width_atr` value across *different* tickers' price levels. Concrete
  evidence: AAPL's 2019-2020 zones (price $46-98) came out only ~$1.5-4
  wide vs. ~$7-8 wide for its 2026 zones (price $240-280) at the identical
  `zone_width_atr` -- each individually reasonable, but looking dense
  together purely from the price-level difference. Fixed by deriving both
  the clustering threshold and `half_width` from `atr_at_pivot / price`
  (converted back to a dollar amount via the cluster's mean price).
  **Empirically mixed, not a uniform win**: re-ran the same 6-ticker check
  at `zone_width_atr=1.5` -- T improved further (17->13 candidates),
  AAPL/KO/JPM unchanged, GME/XOM slightly *more* fragmented (18->19,
  15->16). Kept anyway since it's more theoretically correct (removes a
  real confound), not because it uniformly reduced clutter.
- Diagonal equivalent: `config.diagonal`'s `zone_width_atr` reuse (band
  half-width around the fitted line, in log-ATR terms) will have the exact
  same "cluster too narrow -> fragments into near-duplicate trendlines"
  failure mode. Expect to need the same two-knob (fit tolerance vs.
  post-hoc merge) split, the same empirical-tuning-over-guessing approach,
  and probably the same ATR%-of-price (not raw ATR) normalization for the
  same reason -- a trendline's band width needs to scale with the price
  level it's currently near, not a fixed dollar amount from wherever it was
  fitted.

## Zone start date: use the earliest *pivot*, not the earliest *event*

`events.py`'s walk deliberately doesn't emit an event for the bar it uses
just to bootstrap which side price is on -- there's nothing to compare
against yet on that first bar. So computing a zone's start (`first_touch`)
from the earliest *event* silently skipped the very peak/trough pivot that
defined the level, making zones appear to start later than they actually
did (confirmed visually: a zone that should have started at an obvious
nearby peak started several weeks after it). Fixed by using
`min(p.timestamp for p in candidate.pivots)` directly. Also fixed a related
latent bug: `candidate.pivots` is sorted by *price* (for clustering), not
time, so `pivots[0]` was never a safe way to get "the first pivot
chronologically" even as a fallback.

Diagonal equivalent: a trendline's start should be its earliest defining
pivot too, not its earliest classified event -- same bootstrap-bar gap will
exist in diagonal event classification if it reuses the same walk structure.

## Scoring calibration findings

### `role_reversal` was binary -- fixed to be proportional -- still not enough, fixed again to be quality-weighted

Original: `1.0` if a break was *ever* followed by any confirming
touch/wick-fake, `0.0` otherwise. Real AAPL data showed this let barely-
confirmed flips (one weak retest, near-zero touch quality elsewhere)
outscore never-broken lines with real touch-quality evidence, purely from
this one all-or-nothing bonus. First fix: scaled with the *number* of
confirming touch/wick-fake events after the break, full credit at
`_ROLE_REVERSAL_CONFIRMATIONS_FOR_FULL_CREDIT = 3`. `state` (FLIPPED) stayed
a binary label -- only the score contribution was graded.

**That fix only closed the "1 touch = full credit" case, not the underlying
problem.** Flagged in the milestone-4 PR body and mistakenly marked resolved
in `backlog.md` afterward -- it wasn't. Fresh AAPL smoke test (long_term,
full history) after the count-based fix still showed a line with
`touch_quality=0.011` (almost no real evidence) but `role_reversal=1.0`
(exactly 3 confirming events, regardless of strength) outranking a
never-broken line with `touch_quality=0.205` (real evidence) and
`role_reversal=0.0` -- comparable `relevance_gate` on both, so the gate
wasn't what separated them. 3 confirmations, however weak, was still an
automatic 1.0.

Second fix: `role_reversal` now reuses the same quality-weighting
`touch_quality` already applies (reaction-strength/reclaim-speed x recency
decay, factored into a shared `_event_quality_score` helper in
`scoring.py`), evaluated over the confirming-event subset instead of raw
count. A flip "confirmed" by 3 tiny, long-decayed touches -- the *same*
touches keeping that line's `touch_quality` near zero -- now also scores low
here, since it's the same evidence viewed through the same lens. A flip
reconfirmed by several strong, recent touches still reaches full credit.
Verified on the same AAPL run: the never-broken real-evidence line now
outranks the near-zero-evidence flipped lines, as it should.

Side effect worth remembering: because `role_reversal` now decays with the
same `decay_reference` `touch_quality` uses, a flip's score contribution
here is no longer recency-independent the way the count-based version was --
an old, once-strongly-confirmed flip will fade here too, on top of whatever
the relevance gate separately does to `total`. This is intentional (stale
confirmations shouldn't count the same as fresh ones any more than stale
touches should), not a second, redundant staleness mechanism -- `role_reversal`
measures evidence *strength*, the relevance gate measures *whether the level
still matters given where price is now*; a line can score low on one and
fine on the other.

Diagonal equivalent: this quality-weighting lens (not just event *count*)
should carry over directly once diagonal role-reversal scoring exists --
same `_event_quality_score` helper, no reason to duplicate the count-based
mistake a second time for sloped bands.

### `resilience` (undercut-and-rally) was flat per event -- fixed to decay by time-under

Original: flat `0.15` per wick-fake, `0.35` per (non-pending) body-fake,
regardless of how long price sat on the wrong side before reclaiming. This
let a zone with lots of *slow*, drawn-out reclaims (arguably a sign of a
contested/noisy level, not a defended one) score as "resilient" the same as
one with quick, clean recoveries. Now a body-fake's credit decays against
how much of the `fakeout_reclaim_bars` window the reclaim used, floored at
`_BODY_FAKE_MIN_DECAY = 0.3` (a slow reclaim right at the limit still
genuinely recovered, just less cleanly -- shouldn't decay to ~0). Wick-fakes
are already same-bar (instant reclaim within the candle) so they're
unaffected, keeping flat credit.

Terminology note: the user's frame for this was "Undercut and Rally (U&R)"
as a *weaker, decaying* version of a normal "touch and go" -- worth keeping
this vocabulary for diagonal work too, since the same touch/wick-fake/
body-fake/break taxonomy should apply to a sloped band, not just a flat one.

### Resolved: proximity turned into a multiplicative relevance gate

Concrete real-data example that motivated this (AAPL, full history, no
`as_of`): a level around $51 from 2020 (AAPL now trades near $245, ~5x
higher) scored **0.369** overall. `proximity=0.125` was correctly
near-zero, but `resilience=0.856` and `role_reversal=1.0` alone contributed
~0.33 of weighted total, completely swamping proximity's `0.10` additive
weight. Several other ancient, far-away levels showed the same pattern.

User's framing, directly: *"Apple had great resistance at $100 some time,
but now it is above $300 for two years. This R is not interesting. But if
they have a massive trendline that was broken only lately and might revert
soon, it is another thing."* -- a **soft**, not hard, judgment: recent-and-
nearby should stay fully live; old-and-far should fade out; no clean binary
cutoff.

Fix (`scoring.py`): `proximity` no longer participates as a fifth additive
term (with 5 independent weighted terms, no single weight could suppress a
level strong on every other axis). Instead:

```
total = (weighted sum of touch_quality, duration_density, resilience, role_reversal) * relevance_gate
relevance_gate = proximity * recency
```

`recency` is a new decay factor (same half-life mechanism as
`touch_quality`) measuring time since the line's last event -- critically,
always against the real `now`, *never* frozen the way `touch_quality`'s
`decay_reference` freezes for dead lines. That distinction matters: freezing
would defeat the whole point here, since staleness is exactly what this
needs to capture regardless of whether the line is technically dead.
`config.scoring_weights` no longer has a `proximity` key; the remaining 4
weights renormalize against their own sum rather than assuming they total
1.0.

Verified on real AAPL data: previously-competitive stale levels ($51, $55,
$61, $73 from 2019-2020) no longer appear anywhere near the top -- the
top-10 is now entirely 2024-2026 zones. Side effect worth remembering:
overall score *scale* compressed (best line now ~0.15-0.30 vs ~0.5-0.6
before), since almost nothing has a gate near 1.0 unless both very recent
and very close to price -- any hardcoded strength thresholds from before
this change need rechecking against the new scale.

Applies at least as strongly to diagonals: an old, steep trendline that
hasn't been near price in years should be even less "interesting" than a
stale horizontal level, since a trendline's implied price keeps moving
(in log-price space) purely due to slope, on top of whatever the stock's
actual price has done.

## CLI knobs added so far (for tuning by eye, not guessing)

- `--as-of YYYY-MM-DD` -- freeze detection at a historical date; chart still
  shows real price action past it (see backtesting section above).
- `--top-n N` / `--strength-floor F` (mutually exclusive) -- fixed count vs.
  "everything above this score."
- `--dedup-threshold F` -- post-clustering merge aggressiveness.
- `--zone-width-atr F` -- clustering-time tolerance (see zone geometry
  section above -- usually the more relevant knob of the two).

## Resolved: BREAK/BODY_FAKE markers and break/flip labels were ambiguous on a real chart

Twice on a real NVDA chart, a line with zero BREAK events (all its
crossings were BODY_FAKE -- reclaimed within the window) was misread as
having broken, because (1) BODY_FAKE (`"x"`, `#d62728`) and BREAK
(`"x-thin"`, `#8c1414`) rendered as near-identical reddish X's at normal
zoom, and (2) a *different*, price-adjacent line's real break/flip
annotations, drawn at that other line's own `center` height, visually
landed close enough to the first line's box to read as belonging to it --
markers and annotations are both plotted at a flat `y=line.center`, so two
lines whose centers are only a few dollars apart can have their event rows
visually collide once compressed against the chart's full price range.

Fixed in `plotting.py`: BREAK is now a bold solid black `"x"` (larger,
thicker outline) instead of a slightly-darker-red thin X -- deliberately the
most visually severe marker, matching that it's the only event type that
actually costs a line its role. BODY_FAKE is now a hollow `"circle-open"` --
reads as "attempted, not solid," the opposite of BREAK. Break/flip
annotation text now includes the line ID (`"h19 break"`, not just
`"break"`), so ambiguity between adjacent lines' labels is resolved by the
text itself rather than needing to disambiguate by proximity.

Diagonal equivalent: whatever diagonal event markers end up looking like,
keep BREAK visually distinct from the reclaimed-fakeout types from the
start, and keep line IDs in annotation text -- diagonal bands crossing each
other or running close together in log-price space will have this exact
collision risk too, likely worse since slope adds a second axis they can
converge along.

## Resolved: `dedup_lines` silently left merged lines stale

Found in a pre-merge PR review of the milestone-4 checkpoint, not from a
chart complaint. `lifecycle.dedup_lines` merges a weaker zone's events into
the stronger survivor's `.events` list (that part was always correct and is
the whole point of gap-aware dedup) but never recomputed anything *derived*
from that event stream: `state`, `broken_at`/`flipped_at`, the
`n_touches`/`n_wick_fakes`/`n_body_fakes`/`n_breaks` counts, or
`scores`/`strength`/`proximity` -- all of that kept reflecting only the
survivor's own pre-merge events. Confirmed concretely: merging an ACTIVE
line with a BROKEN line (the latter carrying a real BREAK event) produced a
result still reporting `state=ACTIVE`, `n_breaks=0`, `broken_at=None`,
unchanged `strength` -- while `.events` now actually contained the break.
On a chart that renders as a solid (ACTIVE-styled) box with no "break"
annotation, but a break marker (✖) sitting right on it, and hover text
claiming zero breaks. It also meant `select_lines`'s top-N ranking never
benefited from a merge's "more complete evidence" at all, since it sorts on
the never-updated `strength`.

Fix: `dedup_lines` now takes `bars`/`atr` and, on every merge, calls
`lifecycle._absorb()` to rebuild state (via `flip_status`), counts, and
`scoring.score_line`'s full output from the *union* of events, in place, on
the survivor. Regression test: `test_dedup_rescores_the_survivor_from_the_merged_event_union`
in `tests/test_sr_lines_lifecycle.py`.

Diagonal equivalent: whatever diagonal dedup ends up looking like (milestone
5) needs the same discipline from the start -- merging bands' events without
rescoring the survivor would reproduce this exact bug.

## Resolved: a resolved body-fake after a break now also confirms a flip

Same "Undercut and Rally (U&R)" idea already used for `resilience`
(body-fakes are weaker-but-real evidence a side is being respected,
see above), extended to flip *confirmation*: previously
`lifecycle`'s break/flip status and `scoring._role_reversal` only accepted a
TOUCH or WICK_FAKE after a break as proof the new side was being respected
-- a resolved (non-pending) BODY_FAKE after a break is the same kind of
evidence (price tried to fall back through toward the old side and failed,
closing back on the new side) and is now treated identically. A *pending*
body-fake still doesn't count -- it hasn't resolved yet. Both checks now
share one predicate, `flip_status.is_confirmation_event()`.

## Milestone 5: diagonal (RANSAC-style, log-price) trendlines implemented

Built on `feature/sr-lines-diagonals-and-scoring`, following the geometry
contract `models.py` had already anticipated since milestone 4 (slope/
intercept in log-price-per-bar-index space, `half_width` as a log-space
band -- see `Line.price_at`/`Line.zone_at`).

- `candidates.DiagonalCandidate` + `generate_diagonal_candidates`: seeds
  from same-kind pivot pairs `>= diagonal_min_pivot_separation_bars` apart,
  slope-capped via `max_diagonal_slope_atr_per_bar` (treated as a direct cap
  on log-slope-per-bar, i.e. roughly "max % move per bar" -- the field
  predates this work and its exact intended units were never pinned down
  elsewhere, so this is a judgment call worth a gut-check if it turns out
  wrong), inliers within `zone_width_atr * local ATR%` of the fit (same
  formula shape as horizontal clustering), refit via least-squares over the
  full inlier set, greedily deduped by inlier-set overlap, capped at
  `diagonal_max_candidates`.
- `events.classify_events` generalized to evaluate zone bounds *per bar* via
  `candidate.zone_at(bar_index)` instead of once at the top -- required
  since a diagonal band's position moves with its slope; verified
  equivalent to the old fixed-scalar behavior for horizontal by the full
  existing suite staying green throughout.
- `scoring.score_line` gained an optional `center_at` callable (used by
  `_duration_density`, which needs the center at every bar in its in-play
  window) and `diagonal_fit_penalty`. Every existing horizontal call site
  was left untouched (both are additive, defaulted params) rather than
  changing `candidate_center`'s type everywhere.
- `diagonal_penalty` implemented as `DiagonalCandidate.fit_rms_atr_pct`: RMS
  of each inlier's deviation from the refit line, normalized by the same
  tolerance that made it an inlier, capped at 0.3. A starting formulation,
  not a final one -- like every other scoring constant here, it's meant to
  be checked against real charts, not treated as settled on the first pass.
- `lifecycle.py`: `build_line` branches on candidate type; `dedup_lines`
  gained a diagonal-diagonal merge rule (v1, explicitly flagged as a
  simplification): same gap-based check as horizontal but evaluated at the
  current reference bar via `Line.price_at`, gated by a slope-similarity
  check first so two trendlines that merely cross near "now" without
  actually tracking together don't get merged. Horizontal and diagonal
  lines never merge with each other.
- `plotting.py`: diagonal bands render as a sloped 4-point polygon (`Line.
  zone_at`) instead of a flat rectangle; event markers and break/flip
  annotations follow `price_at(bar_index)` instead of a fixed height.
- CLI: `--diagonals` (off by default, so existing horizontal-only charts
  stay comparable to earlier runs).

Real-data smoke test (AAPL, T; long_term preset, full history): both ran
clean end-to-end, no degenerate geometry (price extrapolation stayed within
a few percent of actual current price for the top-ranked diagonal lines on
both tickers), `diagonal_penalty` visibly discriminating tight vs. loose
fits, diagonal lines competing meaningfully in the top ranks alongside
horizontal ones. **Both tickers hit the `diagonal_max_candidates` (30) cap
before dedup** -- worth watching once the real charts are reviewed visually;
may indicate the cap is too low for a busy 8-year window, or that the
inlier tolerance is too loose and producing more near-duplicate candidates
than it should. Not yet resolved -- first real-chart visual review round
for diagonals is still pending, same as horizontal went through several
rounds of before it stabilized.

## Idea, not yet built: a penetration-depth/volume "erosion" signal

Raised as a question: does scoring account for how deep a wick/body-fake
went, or penalize a level for being tested too many times? It doesn't --
`Event.penetration_atr` and `Event.volume_ratio` are captured on *every*
event but never referenced anywhere in `scoring.py`. Touch count today only
ever helps (`touch_quality` sums quality-weighted touches up to a ceiling)
and can never actively hurt a line's score, no matter how many times it's
been tested.

This maps onto a real, two-sided tension in TA: more touches can mean
"well-established, real level" (the level keeps mattering, more
participants have positioned around it) or "getting worn down, about to
give way" (each test consumes the orders sitting there; the classic "the
more times a level is tested, the more likely it breaks" heuristic). Count
alone can't distinguish these -- the same 5-touch line could be either
story depending on the *shape* of those 5 touches, not how many there are.

Proposed approach (not yet built, not yet validated against real charts):
treat this as a *trend* signal, not a count-based one. Look at
`penetration_atr` (and optionally `volume_ratio`) across a line's touches
in chronological order -- e.g. first-half vs. second-half average
penetration, or a simple slope. Deepening penetration and/or declining
volume on successive tests -> a small penalty (erosion, thesis B).
Shallowing penetration and/or holding volume -> neutral or a small bonus
(fortification, thesis A). Would live as its own signal rather than folded
into `resilience`, since it measures evidence *direction* over time, not
evidence *strength* -- a genuinely different question from what
`resilience`/`touch_quality` already capture.

Deferred to the milestone-7 weight-tuning pass, same as everything else
scoring-related here: build it, then check it against real charts where a
level visually reads as "getting eaten through" vs. "rock solid" and
confirm the number agrees, rather than picking a formula and shipping it
unchecked.

Diagonal equivalent: the same trend-based approach should apply directly --
a diagonal band being tested with deepening penetration on each touch is
the same erosion story, just against a sloped level instead of a flat one.

## Still open / not yet built

- Whether `resilience`'s cap (1.0) needs revisiting -- a zone with enough
  events can still hit the cap even after the time-decay fix, so the decay
  change had only a modest effect on one real chaotic-vs-clean comparison
  that motivated it. Flagged, not yet acted on.
- Diagonal real-chart visual review (band width, dedup aggressiveness, the
  30-candidate cap, whether `max_diagonal_slope_atr_per_bar`'s log-slope
  interpretation is the right one) -- structurally verified, not yet
  visually validated.
- Milestone 6 (`as_of` dedicated test coverage beyond what's already
  implicitly correct) and milestone 7 (a systematic weight-tuning pass,
  now including diagonal-specific weights/penalty calibration) are still
  ahead, per the original spec's milestone order.
