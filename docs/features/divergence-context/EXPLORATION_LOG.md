# Divergence-context study — exploration log (Track A)

One dated line per look, whether or not it went anywhere. Nothing in this
file is a finding; numbers here are bare rates on exploratory data.

## 2026-10-05 — step 0 (prevalence / entanglement / feasibility)

*(Amended same day, pre-merge, after code review: PIT join made rename-aware, Q2's
shape definition aligned with the stored scalars' NaN rule and its boundary filter
moved to p2_date, outcome buckets split three ways. Superseded figures: PIT 2.5–3.6k
dates, entanglement 29.1%, extension bucket 44.8%.)*

- Prevalence (404,634 dev-window events, ≤2021-12-31): pullback+rebuild shape (retrace_frac ≥ 0.33, leg2_bars ≥ 5) = 61.7% of regular/bearish, 69.4% of regular/bullish, ~91% of both hidden cells. Both shape regions well populated → **kill criterion passed, study proceeds**.
- Cells / effective N: raw 9.8–10.5k distinct p2 dates per form×direction cell; PIT-filtered (S&P 500 + NDX membership at p2, rename-aware) 2.6–3.7k dates on 11.1–18.9k rows. Feasible everywhere; yearly coverage continuous from ~1980 through 2021.
- Entanglement (300-ticker sample, as_of 2021-12-31, shape defined identically to the stored scalars — insufficient-lookback pairs excluded, divergence match by p2_date): only **29.2%** of higher-high pivot pairs with the pullback+rebuild shape carry a stored regular-bearish divergence (±5 days). The mechanical-entanglement worry was overstated — binary divergence × context designs have abundant no-divergence controls. (Caveat: ±5-day matching vs the detector's 3-bar pairing window may undercount slightly.)
- Outcome peek (bare rates, confirmed ≤ 2021-11-30, three-way shape buckets): within regular/bearish, invalidation runs extension 45.7% > pullback+rebuild 41.3% > deep-fast 38.9%; regular/bullish is nearly flat (34.7/34.2/33.6). Hidden cells sit far lower (15.0–22.4% shaped; extension sub-buckets higher but tiny, n≈0.8–1.1k) — **cross-form invalidation rates are NOT comparable**, the invalidation threshold sits at the pair extreme, farther from the reference for hidden rows by construction. Median MFE ≈ 4.4–5.4 ATR everywhere. Design input only, no claims.
- Feature-design observation: hidden cells' retrace_frac medians exceed 1 (the interpeak retrace is larger than the 63-bar impulse into p1) — for hidden events p1 is often not an impulse top at all; impulse normalization needs care before any context feature is pre-registered.

## 2026-10-10 — R/R strategy-form sweep: pre-committed grid and kill criterion (written BEFORE any payoff was computed)

*(Machine clock at commit time reads 2026-10-07, as with the DC-B1/B2 rows; narrative date is the study's.)*

Track A follow-up to the DC-B1/B2 Inconclusive readout, and a different question: means
hide what strategies harvest — a stop at the event's own invalidation level amputates the
left tail, so a rule can have positive expectancy where unconditional-return means showed
nothing. Everything below is exploration: no corrections, no findings, no tradeable claims;
the only promotion path is a DRAFT DC-B5 registration presented to the user.

**Grid** (coarse, ~324 event cells before variants):
direction {bearish→short, bullish→long} × form {regular, hidden} × indicator {rsi,
macd_hist, obv} × context class {extension, pullback_rebuild, other = band + deep-fast via
`classify_context` defaults; NaN-retrace events excluded and counted} × strength terciles
within (form × indicator × direction) × duration_bars bins {≤25, 26–45, ≥46} (dev-window
terciles ≈ 26/45). Tercile edges are a dev-window full-sample statistic — the sanctioned
cell-defining-bin exception, same pattern as the frozen PREREGISTRATION's matching bins;
bins define cells, nothing downstream treats them as point-in-time.

**Strategy form** (per event; all exits from one bar walk): enter at the open of the first
bar after `confirmed_at` (invariant #2); stop = pair price extreme (max(p1,p2) bearish /
min(p1,p2) bullish) ± 0.25 × ATR14-at-confirmation beyond it (sensitivity facet: 0.10,
0.50); R = |entry − stop|. Variants: target ∈ {1R, 2R, 3R, none} × max hold ∈ {21, 63}
bars. **Primary variant for the kill criterion: 2R target, 63-bar hold, ε = 0.25,
20 bps.** Walk semantics follow `barriers.py`: gap-through fills at the open, same-bar
target+stop tie resolves to the stop, window past `data_end` = censored (no payoff,
counted), ticker series ending early = delisting-terminal exit at last close, kept and
flagged (invariant #4). Entry already beyond the stop (R ≤ 0) or R < 0.1 × ATR (degenerate
R-multiples) → excluded and counted. Payoffs recomputed from bars loaded as_of 2021-12-31
with fail-closed `data_end` — never from the stored 20-bar lifecycle fields. Holdout
untouched (p2 and every payoff bar ≤ 2021-12-31).

**Universe:** PIT S&P 500 + NDX membership at p2 (rename-aware), delisted kept
(tickers-table timing logic as in the DC-B1/B2 run).

**Controls (mandatory, invariant #5):** the SAME walk on no-divergence pivot pairs —
regular-form events vs `regular_geometry=1, has_divergence=0`; hidden-form vs
`regular_geometry=0, has_divergence=0` (price-only `confirmed_at`). Control baselines per
(direction × geometry × context class × duration bin × p2 month); each event cell's
headline is **event expectancy MINUS the month-reweighted matched-control expectancy**
(weights = the event cell's month distribution; uncovered months dropped and renormalized,
coverage reported). "Buying crashes with stops has positive skew" is true without any
divergence and must not be rediscovered as an edge.

**Metrics per cell × variant** (all descriptive): expectancy in R (gross and net of
20 bps round-trip primary / 10 bps annotated, converted per trade via cost × entry / R),
expectancy in ATR, hit rate, win/loss magnitude ratio, skew (invariant #10 trio), MFE/MAE,
median and p10/p90 of R, resolution mix (stop/target/time/delisted/censored), rows,
**effective N = distinct p2 dates** (invariant #6), trades/year, control delta as above.

**Robustness facets** (inside Track A): era splits 2010–2015 vs 2016–2021 and 2020-in vs
2020-out; neighbor agreement across adjacent strength/duration bins (plateau discipline —
a lone bright cell is noise and will be called noise); stop-ε sensitivity.

**Kill criterion (pre-committed verbatim):** the sweep is DEAD (one log line, stop) unless
at least one (direction × form × context) region shows: net-of-cost expectancy vs matched
controls > 0 at the primary variant with ≥ ~500 distinct p2 dates, the SAME sign in both
era splits, and agreement across its neighboring magnitude/duration bins. A surviving
region's ONLY next step is a drafted DC-B5 pre-registration (own N_tests, own correction,
three-way verdicts — DC-B1/B2 template) presented to the user. No trading claims, no
FINDINGS.md entries, no promotion of any sweep number anywhere.

Code: `src/analysis/divergence_rr_sweep.py`; per-trade cache as parquet under gitignored
`data/derived/divergence_rr_sweep/` (nothing written to the shared sqlite).

### Result (same date, run after the entry above was committed)

*(Amended same date, pre-merge, after code review — step-0's precedent: the per-day
price-dispute exclusion window widened from [d−100, d+25] to [d−100, d+90] calendar days
(Wilder ATR(14) keeps ~28% of a shock 17 bars later, so +25 under-covered the ATR tail),
and the neighbor vote now includes unbinned-strength sub-cells (dropna=False). Verdict
unchanged. Superseded figures: 371 window-disputed exclusions; bearish/regular/other
+0.1032 (neighbors 3/4); bullish/regular/pullback +0.0492 (neighbors 6/8). One
clarification of the entry above, not a change: "tie resolves to the stop" inherits
barriers.py's full same-bar rule, which the code implements — an open already gapped
beyond one barrier decides that barrier; only an undecidable bar goes to the stop.)*

- **The sweep is DEAD per the pre-committed kill criterion** — none of the 12
  (direction × form × context) regions clears all four rails at the primary variant
  (2R/63-bar/ε0.25/20 bps). One line, stop; no DC-B5 draft is warranted.
- Accounting: 88,504 trades walked (33,270 events / 55,234 controls, PIT, dev window);
  1,010 excluded for price disputes (479 whole-history tickers, 531 disputed-day windows);
  primary-variant mix (events): 14,449 stop / 11,676 time / 5,731 target / 852 censored /
  202 never-entered+invalid+degenerate; 0 resolved-but-NaN-return data holes. Effective N
  per region 228–1,534 distinct p2 dates (two mechanically empty hidden-extension regions
  at 4–7, as step 0 predicted).
- Closest non-survivors, named noise per the plateau discipline: **bearish/regular/other**
  adj +0.10 R (619 dates, era-stable, positive across all 10 variants, but neighbor vote
  3/4 — one qualified strength×duration sub-cell disagrees); **bearish/regular/extension**
  adj +0.08 R (365 dates < the 500 floor, 61% control coverage — the thin-extension-pool
  problem again); **bullish/regular/pullback** adj +0.05 R (982 dates, era-stable,
  neighbors 5/8). All hidden-form regions ≈ 0 or negative. 10 vs 20 bps moves nothing
  (cost ≈ 0.04 R/trade at typical 5% risk fractions).
- Argue-against: the bearish positives are "events lose less than controls" — shorting any
  higher-high with a stop above it loses ~0.22–0.28 R net in this 2010–2021 bull window,
  so the delta rides a deeply negative base rate; with hundreds of cells, era-stable
  near-misses at this size are exactly what winner's curse manufactures, which is why the
  neighbor rail exists and why it was allowed to kill them.
- **Survivorship caveat (found while validating the walk, now in backlog.md under
  Signals):** the event base and control pairs contain zero delisted tickers — detection
  ran over yfinance-bars tickers only, and delisted members' bars live under the Tiingo
  sources. The walker's delisting-terminal machinery is correct but unexercised (0
  delisted resolutions). First-order, the control deltas absorb the bias (both sides are
  survivors-only); second-order they don't — divergences cluster near distress, so the
  missing delistings need not hit events and matched controls alike, and the sign of the
  residual bias is unknown. The DEAD verdict is what the criterion says on this event
  base; any future registration (DC-B5 or otherwise) should gate on the delisted
  backfill (backlog item).

## 2026-10-10 — R/R sweep rerun on the recomputed event base: pre-commit (written BEFORE the rerun was computed)

Track A. A rerun of the sweep above on the post-recompute event base (Done #112:
delisted tickers detected on their Tiingo bars, the 7 whole-history-disputed tickers
forgotten, context and control pairs rebuilt). **Grid, strategy form, primary variant,
controls, metrics, robustness facets and the kill criterion are identical to the
2026-10-10 entry above, verbatim — nothing is redefined.** One plumbing change, not a
definition: the walk loads each ticker's bars from the vendor its events were detected on
(`price_basis.resolve_sources`, the divergences fallback), because the original build read
the primary vendor only and a Tiingo-only delisted ticker would otherwise walk as empty.
Reported alongside the verdict: old-vs-new region table, effective N, rows from delisted
tickers, and delisting-terminal exits. Same outcomes as before: DEAD → one line, stop; a
survivor → a DRAFT DC-B5 only, presented to the user.

### Result (rerun, same date, run after the pre-commit note above was committed)

**Amendment 2026-10-11 (pre-merge, after code review; same practice as the first run's
amendment):**

- **Delisted count corrected.** "4,908 event rows on delisted tickers" counted tickers
  inactive today; 2,554 of those rows are on tickers delisted by 2021-12-31.
- **Source rule moved.** The walk's vendor resolution now goes through
  `store.builder_sources`, which adds a vendor-stale check.
- **Cache rebuilt twice.** Each rebuild's walk outputs match the first rerun's by
  content hash (`9880af761b1cf8c3`); the latest cache also carries a new `bar_source`
  column, so the file itself differs. The build log now prints 0 unresolved and 0
  vendor-stale tickers.
- **Dispute filter left vendor-blind,** as in the first run, for comparability. A
  vendor-aware rule would keep 23 of its 534 window drops (9 events, 2 tickers).
- Verdict and every number below unchanged.

- **DEAD again per the pre-committed kill criterion** — no (direction × form × context)
  region clears all four rails at the primary variant (2R/63-bar/ε0.25/20 bps). One line,
  stop; no DC-B5 draft.
- Accounting: 101,989 trades walked (38,343 events / 63,646 controls; old run 33,270 /
  55,234). 124 tickers new to the sweep, 6 gone (the forgotten disputed tickers that were
  PIT members). 4,908 event rows sit on tickers inactive today, and 2,554 of them on
  tickers delisted by 2021-12-31 (old: 0). The rest delisted after the dev window and
  were alive at its end. Primary-variant delisting exits: 44 events / 87 controls
  (old: 0 / 0), so the delisting-terminal path is now exercised. No event on a
  delisted-by-2021 ticker is censored, so no terminal return was dropped. 534 trades
  excluded for disputed-day windows. No ticker was dropped before the walk: 0
  unresolved and 0 vendor-stale. The 7 whole-history-disputed tickers are no longer in
  the base.
- Old vs new, primary variant, control-adjusted net R (distinct p2 dates; neighbors):

  | region | old adj R | new adj R | old → new dates | era 2010–15 / 2016–21 (new) | neighbors old → new |
  |---|---|---|---|---|---|
  | bearish/regular/other | +0.101 | +0.078 | 619 → 706 | +0.078 / +0.079 | 3/4 → 3/5 |
  | bullish/regular/pullback | +0.052 | +0.064 | 982 → 1,077 | +0.120 / +0.009 | 5/8 → 7/8 |
  | bearish/regular/extension | +0.078 | +0.006 | 365 → 440 | +0.041 / −0.028 | 1/2 → 2/4 |
  | bearish/regular/pullback | +0.004 | −0.014 | 1,456 → 1,566 | −0.029 / +0.002 | 3/7 → 4/7 |
  | hidden-form regions | ≈ 0 or < 0 | ≈ 0 or < 0 | — | — | — |

- Closest non-survivor: **bullish/regular/pullback** clears the 500-date floor, both era
  signs and the ex-2020 split, and fails only the neighbor rail on one sub-cell (strength
  tercile 1 × 26–45 bars: −0.013 R, 220 dates). Named noise per the plateau discipline,
  for three reasons:
  - the disagreeing sub-cell is near zero, but the rail is sign-only by pre-commitment;
  - the 2016–21 half is +0.009 R, essentially flat, so the region's mean is carried by
    2010–15;
  - the sub-cells range from −0.01 to +0.15 R with no strength or duration ordering — a
    bumpy surface, not a plateau.
- Not used, recorded so it isn't rediscovered: restricted to the old run's tickers,
  this region would pass all four rails (8/8 neighbors). That is a post-hoc subset of
  the pre-committed universe and is not a survival. If anything, it shows the near-miss
  hinges on which tickers are in the base.
- Cost: 10 vs 20 bps moves no region's adjusted R by more than 0.002 R. Events and their
  matched controls pay the same cost, so it nets out of the delta; net-of-cost levels
  are in the report.
- Argue-against:
  - The bearish positives are still "events lose less than controls": shorting with a
    stop above loses ~0.19–0.25 R net in this bull window.
  - The bullish/pullback edge is concentrated in 2010–15.
  - The 44 delisting-exit events average +0.29 R net. A delisting is often an
    acquisition at a premium, not a failure, so the newly exercised path doesn't only
    add distress.
  - With ~324 cells, a sign-stable near-miss of this size is what winner's curse
    produces.
- Survivorship caveat from the first run: resolved for the vendor-covered universe. About
  50 cap-drop and bankruptcy names have no bars from any vendor (the EODHD question).
  Code change (plumbing only): the walk loads each ticker's bars from its resolved
  vendor by the context/controls builders' rule (`store.builder_sources`), and drops
  unresolved or vendor-stale tickers, of which there were none.
- Caches: the first run's per-trade parquet is still in the main checkout's gitignored
  `data/derived/divergence_rr_sweep/`. This rerun's cache was written to the rerun
  worktree's own data dir, so the old cache was not overwritten. The rebuilt-after-review
  cache matches the first rerun's walk-output hash (`9880af761b1cf8c3`; the cache now
  also carries a `bar_source` column: 87,806 trades yfinance / 14,183 Tiingo).

## 2026-10-11 — hidden-forms prep looks: definitions and gates (written BEFORE anything was computed)

Track A. The two prep looks PREREGISTRATION.md's "Hidden forms" section gates DC-B3/B4
on, run on the recomputed event base (Done #112). Everything below is exploration —
bare rates, no controls, no corrections, nothing stated as a finding. These are
feasibility gates on exploratory data, not hypothesis verdicts: no cell becomes
Alive/Dead/Inconclusive here, and the only promotion path is a drafted DC-B3/B4
registration (own N_tests, own correction) presented to the user.

**Look (a) — co-occurrence.** Does a hidden event mark the same structure as a regular
event of the opposite direction, or is it independent information? The interleaving is
structural: an uptrend's pullback makes hidden-bullish's LOW pair (L1, L2) bracket
regular-bearish's second high H2, and mirrored for downtrends. Match rule: same ticker,
a regular event of the opposite direction with `p2_date` strictly inside the hidden
event's `(p1_date, p2_date)` interval — reported any-indicator and same-indicator,
both conditioning directions (hidden rows with a regular counterpart; regular rows
inside some hidden window), dev window (`confirmed_at <= 2021-12-31`), raw and
PIT-membership-filtered. Outcome peek (bare rates, step-0 discipline: confirmed
<= 2021-11-30, rows with a walked outcome window, within-form comparisons only):
`invalidated` rate and median `max_favorable_move_atr` for hidden events with vs
without a regular counterpart, with distinct p2 dates per bucket.

**Look (b) — impulse-scalar fit for hidden geometry.** Step 0 showed the v0 63-bar
impulse mismeasures hidden structure (retrace_frac medians > 1: p1 is often not an
impulse extreme). Candidate: a **pivot-to-pivot** normalization derived from stored
scalars (DESIGN's ratios-at-analysis-time rule) — the trend leg is p1 → interpeak
extreme, the counter-move is interpeak extreme → p2, and the hidden-fit retrace
fraction is counter-move / trend-leg:
`leg2_gain_pct × (1 + interpeak_retrace_pct) / interpeak_retrace_pct` for LOW pairs
(bullish), `leg2_gain_pct × (1 − interpeak_retrace_pct) / interpeak_retrace_pct` for
HIGH pairs (bearish); NaN wherever an input is NaN or the trend leg is ≈ 0 (invariant
#9). Reported per hidden cell: v0-misfit quantification (% of rows with v0
retrace_frac > 1 vs the regular cells), the candidate's quantiles and NaN rate, and
the shape-class split (candidate frac ≥ 0.33 and rebuild/counter-move ≥ 5 bars vs
not) with rows and distinct p2 dates, raw and PIT — i.e., does hidden get a populated
two-pole context contrast under a scalar that actually fits it, where v0 put ~91% of
hidden mass in one pole?

**Gates (pre-committed):** DC-B3/B4 do NOT get drafted if (a) the disagreement cells
(hidden without a regular counterpart, per direction) cannot plausibly reach useful
effective N as distinct p2 dates PIT-filtered — hidden would be the regular cells'
complement, handled as a form interaction in F6 instead; or (b) no candidate scalar
yields a well-defined, non-degenerate distribution (NaN rate comparable to the
regular cells' v0 scalars, mass on both sides of the shape split) — hidden context
cells would be uninstrumentable. Passing both gates means a DC-B3/B4 draft is
*presented*, not that anything is alive.

Code: `src/analysis/divergence_hidden_prep.py` (read-only over `divergences` +
`divergence_context`; no DB writes, no caches).

### Result (same date, run after the entry above was committed)

*(Amended same date, pre-merge, after two code-review rounds — step-0's precedent.
Every number below is from the final code; each round's rerun reproduced the first
run's figures exactly, so no figure is superseded. Round 1: (1) the shape split's
`leg2_bars >= 5` comparison now carries an explicit NA mask + test (invariant #9); no
number changed — a NaN `leg2_bars` co-occurs with a NaN `leg2_gain_pct` today, so the
undefined rows were already excluded, but only by an undeclared coupling. (2) The
co-occurrence matching was rewritten as a vectorized merge (chunked by ticker after
round 2, so the pre-filter cross product stays bounded as the event base grows). (3)
A confirmation-ordered variant of the counterpart flag was added (counterpart
confirmed by the hidden event's own `confirmed_at`): 29.1%/33.3% vs the
structure-level 29.2%/33.4% — the regular counterpart nearly always confirms first,
so the structure-level flags are not materially look-ahead; the outcome peek is also
reported on that split (same picture). Caveat made explicit: counterparts confirming
after DEV_END are never read (holdout), a small undercount at the window margin. (4)
The disagreement-cell date counts cited below were "dates with any alone row", which
overlap the with-counterpart dates; the conservative **alone-only** count (dates
hosting no counterpart row at all) is reported alongside — PIT dev-window 826
(bearish) / 719 (bullish), still comfortably above any plausible floor, gate
conclusion unchanged. (5) The dev-events loader and shape-bucket edges moved to
`src/analysis/divergence_study_common.py`, shared with step 0, so the definitions
can't drift between the two scripts. Round 2: (6) the candidate scalar is now masked
to hidden rows and to trend legs > 1e-6 of p1's close — on regular rows the
decomposition is defined garbage, and a glitch-sized trend leg would print a huge
"defined" ratio that escapes the NaN rate; neither mask changed any reported number
(0 rows affected among hidden events). (7) The NA-masked shape classifier moved to
the shared module and step 0's two shape computations now use it (behavior-preserving
today, same coupling argument as (1)). (8) Output labels disambiguated: "PIT index
members" (membership scope) vs "conf-ordered" (confirmation ordering) — two different
"PIT"s no longer share a word. Round 3: (9) the conf-ordered flag's `<=` could have
folded in same-bar confirmation ties; a strict-`<` companion flag now measures the
events whose conf-ordering rests ONLY on a same-bar tie (the case where `<=` vs `<`
changes the flag) — **0 such events in every cell**, so "the regular counterpart
nearly always confirms first" is not a tie artifact. (Per-event, not per-pair: an
event with both an earlier and a same-bar counterpart isn't counted, and needn't be —
its ordering doesn't rest on the tie.) (10) The outcome peek's False bucket is labeled per flag
("hidden alone" vs "none confirmed yet") — the two splits' buckets are composed
differently and no longer share a label. (11) Distinct p2 dates added to the v0-misfit
and candidate quantile tables (invariant #6): the 66%/76% misfit rates rest on
10,247/10,533 dates, the candidate's quantiles on 10,277/10,565 — not previously
printed, nothing else changed. (12) The NaN decomposition now reads the scalar's own
mask components (`hidden_fit_undefined_reasons`) instead of re-deriving them. Round 4
(claim accuracy, no new numbers): (13) those reason components made mutually
exclusive so the printed breakdown can't sum past the NaN rate; (14) the `pit_member`
attach moved into the shared module (both scripts call it); (15) the tie count's
per-event semantics and the misfit rates' defined-only denominator stated precisely
(in-place wording fixes in this entry, no figure changed). All reported figures
identical across every round's rerun.)*

- **Both gates pass; a DC-B3/B4 draft is warranted and will be presented to the user.**
  Nothing below is a finding; the registration (own N_tests, own correction) is where
  hypotheses get tested.
- **Look (a) — hidden is NOT the regular cells' complement.** Only 29.2%/33.4% of
  hidden bearish/bullish rows (raw; PIT dev-window 29.7%/33.6%) carry a mirrored-
  direction regular p2 strictly inside their pivot interval (same-indicator: 19–23%).
  The disagreement cells are large: hidden-alone PIT dev-window distinct p2 dates
  ≈ 1,486 (bearish) / 1,530 (bullish), of which 826 / 719 host no counterpart row at
  all (the conservative count) — far above any plausible effective-N floor either way.
  The confirmation-ordered counterpart flag matches the structure-level one to within
  0.1pp.
  Coherence check: the 29–34% rate is the step-0 entanglement number (29.2% of shaped
  higher-high pairs carry a regular-bearish divergence) asked from the other side.
  Conditioning the other way, 28–36% of regular rows sit inside a hidden window —
  co-occurrence is a facet/covariate for DC-B3/B4, not grounds to pool forms (the
  LRP §2.4 / F6 constraint stands).
- Outcome peek (bare rates, within form): invalidation is slightly HIGHER with a
  regular counterpart in both directions (bearish 19.5% vs 18.1%; bullish 17.3% vs
  14.1%; medMFE ≈ equal) — directionally consistent with a reversal label weighing
  against a continuation label on the same swing, and confounded by everything a bare
  rate is confounded by (deeper/busier structures are more likely to print the
  counterpart at all). Design input only.
- **Look (b) — the pivot-to-pivot candidate fits; v0 is confirmed misfit.** v0
  retrace_frac > 1 on 65.7%/75.8% of hidden bearish/bullish rows with a defined v0
  value (v0 NaN on 0.6%/0.5%; 10,247/10,533 distinct p2 dates behind the defined
  rows), vs 5.3%/8.7% of the regular cells' defined rows — the scalar built for
  regular geometry. The candidate
  (counter-move / trend-leg) is defined on 100.0% of hidden rows (0 input-NaN beyond
  the join, 0 degenerate trend-legs) with a smooth distribution: p10≈0.36–0.37,
  p50≈0.67–0.70, p90=0.93 in both directions. Sanity: for a true hidden pair the
  ratio is mechanically bounded in (0,1) (a higher low IS a counter-move smaller than
  the trend leg), so the candidate is exactly "retracement depth of the trend leg" —
  interpretable and bounded where v0 exploded.
- Caveat that shapes the draft: at the regular-geometry 0.33/5-bar edges the shallow
  pole holds only 5.1%/10.0% of defined PIT dev-window rows (259/531 distinct dates)
  — a fixed-edge two-pole split would re-create DC-B1/B2's thin-extension-pool
  problem. DC-B3/B4 context classes should be defined on the candidate's own
  within-cell quantiles (e.g. shallow/middle/deep terciles), which are balanced by
  construction; tercile edges would be the sanctioned cell-defining-bin exception,
  as in the frozen DC-B1/B2 matching bins.
- Argue-against: the co-occurrence rate is an undercount at the margin (strict-
  interior matching; the detector's own 3-bar pairing window can place a counterpart
  p2 just outside the interval) — but no plausible widening moves ~30% to ~90%, so
  the independence conclusion stands. The outcome deltas are bare rates and carry no
  claim.

## 2026-10-14 — confluence vs outcome (the Done #44 follow-up): any-confluence null; triple agreement a lone candidate

One look (`python -m src.analysis.divergence_confluence_outcome`): does multi-indicator
confluence predict better resolution? Decision-time counts, not the stored full-run
`confluence_count` (which exceeds what was knowable at confirmation on 5.3% of the 423k
events confirmed ≤ 2021-12-31 — a later-confirming indicator joins the cluster
retroactively); deltas vs solo divergences
matched on direction × form × indicator × p2-year; PIT S&P 500/NDX members; dev window on
both ends (confirmed 2010-01-01..2021-11-30, the 20-bar outcome buffer; the first cut of
this pass missed the lower bound and silently included pre-2010 history — caught in code
review before the PR, all numbers below are the corrected run); disputed tickers/windows
excluded. CIs are date-clustered bootstrap and likely somewhat narrow (clustering is on
identical p2 dates; neighboring dates' 20-bar outcome windows overlap).

- Headline (PIT confluence ≥2 vs solo, 13.6k rows on 2,117 distinct p2 dates vs 24.1k solo):
  MFE delta **+0.056 ATR**, 95% CI [−0.006, +0.117] — spans zero, ~2% relative at the CI top
  against a ~4.4–5.4 ATR median MFE. Invalidation **+0.37pp** (CI [−0.88, +1.57pp]) — if
  anything confluent events fail marginally more. Not era-stable (2010–15 +0.102 vs 2016–21
  +0.009), not cell-uniform (bullish/hidden −0.017), and the all-ticker aggregate flips
  negative (−0.048). The =2 variant is the same picture (+0.030, CI [−0.031, +0.081], late-era
  sign flip). **"Some confluence" predicts nothing — the Done #44 call: no basis to feed
  confluence into `strength`.**
- The one candidate: **all-three-indicators agreement** (=3 vs solo, 1,250 rows on only 439
  dates): MFE **+0.309 ATR**, CI [+0.139, +0.494], era-stable (+0.34 / +0.27), all four
  direction×form cells positive, and invalidation moves the right way (−2.3pp, CI spans
  zero) — favorable up AND failures down argues against a pure volatility tilt. Against it:
  the =2 neighbor sits 10× lower (no plateau — a lone bright threshold), 439 dates, a likely-
  narrow CI, one of several uncorrected looks, and the balance check shows confluent events
  differ in observables within strata (`price_move_atr` −0.95, `duration_bars` −1.8), so
  selection survives the matching. Track A: **not a finding**; promotable only via a
  pre-registered test (natural home: a model feature + the trading scorecard, per LRP §3)
  if the user wants it.
- Lasting constraint for any consumer: the stored `confluence_count`/`agreeing_indicators`
  are FULL-RUN facts; a PIT consumer must re-cluster (the script's
  `pit_confluence_at_confirmation`, which delegates to `context.pit_confluence`).
