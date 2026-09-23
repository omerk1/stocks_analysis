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

### Whole-grid FDR pass addendum (2026-09-23) — `above_sma_20`

**Survives, at N=50.** In the original 2026-09-17/2026-09-20 passes (N=31, then 35)
this cell missed by a hair (p=0.0090 against a rank-3 threshold of 0.0086). Extending
the grid to N=50 with Batch-1's four new modules (`STATUS.md`'s "Whole-grid FDR pass"
section) shifts this cell to rank 5 — its p-value is unchanged, but
`slope_pctile_21_sma_50`'s (M6.3, p=0.00005) very small p-value now anchors BH's
step-up procedure, and rank 5's own threshold (0.0100) happens to clear this cell's
p-value even though ranks 2–4 individually do not clear theirs. Mathematically valid
under BH (adding tests can loosen as well as tighten a specific cell's effective
threshold, depending where the new tests land in the ranking) — not a new
independently-detected effect.

**Tier: unchanged at 3 — not promoted to Tier 2.** This cell fails cost outright (the
CI-based near-edge test misses the hurdle, established above, unrelated to FDR) — a
substantive failure, not a missing-infrastructure gap. Per this study's own established
convention (`M11`'s own entry: "clearing cost doesn't promote it" when FDR/holdout are
the binding constraint), the same logic runs in reverse here: clearing FDR doesn't
promote a cell that fails cost. Also still missing the holdout infrastructure common to
every Tier-3 cell.

**What would change the verdict:** unchanged from above — a broader universe reducing
the 38.2% row loss; a holdout check. FDR is no longer an open item for this cell.

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

---

## M2 — Stack states and Minervini ablation (2026-09-13)

### `stack_fully_bearish`, 21d

**Hypothesis:** The full 4-MA stack in perfect bearish order (price < SMA20 < SMA50 <
SMA150 < SMA200) carries forward-21-day-return information beyond what M1's single
`above_sma_50` state already showed — the specific incremental question this module's
part (a) pre-registered (`PREREGISTRATION.md`, 2026-09-12), not merely whether the
stack cell is nonzero in isolation.

**Why it was plausible:** DESIGN §8 M2 frames this as the highest-expected-value
module in the doc with no kill criterion on the ablation itself; the incremental
question (stack vs. single MA) was pre-registered specifically because M1 already
found `above_sma_50` real-but-cost-failing (Tier 3), leaving open whether *more*
alignment info adds anything beyond that one lookback.

**What was run:** `stack_fully_bearish`'s own C2 (`mom_tercile`/`vol_tercile`/`sector`)
block-bootstrap delta on `fwd_ret_21`, then `block_bootstrap_group_diff` against M1's
`above_sma_50` C2 delta on the row population where both cells are C2-eligible
(intersection of eligibility masks, block length 42, 500 draws, 90% CI) — the kill
rule is M1's own `evaluate_kill_criterion` formula, `max(|ci_low|, |ci_high|) < 0.10%`,
applied to this diff (see `PREREGISTRATION.md`'s 2026-09-13 wording correction: this is
M1's actual rule, not the separate cost-test spans-zero fix an earlier pre-reg
paragraph conflated it with).

