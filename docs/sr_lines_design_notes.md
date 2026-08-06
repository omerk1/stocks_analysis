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
clean end-to-end, no degenerate geometry, `diagonal_penalty` visibly
discriminating tight vs. loose fits, diagonal lines competing meaningfully
in the top ranks alongside horizontal ones.

## Resolved: candidate-level dedup + the 30-candidate cap were silently discarding real, visually obvious trendlines

First real-chart review found this directly: a clean, visually obvious
3-touch descending resistance line on AAPL (Dec 2025 -> Feb 2026 highs,
user hand-drew it on the chart) never appeared, even filtered down to
"descending only." Root cause had two parts, both confirmed against the
real AAPL data before fixing:

1. **`generate_diagonal_candidates`'s dedup only checked pivot overlap, not
   slope.** The exact 3-pivot line the user drew *was* generated as a raw
   candidate (`slope=-0.00072`, matching their line almost exactly) -- it
   just got discarded because it shared pivots with unrelated, longer,
   *ascending* candidates that had more inliers and were kept first. A
   single pivot can legitimately sit on two geometrically unrelated
   trendlines (a short recent one and a long slow one just happen to cross
   near it); pivot-set overlap alone can't tell them apart.
2. **The similarity threshold used to gate that overlap check --
   `max_diagonal_slope_atr_per_bar` (0.05, the *slope-rejection* cap) --
   was two orders of magnitude too loose to matter anyway.** Real trendline
   slopes run ~0.0001-0.001; a 0.05 tolerance calls almost any two
   same-magnitude slopes "similar" and, worse, doesn't reliably separate a
   gentle ascending line from a steep descending one. This exact bug
   existed in *two* places -- `candidates.py`'s dedup and `lifecycle.py`'s
   diagonal-diagonal merge check both reused this same too-loose constant.
   Fixed with a dedicated `candidates.slopes_are_similar()` (opposite signs
   are never similar; same-signed slopes must be within 2x of each other),
   now the single shared implementation both modules call.
3. **Even with dedup fixed, the pre-scoring cap still crowded it out.**
   AAPL's HIGH pivots alone produced 1,069 raw seed-pair candidates; after
   *correct* dedup, 255 genuinely distinct lines remained -- but sorting
   survivors by raw pivot count before applying `diagonal_max_candidates=30`
   still buried a real, tight, 3-pivot recent line 204th out of 241,
   crowded out by long, low-precision multi-year lines with more inliers.
   Raised the cap to 300 (comfortably covers 255/228 seen on AAPL/T) so
   candidate generation stops pre-filtering by "most pivots" and leaves the
   actual ranking to scoring's relevance/quality machinery, which is what
   it's for. Cost: detection is noticeably slower on a long_term window
   (~1s -> ~8-10s) -- acceptable for a CLI tool run occasionally, not
   optimized further yet.

Verified on the same AAPL run: descending diagonal count went from 1 (the
bug) to 30; T went from 5 to 78. The exact line the user drew now survives
and scores with a real (if unranked-in-top-N, since price broke through it
by "now") strength.

Diagonal equivalent note doesn't apply here -- this section *is* the
diagonal-specific fix; nothing analogous exists for horizontal (single-pass
clustering, not pairwise seed fitting, so this particular failure mode is
structural to the RANSAC approach, not something horizontal shares).

## Resolved: diagonal candidate-level dedup used pivot overlap, not price proximity

Follow-up finding from the same chart review: even after the fix above,
the top-15 for T was still dominated by 8+ near-identical-looking ascending
lines. Checked concretely -- they weren't exact duplicates from the fixed
bug (none shared pivots), but genuinely distinct RANSAC fits from disjoint
pivot subsets that happened to track nearly the same price band (1.4-14%
apart) on a long, channel-trending stock. The old dedup never compared
them at all, since it only ever looked at candidates sharing pivot points.

Replaced with an actual price-proximity check (`candidates.
_candidates_are_duplicate`): two candidates are duplicates if their slopes
are similar and their fitted prices stay within `dedup_overlap_threshold *
(half_width_a + half_width_b)` of each other, sampled at both the later of
their two starting points and at "now" -- reusing the existing
`dedup_overlap_threshold`/`--dedup-threshold` knob rather than inventing a
diagonal-only one. T's total diagonal count dropped 177 -> 132. Raising
the threshold further (0.6 -> 6.0) only reduced it to 116 -- notably
weaker than horizontal dedup's response to the same knob on a similar T
cluster (28 -> 9 at `zone_width_atr=3.0`). Not fully understood: either
these really are more genuinely-distinct trendlines than they visually
appear (plausible, same as AAPL's COVID-era horizontal density turning out
to be real), or the 2-point sampling is still missing pairs that are close
across most of their range but diverge at one of the two checked points.

