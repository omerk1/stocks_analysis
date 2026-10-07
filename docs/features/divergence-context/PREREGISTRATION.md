# Divergence-context study — Track B pre-registration

> **STATUS: DRAFT — open for discussion, nothing frozen.** Per the repo's
> protocol, an entry freezes at the commit immediately preceding its run;
> until then edits are ordinary review. After a run: addenda only, never
> silent edits.

## DC-B1 / DC-B2 — does structural context change regular-divergence outcomes?

**Module/track:** divergence-context, Track B. First pre-registered cells.
**Promoted from:** EXPLORATION_LOG 2026-10-05 step-0 entry — shape prevalence 62–69%
of regular cells with both context poles populated; 29.2% entanglement (abundant
no-divergence controls); monotone invalidation ordering across the structure spectrum
(45.7% / 41.3% / 38.9%, bare rates).

**Hypothesis.** For regular divergences, forward outcomes after events in
*extension* context (little/no reset before the second pivot) differ from events in
*pullback+rebuild* context (meaningful retracement then rebuild), beyond what the
same structures show *without* a divergence. DC-B1 = bearish, DC-B2 = bullish.
Direction of the difference is deliberately not pre-committed — normalization vs
deterioration is exactly the open question.

### Event set

- Regular-form, **RSI only** for the primary test (largest single-indicator set; no
  duplicate-swing pooling across indicators — a swing printing on 2 indicators is one
  piece of evidence, not two events). **MACD-hist repeats as a pre-named same-sign
  robustness pass**, not a new hypothesis: the speed-normalization mechanism applies
  to it as much as to RSI, and sign agreement there is the generalization check
  without doubling N_tests. If the two disagree in sign, that disagreement is itself
  the result, and any pooled momentum cell is a new, later registration.
- **OBV is excluded from these cells by mechanism, not oversight**: it cumulates
  volume flow (participation), not price speed — a calm second leg does not
  mechanically depress OBV highs, so the normalization-vs-deterioration frame does
  not apply to its divergences. (Decided 2026-10-06, draft stage.)
- Hidden forms are **not** in these cells — see "Hidden forms — planned second
  experiment" below. (Decided 2026-10-06: separate experiment, own correction,
  never combined into this one's N_tests.)