**The number(s):** standalone C2 delta +0.4737%, 90% CI [+0.1612%, +0.7761%] (CI
excludes zero). Incremental diff vs. `above_sma_50`: +1.0551%, 90% CI [+0.4189%,
+1.7400%] — **does not clear the kill floor** (`max(0.4189%, 1.7400%) ≥ 0.10%`), i.e.
**not killed: the full stack adds real information beyond the single MA alone**, on
the bearish side. (`stack_fully_bullish`'s mirror-image test *is* killed — diff CI
[−0.0661%, +0.0865%], both endpoints under the 0.10% floor — logged in
`EXPERIMENTS.csv`, no `FINDINGS.md` entry since it's Tier 4.) Independently
reproduced end-to-end against the real DB by the coordinating session (full
408-ticker panel rebuild, not read from the agent's report) — matches to the reported
precision.

**Effective N:** 40,102 raw rows, 2,696 distinct dates, 399 tickers (standalone cell);
133,034 shared rows, 2,672 distinct dates (incremental diff's row population).

**Cost:** `stack_fully_bearish`'s own turnover: 2.863 signals/yr → hurdle 0.286%/yr
(`stats/costs.py`, 10bps/rt, same convention as M1/M4/M11). Point, annualized (×12):
+5.68%, clears. Near edge (+1.934%): clears. Far edge (+9.31%): clears. Clears at
every reading, by a wide margin. `decisive_test_status`: `never_tested` (part (a) has
no per-cell decisive sub-test beyond the kill rule itself, which this cell did not
trigger).

**Tier:** 3 — capped twice over, neither reason optional: (1) missing FDR/holdout
infrastructure, the same cap every Tier-3 cell in this study carries; (2) DESIGN
§7.3's survivorship cap on weak/bearish-state buckets specifically (delisted-ticker
price history exists only 2024–2026 in this repo's loaded data) — `stack_fully_bearish`
is exactly this shape, so it cannot reach Tier 1/2 regardless of how clean these
numbers are.

**Argue against this result — checked 2026-09-17, partially survives (see addendum
below):** the sign pattern — bearish/near-lows predicting *higher* control-adjusted
forward returns, bullish/near-highs predicting *lower* ones (see part (b) below) — is
exactly the signature uncontrolled short-term reversal would produce, not a distinct
Minervini-thesis effect. `mom_12_1` (this module's only momentum control leg, reused
unchanged from M1/M4/M11) deliberately skips the most recent month, so nothing in this
cell's pre-registered C2 spec controls for a stock's very recent drawdown — the same
gap M1 diagnosed and added a `rev_tercile`/`mom_1_0` robustness layer for
(`PREREGISTRATION.md`'s M1 entry, "post-hoc short-term-reversal control"). The
2026-09-17 addendum below runs that same check for this cell: the effect attenuates
but survives, so this is a *partial*, not a full, alternative explanation.

**What would change the verdict:** the whole-grid FDR pass; a holdout check — both
still open, both still required before this cell could reach Tier 1/2 regardless of
the reversal-robustness result below.

### Reversal-robustness addendum (2026-09-17)

Ran the check the paragraph above flagged as missing: `rev_tercile` (prior-21-day-
return tercile, `mom_1_0`'s own bucket, same construction M1 used for its own lb200
diagnostic) added to the C2 match set, `("mom_tercile", "vol_tercile", "sector",
"rev_tercile")` instead of the pre-registered 3-column spec.

**Result: survives, attenuated.** C2 delta +0.4675% → +0.3188% (CI [+0.1488%,
+0.7762%] → [+0.0444%, +0.5976%]), n_events 39,759 → 31,297, n_dates 2,696 → 2,642
(standalone C2-eligible population; not the same row set as this entry's incremental-
diff n_events=40,102 above). The point estimate loses about a third of its magnitude
once short-term reversal is matched out — reversal is a real, partial contributor —
but the CI still excludes zero and clears the 0.10% kill floor by a wide margin (edge
0.598%), and the annualized gross edge (≈+3.83%/yr point, ≈+0.53%/yr near edge,
≈+7.17%/yr far edge) still clears the unchanged 0.2863%/yr cost hurdle at every
reading.

**Reading:** "the stack adds real bearish-side information beyond a single MA" and
"this is entirely uncontrolled 1-month reversal" are no longer both live — the second
is ruled out as a *complete* explanation, though it does explain part of the gross
magnitude. Tier is unchanged at 3 (the FDR/holdout and §7.3 survivorship caps above are
untouched by this result) — this addendum closes the confound question, not the
infrastructure gap. Full numbers: `EXPERIMENTS.csv`,
`stack_fully_bearish_h21_reversal_robustness` row; pre-registration:
`PREREGISTRATION.md`'s M2 entry, "Reversal-robustness addendum."

**Part (b) — Trend Template ablation (descriptive, no tier, no `FINDINGS.md`-worthy
claim per DESIGN's own "kill: none" framing — noted here for completeness, full
numbers in `EXPERIMENTS.csv`):** DESIGN's stated prior ("criteria 6–8 dominate,
MA-stack criteria contribute modestly") did not hold. The single largest linear
attribution coefficient is criterion 7 (within 25% of the 52-week high), and it is
*negative* (−2.31%); the MA-stack criteria (4, 5) are comparable in magnitude to the
momentum criteria, not modest. Corroborates the same-direction primary-cell result:
the all-8-criteria-true subset's C1 delta is −0.171%, the all-8-false subset's is
+0.160% — satisfying the full Trend Template reads *worse*, not better, in this
control-adjusted view. Two caveats logged in `PREREGISTRATION.md`'s 2026-09-13
addendum, not repeated in full here: `linear_attribution` has **no control at all**
(not even C1 date-matching) — read coefficients as first-pass, not controlled;
criteria 6/7 are both derived from the same 52-week range and are likely severely
collinear (opposite-signed, both large) — individual coefficients aren't clean
independent attributions.

### Shape fields addendum (2026-09-15) — `stack_fully_bearish`

DESIGN §6.11.1's three shape fields (hit rate vs. control, win/loss magnitude ratio,
skew — CLAUDE.md invariant #10), computed now because this cell ran after the
invariant existed (2026-09-10) and should have reported them at the time; this is a
same-scope completion, not a backfill of the M1/M4/M11 entries above, which predate
the invariant and are deliberately left alone (DESIGN §6.11.1's own reasoning against
adding a new statistic to an already-tiered result after the fact). Descriptive only,
per the invariant: no CI, no kill criterion, no `N_tests` contribution.

**`stack_fully_bearish`:** raw hit rate 63.85% (`P(fwd_ret_21 > 0 | event)`), hit-rate
delta vs. C1 control +0.63pp, vs. C2 control +0.32pp (same direction as the mean
delta, internally consistent). Win/loss magnitude ratio **1.32** (wins average ~32%
larger than losses). Skew **+0.99** — a real right tail, a few large wins pulling the
distribution, not "loses small often, wins large rarely" in reverse. n_wins=25,606,
n_losses=14,466.

**`stack_fully_bullish` (Tier 4, logged for contrast — this is exactly the shape §6.11.1
was built to catch):** raw hit rate 58.57%, hit-rate delta vs. C2 control **+1.21pp
(positive)** despite the mean C2 delta being essentially flat and CI-spanning-zero
(`-0.064%, [-0.202%,+0.067%]`). Win/loss ratio 1.04 (barely favorable), **skew −0.35**
(a real left tail). Read together: the bullish stack wins slightly more often than its
control, but a meaningful minority of its losses are disproportionately large relative
to its wins — the "high hit rate, flat-to-negative mean, negative skew" signature
DESIGN §6.11.1 names explicitly as invisible to a plain mean/CI. This doesn't change
`stack_fully_bullish`'s Tier 4 verdict (the mean is still the pre-registered kill
criterion's basis, per invariant #10's own rule that shape fields don't carry kill
authority) — it explains *why* the mean looks the way it does, which the CI alone
didn't.

### Whole-grid FDR pass addendum (2026-09-17) — `stack_fully_bearish`

**Does not survive.** The incremental-vs-M1 statistic this entry is built on
(point +1.0551%, CI [+0.4189%, +1.7400%]) has a two-sided Wald p-value (backed out of
the CI, `stats/multiple_testing.py::p_value_from_ci`) of **0.0086** — individually
significant at any conventional threshold, and in fact the single smallest p-value in
this study's entire deduplicated 31-test grid. It still fails Benjamini–Hochberg
correction at q = 0.10: its rank-1 BH threshold is 1/31 × 0.10 = 0.0032, and 0.0086
does not clear it. **Status change: from "capped at Tier 3 by missing FDR
infrastructure" to "tested against FDR, and it failed."** This is not a silent
re-tiering (`EXPERIMENTS.csv`'s original row is untouched; the FDR pass's own summary
row and full ranked table live in `STATUS.md`'s "Whole-grid FDR pass" section) — the
point estimate, CI, and cost annotation above are exactly as reported, and remain the
most defensible standalone reading of this cell. What changes is the whole-grid-aware
conclusion: **this is not distinguishable, at 0.10 FDR, from what you'd expect to see
by chance among 31 independent tests.**

**Reproducibility:** computed end-to-end against the real DB (full 408-ticker panel
rebuild) by the coordinating session, via `stats/shape.py` (new: `hit_rate_deltas`,
`distribution_shape`), wired into `modules/stack_minervini.py::_cell_row`. Full numbers
(including `n_wins`/`n_losses`/`mean_win`/`mean_loss`) in `EXPERIMENTS.csv`'s notes
field for both primary cells.

### Whole-grid FDR pass re-run (2026-09-23) — now survives, tier unaffected

Extending the 2026-09-17 pass's N=35 to N=50 with Batch-1's four new modules
(`STATUS.md`'s "Whole-grid FDR pass" section) changes this cell's own status a second
time: its p-value is unchanged (0.0086), but `slope_pctile_21_sma_50`'s (M6.3,
p=0.00005) very small p-value now anchors BH's rank-1 threshold, and the step-up rule
sweeps this cell in at rank 4 (individually still a miss against its own rank's
threshold, 0.0080 — the same pattern as `ribbon_direction_magnitude`/M7 and
`above_sma_20`/M1 below). Not a new independently-detected effect.

**Tier: unchanged at 3, for the reason already established above and untouched by
this development** — DESIGN §7.3's survivorship cap on weak/bearish-state buckets is a
pre-existing, explicit, named cap (not an infrastructure gap FDR-survival could lift).
This cell now clears both C2 and FDR, which would ordinarily be the Tier-2 bar per
DESIGN §9.2 — but §7.3's cap applies "regardless of what the statistics show," by its
own wording, precisely to prevent a result like this one from reading as more settled
than the underlying delisted-ticker data gap allows. Also still missing the
holdout/universe-tier infrastructure common to every Tier-3 cell.

---

## M6.2 — Slope as conditioner (2026-09-17)

### `extension_x_slope`, SMA50 top decile, 21d ("Finding 1")

**Hypothesis:** DESIGN §6.2's own named sub-question — "is +5 ATR above a flat 50-day
a different object from +5 ATR above a steeply rising one" — restated as a testable
claim: among stocks already in the top decile of `dist_atr_sma_50` (M4's own
"extended" territory), forward-21-day return differs depending on whether the 50-day
is rising or falling.

**Why it was plausible:** DESIGN's own prior for this whole module — "conditioning
demands far less of the data than prediction does," M6.2 named as "the most likely
Tier-1 producer in the whole slope module." M4 had already established that extension
itself (top vs. bottom decile) predicts lower forward returns; this asks whether
*slope*, not just distance, further sharpens that read.

**What was run:** Restrict the main cached panel to `dist_atr_sma_50`'s top decile
(per-date `cross_sectional_bucket`), then `stats.inference.block_bootstrap_delta` with
`group_col=slope_sign_sma_50` (sign of the already-cached, already-lagged
`slope_log_21_sma_50`), `value_col=fwd_ret_21`, C2 match columns unchanged
(`mom_tercile`/`vol_tercile`/`sector`), block length 42, 500 draws, 90% CI — the same
primitive every other module's C1/C2 delta uses, applied to a pre-restricted
population rather than the whole panel.

**The number(s):** C2 delta (rising minus falling, within the top decile) **−0.592%**
per 21d, 90% CI **[−1.047%, −0.175%]** — excludes zero. Read: among equally-extended
stocks, an actively rising 50-day predicts a *lower* forward return than a
flattening/falling one — the opposite of "a rising trend makes overextension safer."

**Effective N:** 104,129 rows, 2,747 distinct dates, 402 tickers (the "rising" side is
94,516 of these; the "falling" side is only 7.1% of the top-decile population — a real
but comparatively rare subgroup, noted as a live caveat below).

**Cost:** combined "top-decile-and-rising" flag's own turnover: 8.061 flips/ticker-yr
→ hurdle 0.806%/yr (`stats/costs.py`, 10bps/rt, same convention as every prior
module). Point, annualized (×12): −7.11%/yr, clears. Near edge (−2.10%/yr): clears.
Far edge (−12.56%/yr): clears. Clears at every reading.

**Tier:** 3 — capped by the same missing FDR/holdout infrastructure every Tier-3 cell
in this study carries; clearing cost doesn't lift it.

**Reversal-robustness (C2 + `rev_tercile`, addendum 2026-09-21):** −0.5503%, CI
[−0.9777%, −0.1033%] — still excludes zero, attenuates only ~6.7% off this addendum's
own freshly-recomputed default-C2 baseline (−0.5898%; see `PREREGISTRATION.md`'s
addendum for a small, separately-noted reproducibility drift against the original
2026-09-17 row that doesn't affect this read). Short-term reversal is not the driver of
this cell's effect.

**Argue against this result (reversal now checked and ruled out; other caveats live):**
M6.3's own explicit warning about post-earnings-gap/low-float contamination of the top
slope decile still applies to this cell's "falling despite being far above" side
specifically — reversal-matching doesn't rule out a *slower* momentum-composition
effect `mom_12_1` itself might not fully capture. The "falling" side's rarity (7.1% of
the top-decile population) means this is a real effect on a specific, non-majority
subgroup, not (yet shown to be) a general one.

**What would change the verdict:** the whole-grid FDR pass (run, see below); a holdout
check.

**Plateau check:** sign agrees with M4's own SMA50 decile-spread sign (extension
already predicts lower returns; this cell's "rising side underperforms the falling
side within the same extended decile" intensifies that pattern rather than
contradicting it).

### `touch_x_slope`, SMA50 from_above, 21d ("Finding 2")

**Hypothesis:** DESIGN §6.2's own named sub-question — "MA touch with rising vs
falling MA — support in an uptrend vs resistance in a downtrend" — restated: among
first-touch-of-the-50-day events approaching from above (M5's own event definition,
applied here to the real MA only, no synthetic-neighbor comparison), `P(hold)` differs
depending on whether the 50-day is rising or falling at the touch day.

**Why it was plausible:** Same DESIGN prior as Finding 1 above — a conditioning
question, not a standalone-signal one. Directly motivated by M5's own touch/bounce
event machinery (`features/touch.py`), reused here unchanged rather than rebuilt.

**What was run:** `features/touch.py::touch_events` on the main cached panel's
`dist_atr_sma_50` (the real MA, not a synthetic neighbor), restricted to `direction=
from_above`, then `block_bootstrap_delta` with `group_col=slope_sign_sma_50` (slope
sign at the touch day), `value_col=hold_flag`, same C2 match columns, block length 10
(M5's own convention for sparse, non-overlapping touch events).

**The number(s):** C2 delta (rising minus falling) **−5.75pp**, 90% CI **[−10.22pp,
−1.94pp]** — excludes zero, far past M5's own 2pp floor. Read: a support test on a
50-day that's still rising holds *less* often than the same test on a falling
50-day — counter to the folklore that an established uptrend makes a pullback safer
to buy.

**Effective N:** 14,138 events, 2,410 distinct dates, 402 tickers.

**Cost:** not applicable, per this module's own pre-registered convention — a
hold-rate comparison is a mechanism read (does the level's own trend direction
matter), not a tradeable-edge question on its own, same reasoning M5 used.

**Tier:** 3 — same infrastructure cap as every Tier-3 cell in this study.

**Reversal-robustness (C2 + `rev_tercile`, addendum 2026-09-21) — this cell does *not*
survive.** −3.3259pp, CI [−8.1800pp, +1.2450pp] — off this addendum's own
freshly-recomputed default-C2 baseline (−5.4968pp, CI [−10.0474pp, −1.8643pp]; see
`PREREGISTRATION.md`'s addendum for a small, separately-noted reproducibility drift
against the original 2026-09-17 row). The point estimate attenuates ~40% and **the CI
now spans zero** — not "killed" under the pre-registered 2pp-floor rule (the edge,
8.18pp, still clears it), but inconclusive rather than confirmed under this control:
effective bootstrap dates also drop from 307 to 196 as the date × mom × vol × sector ×
`rev_tercile` stratification gets sparser. **Read: unlike Finding 1, this cell's gross
number is substantially, not just partially, explained by uncontrolled 1-month
reversal** — the "falling side is a rare, plausibly-just-bounced subpopulation"
alternative this entry itself named as a live caveat turns out to account for most of
the effect, not a small part of it.

**Argue against this result:** no parent-module sign to check this against directly
(M5 found no real-vs-synthetic distinction at any lookback — a different axis
entirely); its own internal-consistency read is the same sign at SMA200/`from_above`
(−8.05pp) though that cell's CI spans zero and is much noisier (`n_events=6,107`) — a
directionally-consistent, not lone-pixel, read, but not independent confirmation
either. The outcome window (5 trading days, M5's own convention) is short — this
cell's CI spans a 5x range between its near and far edges, so the *magnitude* is much
less certain than its sign. **Reversal is now checked, and is the dominant, not a
minor, alternative explanation** (see above) — the strongest of this entry's caveats.

**What would change the verdict:** the whole-grid FDR pass (run, see below — already
failed independently); a holdout check; a longer outcome-horizon robustness check
(5 days is M5's own first-pass choice, not DESIGN-derived) — though given this cell no
longer clears its own confound check, none of these would promote it; at most they'd
further characterize a result already better read as reversal, not slope-conditioning.

**Both findings, read together (revised 2026-09-21):** originally read as "two
independently constructed cells (a decile restriction vs. an event-based restriction),
same lookback, same sign" — a soft corroboration. The 2026-09-21 reversal-robustness
addendum weakens this: **Finding 1 survives reversal-matching essentially intact;
Finding 2 does not** — its CI spans zero once reversal is controlled for. The two
cells no longer corroborate each other as strongly as the original write-up suggested;
Finding 1 is the one with a reversal-independent mechanism behind it, Finding 2 is
better read as substantially a reversal artifact that happened to share Finding 1's
sign and lookback. Full numbers, the unresolved SMA200 extension cell, and the 9
inconclusive cells: `PREREGISTRATION.md`'s M6.2 "Result" section and 2026-09-21
reversal-robustness addendum; `EXPERIMENTS.csv` (14 rows: 12 primary + 2
reversal-robustness).

### Whole-grid FDR pass addendum (2026-09-17) — both findings

**Neither survives.** Finding 1 (`extension_x_slope`/SMA50/top, CI [−1.047%, −0.175%])
has a Wald p-value of **0.0254** (BH rank 7 of 31, threshold 0.0226 — does not clear
it). Finding 2 (`touch_x_slope`/SMA50/`from_above`, CI [−10.22pp, −1.94pp]) has a Wald
p-value of **0.0223** (BH rank 6 of 31, threshold 0.0194 — also does not clear it).
Both are individually significant at the conventional 10% level — both are among the
7 smallest p-values in the study's entire deduplicated grid — and both fail
Benjamini–Hochberg correction at q = 0.10 once the actual number of tests this study
ran (31, not 1 or 2) is accounted for. Full ranked table and methodology:
`STATUS.md`'s "Whole-grid FDR pass" section.

**Status change, same as `stack_fully_bearish`'s own addendum above:** from "capped at
Tier 3 by missing FDR infrastructure" to "tested against FDR, and it failed." Not a
silent re-tiering — `EXPERIMENTS.csv`'s original rows are untouched, the point
estimates/CIs/cost annotation above stand as reported. **The "both findings point the
same direction" corroboration named above is worth re-reading in this light**: two
individually-significant, same-signed results is a weaker form of evidence than it
first appears once you know they're 2 of 31 tests run, not 2 of 2 — DESIGN's own
Sullivan/Timmermann/White motivation for §6.6 (applying a Reality Check to a whole
rule universe substantially weakens results that look strong in isolation) is exactly
what happened here.

## M18 — 52-week high/low range as a standalone predictor (2026-09-20)

Run after this study's formal termination (`STATUS.md`, 2026-09-17) — see
`PREREGISTRATION.md`'s M18 entry and DESIGN.md's M18 section for the full
promoted-from/hypothesis/kill-criterion statement. `dist_from_52w_high` killed
cleanly at both horizons (Tier 4, `EXPERIMENTS.csv` only, no entry needed here); both
entries below are `dist_from_52w_low`.

### `dist_from_52w_low`, 63d

**Hypothesis:** forward 63-day return is a structured function of position within the
trailing 252-day high/low range (`close/rolling_252d_min − 1`) beyond a
momentum/vol/sector-matched control.

**Why it was plausible:** the 2026-09-16 348-cell IC sweep found this the second-
strongest cell in the entire grid (mean IC +0.021 at 63d, +0.037 at 126d) —
strengthening, not fading, with horizon, unlike every SMA-distance feature this study
built. Never run through this study's own C1/C2 machinery before now.

**What was run:** Decile bucket of `dist_from_52w_low` (cross-sectional, per date),
C2-adjusted (`mom_tercile`/`vol_tercile`/`sector`) decile9-minus-decile0 spread on
`fwd_ret_63`, block-bootstrapped (block length 126, 500 draws, 90% CI) —
`modules/high_low_52w.py`, generalizing M11's `cell_result` to a single-column feature.

**The number:** +0.009558, 90% CI [+0.001281, +0.018429]. CI excludes zero.

**Effective N:** 1,095,030 rows, 2,706 distinct dates, 405 tickers.

**Cost:** hurdle 0.8246%/yr (`costs.py::signals_per_year`, 10bps/rt, entry+exit
convention, combined top+bottom-decile legs). Point, annualized (×252/63): +3.82%/yr,
clears. Far edge: +7.37%/yr, clears. **Near edge: +0.51%/yr, fails.**
`decisive_test_status`: `never_tested`.

**Reversal-robustness (C2 + `rev_tercile`):** +1.25%, CI [+0.52%, +1.91%] — still
excludes zero, magnitude essentially unattenuated (if anything larger than the
standard-C2 point). Short-term reversal is not the driver of this cell's effect.

**Tier:** 3. Capped by missing FDR/holdout infrastructure and by failing cost on the
CI-based test.

**Plateau check:** same sign as the 126d cell below, weaker — consistent with the
2026-09-16 sweep's own "strengthens with horizon" finding, not a lone-bright-pixel
reading against its own neighbor.

**What would change the verdict:** the whole-grid FDR pass (run, see below); a holdout
check; decile-level (not tercile) C2 matching at a broader universe.

### `dist_from_52w_low`, 126d

**Hypothesis:** same as above, at a 126-day horizon — the horizon where the 2026-09-16
sweep found this feature's IC strongest.

**Why it was plausible:** same motivation as the 63d cell; DESIGN's own M18 section
also flags the George & Hwang 52-week-high academic anomaly as a standard prior for
this feature family generally (that literature's claim runs the opposite direction on
`dist_from_52w_high`, not this feature — see the M18 pre-registration entry's own
discussion of the sign question, resolved by `dist_from_52w_high` killing cleanly
rather than confirming either direction).

**What was run:** identical construction to the 63d cell, `fwd_ret_126`, block length
252.

**The number:** +0.025042, 90% CI [+0.011043, +0.040170]. CI excludes zero.

**Effective N:** 1,069,515 rows, 2,643 distinct dates, 405 tickers.

**Cost:** hurdle 0.8336%/yr. Point, annualized (×252/126): +5.01%/yr, clears. Near
edge: +2.21%/yr, **clears**. Far edge: +8.03%/yr, clears. **Clears cost at every
reading** — the same shape as `stack_fully_bearish` (M2) and `extension_x_slope`/SMA50
(M6.2), this study's other two cost-clearing Tier-3 cells.

**Reversal-robustness (C2 + `rev_tercile`):** +2.64%, CI [+1.57%, +3.71%] — still
excludes zero, essentially unattenuated (if anything a touch larger, tighter CI).
Short-term reversal is not the driver of this cell's effect either.

**Tier:** 3. Capped by missing FDR/holdout infrastructure, not by cost or by this
confound.

**Plateau check:** same sign as the 63d cell, stronger — matches the 2026-09-16 sweep's
own horizon-shape finding exactly (both features get stronger, not weaker, from 63d to
126d), the cleanest plateau read of any of this study's cells that varies by horizon
rather than by lookback or decile.

**Argue against this result:** `mom_tercile` (built from `mom_12_1`) is conceptually
close to `dist_from_52w_low` — both are functions of roughly the trailing year's price
path — so a cell that survives this particular C2 match is clearing a harder bar than
most of this study's other C2 tests, not an easier one; that said, "close to" is not
"identical to," and a genuinely tighter momentum control (e.g. decile rather than
tercile matching, or a direct residualization of `dist_from_52w_low` on `mom_12_1`)
has not been run. No holdout check. `dist_from_52w_high` and `dist_from_52w_low` are
only moderately correlated (per-date median Spearman 0.4677, checked before trusting
these as 2 of 4 independent M18 cells) — not so correlated that `dist_from_52w_high`'s
clean kill at both horizons should be read as corroborating evidence against this cell
being real; they are different quantities, empirically as well as by construction.

**What would change the verdict:** the whole-grid FDR pass (run, see below); a holdout
check; a decile-level (not tercile) C2 match; a direct residualization of
`dist_from_52w_low` against `mom_12_1` rather than tercile-matching it.

### Whole-grid FDR pass re-run (2026-09-20) — both `dist_from_52w_low` cells

**Neither survives, but this is the closest miss in the whole study.** M18's 4 primary
cells were added to the 2026-09-17 pass's deduplicated 31-test grid (N=35 — see
`STATUS.md`'s "Whole-grid FDR pass" section for the full updated ranked table), per
this entry's own pre-registered "FDR re-entry" plan (`PREREGISTRATION.md`) — not
reported as a standalone significance claim outside the study's whole-grid discipline.

**`dist_from_52w_low`, 126d is now the smallest Wald p-value in the entire study**
(0.0047, rank 1 of 35) — smaller than `stack_fully_bearish`'s 0.0086 (now rank 2). Its
own BH threshold at rank 1 is 0.10/35 = 0.002857; **0.0047 is 1.64× that threshold** —
still a miss, but a tighter one than any cell in this study has come to clearing its
own threshold (the prior closest, `stack_fully_bearish`, missed by 2.7×). `dist_from_
52w_low`, 63d (p = 0.0667, rank 10 of 35) is not close. **0 of 35 rejected at q = 0.10,
0 of 35 at q = 0.05.**

**Status, same convention as every other Tier-3 cell's FDR addendum:** "capped at
Tier 3 by missing FDR infrastructure" → "tested against FDR, and it failed." The point
estimate, CI, and cost-clearance reported above stand unchanged — what changed is the
accounting for how many hypotheses produced this number, not the underlying evidence.
Worth naming directly: **this is the single closest a result in this entire study has
come to surviving multiple-testing correction**, and it was found by explicitly
continuing to look after the study's own termination criteria had already been met —
a genuine tension with "a null result is a successful outcome, don't keep looking for a
cut that works" (CLAUDE.md), resolved here only because the candidate was flagged by
two independent methods *before* this test was run, pre-registered with an honest kill
criterion, and killed by the correction on the same terms as everything else — not
because looking longer was assumed to eventually pay off.

### Whole-grid FDR pass re-run (2026-09-23) — now survives

**The closest miss became a survivor.** The pass above extended the grid to N=35;
Batch-1's four new modules extend it further to N=50 (`STATUS.md`'s "Whole-grid FDR
pass" section, 2026-09-23 update). This cell's own p-value is unchanged (0.0047) — what
changed is the ranking around it: `slope_pctile_21_sma_50` (M6.3, p=0.00005) now anchors
rank 1 with a threshold so far under its own p-value that BH's step-up procedure sweeps
in every smaller-p cell ranked ahead of where this cell's own threshold would otherwise
fall, including this one (now rank 2 of 50, threshold 0.0040 — still individually a
miss at its own rank, but caught by the step-up rule from rank 5's clearance). **This
is not a new, independently-detected effect** — the underlying number is identical to
the 2026-09-20 reading; only the correction's context changed.

**Tier: unchanged at 3 — not promoted to Tier 2.** M6.3's `slope_pctile_21_sma_50`
carried an analogous caveat and *was* promoted the same day (see that entry), once a
direct rising-tail-only vs. falling-tail-only decomposition ruled it out. **That test
doesn't transfer here**, and this cell stays unresolved for a structural reason: this
cell's own hypothesis is specifically *about* the near-52-week-low population — a
stock that recently sat near its 52-week low is, by construction, in a weak/
beaten-down state, structurally the same population M1's and M2's already-capped
buckets occupy. Unlike `slope_pctile_21_sma_50`'s two-sided, symmetric construction
(which could be split into a survivorship-exposed half and a survivorship-immune half
and compared), this cell's claim is asymmetric and squarely about the weak-state
population itself — there's no survivorship-immune "other side" to decompose it
against. A pre-2024-delisted, bankrupt ticker would have traded near its 52-week low
immediately before disappearing from this panel (DESIGN §7.3's delisted-history
ceiling); if such tickers are systematically absent from exactly this bucket, its
observed forward return is inflated the same way §7.3 already documents for M1/M2.
Closer in kind to `stack_fully_bearish`'s already-accepted cap than to a resolvable
open question — extended by analogy rather than literal enumeration (DESIGN §7.3
names M1/M3/M4 only). Also still capped by the pre-existing holdout/universe-tier
infrastructure gap, unchanged by this result.

**What would change the verdict:** a delisted-history extension pre-2024 (DESIGN
§7.3's own stated resolution path) or an explicit bound against a published reference
using full delisted-history data — either would let this cell's survivorship exposure
actually be checked instead of argued from mechanism; a holdout check; a second
universe tier.

## M7 — Ribbon compression / expansion (2026-09-22)

### `ribbon_direction_magnitude`, 21d

**Hypothesis:** DESIGN's own M7 text — low MA-ribbon dispersion (compression) precedes
volatility expansion. Restated as a testable claim on the specific outcome this cell
uses: among rows in the bottom decile of `ribbon_width_pctile` (a compressed SMA
ribbon, {20,50,150,200}), the subsequent 21-day |return| (net displacement magnitude,
distinct from full-window realized vol) is larger than among rows in the top decile
(an already-dispersed ribbon).

**Why it was plausible:** DESIGN's own stated prior for this module — "vol prediction
works ... direction prediction does not, except conditional on prior trend." This
specific cell tests the vol-adjacent half of that prior on a magnitude measure, as a
sibling to (not a replacement for) the module's direct realized-vol cells, which came
out null (see below).

**What was run:** `ribbon_width` (coefficient-of-variation dispersion of the four
already-cached SMAs, `features/ribbon.py`) scaled into `ribbon_width_pctile` (per-ticker
rolling min-max range position over a trailing 252-day window — a fast, vectorized
approximation of a rolling percentile rank, same construction family as this
codebase's own `dist_from_52w_high`/`dist_from_52w_low`) and bucketed into 10 deciles.
`stats/inference.py::block_bootstrap_spread` (M4/M11/M18's own decile-spread
primitive, reused unchanged), decile-9-minus-decile-0 spread of `fwd_absret_21`
(`|forward 21-day return|`, a new label — `labels/forward_returns.py`), C2-matched
(`mom_tercile`/`vol_tercile`/`sector`).

**The number:** −0.2471%, 90% CI [−0.3976%, −0.0927%]. CI excludes zero, clears the
pre-registered 0.10% floor.

**Effective N:** 175,152 rows, 2,549 distinct dates, 402 tickers.

**Cost:** compressed-decile membership flag turnover 3.163 flips/ticker-yr → hurdle
0.3163%/yr (`stats/costs.py`, 10bps/rt, entry+exit convention, same as every prior
module). Point, annualized (×12): −2.97%/yr, clears. Near edge (−1.11%/yr): clears.
Far edge (−4.77%/yr): clears. **Clears at every reading — but with a caveat distinct
from every other Tier-3 cell in this study**: `fwd_absret_21` is a magnitude, not a
signed return. "Clears cost" here means the shift in |return| exceeds the turnover
cost of the flag, not "going long or short this signal is profitable" — no signed
trading strategy is tested or implied. Turning this into an actionable claim would
need a specific construction this cell doesn't provide (e.g. a long-volatility/
straddle-style position, or a position-sizing/stop rule keyed to the flag).

**Tier:** 3 — capped by the same missing FDR/holdout infrastructure every Tier-3 cell
in this study carries, *and* by the magnitude-vs-signed-return actionability gap named
above (a second, cell-specific cap).

**Reversal-robustness (2026-09-23 addendum) — survives, if anything strengthened.**
The leading candidate confound was short-term reversal/mean-reversion — the same
confound class this study has checked repeatedly elsewhere (M1's lb200 diagnostic,
M2's `stack_fully_bearish` addendum, M18's `dist_from_52w_low` cells, M6.3's SMA50/200
cells, all via a `rev_tercile`/`mom_1_0`-augmented C2). Decile 9 (dispersed ribbon)
mechanically correlates with tickers that *just had* a large recent price move — that's
mechanically what pushed the ribbon apart; if such tickers partially mean-revert, their
subsequent |return| would shrink relative to decile 0's for reasons having nothing to
do with "compression precedes expansion." C2 + `rev_tercile` (prior-1-day-return
tercile, `modules/slope_conditioner.py`'s own `C2_MATCH_COLS_WITH_REVERSAL`
construction): **−0.266%**, CI **[−0.424%, −0.103%]** (n_events/n_dates unchanged,
175,152/2,549). The point estimate is ~7.6% *larger* in magnitude than the default-C2
number, not smaller, and the CI still excludes zero. **Not explained by short-term
reversal — if anything sharpened.** Full detail: `PREREGISTRATION.md`'s M7
reversal-robustness addendum.

**Plateau check:** not a lookback-neighborhood question (this module has no lookback
grid — {20,50,150,200} is the whole ribbon) — read instead as internal consistency
against this module's own sibling cells: the two vol-expansion readings (with/without
`vol_tercile` match) agree in sign and magnitude with each other (both null, same
direction), and this cell's own sign is directionally consistent with M4's own
extension-predicts-lower-forward-return finding in spirit (net displacement is larger,
not that displacement is necessarily *positive*) — not a formal cross-module plateau
check, just a directional sanity read.

**What would change the verdict:** the whole-grid FDR pass (pending, not yet re-run —
see `STATUS.md`); a holdout check; and, separately from any statistical test, an actual
strategy construction that would make the magnitude-vs-signed-return caveat moot (this
cell alone cannot answer "is this tradeable," only "is the effect real"). (The
reversal-robustness check above is now resolved — this cell survives it.)

**Companion cells, not separately entered here (Tier 4, `EXPERIMENTS.csv` only):**
both vol-expansion readings (`ribbon_vol_expansion_c2_standard`/`_c2_no_vol_match`)
killed cleanly under the pre-registered floor — DESIGN's "vol prediction works" prior
does not hold in this specific 21-day realized-vol construction, a clean negative.
`ribbon_direction_signed` (unconditional direction) is inconclusive, consistent with
DESIGN's own prior. `ribbon_direction_conditional_on_trend` is also inconclusive —
notably **not** confirming DESIGN's own stated prior that trend-conditional direction
should show more signal than unconditional direction; stated plainly as a partial
disconfirmation of that prior, not smoothed over.

### Whole-grid FDR pass addendum (2026-09-23) — `ribbon_direction_magnitude`

**Survives.** Added to the whole-grid pass's deduplicated grid (N=50 —
`STATUS.md`'s "Whole-grid FDR pass" section) per HANDOVER.md's consolidation plan.
Two-sided Wald p-value: **0.0077**, individually below its own rank-3 threshold at N=50
(0.0060 — a genuine individual miss, same shape as `stack_fully_bearish`/`above_sma_20`
below), but swept into BH's rejection set by the step-up rule once
`slope_pctile_21_sma_50`'s (M6.3) very small p-value anchors rank 1. Mathematically
valid under BH, not a new independently-detected effect — the underlying number is
unchanged from this module's own original write-up.

**Tier: unchanged at 3 — not promoted to Tier 2.** Clearing FDR resolves one of this
cell's two named caps (missing FDR infrastructure); it does nothing for the other,
cell-specific one: the magnitude-vs-signed-return actionability gap named at this
entry's own "Cost" section above. `fwd_absret_21` is not a tradeable direction — no
amount of statistical significance on a magnitude statistic answers "is this
profitable," only "is the effect on |return| real." That gap, not an infrastructure
gap, is what keeps this at Tier 3 regardless of FDR status. Still also missing the
holdout/universe-tier infrastructure common to every Tier-3 cell in this study.

**What would change the verdict:** a specific tradeable construction built on top of
this magnitude effect (e.g. a long-volatility/straddle-style position) that would let
"clears cost" mean something directional; a holdout check; a second universe tier.

---

## M6.3 — Slope magnitude: monotonic or humped? (2026-09-22)

DESIGN's own hypothesis for this module was "humped" (middle-magnitude slope beats
extreme slope, "some trend is good, too much is exhaustion"). **All three lookbacks
found the opposite: a U-shape.** Two logged deviations from DESIGN's literal method
text shape all three entries below — `slope_atr_21` was not built (a price-unit slope
that conflicts with CLAUDE.md invariant #7); `slope_pctile_21` (cross-sectional rank of
the existing log-scale `slope_log_21_sma_k`) is used instead. The "earnings-excluded
companion" DESIGN asks for is a proxy (`recent_large_move`, a large-single-day-move
exclusion flag) — no earnings-date table exists anywhere in this repo's DB. Full
scope, method, and deviation rationale: `PREREGISTRATION.md`'s M6.3 entry.

### `slope_pctile_21_sma_50` — middle vs. tails, 21d

**Hypothesis:** forward 21-day return differs between stocks in the middle deciles
(4, 5) of `slope_pctile_21_sma_50` and stocks in the pooled tail deciles (0, 1, 8, 9).

**Why it was plausible:** DESIGN's own module (predicted humped, not U-shaped) —
tested here as a genuine open question, not assumed in advance.

**What was run:** `stats.inference.block_bootstrap_delta` (block length 42, 500
draws, 90% CI), `group_col=is_middle`, `value_col=fwd_ret_21`, restricted first to
only the middle+tail decile rows, C2 match columns unchanged
(`mom_tercile`/`vol_tercile`/`sector`) — the same restrict-then-delta primitive
M6.2's own sub-questions use.

**The number:** C2 delta (middle minus tails) **−0.248%** per 21d, 90% CI
**[−0.354%, −0.153%]** — excludes zero. Read: stocks with the steepest slope
magnitude, rising *or* falling, outperform stocks with the flattest slope — the
opposite of "some trend is good, too much is exhaustion."

**Effective N:** 219,700 rows, 2,747 distinct dates, 402 tickers.

**Cost:** combined `is_middle` state-flip turnover (`stats/costs.py::signals_per_year`,
same convention as M1): 7.691 flips/ticker-yr → hurdle 0.769%/yr. Annualized (×12):
point −2.976%/yr, near edge −1.833%/yr, far edge −4.248%/yr — **clears at every
reading.** This study's fifth cost-clearing Tier-3 cell (alongside `stack_fully_bearish`
/M2, `extension_x_slope`-SMA50/M6.2, `dist_from_52w_low`@126d/M18, and this module's own
SMA200 cell below).

**Robustness (recent-large-move-excluded companion):** −0.264%, CI [−0.376%, −0.168%]
— survives essentially unattenuated (if anything slightly larger). Recent large
single-day moves are not the driver of this cell's effect.

**Tier:** 3 — capped by the same missing FDR/holdout infrastructure every Tier-3 cell
in this study carries; clearing cost and the large-move-exclusion check doesn't lift
it. **Not yet run through the whole-grid FDR pass** (pending re-entry — see
`PREREGISTRATION.md`).

**Reversal-robustness (2026-09-22 addendum):** C2 + `rev_tercile` (prior-1-day-return
tercile, `modules/slope_conditioner.py`'s own `C2_MATCH_COLS_WITH_REVERSAL`
construction): **−0.283%**, CI **[−0.389%, −0.175%]** (n_events/n_dates unchanged,
219,700/2,747). The point estimate is ~13.9% *larger* in magnitude than the default-C2
number, not smaller, and the CI still excludes zero by a wide margin. **Survives —
if anything strengthened, not explained by short-term reversal.** Full detail:
`PREREGISTRATION.md`'s M6.3 reversal-robustness addendum.

**What would change the verdict:** the whole-grid FDR pass; a holdout check. (The
reversal-robustness check above is now resolved — this cell is the module's
reversal-robust survivor, unlike the SMA200 cell below.)

**Plateau check:** same sign as SMA20 and SMA200 (below) — not a lone bright pixel on
the headline sign — but the *shape* is not uniform across lookbacks: SMA50/200 are
roughly symmetric (both tails elevated), SMA20 is asymmetric (falling-tail-driven) and
does not survive its own large-move-exclusion check. See `PREREGISTRATION.md`'s
per-decile `shape_table` numbers for the full picture.

### Whole-grid FDR pass addendum (2026-09-23) — `slope_pctile_21_sma_50`

**Survives — the first cell in this study's history to clear Benjamini–Hochberg
correction.** Added to the whole-grid pass's deduplicated grid (N=50, up from 35 —
`STATUS.md`'s "Whole-grid FDR pass" section has the full ranked table and dedup
accounting) per HANDOVER.md's consolidation plan. Two-sided Wald p-value backed out of
this cell's own CI: **0.00005** — its rank-1 BH threshold at N=50 is 0.0020, so this
clears by more than an order of magnitude, and it is the only one of this pass's 5
survivors that also clears the stricter q=0.05 screen. Stress-tested against three
alternative reasonable ways to count Batch-1's new cells (N=47/50/51): rank 1 and its
p-value are unchanged in every case — this is not an artifact of a specific dedup
judgment call.

**Tier: promoted to 2 — the first Tier-2 result in this study's history**, resolved
the same day the caveat above was first raised, via a direct test rather than left
open. The caveat: this cell's tail-decile population includes the
extreme-negative-slope rows, structurally the same shape of population as M1's
already-capped "weak/below-MA-state" bucket and M2's already-capped
`stack_fully_bearish` — a row a pre-2024-delisted, bankrupt ticker would have occupied
immediately before disappearing from this panel (DESIGN §7.3's delisted-history
ceiling, 2024–2026 coverage only). If such tickers were systematically missing from
exactly this bucket, the bucket's observed forward return would be inflated by the
same survivorship mechanism §7.3 already names for M1/M2.

**Resolved by direct test (2026-09-23 tail-decomposition addendum), not by
analogy.** Split the pooled tail into rising-only (deciles 8,9 — zero survivorship
exposure, the strongly-bullish side) vs. falling-only (deciles 0,1 — the
theoretically-exposed side), each compared against the same middle deciles (4,5)
independently. **Rising-tail-only: `c2=-0.2544%`, CI `[-0.4290%,-0.0846%]` — excludes
zero. Falling-tail-only: `c2=-0.2442%`, CI `[-0.4127%,-0.0959%]` — excludes zero.**
The two are within 5% of each other's magnitude. If the pooled result were a
falling-tail survivorship artifact, the rising-tail-only reading — immune to that
mechanism by construction — would be null or much smaller; instead it independently
confirms the same effect. This is not a literal application of DESIGN §7.3's own
enumerated cap (M1/M3/M4 only) — the concern was raised by analogy, and now ruled out
by a direct test, the same standard the short-term-reversal confound above was held
to. Full detail: `PREREGISTRATION.md`'s M6.3 tail-decomposition addendum.

**Per DESIGN §9.2, Tier 2 = "survives C2 and FDR, but fails one of: universe
generality, holdout, or cost."** This cell now clears C2, FDR (both q=0.10 and
q=0.05), and cost at every reading; its remaining gaps (holdout, a second universe
tier) are missing infrastructure, not failures — exactly the Tier-2 profile. This is
the first cell in the study to reach it.

**What would change the verdict:** a holdout check; a second universe tier — the same
two items every other Tier-3 cell in this study is still waiting on, now the only
two remaining for this one.

### `slope_pctile_21_sma_200` — middle vs. tails, 21d

**Hypothesis / what was run:** identical construction to the SMA50 cell above, at
lookback 200.

**The number:** C2 delta **−0.193%** per 21d, 90% CI **[−0.337%, −0.056%]** —
excludes zero.

**Effective N:** 219,731 rows, 2,747 distinct dates, 402 tickers.

**Cost:** turnover 3.819 flips/ticker-yr → hurdle 0.382%/yr. Annualized (×12): point
−2.313%/yr, near edge −0.668%/yr, far edge −4.044%/yr — **clears at every reading.**
This study's sixth cost-clearing Tier-3 cell.

**Robustness (recent-large-move-excluded companion):** −0.169%, CI [−0.312%, −0.030%]
— survives with modest attenuation. Recent large single-day moves are a partial but
not dominant contributor.

**Tier:** 3 — same infrastructure cap as every Tier-3 cell in this study. **Not yet
run through the whole-grid FDR pass.**

**Reversal-robustness (2026-09-22 addendum) — does not survive.** C2 + `rev_tercile`:
**−0.038%**, CI **[−0.198%, +0.120%]** (n_events/n_dates unchanged, 219,731/2,747) —
attenuates ~80.5% from the default-C2 point estimate and **the CI now spans zero**.
Unlike the SMA50 cell above, this cell's gross number is now best read as
substantially, not just partially, a short-term-reversal artifact — the
falling-tail/bounce mechanism named as a live alternative at pre-registration
substantially accounts for it. Does not change the tier (already Tier 3, already
pending the same whole-grid FDR re-entry as every other cell here) but materially
weakens confidence in the underlying "slope magnitude, not just direction, matters at
SMA200" mechanism claim. Full detail: `PREREGISTRATION.md`'s M6.3 reversal-robustness
addendum.

**What would change the verdict:** already resolved unfavorably by the check above;
a holdout check remains open but is now secondary to the reversal read.

**Plateau check:** same sign as SMA20/SMA50; roughly symmetric tail shape like SMA50,
unlike SMA20.

### `slope_pctile_21_sma_20` — middle vs. tails, 21d (fails cost and its own
robustness check — reported in full per this study's own convention that a cost- or
robustness-failing Tier-3 cell still gets a complete entry, same as M4's
`dist_pct_sma_20`@21d)

**Hypothesis / what was run:** identical construction to the SMA50/200 cells above, at
lookback 20.

**The number:** C2 delta **−0.117%** per 21d, 90% CI **[−0.229%, −0.006%]** —
excludes zero, clears the 0.10% kill floor.

**Effective N:** 219,654 rows, 2,747 distinct dates, 402 tickers.

**Cost:** turnover 13.365 flips/ticker-yr (by far the highest of the three lookbacks)
→ hurdle 1.337%/yr. Annualized (×12): point −1.408%/yr (clears), near edge −0.075%/yr
— **fails** — far edge −2.743%/yr (clears). **Fails on the CI-based test.**

**Robustness (recent-large-move-excluded companion): does not survive.** −0.117%, CI
**[−0.237%, +0.001%]** — the CI now spans zero, the only one of the three lookbacks
where the large-move exclusion flips the read. Read: this cell's gross effect looks
substantially driven by exactly the gap-contamination mechanism DESIGN's own "watch
for" line named for this module, not a real U-shape distinguishable from that
confound.

**Tier:** 3 on the literal CI-excludes-zero kill rule, but functionally the weakest
cell in this module — fails cost *and* fails its own robustness companion, unlike
SMA50/200 which pass both. Not promoted to the same standing as its siblings.

**Argue against this result:** the large-move-exclusion failure above is itself the
strongest argument against treating this as a real effect — it isn't a live,
unresolved caveat here, it's a check that was run and failed.

**What would change the verdict:** nothing pre-registered in this pass would rescue
this cell — its own robustness companion already killed the confound-free reading.

**Plateau check:** same sign as SMA50/200 (middle underperforms tails), but the shape
is asymmetric — concentrated on the falling side (decile 0 = +0.104%, decile 1 =
+0.125%) with the rising side barely positive to negative (decile 8 = −0.062%, decile
9 = +0.015%, per `PREREGISTRATION.md`'s `shape_table` numbers) — a different shape
from SMA50/200's roughly symmetric U, not just a noisier version of the same one.

---

## M13 — Context conditioning (2026-09-22)

Post-termination module, one of a batch of parallel Batch-1 modules scoped and run
independently (see `PREREGISTRATION.md`'s M13 entry for the full hypothesis/method/
kill-criterion statement). Both entries below carry an unusually strong "read this
skeptically" framing in their own text, not as a hedge but as the entry's actual
honest reading of the evidence — see "Why this probably isn't real" in each.

### `above_sma_200`, restricted to VIX bottom tercile ("low-VIX regime")

**Hypothesis:** M1's own `above_sma_200` conditional effect on `fwd_ret_21` differs
materially in a low-VIX regime (bottom trailing tercile of FRED's `VIXCLS`, 252-day
rolling window) vs. the whole-sample baseline.

**What was run:** `block_bootstrap_delta(group_col="above_sma_200",
value_col="fwd_ret_21", match_cols=("mom_tercile","vol_tercile","sector"))` — M1's own
C2 spec, unchanged — restricted to rows where a trailing 252-day rolling VIX
percentile rank falls in the bottom tercile.

**The number(s):** C2 delta **−0.318%** per 21d, 90% CI **[−0.551%, −0.073%]** —
excludes zero.

**Effective N:** 392,184 rows, 1,195 distinct dates, 402 tickers.

**Cost:** turnover (above_sma_200 flip rate within this regime-restricted population)
6.894 flips/ticker-yr → hurdle 0.689%/yr (`stats/costs.py`, 10bps/rt — a labeled
simplification, does not additionally count regime-entry/exit turnover). Annualized
(×12): point −3.82%/yr, near edge −0.87%/yr, far edge −6.61%/yr. **Clears at every
reading, but barely** — the near-edge margin over the hurdle is under 0.2pp/yr.

**Tier:** 3, by this study's own mechanical convention (CI excludes zero, clears
cost → Tier 3, capped by missing FDR/holdout infrastructure). **Pending whole-grid
FDR re-entry** — not run in this module's own pass; the coordinating session re-runs
the whole-grid pass once, after every parallel Batch-1 module lands.

**Why this probably isn't real (the actual honest read, not a formality):** M1's own
`above_sma_200` whole-sample cell already has a CI that "touches zero" and carries
this study's most heavily flagged SMA200 anomaly (`STATUS.md`'s cross-module SMA200
watch). This cell's point estimate (−0.318%) is the same sign and same order of
magnitude as that whole-sample number (−0.215%) — not a larger, distinctly
regime-driven effect, just ordinary sampling variation around an already-small,
already-borderline number, exposed by restricting to one half of a binary regime
split. Splitting a near-zero cell into independent binary facets and finding that
*some* of the resulting buckets' CIs exclude zero is close to the base-rate outcome
that kind of slicing produces on its own — exactly the shape DESIGN's own
multiple-testing discipline exists to catch. Shape stats reinforce this reading only
partially: hit rate 57.09% (C2 delta −0.81pp, consistent direction with the mean),
win/loss ratio 1.11, skew +0.30.

