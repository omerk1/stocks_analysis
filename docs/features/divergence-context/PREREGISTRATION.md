# Divergence-context study — Track B pre-registration

> **STATUS: FROZEN 2026-10-08** — this commit is the final pre-run state of
> DC-B1/DC-B2. From here on: **dated addenda only, never edits** — a scope
> change, a new result, or a correction is a separately dated section appended
> below the entry it concerns. The draft phase's own amendment history (with
> superseded text preserved verbatim) is in the "Amendment history" section.
> Run-mechanics discoveries that do not change any registered definition
> (hypotheses, grid, classification thresholds, matching, outcomes, verdicts,
> kill criteria) are implementation, not amendments; anything that does change
> one is an addendum, and the affected cells report under the amended
> definition with the addendum cited.

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
arm is a pre-identified Inconclusive risk** (85 matched events at the current calibration); if it reads out
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

---

## Addendum 2026-10-09 — pre-unblinding clarifications (user-approved)

Appended per the frozen header's rule, **before any outcome was computed** (the
run script's blind gate had not been crossed), prompted by code review of the run
script (PR #186). Three clarifications of registered definitions; no hypothesis,
threshold, outcome, or verdict category changes.

1. **Sign convention of the binary-vs-continuous gate.** The frozen kill
   criterion reads "the binary and continuous formulations disagree in sign."
   The binary DiD is defined extension-minus-pullback, while the continuous
   cell's b3 is the per-unit-retrace slope of the divergence effect — so a real
   context effect produces *opposite* signs in the two formulations by
   construction. The gate's registered intent is agreement about the underlying
   effect direction: **the formulations agree iff sign(DiD) × sign(b3) < 0.**
2. **Cost band for the continuous cells.** The 20 bps hurdle and the Dead band
   are defined in round-trip return units; b3 is a slope per unit retrace
   fraction. For DC-B1c/B2c the band applies to **b3 scaled to return units by
   the inter-pole retrace gap** (median retrace of the pullback pole minus
   median of the extension pole, pooled events+controls, per direction) — a
   covariates-only quantity, computed and printable blind.
3. **Plateau and gate scoping.** The 3×3 plateau is evaluated **at each cell's
   own horizon**; the binary-vs-continuous gate is direction-level as frozen
   (the registered grid has no 21d continuous cell). Each plateau neighbor is a
   full re-classification AND re-matching from the unfiltered event/control
   frames (reclassifying the frozen-threshold panel would deny widening
   neighbors the buffer-band and deep-fast events their definitions include).
   Finite neighbors must agree in sign; an incomputable neighbor is absence of
   evidence, not disagreement, and the finite count is reported per cell.

---

## Result (2026-10-09 run — the registered DC-B1/DC-B2 readout)

Executed once, `--unblind --log`, against the frozen text + the 2026-10-09
addendum; full per-cell record in `EXPERIMENTS.csv` (this run's six rows; the
CSV's date column carries the machine clock).

**All six cells: `inconclusive_underpowered`.** No cell is Alive; no cell is
Dead — every 95% clustered CI spans zero AND extends far beyond the ±20 bps
band (half-widths ≈ 1–4% per 63d trade vs a 0.2% hurdle), so an economically
meaningful effect is neither demonstrated nor ruled out.

| cell | point | 95% CI | p | arms (ext / pb) | eff. N (dates) |
|---|---|---|---|---|---|
| DC-B1a (bear, 63d DiD) | −0.0054 | [−0.0281, +0.0144] | 0.62 | −0.0017 / +0.0037 | 1,246 |
| DC-B1b (bear, 21d DiD) | +0.0022 | [−0.0096, +0.0134] | 0.71 | +0.0018 / −0.0004 | 1,267 |
| DC-B1c (bear, 63d b3) | +0.0046 | [−0.0132, +0.0224] | 0.61 | — | 1,573 |
| DC-B2a (bull, 63d DiD) | +0.0264 | [−0.0078, +0.0717] | 0.19 | +0.0242 / −0.0022 | 672 |
| DC-B2b (bull, 21d DiD) | −0.0066 | [−0.0330, +0.0280] | 0.67 | −0.0035 / +0.0030 | 686 |
| DC-B2c (bull, 63d b3) | −0.0161 | [−0.0461, +0.0139] | 0.29 | — | 966 |

Gates: plateau 9/9 finite everywhere, sign-stable except DC-B1b (failed, moot
under its verdict); formulations agree (opposite DiD/b3 signs) in both
directions. The pre-identified bullish/extension Inconclusive risk realized
exactly as registered.

**Descriptive observations — NOT findings, bare and uncorrected:** the sign
pattern is internally consistent across formulations within each direction and
opposite between directions (bearish divergence fares relatively better after
consolidation; bullish relatively better after explosive selloffs — DC-B2a's
extension arm shows +2.4%/63d vs matched controls on a 0.50 hit rate, 1.32
win/loss ratio, +1.1 skew: a crash-rebound shape on 134 months). Wide CIs
contain all of this comfortably.

**Disposition, per the frozen rules:** Inconclusive = stop; no FINDINGS.md
entries; the cells are eligible for a dated POWER addendum (era pooling
1990–2009, longer windows, or variance-reduction via the continuous
formulation only) — which would be a new, separately registered decision, not
a re-run. The context study's Track-B phase closes here unless such an
addendum is proposed.
