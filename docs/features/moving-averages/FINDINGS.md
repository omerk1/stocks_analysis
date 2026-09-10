# Findings register — Tier 1, 2, and 3 results

**Dependency note (resolved 2026-09-10):** PR #68 (M11 tier assignment, corrections,
the `dist_pct_sma_50_h21` tier change) and PR #69 (DESIGN §6.11's shape-field schema
and forward-only rule) are both merged. This branch is rebased onto that content —
every cross-reference to `EXPERIMENTS.csv`'s
`decisive_test_status`/`counted_in_n_tests` columns and to DESIGN §6.11 now resolves
against real content on `main`, nothing below is a forward pointer anymore.

**Track B only** (DESIGN §1.5/§6.6) — every entry below is a pre-registered,
confirmatory result with a tier assignment; nothing here is a Track A exploratory
number. Stated explicitly per CLAUDE.md's "always state which track you are working
in."

Sibling to `DEAD_ENDS.md`: same per-entry discipline (hypothesis, why it was plausible,
the number, effective N, what would change the verdict), for results that survived
instead of ones that didn't. One entry per Tier 1/2/3 cell.

## Read this before any entry below

**Entries here were judged under criteria that differ by module, and that difference
is not evidence.** M11's cells faced a pre-registered *per-cell* magnitude floor (a
0.02 IC threshold, evaluated at the CI's near-zero edge) in addition to the standard
Tier rubric. M1's and M4's cells faced no such floor. Applied retroactively
(`PREREGISTRATION.md`, M11's 2026-09-10 feasibility addendum), **none of M1's or M4's
five Tier-3 cells clear M11's 0.02 floor either** — their near-zero CI edges run
0.0003–0.0014, an order of magnitude short. So the gap between an ordinary Tier-3
entry here and M11's primary cell's "killed as a construction" verdict is **partly the
criterion that cell was held to, not a difference in the underlying evidence.** Every
entry carries `decisive_test_status` (`never_tested` / `failed`) so this is visible per
row, not just in this header.

**Six of these nine entries are not independent of each other, across modules, and a
reader counting corroborating results would double-count them.** They form three
duplicate *pairs*, not three isolated numbers: M11's sector/vol/momentum-neutralized
spread for `dist_pct_sma_20`, `dist_atr_sma_20`, and `dist_z_sma_20` (all 21d) is each
a deterministic recomputation of the corresponding M4 entry's own C2 spread — traced
at the code level (`PREREGISTRATION.md`'s 2026-09-10 correction): both call
`block_bootstrap_spread` with identical arguments. Flagged inline on both sides of
each pair below, not just here. A fourth cell (`dist_pct_sma_50_h21`) matched the
same way for the same reason, but is **not** in this register — its neutralized-layer
CI spans zero, so it tiers Tier 4 (`PREREGISTRATION.md`'s 2026-09-10 tier-change
addendum) and doesn't qualify for a Tier 1/2/3 entry. Four overlapping cells matched
in total; three of the four appear here as duplicate pairs.

**Shape fields (hit rate, win/loss magnitude ratio, skew) are part of this register's
schema and are empty for every entry below.** DESIGN §6.11 is forward-only — these
three modules are exactly the ones whose weak means motivated inventing the
statistics, and computing them here, after tiering, would be indistinguishable from
having gone looking for a rescuing framing (§6.11's own stated reasoning). The columns
exist now so the schema doesn't need to grow later, not because they're populated.

**Cost is reported at both CI ends, not just the point estimate, with the turnover
convention stated per entry.**

---

## M4 — Distance from MA (2026-09-08)

### `dist_pct_sma_20`, 21d

**Hypothesis:** Forward 21-day return is a structured function of displacement from
SMA20, normalised as raw percentage distance.

**Why it was plausible:** DESIGN §2.3's literature conflict on extension (does it
predict continuation or reversion — §2.3 item 1, horizon), plus §2.3(3) specifically
(ATR-normalisation implicitly conditions on volatility, so both normalisations need
testing, not one) and the 2026-09-07 M0.1 finding that confirms it empirically —
ATR-normalisation visibly changes the distance distribution's shape, not just its
scale.

**What was run:** Decile bucket of `dist_pct_sma_20` (cross-sectional, per date),
C2-adjusted (`mom_tercile`/`vol_tercile`/`sector`) decile9-minus-decile0 spread,
block-bootstrapped (block length 42, 500 draws, 90% CI).

**The number:** −0.004639, 90% CI [−0.007758, −0.001366]. CI excludes zero.

**Not independent of M11:** M11's sector/vol/momentum-neutralized spread for this same
cell (`dist_pct_sma_20`, 21d — see the M11 primary-cell entry below) recomputes this
exact number. Same function (`block_bootstrap_spread`), same arguments. The two are
one piece of evidence, not two.

**Effective N:** 244,356 raw rows, 2,747 distinct dates. Ticker count not separately
recorded in the original run.

**Cost:** hurdle 2.465%/yr (`costs.py::signals_per_year`, 10bps/rt, reconciled
2026-09-09 — original ad hoc figure was ~5.06%/yr). Point, annualized (×12): −5.57%,
clears. Far edge: −9.31%, clears. **Near edge: −1.64%, fails.**
`decisive_test_status`: `never_tested`.

**Tier:** 3. Capped by missing FDR/holdout infrastructure.

**What would change the verdict:** decile-level (not tercile) C2 matching once the
universe broadens past S&P 500; the whole-grid FDR pass; a holdout check.

### `dist_atr_sma_20`, 21d

**Hypothesis / why plausible / what was run:** as above, ATR-normalised distance.

**The number:** −0.003716, 90% CI [−0.006649, −0.000937]. CI excludes zero.

**Not independent of M11:** M11's neutralized spread for this same cell (see the M11
`dist_atr_sma_20` entry below) recomputes this exact number, same function, same
arguments — one piece of evidence, not two.

**Effective N:** 244,356 raw rows, 2,747 distinct dates.

**Cost:** hurdle 2.619%/yr. Point, annualized: −4.46%, clears. Far edge: −7.98%,
clears. **Near edge: −1.12%, fails.** `decisive_test_status`: `never_tested`.

**Tier:** 3, same infrastructure cap.

**What would change the verdict:** moves with `dist_pct_sma_20` above — 0.94–0.98
correlated, found 2026-09-09 during M11's own pre-registration (`PREREGISTRATION.md`'s
M11 entry, "Independence check"; also tracked in `STATUS.md`'s whole-grid FDR section),
not an independent piece of evidence.

### `dist_z_sma_20`, 21d

**Hypothesis / why plausible / what was run:** as above, 252-day self-normalised
z-score distance.

**The number:** −0.003736, 90% CI [−0.006543, −0.001182]. CI excludes zero.

**Not independent of M11:** M11's neutralized spread for this same cell (see the M11
`dist_z_sma_20` entry below) recomputes this exact number, same function, same
arguments — one piece of evidence, not two.