**What would change the verdict:** the whole-grid FDR pass (very likely to kill this,
given the reasoning above); a formal delta-of-deltas test against the whole-sample or
opposite-bucket estimate (not built this slice, see `PREREGISTRATION.md`'s kill-
criterion section); a holdout check.

### `above_sma_200`, restricted to breadth top tercile ("high-breadth regime")

**Hypothesis:** M1's own `above_sma_200` conditional effect on `fwd_ret_21` differs
materially in a high-breadth regime (top trailing tercile of `pct_above_sma_200`,
the U1 universe's own cross-sectional breadth, 252-day rolling window) vs. the
whole-sample baseline.

**What was run:** identical construction to the VIX cell above, restricted instead to
rows where the trailing rolling percentile rank of daily cross-sectional breadth
falls in the top tercile.

**The number(s):** C2 delta **−0.388%** per 21d, 90% CI **[−0.690%, −0.074%]** —
excludes zero.

**Effective N:** 298,354 rows, 882 distinct dates, 402 tickers.

**Cost:** turnover 6.404 flips/ticker-yr → hurdle 0.640%/yr. Annualized (×12): point
−4.66%/yr, near edge −0.88%/yr, far edge −8.28%/yr. **Clears at every reading, but
barely** — same shape as the VIX cell above.

**Tier:** 3, same mechanical convention and same FDR-pending status as the VIX cell
above.

**Why this probably isn't real:** the same argument as the VIX cell above applies in
full — same sign, same order of magnitude as M1's own whole-sample −0.215%, most
plausibly the same weak baseline effect exposed by regime-slicing rather than a
distinct high-breadth mechanism. Shape stats here are *less* consistent with a
coherent story than the VIX cell's: hit rate 57.72% but the **hit-rate C2 delta is
essentially zero/slightly positive (+0.15pp)** despite a negative mean delta — a
"more frequent small losses, not fewer wins" shape isn't what the hit-rate number
shows, which argues against reading this as a clean effect even before the FDR pass
runs. Win/loss ratio 1.02, skew −0.74.

**What would change the verdict:** same as the VIX cell above.

**Both cells, read together:** two regime facets (VIX, breadth), both producing a
CI-excluding-zero, cost-clearing bucket on the same underlying M1 cell, with the same
sign and similar magnitude to M1's own already-weak whole-sample number and to each
other. This is the shape of "an already-borderline cell sliced two more ways,
producing two more borderline-significant sub-cells" — not the shape of "a real,
economically distinct regime interaction was found." Logged honestly as Tier 3 per
this study's mechanical convention, with this reasoning attached rather than presented
as a clean finding.

---

## M6.6 — Slope agreement across the ribbon (2026-09-23)

### `ribbon_agreement_extreme_drawdown`

**Hypothesis:** DESIGN's own M6.6 text — the fraction of the ribbon {10, 20, 50, 100,
200} with positive slope, as an ordinal 0–5 state, is associated with forward outcomes,
"more likely to be useful," per DESIGN, "in forward *drawdown*" than in forward return.
Restated as the decisive, testable claim this cell runs: the two extremes of that
ordinal state — state 5 (all five lookbacks rising) vs. state 0 (all five falling) —
differ in `fwd_mdd_21` (the worst low touched over the next 21 trading days, relative to
today's close), beyond what a single MA's own slope, momentum, volatility, and sector
already explain.

**Why it was plausible:** DESIGN's own stated intuition — synchronized agreement across
every timeframe at once (not just one MA) is a stronger "healthy uptrend" signal than
any single lookback alone, and a stronger such signal should manifest first as reduced
downside risk (shallower drawdowns), before it necessarily shows up as higher expected
*return* (a noisier, harder-to-detect outcome at this horizon).

**What was run:** `slope_log_21_sma_{10,100}` built module-local (rolling SMA off raw
`close`, then `slope_log_k`, then the shared `apply_lag`) since the cached panel has no
10-day or 100-day SMA; `slope_log_21_sma_{20,50,200}` reused from the cache unchanged.
`ribbon_agreement_state` = count of the five lookbacks with positive slope (NaN unless
all five are defined — CLAUDE.md invariant #9, enforced by this module's own test).
`labels/path_metrics.py::forward_max_drawdown` (new label): the worst
`low[t+k]/close[t] − 1` for k in 1..21. `stats/inference.py::block_bootstrap_delta`
(reused unchanged, block length 42, 500 draws, 90% CI, seed 0), C2-matched
(`mom_tercile`/`vol_tercile`/`sector`), restricted to states {0, 5} first, then a
`is_high` (state==5) group delta — same restrict-then-delta construction M6.2/M6.3
established.

**The number:** **+0.6538%**, 90% CI **[+0.4379%, +0.8870%]**. CI excludes zero, clears
the pre-registered 0.10% floor. Positive means state 5's worst 21-day drawdown is
*shallower* (less negative) than state 0's, by 0.65 percentage points, beyond the C2
match.

**Effective N:** 406,663 rows, 2,747 distinct dates, 402 tickers.

**Cost:** `ribbon_agreement_state == 5` ("fully agreeing bullish") flag turnover: 5.415
flips/ticker-yr → hurdle 0.5415%/yr (`stats/costs.py`, 10bps/rt, entry+exit convention,
same as every prior module). Point, annualized (×12): +7.85%/yr, clears. Near edge
(+5.25%/yr): clears. Far edge (+10.64%/yr): clears. **Clears at every reading — with the
same kind of caveat M7's `ribbon_direction_magnitude` carries**: `fwd_mdd_21` measures
an avoided-loss/drawdown-shallowing effect, not a signed realized-return claim. "Clears
cost" here means the shift in worst-case-drawdown exceeds the turnover cost of the
flag, not "going long this signal earns excess return" — no signed trading strategy is
tested here (the companion return-outcome cell, below, is the direct test of that, and
it does not confirm).

**Tier:** 3 — capped by the same missing FDR/holdout infrastructure every Tier-3 cell in
this study carries, and by the avoided-loss-vs-signed-return actionability gap named
above (a second, cell-specific cap, same shape as M7's).

**Reversal-robustness (2026-09-23, run same day) — survives, mildly attenuated.** The
leading candidate confound: state 5 (all-rising ribbon, including the fast 10-day MA)
mechanically overlaps heavily with "strong recent short-term momentum" (`mom_1_0`);
stocks that have just risen sharply across every timeframe at once may simply be less
likely to have a rough next 21 days for reasons of short-term continuation/reversal
dynamics, nothing to do with "ribbon agreement" as a distinct construct. C2 +
`rev_tercile` (prior-1-day-return tercile, this module's own
`C2_MATCH_COLS_WITH_REVERSAL`, same construction as M2's/M6.3's/M7's own reversal
checks): **+0.5346%**, CI **[+0.2397%, +0.8361%]** (n_events/n_dates/n_tickers
unchanged, 406,663/2,747/402). Attenuates ~18% but the CI still excludes zero and
clears the 0.10% floor by a wide margin — reversal is a minor contributor at most, not
the driver of this cell's effect.

**Plateau check:** not a lookback-neighborhood question (this module's grid is a single
ordinal state, not a swept parameter) — read instead as consistency across the six
states' own `shape_table` point estimates (descriptive, no CI): `c2_drawdown` runs
−0.305% (state 0) → −0.044% (1) → −0.166% (2) → −0.017% (3) → +0.030% (4) → +0.220% (5)
— directionally consistent end to end (state 0 worst, state 5 best) but **not a clean
monotonic staircase through the middle** (state 1 is less negative than state 2). Read
the same way M6.3 read its own U-shape's imperfect middle: the two-extremes spread this
cell actually tests is clean, but "a smooth function of agreement" is not established —
only "the two ends differ."

**What would change the verdict:** the whole-grid FDR pass (pending, not yet re-run —
see `STATUS.md`, out of scope for this module's own fork); a holdout check; a second
universe tier; a concrete trading/risk-management construction (e.g. a position-sizing
or stop-width rule keyed to the state-5/state-0 flag) that would make the
avoided-loss-vs-signed-return caveat moot.

### `ribbon_agreement_extreme_return` — inconclusive, not confirmed

The companion return-outcome cell (same construction, `fwd_ret_21` in place of
`fwd_mdd_21`): **−0.2060%**, CI **[−0.6231%, +0.1835%]** — CI spans zero, not confirmed
(edge 0.6231% would clear the 0.10% floor, so this is a genuine "not detected" read, not
a floor-based kill). `shape_table`'s per-state point estimates are not monotonic either
(+0.294%, +0.189%, −0.122%, −0.011%, −0.075%, −0.012% across states 0–5) — a decline
into a near-zero plateau, not a clean function of agreement. Tier 4, `EXPERIMENTS.csv`
only, no separate entry here (this study's standard Tier-4 convention). Read together
with the drawdown cell above: DESIGN's own stated expectation — "more likely to be
useful in forward drawdown [than] forward return" — held exactly as predicted.

**Correlation matrix (required regardless of outcome, DESIGN's own text — "report the
correlation matrix rather than pretending it's five signals"):** per-date median
Spearman among the five lookbacks' `slope_log_21` values ranges **0.279** (10-day vs.
200-day) to **0.887** (10-day vs. 20-day); `ribbon_agreement_state` itself correlates
0.60–0.76 with each individual lookback. Every pair sits at or below this study's 0.89
non-redundancy bar (M11's precedent) — **the ribbon does not collapse to a single MA's
own slope**; DESIGN's stated collinearity concern is not borne out empirically, though
the two fastest lookbacks (10, 20) come close. Full matrix:
`output/moving_averages/m6_6_ribbon_slope_agreement_correlation_matrix.csv`.
