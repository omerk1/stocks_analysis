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

---

## Addendum 2026-10-09 — record notes on the DC-B1/B2 readout (no definitions changed)

1. **The MACD-hist same-sign robustness pass was not run, and is moot under the
   disposition.** The frozen text named it as a generalization check on the six
   registered tests; its role was to confirm or contradict an Alive RSI result.
   With all six cells Inconclusive there is nothing for sign agreement on noise
   to establish. If a power addendum revives the cells, the robustness pass
   revives with them.
2. **Survivorship caveat on the event base (found by the R/R sweep thread,
   backlog "Signals" / Done #103).** The `divergences` and
   `divergence_control_pairs` tables contained zero delisted tickers at run
   time — the backfills covered tickers with yfinance bars, while delisted
   members' bars exist only under the Tiingo sources. This registration's
   "delisted members included; delisting-terminal returns realized" therefore
   held for the forward-return machinery but **vacuously for the event base**:
   the readout's cells are survivors-only, which biases weak-trend buckets
   upward (repo invariant #4) and most plausibly flatters the bullish arms.
   The Inconclusive verdicts stand (a survivors-only Inconclusive is still
   Inconclusive), but any power addendum or DC-B5 must run on the recomputed,
   fallback-covered event base (backlog lists the pending recompute steps).

---

## Addendum 2026-10-10 — the event base was recomputed (no definitions changed)

The survivorship caveat in the 2026-10-09 addendum (note 2) points to backlog
steps that have now run (Done #112). `divergences` now includes every delisted
ticker the vendor fallback covers — 117 added, all 111 delisted S&P 500/NDX
members with 2010–2021 membership among them — and the 7 whole-history-disputed
tickers are gone. `divergence_context` and `divergence_control_pairs` were
rebuilt on that base. The DC-B1/B2 readout above is not re-run by this; its
numbers remain survivors-only as recorded. Any power addendum or DC-B5 runs on
the recomputed base.

---

## DC-B3 / DC-B4 — DRAFT 2026-10-11, NOT FROZEN: does retracement depth change hidden-divergence outcomes?

> **STATUS: DRAFT.** Pre-freeze edits are legitimate here (substantive ones noted in
> the draft history at the end of this section); the section freezes at the final
> pre-run commit of its run PR, after which the frozen header's dated-addenda-only
> rule applies. Nothing in this section alters any DC-B1/B2 text above.

**Module/track:** divergence-context, Track B. Second (and, per the disposition below,
final) registered experiment of this study.
**Promoted from:** EXPLORATION_LOG 2026-10-11 hidden-forms prep looks (Done #119) —
both prep gates the "Hidden forms" section above required: (a) hidden is independent
information, not the regular cells' complement (only 29–34% of hidden events carry a
mirrored-direction regular counterpart inside their pivot interval; hidden-alone cells
~1,490–1,530 PIT dev dates); (b) the pivot-to-pivot retrace fraction is a well-defined
hidden-geometry scalar (100% defined, mechanically bounded in (0,1), smooth) where the
v0 63-bar impulse was shown misfit (retrace_frac > 1 on 66%/76% of defined hidden rows).

**Hypothesis.** Hidden divergence is a continuation claim. For hidden divergences,
forward outcomes after a *shallow* counter-move (trend barely dented — the textbook
"strong trend" continuation setup) differ from outcomes after a *deep* counter-move
(trend nearly given back), beyond what the same hidden-geometry structures show
*without* a divergence. DC-B3 = bearish (downtrend, lower-high pairs), DC-B4 = bullish
(uptrend, higher-low pairs). Direction of the difference is deliberately not
pre-committed.

### Event set

- **Hidden form, RSI only** for the primary test (largest single-indicator hidden set;
  no duplicate-swing pooling across indicators). **MACD-hist repeats as a pre-named
  same-sign robustness pass**, not a new hypothesis — same speed-oscillator reasoning
  as DC-B1/B2. **OBV excluded by mechanism**, as there: its hidden divergence (volume
  flow breaking while price holds its trend) is a participation claim, not a momentum
  one; any OBV cell is a separate, later registration.
- Window: p2 dates 2010-01-01..2021-12-31. Universe: PIT S&P 500 + Nasdaq-100
  membership at p2 (rename-aware), delisted members included, delisting-terminal
  returns realized. **Runs on the recomputed event base (Done #112)** — the first
  registration of this study drafted after the survivorship recompute, so DC-B1/B2's
  2026-10-09 addendum-note-2 caveat does not apply.
- **Context scalar: the hidden-fit retrace fraction** — counter-move / trend-leg,
  derived at analysis time from the stored scalars:
  `leg2_gain_pct × (1 + interpeak_retrace_pct) / interpeak_retrace_pct` for LOW pairs
  (bullish), the `(1 − interpeak_retrace_pct)` variant for HIGH pairs (bearish); NaN
  wherever an input is NaN or the trend leg is ≤ 1e-6 of p1's close (invariant #9) —
  the formula and NaN/eps discipline of
  `src.analysis.divergence_hidden_prep.hidden_fit_retrace_frac`, with that function's
  hidden-form domain mask replaced, for control pairs (which carry no `form`), by the
  strict pair-geometry filter in the Controls section. Undefined rows are excluded
  and counted. Measured definedness on this base, blind: events 100.0% (the Done #119
  prep), control pairs 100.0% (`src/analysis/divergence_dcb3b4_sizing.py`, committed
  with this draft).

### Context classification (at event time, from the scalar above)

- **Poles by within-direction terciles of the EVENT distribution** (RSI events, per
  direction): **shallow = tercile 1, deep = tercile 3**; the middle tercile is the
  buffer — excluded from the binary contrast, included in the continuous cells.
  Controls are classified by the same event-derived edges. Event arms are thirds **by
  construction** (pooled-edge terciles would not guarantee this: the control pools
  are 1.9–2.7× larger and DC-B1/B2's balance work showed events sit systematically
  shifted within a class, so pooled edges could quietly re-create the starved-arm
  failure this design exists to avoid — DC-B2a's extension arm had 85 matched
  events). Control-arm counts and per-pole control:event coverage are part of the
  blind balance report. Tercile edges are the same sanctioned full-sample
  cell-defining-bin exception as the matching bins (invariant #3 note in DC-B1/B2).
  *Why terciles and not DC-B1/B2's fixed edges:* the prep showed the
  regular-geometry 0.33 edge leaves a 5–10% shallow pole (259/531 PIT dates), and no
  prior literature pins a natural edge for this scalar. **Edge scoping, registered
  now:** the MACD-hist robustness pass re-derives tercile edges from its OWN event
  distribution (the registered procedure applied to the robustness indicator — the
  pass is a standalone re-run of the design, as DC-B1/B2's was); the era-split facet
  reuses the full-window edges (eras split the registered cells, they do not
  re-register them).
- **Plateau rule:** the binary contrast must agree in sign under two pre-named
  re-classifications — **quartile poles (Q1 vs Q4)** and a **median split** (both on
  the event distribution) — each a full re-classification AND re-matching from the
  unfiltered event/control frames (DC-B1/B2's 2026-10-09 addendum item 3 semantics).
  Finite neighbors must agree in sign; an incomputable neighbor is absence of
  evidence, and the finite count is reported per cell. **The plateau gate is
  direction-level**, like the binary-vs-continuous gate: sign instability of a
  direction's binary contrast blocks Alive for both of that direction's cells (a and
  b).

### Controls

Matched **no-divergence** pivot pairs with **strict hidden geometry** — bearish:
`p2_price < p1_price` (lower high); bullish: `p2_price > p1_price` (higher low) — the
explicit price comparison, NOT `regular_geometry = 0` alone, which also admits
equal-extreme pairs that are neither geometry and for which the scalar's (0,1) bound
argument does not hold. Span ≥ 5 bars, same context class, and **two divergence
exclusions**:

1. `has_divergence = 0` — the stored flag, which the builder computes against
   **regular** stored divergences of the same direction (±3 bars of p2, any
   indicator);
2. **no stored HIDDEN divergence of the same direction within ±3 bars of p2 (any
   indicator), consulting only stored rows with `confirmed_at <= 2021-12-31`** —
   the study's dev-window truncation; the pool definition must not read holdout
   rows (invariant #1). Without this exclusion the pool contains the treatment
   itself: a hidden pair IS a strict-hidden-geometry pair, and sizing measured the
   contamination at 37–44% of the pool (16,333 → 10,247 bearish; 22,534 → 12,706
   bullish rows, ±5 calendar days as the sizing approximation of the bar rule).
   Implementing this exclusion exactly (±3 bars) is prerequisite 1.

Control timing is the pair's own price-only `confirmed_at`; events confirm at
max(price, indicator) and so enter slightly later on average — a level difference the
difference-in-differences absorbs, noted as in DC-B1/B2.

- Matching mirrors the DC-B1/B2 build as amended and balance-validated: hard cell =
  p2 calendar month within direction × context class; covariates bucketed on POOLED
  events+controls quantiles computed per direction × context class (pooled bins are
  the matching convention; only the pole-defining tercile edges are event-only, per
  the classification section) — **`interpeak_retrace_pct` deciles** (the trend-leg
  magnitude: hidden geometry's analogue of impulse_gain_pct), **`realized_vol_63`
  quintiles**, **hidden-fit fraction quintiles** (the within-class depth confound,
  playing retrace_frac's DC-B1/B2 role) — ±1-bin caliper per covariate; within the
  caliper nearest by raw trend-leg distance, depth then vol as tiebreakers; up to 3
  controls per event, without replacement, breadth-first rounds over a seed-fixed
  random event order.
- A match-quality (covariate balance) report runs before any outcome is read, as for
  DC-B1/B2.

### Outcome, effect, inference

- Entry: open of the bar after `confirmed_at` (invariant #2). Primary outcome:
  **63-trading-day forward log return** (delisting-terminal; fail-closed `data_end`;
  per-horizon confirmation cutoff — all exactly the DC-B1/B2 machinery). **No 21-day
  cells**: DC-B1b/B2b added noise and N_tests, not information.
- **Binary effect = difference-in-differences:**
  `(div_shallow − ctrl_shallow) − (div_deep − ctrl_deep)`.
- **Continuous effect:** fwd ret ~ divergence × hidden-fit fraction, over all events
  and controls (middle tercile included), date-clustered (p2 calendar month) with
  block-bootstrap confirmation; the cost band applies to **b3 scaled to return units
  by the inter-pole gap** (median hidden-fit fraction of the deep pole minus the
  shallow pole, over pooled events+controls classified by the event-tercile edges,
  per direction — covariates-only, printable blind), per the DC-B1/B2 2026-10-09
  addendum item 2.
- Effective N = distinct p2 dates, in every table (invariant #6). Hit rate, win/loss
  magnitude ratio, skew reported per cell — descriptive only (invariant #10). Costs:
  20 bps round-trip hurdle primary, 10 bps liquid-core annotated (invariant #8).

### Registered test grid and multiplicity

| id | direction | outcome | formulation |
|----|-----------|---------|-------------|
| DC-B3a | bearish | 63d fwd ret | binary DiD (shallow − deep) |
| DC-B3b | bearish | 63d fwd ret | continuous: fwd ret ~ divergence × hidden-fit frac |
| DC-B4a | bullish | 63d fwd ret | binary DiD (shallow − deep) |
| DC-B4b | bullish | 63d fwd ret | continuous interaction |

**N_tests = 4**, BH-corrected together, separate from DC-B1/B2's correction (as the
"Hidden forms" section committed). Robustness checks on these four, never new tests:
MACD-hist same-sign pass; era split 2010–2015 / 2016–2021; the two plateau
re-classifications; a **co-occurrence facet** (split by whether a mirrored-direction
regular counterpart was confirmed by the event's own `confirmed_at` — the prep's
`counterpart_confirmed_first`, ~30% of hidden events); a **counter-move duration
facet** (`leg2_bars` terciles — duration is deliberately a facet, not a pole
dimension, to keep the primary contrast one-dimensional).

### Verdicts and kill criteria (pre-committed; three-verdict rule as in DC-B1/B2)

Three verdicts per cell:

- **Alive**: BH-corrected 95% clustered CI excludes 0 and the point estimate clears
  the cost hurdle.
- **Dead** — a demonstrated economic null, and a successful outcome: the entire 95%
  CI sits inside the cost-hurdle band (±hurdle).
- **Inconclusive**: the CI includes 0 but extends beyond the hurdle band on either
  side — underpowered, never logged as dead.

**One deliberate difference from the DC-B1/B2 wording, stated rather than smuggled:**
their Inconclusive verdict carries "a power amendment … may be proposed as a dated
addendum"; for these cells that clause is **replaced** by the pre-committed
no-power-addendum disposition below — the power analysis has already been done at
registration time, so an Inconclusive readout here is final.

Additionally, a cell cannot be Alive if (1) the direction-level plateau check fails
(see the plateau rule above), or (2) the binary and continuous formulations disagree
about the underlying direction — by construction (DiD is shallow-minus-deep; b3 is
per-unit-depth slope) **the formulations agree iff sign(DiD) × sign(b3) < 0**. Every
cell's verdict goes to `EXPERIMENTS.csv`; Tier 1–3 survivors to `FINDINGS.md`.

### Pre-identified power risk and pre-committed disposition (the load-bearing part)

Sized blind on the recomputed base — counts and covariate definedness only, no
outcome read — by `src/analysis/divergence_dcb3b4_sizing.py` (committed with this
draft, output reproducible): RSI hidden events, PIT, dev window: **DC-B3 3,758 rows /
1,334 distinct p2 dates; DC-B4 6,780 / 1,451**; control pools after the strict
geometry and both divergence exclusions: **10,247 / 12,706 rows (2,011 / 2,067
dates)** — 1.9–2.7× the event sets in aggregate, with per-pole coverage deferred to
the blind balance report.

The power implication is derivable from this file's own registered DC-B1/B2 readout
(the 2026-10-09 result table above), with no external citation: its four 63d cells
ran at 672–1,573 effective dates and produced 95% CI half-widths of ≈ 1.8–4.0% per
63d trade against the ±0.2% hurdle band. DC-B3b/B4b (continuous, all events) run at
1,334 / 1,451 dates — inside that range, so comparable half-widths follow by √N
scaling. DC-B3a/B4a (binary DiD) use only the outer terciles, ≈ two-thirds of those
dates split across two arms (plus two control arms), so their effective per-arm N is
roughly a third of the events and their CIs are wider still — DC-B1a/B2a, the
corresponding DiD cells, showed exactly that (±2.1% / ±4.0%). Hence:

- **Dead is unreachable in these cells.** Shrinking a ≈ 2% half-width inside a
  ±0.2% band needs ~10× tighter CIs, i.e. on the order of **100× the effective N**;
  no admissible extension supplies it (even tripling N buys only √3 ≈ 1.7×, and
  pre-2010 data is outside the repo's supported development window — CLAUDE.md
  invariant #1's 2026-09-07 revision note). The registered cells can therefore only
  read **Alive** or **Inconclusive** — and Alive requires a true effect ≳ ~2% per
  63d for the continuous cells, larger still for the binary DiD cells. This is registered
  knowingly: the event-tercile design removes DC-B1/B2's starved-arm failure mode,
  the build/matching/inference machinery exists, and the run is cheap.
- **Pre-committed disposition if no cell is Alive:** the hidden Track-B line closes —
  **no power addendum will be proposed** (the paragraph above is that analysis, done
  at registration instead of after the readout), and the hidden-fit retrace fraction
  routes to the combined-model feature track as a continuous feature (IDEAS F6 /
  LRP §2.4, whose constraint 2 already mandates hidden/regular form separation). The
  experiment is decision-complete at registration: every outcome has a pre-named
  next step.

### Prerequisites before this can run (implementation, separate PR)

1. **The hidden-divergence control exclusion**: extend the controls machinery
   (`controls.flag_divergences` computes against regular form only) so hidden-form
   stored divergences of the same direction within ±3 bars of p2 (any indicator,
   `confirmed_at <= 2021-12-31` — never holdout rows) also disqualify a pair — as a
   second flag column or an analysis-time join; the registered pool is defined by
   BOTH exclusions.
2. Extend the Track-B machinery (`divergence_trackb_balance.py`,
   `divergence_trackb_run.py`, matching) to hidden geometry: the hidden-fit scalar
   as the classification/matching input, event-tercile classes, strict-geometry
   control pools.
3. The co-occurrence and duration facets wired as report splits.
4. Balance report run and reviewed blind (before any outcome) — including per-pole
   control:event coverage and minimum-arm counts.
5. The run happens only after this section's final pre-run commit freezes it; the
   runner stays blind-by-default with `--unblind` crossed exactly once.

### Draft history (pre-freeze edits, per the no-silent-change spirit)

- 2026-10-11, same day as first commit, after code review and a re-run of the blind
  sizing: control pool redefined from `regular_geometry = 0, has_divergence = 0` to
  strict price-inequality geometry plus the explicit hidden-divergence exclusion
  (the stored flag covers regular form only — the first definition left hidden
  treatment structures in the pool, measured at 37–44% of it; superseded pool
  counts: 16,412 / 22,587 rows, 2,283 / 2,344 dates); pole terciles moved from the
  pooled events+controls distribution to the event distribution (pooled edges could
  not guarantee balanced event arms); the power argument re-derived from this file's
  own DC-B1/B2 readout table and the sizing script committed (the first draft cited
  an unmerged power-addendum analysis, which is not citable); the Inconclusive
  verdict's deviation from DC-B1/B2 wording made explicit; the plateau gate scoped
  direction-level.
- 2026-10-11, same day, second review round: the hidden-divergence exclusion (and
  the sizing script) bounded to stored rows with `confirmed_at <= 2021-12-31` — the
  first version consulted full-history (holdout-era) rows, letting post-2021 events
  shape the dev-window pool (invariant #1; corrected bullish pool 12,705 → 12,706);
  the power paragraph's half-width range restated 63d-only (1.8–4.0%, not 1.2–4.0%
  which included the 21d cells) with the binary cells' smaller per-arm N stated;
  MACD-pass and era-split tercile-edge scoping registered explicitly; sizing script
  now reuses the shared study loader, membership attach, and the scalar's own mask
  components instead of private copies.
