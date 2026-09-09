# Dead Ends

Negative Track B results (CLAUDE.md: "Negative results → `DEAD_ENDS.md` with the number
that killed it and the effective N"). Each entry: hypothesis, what was run, the number
that killed it, effective N, and the conditions under which it would be worth revisiting.
**A null result here is a successful outcome** — do not re-run these looking for a
framing that makes them alive again.

## M4 — Distance from MA: SMA50 and SMA200 facets (2026-09-08)

**Hypothesis:** forward 21-day return is a non-monotonic (or otherwise structured)
function of displacement from SMA{50,200}, across `dist_pct`/`dist_atr`/`dist_z`. See
`PREREGISTRATION.md`'s M4 entry for the full pre-registration.

**Why it looked plausible:** point-estimate decile tables showed a broadly monotonic
decline (SMA50) or a genuine U-shape (SMA200 `dist_pct`/`dist_atr`) surviving C2 matching
— visually indistinguishable, at that stage, from the SMA20 facets that ultimately
survived. Only the block-bootstrap inference layer separated them.

**What was run:** `stats/inference.py::block_bootstrap_spread` — the C2-adjusted
`decile9 - decile0` spread, 500 draws, dates resampled in contiguous blocks of 42 (2x
the 21-day horizon), 90% CI.

**The number that killed it:** every one of the 6 facets' 90% CI includes zero.

| Facet | Point estimate | 90% CI | Raw N (decile 0 + decile 9 rows) | Effective N (distinct dates) |
|---|---|---|---|---|
| `dist_pct_sma_50` | -0.0030 | [-0.0065, +0.0003] | 241,891 | 2,747 |
| `dist_atr_sma_50` | -0.0026 | [-0.0058, +0.0004] | 241,891 | 2,747 |
| `dist_z_sma_50`   | -0.0018 | [-0.0045, +0.0010] | 221,292 | 2,699 |
| `dist_pct_sma_200`| -0.0016 | [-0.0053, +0.0024] | 229,580 | 2,747 |
| `dist_atr_sma_200`| -0.0020 | [-0.0052, +0.0014] | 229,580 | 2,747 |
| `dist_z_sma_200`  | -0.0027 | [-0.0055, +0.0002] | 208,973 | 2,549 |

**Effective N:** 2,549–2,747 distinct dates per facet, alongside the raw row count
(the effective-N invariant in CLAUDE.md / DESIGN §6.3 require both, not just one) — the CI is built from
the effective N, since 21-day return overlap means the raw row count vastly overstates
usable information.

**Tier:** 4 (Rejected) — tested, no effect beyond C2 control.

**Revisit if:** the C2 tercile-vs-decile deviation (`PREREGISTRATION.md`) is resolved by
a broader universe (past S&P 500) and the effect reappears under proper decile matching
— plausible in principle (a coarser match leaves more room for residual confounding to
mask a real effect) but not assumed; re-test, don't just widen the universe and declare
it fixed. For `dist_z_sma_200` specifically, the normalisation-window diagnostic in
`notebooks/moving_averages_distance_from_ma.ipynb` found the 252-day self-normalisation
window measurably unstable at that lookback (cross-sectional rank correlation with
`dist_pct` drops to ~0.69 vs. ~0.88-0.93 at shorter lookbacks) — a plausible mechanism
for why this specific facet is noisy, independent of the universe-size question.

## M1 — Baseline state: SMA200 primary cell (2026-09-09)

**Hypothesis:** forward 21-day return differs conditional on price being above vs.
below the 200-day SMA, C2-adjusted. See `PREREGISTRATION.md`'s M1 entry for the full
pre-registration.

**Why it looked plausible at first:** the module-level kill criterion (evaluated on the
CI's most-favorable-to-survival edge) did not fire — `max(|ci_low|, |ci_high|)` cleared
0.10% at 3D for lb200, same as lb20/lb50.

**The number that killed it:** the 3D CI already touches zero (`ci_high = +0.000048`,
21-day, C2-adjusted) and the 4D (reversal-controlled) CI spans it clearly
(`[−0.002896, +0.000839]`). Under the corrected CI-based cost test (see
`PREREGISTRATION.md`'s 2026-09-09 cost-test-definitional-gap correction — a CI spanning
zero automatically fails, since zero is itself a valid point inside it), lb200 fails the
CI-bound cost check unambiguously; it was previously miscategorized as passing under a
flawed near-zero-endpoint comparison. It is also the lookback with the worst row loss
(51.9% at 3D, 74.9% at 4D) and heaviest all-above singleton-stratum skew (84.5% of
dropped rows) of the three lookbacks tested — the weakest statistically and the most
selection-exposed, consistently.

**Effective N:** 2,747 distinct dates (3D, `above`/`below` combined via the mirror
identity — see below), 405 tickers, C2-restricted population.

**Tier:** 4 (Rejected) — CI does not exclude zero at the pre-registered 3D spec.

**Note on above/below:** M1's above/below cells are exact algebraic mirrors under C1/C2
(`PREREGISTRATION.md`'s 2026-09-09 correction) — this entry covers both directions at
lb200 as one number, not two independent tests.

**Revisit if:** a broader universe (past S&P 500) makes decile-level C2 matching viable
and the C2-eligible row loss drops meaningfully below its current 52-77% — the current
CI width is plausibly inflated by the small, skewed retained sample as much as by a
genuinely weak or absent effect at this lookback specifically.

## M1 — Baseline state: run-length sub-question, "does the age of the state matter?" (2026-09-09)

**Hypothesis:** forward 21-day return varies with the age of the above/below state
(run-length bucket: 1-5, 6-21, 22-63, 64+ trading days), C2-adjusted, within each
direction and SMA lookback. DESIGN §8 M1's "key sub-question" — folklore says fresh
reclaims are strongest.

**Why it looked plausible:** the plain existence of a 24-cell grid with visible sign
variation across buckets invites a "the pattern shows something" read if looked at
casually.

**The number that killed it:** DESIGN §6.7's plateau rule — neighbouring parameters must
agree. None of the 24 cells' 1-5→6-21→22-63→64+ sequences show a smooth progression;
every one zigzags in sign (e.g. lb20 above: +0.0009, −0.0003, −0.0004, −0.0029; lb50
below: +0.0001, −0.0006, +0.0006, −0.0003). Of the 24 cells, only one (lb50 above /
6-21) has a 3D CI excluding zero (`[−0.002268, −0.000031]`) — but its immediate
neighbours (1-5: `[−0.000715, +0.001670]`; 22-63: `[−0.000382, +0.002056]`) are
opposite-signed and don't exclude zero themselves. A lone significant cell with
non-agreeing neighbours is, per §6.7, noise — not a finding.

**Effective N:** 2,483–2,747 distinct dates per cell (3D), 16–405 tickers per cell (the
lb20 below/64+ cell is itself separately investigated below — small-sample, not a
defect, but not evidence either way for this sub-question).

**Tier:** 4 (Rejected) — fails the plateau rule; no cell-level survival promoted past it.

**Revisit if:** a broader universe increases per-bucket sample size enough that the
zigzag pattern either resolves into a real progression or is confirmed as pure noise
with tighter CIs — at current sample sizes the zigzag is as consistent with "genuinely
no age effect" as with "underpowered to see one," and this entry doesn't distinguish
between them.

## M1 — lb20-below/64+ cell investigation, not a defect (2026-09-09)

Not a killed hypothesis — logged per instruction, "either way." This cell
(`n_events=179`, `n_tickers=16`, already flagged `below_threshold=True` by the module's
own §6.9 check) showed the largest point estimate in the entire run-length grid
(C0 = +3.50%, mean `fwd_ret_21` in-cell = +4.97%), large enough to warrant checking
whether it was a censoring or bucketing defect rather than a genuine small sample.

**What was checked:** the ticker list (COP, AIG, CVX, TMUS, BBWI, DVN, TTWO, BAC, CE,
GWW, AKAM, UAA, ETN, CF, PPG, CMG), year distribution (concentrated in 2011: 32,
2012: 33, 2015: 60, 2016: 13, 2017: 27, 2020: 14 — the European-debt-crisis correction,
the 2015 oil-price crash, and the 2020 COVID crash respectively), and a direct spot
check: COP's raw `close` vs. `sma_20` recomputed independently over the 70 trading days
ending at its first flagged date (2015-08-03), cross-checked against
`run_length_bucket_sma_20`'s actual labels row by row.

**Result: verified correct, not a defect.** COP's close genuinely closed below its
20-day SMA continuously from 2015-05-04 through 2015-08-03 — 64 consecutive trading
days, no gaps — and the bucket labels transition exactly where the day-count predicts
(1-5 for days 1-5, 6-21 for days 6-21, 22-63 for days 22-63, 64+ starting exactly on
day 64). The labeling logic is sound.

**Conclusion:** this is a genuine but tiny, event-clustered sample — sustained 64+-day
stretches below a *short* (20-day) MA are inherently rare, and several of the 16
tickers each contribute a run of consecutive, highly-overlapping days from a single
continuous episode (e.g. COP's 21 rows are one uninterrupted 2015 stretch, not 21
independent observations) rather than independent draws. The module's own
`below_threshold` flag (16 tickers < the §6.9 minimum of 30) already catches this
correctly — the large point estimate reflects real oversold-bounce behavior in these
specific crisis episodes, not a bug, but is untrustworthy as a number precisely because
of how it's already flagged.

**Not tiered** — this is a data-quality check, not a hypothesis test.