**Effective N:** 223,752 raw rows, 2,729 distinct dates (fewer — `dist_z`'s own
252-day rolling-window warmup on top of the MA's).

**Cost:** hurdle 2.617%/yr. Point, annualized: −4.48%, clears. Far edge: −7.85%,
clears. **Near edge: −1.42%, fails.** `decisive_test_status`: `never_tested`.

**Tier:** 3, same cap.

**What would change the verdict:** moves with the other two SMA20 facets, not
independently.

---

## M1 — Baseline state conditioning (2026-09-09)

### `above_sma_20` (above/below state)

**Hypothesis:** Forward 21-day return differs conditional on price being above vs.
below the 20-day SMA.

**Why it was plausible:** DESIGN §12's own recommended minimal-core *first* module.

**What was run:** C2-adjusted delta between above-state and below-state forward
returns, block-bootstrapped, on the C2-eligible row subset.

**The number:** −0.002146, 90% CI [−0.003495, −0.000791]. CI excludes zero.
Above/below are exact algebraic mirrors under C1/C2 — one independent number, not two.

**Effective N:** 751,406 raw rows (C2-eligible), 2,744 distinct dates, 405 tickers.
38.2% row loss to C2 eligibility (open, unresolved selection-mechanism caveat).

**Cost:** hurdle 3.038%/yr (30.377 flips/ticker-yr). Point, annualized: −2.58%,
fails. **Far edge: −4.19%, clears.** **Near edge: −0.95%, fails.**
`decisive_test_status`: `never_tested`.

**Tier:** 3. Capped by missing FDR/holdout infrastructure.

**What would change the verdict:** a broader universe reducing the 38.2% row loss and
its all-above-skewed composition; the whole-grid FDR pass; a holdout check.

### `above_sma_50` (above/below state)

**Hypothesis / why plausible / what was run:** as above, at the 50-day SMA.

**The number:** −0.001830, 90% CI [−0.003406, −0.000306]. CI excludes zero.

**Effective N:** 743,745 raw rows (C2-eligible), 2,746 distinct dates, 405 tickers.

**Cost:** hurdle 1.799%/yr. Point, annualized: −2.20%, clears. Far edge: −4.09%,
clears. **Near edge: −0.37%, fails.** Point clears, CI-based test does not.
`decisive_test_status`: `never_tested`.

**Tier:** 3, same cap.

**What would change the verdict:** same as lb20.

---

## M11 — Cross-sectional formulation (2026-09-09/10)

### `dist_pct_sma_20`, 21d (PRIMARY cell)

**Hypothesis:** Cross-sectional rank of `dist_pct_sma_20` carries forward 21-day
return information beyond zero, after cost.

**Why it was plausible:** M4's own SMA20 facets above already showed a real,
CI-excluding-zero, cost-failing effect via decile-bucket construction.

**What was run:** Daily cross-sectional Spearman rank-IC and a C1 long-short decile
spread, block-bootstrapped (~71 effective independent blocks). Decided by a
pre-registered two-part kill criterion: IC near-zero edge must clear 0.02 *and* spread
near-zero edge must clear cost, both CI-based.

**The number(s):** IC = −0.018966, 90% CI [−0.032670, −0.001304] — excludes zero, near
edge (0.0013) far short of the 0.02 floor (would need a point IC of −0.0377 at this
sample size — 1.8× the largest IC this grid produced). C1 spread = −0.005045, 90% CI
[−0.009072, −0.000424]. **Neutralized spread = −0.004639, 90% CI [−0.007758,
−0.001366] — not independent of M4: this is M4's `dist_pct_sma_20` C2 spread above,
recomputed exactly (same function, same arguments).**

**Effective N:** 1,214,970 raw rows, 2,980 distinct dates, 408 tickers — for the IC
and C1-spread numbers above. Zero row loss beyond feature/return warmup (C1 layer).
**The neutralized spread's N is different and smaller**, since that number is M4's
`dist_pct_sma_20` C2 spread (above), not a fresh computation: 244,356 raw rows, 2,747
distinct dates — see that entry.

**Cost:** hurdle 2.463%/yr (24.635 combined flips/ticker-yr). Spread point, annualized
(×12): −6.05%, clears. Far edge: −10.89%, clears. **Near edge: −0.51%, fails.**

**`decisive_test_status`: `failed`** — the only entry in this register with this
status. Failed the IC floor sub-test; the cost sub-test also fails independently.
**Killed as a construction**, per DESIGN §9.2's 2026-09-10 addendum — a methodology
verdict, separate from the tier below.

**Tier:** 3. Per this register's header caveat.

**What would change the verdict:** the whole-grid FDR pass; a holdout check; a
`mom_1_0`-neutralized re-run (flagged, not run — a live momentum-collinearity
concern).

### `dist_pct_sma_20`, 5d (secondary: horizon term structure)

**Hypothesis / why plausible:** as the primary cell, at a 5-day forward horizon — the
term-structure follow-up M4's own entry flagged as motivated.

**What was run:** as the primary cell's construction, `fwd_ret_5` in place of
`fwd_ret_21`. No M4 counterpart exists at this horizon — M4 tested 21d only.

**The number(s):** IC = −0.013796, 90% CI [−0.022463, −0.004092]. C1 spread =
−0.002123, 90% CI [−0.003492, −0.000685]. Neutralized spread = −0.002144, 90% CI
[−0.003158, −0.001213] — **independent of M4** (no counterpart exists at this
horizon), unlike the three 21d entries above.

**Effective N:** 1,221,498 raw rows, 2,996 distinct dates, 408 tickers — applies to
all three numbers above; unlike the 21d cells, nothing here is borrowed from a
smaller M4 subset.

**Cost:** hurdle 2.466%/yr — verified horizon-independent (turnover is driven by the
feature's own daily decile-membership flips). Spread point, correctly annualized
(×50.4, corrected 2026-09-10 — see `PREREGISTRATION.md`'s correction addendum):
−10.70%, clears. Far edge: −17.60%, clears. **Near edge: −3.45%, clears — the only
entry in this register whose CI-based cost test passes.**
`decisive_test_status`: `never_tested`.

**Necessary context, not a weakening of the result above:** this is the shortest
forward horizon in M11's grid, and `dist_pct_sma_20` is mechanically close to recent
price change — a short-term-reversal generator (via the uncontrolled `mom_1_0`
confound) is strongest at the shortest horizon and decays as the window lengthens,
exactly the shape observed here. A genuine MA-distance effect has no particular reason
to concentrate at the shortest horizon. This cell's cost-clearance should not be read
as stronger evidence for cross-sectional MA-state information than the rest of this
register.

**Tier:** 3, missing-infrastructure cap — unaffected by clearing cost.

**What would change the verdict:** a `mom_1_0`-neutralized re-run specifically (this
is the cell most exposed to that confound); the whole-grid FDR pass; a holdout check.

### `dist_atr_sma_20`, 21d (companion, not counted in `N_tests`)

**Hypothesis / why plausible / what was run:** as the primary cell's normalisation
question, ATR-distance instead of raw percentage. Excluded from `N_tests` at
declaration (0.94–0.98 correlated with `dist_pct_sma_20`).

**The number(s):** IC = −0.019595, 90% CI [−0.033436, −0.002196]. C1 spread =
−0.004896, 90% CI [−0.008455, −0.000686]. **Neutralized spread = −0.003716, 90% CI
[−0.006649, −0.000937] — not independent of M4: this is M4's `dist_atr_sma_20` C2
spread above, recomputed exactly.**

**Effective N:** 1,214,970 raw rows, 2,980 distinct dates, 408 tickers — for the IC
and C1-spread numbers above. **The neutralized spread's N is different and smaller**
(it's M4's `dist_atr_sma_20` C2 spread, not a fresh computation): 244,356 raw rows,
2,747 distinct dates — see that entry.

**Cost:** hurdle 2.619%/yr. Point, annualized: −5.88%, clears. Far edge: −10.15%,
clears. **Near edge: −0.82%, fails.**

**Tier:** 3, missing-infrastructure cap.

**What would change the verdict:** moves with `dist_pct_sma_20` above, not
independently.

### `dist_z_sma_20`, 21d (companion, not counted in `N_tests`)

**Hypothesis / why plausible / what was run:** as above, z-score distance. Excluded
from `N_tests` at declaration, same reason.

**The number(s):** IC = −0.020977, 90% CI [−0.034723, −0.007419] — the largest `|IC|`
in this entire register. C1 spread = −0.005518, 90% CI [−0.009040, −0.002149].
**Neutralized spread = −0.003736, 90% CI [−0.006543, −0.001182] — not independent of
M4: this is M4's `dist_z_sma_20` C2 spread above, recomputed exactly.**

**Effective N:** 1,112,562 raw rows, 2,729 distinct dates, 408 tickers — for the IC
and C1-spread numbers above. **The neutralized spread's N is different and smaller**
(it's M4's `dist_z_sma_20` C2 spread, not a fresh computation): 223,752 raw rows,
2,729 distinct dates — see that entry.

**Cost:** hurdle 2.617%/yr. Point, annualized: −6.62%, clears. Far edge: −10.85%,
clears. **Near edge: −2.58%, fails — the closest miss in this register among
companion entries, not the study's strongest near-result** (companion, excluded from
`N_tests`; gap to hurdle 0.04pp).

**Tier:** 3, missing-infrastructure cap.

**What would change the verdict:** moves with `dist_pct_sma_20` above, not
independently.
