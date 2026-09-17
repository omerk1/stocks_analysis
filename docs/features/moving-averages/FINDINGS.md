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

**Reproducibility:** computed end-to-end against the real DB (full 408-ticker panel
rebuild) by the coordinating session, via `stats/shape.py` (new: `hit_rate_deltas`,
`distribution_shape`), wired into `modules/stack_minervini.py::_cell_row`. Full numbers
(including `n_wins`/`n_losses`/`mean_win`/`mean_loss`) in `EXPERIMENTS.csv`'s notes
field for both primary cells.