- Window: p2 dates 2010-01-01..2021-12-31 (the repo's supported development window);
  1990–2009 as a robustness era split only. Holdout untouched.
- Universe: PIT S&P 500 + Nasdaq-100 membership at p2 (rename-aware). Delisted
  members included; delisting-terminal returns realized, never dropped.
- Events with undefined context scalars (NaN impulse — short pre-p1 history) are
  excluded and counted in the report.

### Context classification (at event time, from stored scalars)

- **Extension:** `interpeak_retrace_frac < 0.25`.
- **Pullback+rebuild:** `interpeak_retrace_frac >= 0.33` and `leg2_bars >= 5`.
- Deep-fast (retrace ≥ 0.33, rebuild < 5 bars) and the 0.25–0.33 buffer band sit in
  neither pole: excluded from the primary contrast, reported descriptively. The
  buffer exclusion is deliberate (decided 2026-10-06): boundary-noise events dilute
  the contrast (attenuation), and nothing is lost study-wide — the continuous tests
  (c-cells) use every event including the band, and the plateau neighborhood probes
  the thresholds.
- **Plateau rule (DESIGN §, inherited):** the contrast must agree in sign at
  neighboring thresholds — retrace ∈ {0.25, 0.33, 0.50} × leg2_bars ∈ {3, 5, 8}. A
  lone bright cell at (0.33, 5) is noise and will be called noise.

### Controls (the load-bearing part)

Matched **no-divergence** pivot pairs: consecutive same-kind price-pivot pairs with
regular geometry (bearish: higher high; bullish: lower low), span ≥ 5 bars, same
context classification, and **no stored divergence of the tested direction/form
within ±3 bars of p2** (any indicator). Step 0 measured this pool at ~71% of shaped
pairs — the PULLBACK pools are plentiful. **The extension pools are not** (balance
report, 2026-10-07: 830 bearish / 232 bullish PIT controls vs 1,221 / 328 events):
an explosive new extreme *without* a divergence is mechanically scarce — the mirror
of step 0's entanglement finding. Recorded now, pre-freeze: the **bullish/extension
arm is a pre-identified Inconclusive risk** (74 matched events at the current calibration); if it reads out
Inconclusive, that was expected at registration, not discovered at readout.

- Matching (amended 2026-10-07/08 to what the build implements and the balance
  report validated): hard cell = p2 calendar month (within direction × context
  class); covariates bucketed on POOLED events+controls quantiles **computed per
  direction × context class** (cross-class pooling makes the retrace caliper
  vacuous inside the extension class, whose values all sit below pullback-dominated
  edges) — impulse_gain_pct deciles, realized_vol_63 quintiles,
  interpeak_retrace_frac quintiles — with a **±1-bin caliper** per covariate
  (exact-bin cells are brittle at bin edges); within the caliper, nearest by raw
  impulse distance, retrace then vol as tiebreakers; up to 3 controls per event,
  without replacement, assigned in **breadth-first rounds** over a seed-fixed random
  event order — every event receives its rank-r control before any event receives
  rank r+1 (amended 2026-10-08: depth-first take-3 let early events empty a scarce
  cell's caliper and starve later ones, understating matched counts exactly in the
  thin extension arms; rank-1 assignments are identical, total matched events
  strictly ≥).
- **Sanctioned exception to the rolling-statistics invariant (#3), stated
  explicitly:** the quantile edges are a dev-window (full-sample) statistic.
  Matching is ex-post control construction at analysis time, not a tradable
  feature — nothing downstream treats a bin as a point-in-time quantity.
- **interpeak_retrace_frac is the third matching covariate** (amended 2026-10-07):
  matched on impulse+vol alone it retained SMD −0.37/−0.50 within the pullback
  class — events sit shallower in the class than their controls, a within-class
  confound. It is a covariate, not the treatment: treatment is divergence presence.
- Control timing: a control pair's "event time" is its p2 pivot's own price-only
  `confirmed_at`. Divergence events confirm at max(price, indicator) confirmation, so
  events enter on average slightly later than controls — a level difference the
  difference-in-differences absorbs; noted, not "fixed."

### Outcome, effect, inference

- Entry: open of the bar after `confirmed_at` (one-bar lag, repo invariant #2).
- Primary outcome: 63-trading-day forward log return (delisting-terminal); secondary:
  21-day. MFE/MAE and invalidation are descriptive context only in these cells.
- **Per-horizon confirmation cutoffs (added 2026-10-08):** each horizon includes
  only entities whose full h-bar window fits inside the dev window — a series
  ending at the loaded boundary is right-censored and contributes nothing to that
  horizon, while a series ending *before* the boundary is a delisting whose
  terminal return is kept and flagged (the two are distinguished explicitly in
  `forward_returns.py` via its `data_end` parameter; conflating them would smuggle
  shortened holds into the late-window cells). `data_end` is enforced fail-closed —
  no entry or exit bar past it produces a return regardless of how the caller
  loaded bars — and the run passes each ticker's delisted status (tickers table)
  explicitly, with the calendar-tolerance inference only as the no-information
  fallback (added 2026-10-08).
- **Effect = difference-in-differences:**
  `(div_extension − ctrl_extension) − (div_pullback − ctrl_pullback)`.
  A bare divergence-vs-control difference within one context is reported but is not
  the registered hypothesis.
- Inference: date-clustered SEs (cluster = p2 calendar month) with block-bootstrap
  confirmation, reusing `src/signals/moving_averages/stats/inference.py`. Effective N
  = distinct p2 dates per cell, reported in every table (invariant #6).
- Distribution shape (hit rate, win/loss magnitude, skew) reported per cell —
  descriptive only, no CI, no `N_tests` contribution (invariant #10).

### Registered test grid and multiplicity

| id | direction | outcome | formulation |
|----|-----------|---------|-------------|
| DC-B1a | bearish | 63d fwd ret | binary DiD |
| DC-B1b | bearish | 21d fwd ret | binary DiD |
| DC-B1c | bearish | 63d fwd ret | continuous: fwd ret ~ divergence × retrace_frac (clustered) |
| DC-B2a | bullish | 63d fwd ret | binary DiD |
| DC-B2b | bullish | 21d fwd ret | binary DiD |
| DC-B2c | bullish | 63d fwd ret | continuous interaction |

**N_tests = 6**, BH-corrected together. MACD-hist robustness, era split, and plateau
neighbors are robustness checks on these six, not new tests.

### Verdicts and kill criteria (pre-committed)

Three verdicts per cell, not two (amended 2026-10-07, draft stage: "CI includes 0
and point < hurdle" conflated a demonstrated null with an underpowered cell):

- **Alive**: BH-corrected 95% clustered CI excludes 0 and the point estimate clears
  the cost hurdle.
- **Dead** — a demonstrated economic null, and a successful outcome: the **entire
  95% CI sits inside the cost-hurdle band (±hurdle)** — an effect big enough to
  matter is affirmatively ruled out.
- **Inconclusive**: the CI includes 0 but extends beyond the hurdle band on either
  side — the cell lacked the power to decide. Operationally also a stop, but logged
  as *underpowered*, never as dead; a power amendment (era pooling, longer window)
  may be proposed as a dated addendum, a dead cell gets none.

The cost hurdle is **pre-committed at 20 bps round-trip** (conservative for this
universe's mid-cap and delisted tail; one round trip per signal at the 63d horizon),
with the 10 bps liquid-core variant annotated alongside every gross number
(invariant #8). Decided 2026-10-06: the stricter number is the hurdle so a surviving
effect is robust to the cost assumption, not flattered by it.

Additionally, a cell cannot be Alive if:
1. the plateau check fails — the effect's sign is not stable across the 3×3 threshold
   neighborhood (a lone bright cell demotes to Inconclusive at best); **or**
2. the binary and continuous formulations disagree in sign for the same direction.

Every cell's verdict — Alive, Dead, or Inconclusive — gets logged the same way
(`EXPERIMENTS.csv`-style row; file created for this study at first Track-B result).

## Hidden forms — planned second experiment (DC-B3/DC-B4, not yet drafted)

Hidden divergence tests the opposite-shaped claim (continuation, not reversal), its
extension pole is ~20× thinner than its pullback pole (step 0: ~91% of hidden events
are pullback+rebuild — near-mechanical, since hidden requires price to hold inside
its prior extreme), and the v0 impulse scalar mismeasures its structure
(retrace_frac medians > 1: p1 is often not an impulse top for hidden events).
Combining it into DC-B1/B2 would tax their BH correction to fund a hypothesis known
to be badly instrumented, so it is its own experiment, gated on two Track-A prep
looks:

1. **Co-occurrence**: how often do a hidden bullish (at the pullback low) and a
   regular bearish (at the new high) mark the same structure, and how do outcomes
   look where the two labels "disagree" — i.e., is hidden independent information or
   the regular cells' complement?
2. **Scalar rework**: an impulse measure that fits hidden geometry (normalized to
   local trend or pivot-to-pivot structure, not a fixed 63-bar window).

DC-B3/B4 get drafted only if those motivate them, with their own N_tests and
correction. Nothing here constrains DC-B1/B2's run.

## Amendment history (superseded draft text, preserved verbatim)

The draft header makes pre-freeze edits legitimate, but the matching definition was
executed (covariate-balance runs) between amendments — so per the spirit of the
repo's no-silent-edit convention, the superseded wording is preserved here rather
than left to git history:

- **Matching, as first drafted (2026-10-06, superseded 2026-10-07/08):** "Matching:
  within p2 calendar month, nearest-neighbor on (impulse_gain_pct decile, trailing
  63-day realized-vol bucket), up to 3 controls per event, sampled without
  replacement." Superseded by: per-class pooled-quantile bins, the ±1-bin caliper,
  the retrace third covariate, and breadth-first assignment (each dated inline
  above, with the balance evidence in PR #179/its follow-up).
- **Control-pool sizing, as first drafted (2026-10-06):** "Step 0 measured this pool
  at ~71% of shaped pairs — controls are plentiful." Superseded 2026-10-07: true for
  the pullback pools only; the extension pools are thin (see the Controls section).

### Prerequisites before this can run (implementation, separate PR)

1. Control-pair extraction and storage (productionize step 0's Q2 machinery: pairs,
   context scalars, price-only confirmed_at, no-divergence flag).
2. Forward-return computation for events and controls (lagged entry,
   delisting-terminal, dev-window-bounded).
3. Matching implementation + match-quality report (covariate balance before/after).
4. The run itself happens only after this file's content is frozen by its final
   pre-run commit; any later scope change is a dated addendum.