## Resolved: diagonal merges were displaying/scoring events against the wrong geometry

Most serious finding from the same review round -- user-reported "floating
markers" and zones seeming to not start from any real bar. Root cause:
`lifecycle._absorb` unioned pre-computed events from merged candidates
directly, which is only safe when the merged zones are close *everywhere*,
not just at the points a proximity check happened to sample. Horizontal's
constant bounds guarantee this; diagonal's price-proximity dedup (see
above) only samples 2 points, so two candidates could pass that check
while diverging meaningfully elsewhere along their span. After merging,
*every* event -- including ones originally validated against the *other*
candidate's zone -- got displayed and scored against the survivor's single
final geometry.

Confirmed concretely on a real T line: a ~0.5%-wide band had dozens of
touch/break events whose actual close price sat 5-49% away from it --
physically impossible for a genuine interaction with that narrow a zone.

Fixed by re-classifying events from scratch against the survivor's own
kept geometry on every diagonal merge, instead of unioning stale ones
(`events.classify_events` gained an optional `start_ts` override so it can
be called with a `Line`, which has no `.pivots`, as the "candidate").
Verified: max deviation on T's top-15 diagonal lines dropped from 49.6% to
12.6%. The remaining gaps are explained, not bugs: mostly genuine (a BREAK
event's `end` is several bars after the actual crossing, by which point
price may have kept moving away -- that's what a real, continuing
breakdown looks like) -- except one, a same-day TOUCH with a 12.6% gap on
T, 2023-01-24, which traces to a **pre-existing bad data point**: that
day's bar has `high=17.81` against `open=15.69`/`close=15.85`, an ~13%
intraday spike that fully reverses within the same session. Not caught by
the current validation gate (`data.py`'s hard checks only verify internal
OHLC consistency; the soft day-over-day jump check only looks at
close-to-close continuity, not intraday range plausibility) -- a real,
separate data-quality gap, unrelated to sr_lines logic. Not yet
investigated further or fixed; flagged in `docs/backlog.md`.

Cost: `_absorb` now does a full `classify_events` pass (O(bars)) on every
diagonal merge instead of a cheap list union -- detection is noticeably
slower again (~25s vs ~8-10s on T's long_term window). Not yet optimized;
correctness took priority.

## Resolved (volume half): a level touched on high volume now outscores one touched on low volume

Originally raised alongside penetration depth as a combined "erosion
signal" idea (see below for the still-open penetration-*trend* half).
`Event.volume_ratio` (vs. 20-day average volume) was captured on every
event but never referenced anywhere in `scoring.py` -- a level touched 4
times on high volume scored identically to one touched the same way on
thin volume.

Fixed via a new `scoring._volume_factor(volume_ratio)`: neutral (1.0, no
adjustment) at average volume or when volume data is missing (e.g. the
first 20 bars, before the rolling average warms up -- absent data isn't
penalized), capped boost up to 1.3x at 2x+ average volume, floored penalty
down to 0.7x at zero volume -- graceful on both ends, matching the style of
every other per-event factor here (`reaction_atr` capped, body-fake decay
floored), never fully zeroing out a low-volume event since it's still real
price action. Applied as a multiplier in `_event_quality_score` (so it
affects both `touch_quality` and `role_reversal`, which both consume it)
and separately in `_resilience` (a high-volume U&R reclaim is more
convincing than the same reclaim on thin volume).

Found and fixed a small related bug while in this code: `events.
_merge_adjacent` picked whichever merged event's `volume_ratio` happened to
be *later* in time, not the max -- inconsistent with `penetration_atr`/
`reaction_atr`, which both already keep the max across a merged cluster.
Fixed to match.

## Resolved: the "hovering" bug -- duration_density's in-play fraction diluted into irrelevance by saturated components

Third real diagonal bug this review round, and the most fundamental one --
user kept seeing the same "lines don't track real price" complaint across
multiple rounds ("we don't get any progress") even after the dedup and
event/geometry fixes above, on a fresh AAPL chart.

Drilled into the actual top-15 AAPL diagonal lines directly rather than
guessing further: **every single one** had `resilience=1.000` and
`role_reversal=1.000` -- both fully saturated. Unsurprising for a
long-history line: over 6-8 years a real stock crosses any given trendline
many times, easily accumulating enough break/reclaim cycles to hit those
caps. Meanwhile `duration_density` (which used to bundle `span_score *
fraction_in_play` together) sat at 0.19-0.53 -- correctly detecting that
these lines spent a lot of their claimed lifetime far from where price
actually was, but at its ~0.20-of-0.90 additive weight, that signal
couldn't meaningfully suppress a line that was maxed out on three other
axes. Same failure shape as the original `proximity` bug: an additive term
can't suppress a line that's strong everywhere else, because the other
weights simply absorb the loss.

**This is structurally the same bug, so it got the same fix.** Split
`duration_density` into two things that were always conceptually different:
- `_duration_score` (kept as the additive `duration_density` weighted
  component): span length only -- "has this level/trend existed long
  enough to be mature." Unchanged from the prior duration_density fix.
- `_in_play_fraction` (new): fraction of the line's own [first_event,
  last_event] span where price actually stayed within 3 ATR of it, as
  opposed to the line extrapolating through empty space. This is now a
  **second multiplicative gate** (`in_play_gate`, alongside `relevance_gate`)
  on the whole score, not an additive term -- so it can no longer be
  "bought back" by touch_quality/resilience/role_reversal being strong.

