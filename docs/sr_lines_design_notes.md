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
  sync with `lifecycle.py`'s "flipped is sticky" state determination (see
  below) -- a line reported as FLIPPED must never have its score frozen as
  if dead. `scoring._decay_reference` and `lifecycle._break_and_flip_status`
  are two independent implementations of the same "is this actually flipped"
  logic and have already drifted out of sync once (see below) -- worth
  factoring into one shared function before diagonals duplicate the risk.

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

### `role_reversal` was binary -- fixed to be proportional

Original: `1.0` if a break was *ever* followed by any confirming
touch/wick-fake, `0.0` otherwise. Real AAPL data showed this let barely-
confirmed flips (one weak retest, near-zero touch quality elsewhere)
outscore never-broken lines with real touch-quality evidence, purely from
this one all-or-nothing bonus. Now scales with the number of confirming
touch/wick-fake events after the break, full credit at
`_ROLE_REVERSAL_CONFIRMATIONS_FOR_FULL_CREDIT = 3`. `state` (FLIPPED) stays
a binary label -- only the score contribution is graded.

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

## Still open / not yet built

- Whether `resilience`'s cap (1.0) needs revisiting -- a zone with enough
  events can still hit the cap even after the time-decay fix, so the decay
  change had only a modest effect on one real chaotic-vs-clean comparison
  that motivated it. Flagged, not yet acted on.
- `scoring._decay_reference` and `lifecycle._break_and_flip_status` are
  still two independent implementations of the same "is this actually
  flipped" check (see backtesting section above) -- already drifted out of
  sync once; worth factoring into one shared function before diagonals
  duplicate the risk a third time.
- Milestones 5 (diagonals), 6 (`as_of` dedicated test coverage beyond what's
  already implicitly correct), 7 (systematic weight-tuning pass) are all
  still ahead, per the original spec's milestone order.