Verified on the same AAPL run: `in_play_gate` values for the old top-15
ranged 0.28-0.53, and applying it multiplicatively dropped the top score
from 0.368 to 0.202 and meaningfully re-ranked the list (several lines with
better in-play fractions displaced ones that were previously winning purely
on saturated touch_quality/resilience/role_reversal). Applies uniformly to
horizontal too (checked -- values there ranged 0.27-0.84 across AAPL's
top-10 horizontal zones, no degenerate output).

`ScoreBreakdown` gained an `in_play_gate` field so this is visible in hover
text/JSON like every other component. Diagonal equivalent note doesn't
apply -- this fix already covers both kinds identically, same formula.

## Resolved: a diagonal merge could pull the survivor's displayed start back past its own fitted geometry

Fourth diagonal dedup/merge bug found this review round, and found from a
plain user question rather than a complaint: a fresh AAPL chart showed one
clearly visible diagonal line, and the user asked "where is this starting
from?"

That line (`d81`) had `first_touch="2018-09-10"`. Its fitted price at that
date was $67.97 -- but AAPL actually closed at $51.62 that day, a ~30%
mismatch. Pulling the underlying candidate's raw pivot list directly showed
all 5 of its actual defining pivots span 2020-07-13 through 2026-02-06 (each
fitting the final line within 0.1-0.4%, an essentially perfect fit for the
geometry the candidate was actually built from) -- nothing about the line's
own geometry had anything to do with 2018.

Root cause: `lifecycle._absorb`'s horizontal-derived line
`survivor.first_touch = min(survivor.first_touch, absorbed.first_touch)`
was applied unconditionally, including for diagonal merges. That's valid
for horizontal, where a zone's bounds are a constant (lo, hi) -- if the
zone was there, "it was touched earlier too" holds regardless of when.
It's not valid for diagonal: the survivor keeps its *own* slope/intercept
through a merge (a merge never refits them), so pulling the displayed
start back to an absorbed candidate's earlier `first_touch` renders the
box across a period the survivor's fitted line was never actually fit
against or validated for. Compounding this, the price-proximity dedup
check that allows a diagonal merge (`candidates._candidates_are_duplicate`)
only verifies agreement from the *later* of the two candidates' own starts
onward -- it never checks the region before that, so nothing had ever
confirmed the two candidates' geometries actually agreed back in 2018 in
the first place.

Fixed: `_absorb` now only extends `first_touch` backward for horizontal
merges. Diagonal survivors keep their own original `first_touch`
unconditionally, regardless of what gets absorbed into them. Verified on
a fresh AAPL long_term detection run: the top diagonal line's `first_touch`
is now `2020-07-13`, exactly its own earliest defining pivot, with a fitted
price ($149.85) within 1.6% of the real close that day ($147.54) -- sane,
where before the mismatch was ~30%.

## Still open: the penetration-depth *trend* half of the erosion signal

The other half of the original idea -- is a level getting tested with
*deepening* penetration over time (erosion, weakening) or *shallowing*
penetration (fortification, strengthening) -- is still not built. This is
a genuinely different question from volume (which is now resolved, see
above) and from `resilience`/`touch_quality` (which measure evidence
*strength*, not *direction* over time): the same 5-touch line could read
as either story depending on the shape of those 5 touches' penetration
depths, not their count or individual strength. Proposed approach
unchanged from the original idea: first-half vs. second-half average
`penetration_atr`, or a simple slope, as its own signal rather than folded
into `resilience`. Deferred to the milestone-7 weight-tuning pass -- build
it, then check it against real charts where a level visually reads as
"getting eaten through" vs. "rock solid" and confirm the number agrees.

Diagonal equivalent: the same trend-based approach should apply directly --
a diagonal band being tested with deepening penetration on each touch is
the same erosion story, just against a sloped level instead of a flat one.

## Reviewed and confirmed by design: an old, decisively-broken trendline scores near zero once price has run away from it

User hand-drew an obvious multi-year descending resistance on a PAAS chart
(2020 high ~$37 down to ~$12-13 by 2026) and asked why nothing like it shows
up in the top-N. Investigated with real data rather than assuming a bug:
the matching candidate does exist and fits tightly --
`fit_rms_atr_pct=0.075` (one of the best fits in the whole 300-candidate
set) through pivots at 2020-08, 2021-02, 2021-05, 2024-05, 2024-08 -- and
classifies exactly as expected: touches through 2021, a clean BREAK on
2024-07-10, a fakeout retest, then a decisive break and flip to FLIPPED by
2025-01-02. A textbook "broke out of a multi-year descending resistance"
pattern.

Its score is 0.013, though, crushed by the same two gates that fixed the
"hovering" bug (see above): `relevance_gate=0.148` (PAAS is now ~3x above
where the line sits today, and the last event was ~19 months ago) and
`in_play_gate=0.217` (there's a real ~3-year idle gap, 2021-05 to 2024-05,
where price never came near the band before the eventual breakout -- the
same shape as a genuinely hovering, never-tested line, even though this one
*was* eventually tested and broken).

Confirmed with the user this is the intended tradeoff, not a bug: top-N is
about what's relevant to price *right now*, and a level price has
decisively broken and moved 3x away from has correctly aged out, even
though it was a real and well-fit pattern in its own era. No code change.
If a future need comes up for surfacing historically-significant breaks
regardless of current relevance (a separate "notable past breaks" view, or
exempting strong role_reversal evidence from `relevance_gate`), those were
the two live alternatives discussed and explicitly deferred -- see this
section if this class of complaint recurs.

## Still open / not yet built

- Whether `resilience`'s cap (1.0) needs revisiting -- a zone with enough
  events can still hit the cap even after the time-decay fix, so the decay
  change had only a modest effect on one real chaotic-vs-clean comparison
  that motivated it. Flagged, not yet acted on.
- **Possible inversion in wick-fake vs. body-fake resilience credit,
  flagged but not changed.** `_WICK_FAKE_RESILIENCE` (0.15, flat) is lower
  than a *quick* `_BODY_FAKE_RESILIENCE` reclaim (0.35 x up to ~0.86 decay
  ~= 0.30) -- meaning a level that never even closed through a zone
  (wick-fake, same-bar instant reject) currently scores as *weaker*
  evidence than one that did close through and had to recover within the
  reclaim window (body-fake). Arguable either way (a wick could reflect a
  more violent/uncertain test even though it held; a fast body-fake reclaim
  could reflect stronger following-bar conviction) -- a values judgment
  about market behavior, not an obvious bug, so left as-is pending real-chart
  discussion rather than changed unilaterally.
- Diagonal real-chart visual review (band width, dedup aggressiveness, the
  30-candidate cap, whether `max_diagonal_slope_atr_per_bar`'s log-slope
  interpretation is the right one) -- structurally verified, not yet
  visually validated.
- Milestone 6 (`as_of` dedicated test coverage beyond what's already
  implicitly correct) and milestone 7 (a systematic weight-tuning pass,
  now including diagonal-specific weights/penalty calibration) are still
  ahead, per the original spec's milestone order.
