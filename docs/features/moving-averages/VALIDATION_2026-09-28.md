# Moving-averages study — results and recommendations validation (2026-09-28)

**What this is.** A reproduction and audit of the study's logged Track B results, the
whole-grid FDR pass, the cost arithmetic, the cross-document consistency of the
headline numbers, and the recommendations built on them. It is neither a Track A look
nor a new Track B cell: no new hypothesis is tested, nothing here is added to
`EXPERIMENTS.csv`, `FINDINGS.md` or `EXPLORATION_LOG.md`, and no shared study doc is
edited — every proposed correction is listed in §H for the coordinating session to
apply. Holdout (post-2021-12-31) was never read. Every reproduction uses the cached
panel and each module's *own* code path (`modules/*.py`) with the logged
seed/draws/block-length settings; scratch drivers live outside the repo.

**Sibling reviews running in parallel:** code review (`review/ma-code-review`) and
modeling-phase insights (`review/ma-modeling-insights`). Suspected code defects found
here are flagged for the code-review branch, not fixed.

---

## Executive verdict

1. **The numbers reproduce.** Every headline cell re-run here (M6.3's Tier-2 cell and
   its three robustness companions, M14 pooled + VCP, M6.6, M12, M6.4's three SMA20
   strata, M18's four cells, M1's three lookbacks) matches `EXPERIMENTS.csv` to the
   logged precision — see §C. The pipeline is deterministic and the gates (§A) pass.

2. **The headline (`slope_pctile_21_sma_50`, Tier 2) holds.** It reproduces exactly,
   survives seeds 1–3 with the CI moving by less than a tenth of its width, both tails
   independently reproduce, and it clears cost at 20 bps as well as 10. Its Tier-2
   assignment is consistent with DESIGN §9.2. The one thing to add to its record is
   the size: −0.25 % per 21 days is about −3 %/yr gross, on a universe that is
   survivors-only by construction (§B.4).

3. **The 11-survivor FDR table is overstated in two specific, correctable ways
   (§D).**
   - The three M6.4 survival cells (ranks 1, 3, 5, "the three smallest p-values the
     study has ever produced") are **not p-values in the same sense as the other
     cells**: their `ci_low/ci_high` columns hold the GBM null's simulation envelope,
     not a confidence interval on the estimate, so `p_value_from_ci` divides the
     point estimate by the *null's* spread. That is a different (and much more
     favourable) test statistic. Removing them leaves 5 survivors at q = 0.10 and 3 at
     q = 0.05; the M6.3 headline and its rank are unaffected.
   - `EXPERIMENTS.csv`'s `counted_in_n_tests` flag is stale relative to the pass:
     116 rows with a valid CI carry the flag, against the documented N = 107. The
     survivor set is identical at N = 116, so nothing changes, but the ledger and the
     scoreboard disagree and one of them should be fixed.

4. **M14's VCP cell (rank 6, "largest point estimate in the study") has a look-ahead
   problem in its event definition, not just an unrun robustness check.** The
   `in_pattern_context` flag selects reclaims inside a 21-day window after
   `formation_end` of patterns whose `breakout_bar IS NOT NULL` — but `breakout_bar`
   is resolved by walking *forward* from `formation_end` (`patterns/lifecycle.py`),
   so on the reclaim date the breakout that qualifies the pattern is often still in
   the future. §C.2 quantifies this on the actual events and re-runs the cell with the
   flag restricted to breakouts already observed by the reclaim date. This is the
   single most consequential finding in this audit; the cell should not be described
   as a signal until that number is in its record.

5. **Costs are arithmetically right** for every 21d/63d/126d cell checked (§E); the
   M11 rows are the exception only because the CSV stores their rank-IC, not the
   spread the cost verdict was computed on. At 20 bps round trip, M6.3/SMA50, M12,
   M6.6, M18@126d and M14-VCP still clear; M6.3/SMA200, M13's two cells and M2's
   reversal-controlled reading do not.

6. **Documents are mostly consistent** for the survivor cells (§F). Remaining stale
   text: REPORT §1 still says "on 50 independent tests"; REPORT §5 still says "M15
   remains the only module not yet run"; `docs/backlog.md`'s MA entry describes the
   study as of M1; `EXPERIMENTS.csv` reports the M14 VCP rows' effective N as the whole
   reclaim population (39,452 / 2,656 dates) rather than the 505 events / 131
   bootstrap-contributing dates the text reports.

7. **Of the four modeling-inbox claims (§G.4): one supported, two overstated, one
   partly wrong.** "Extension is the recurring confound" cites M6.2's touch cell,
   which died to the *reversal* control, not extension.

---

## A. Gates

| gate | result | wall time |
|---|---|---|
| `pytest tests/test_moving_averages_*.py -q` | **361 passed**, 0 failed, 34 warnings | 280 s |
| `python -m src.signals.moving_averages.cli validate-synth` | **GATE: PASS** — planted +0.0300 recovered +0.0309; null +0.0009; shifted +0.0151 | 3 s |

What `validate-synth` actually asserts (`synthetic.py`, `gate_verdict`): 300 tickers ×
300 days of iid Gaussian log-returns (σ = 2 %/day), a 5-day SMA above/below flag, and
a **+3 % additive plant** on the 21-day forward return wherever the correctly-lagged
flag is True. Three checks: (i) the C1 delta on the planted panel lands within ±0.5 pp
of +3.0 %; (ii) the C1 delta on the unplanted panel is within ±0.5 pp of zero; (iii)
shifting the flag one extra day drops the recovery below 70 % of the correct one.

Two observations on what this gate does and does not cover:
- The planted effect (+3 %/21d) is **more than ten times larger** than any effect the
  study reports (the Tier-2 cell is −0.25 %/21d). The gate proves the lag and C1
  plumbing are wired correctly; it says nothing about the pipeline's behaviour at the
  effect sizes actually at stake, and it never exercises C2 matching, the block
  bootstrap, `p_value_from_ci`, or BH. A planted effect at 0.3 % with the real
  bootstrap would be the honest version of this gate for the modeling phase.
- The "null reports nothing" check is a point-estimate tolerance (|Δ| < 0.5 pp), not a
  false-positive-rate check. It cannot detect a CI that is too narrow.

Two `FutureWarning`s (pandas downcasting in `synthetic.py:77`) and a
`ConstantInputWarning` in the M6.6 correlation test are cosmetic; flagged for the
code-review branch.

## B. Data invariants (cached panel)

| check | value | logged | verdict |
|---|---|---|---|
| rows | 1,222,605 | 1,222,605 (REPORT §9) | match |
| tickers | 405 | 405 (REPORT §9; older docs say 408) | match; see B.3 |
| min / max date | 2010-01-04 / 2021-12-31 | same | **holdout clean** — the cache itself contains nothing past the boundary |
| one-bar lag | `sma_20` on row *t+1* equals SMA(20) of raw closes through *t* to within 2e-5 (float32) on AAPL/MSFT/JPM/XOM; same-bar difference is O(1) | — | **lag confirmed** |
| `sector` | exactly one value per ticker across all dates; 3 tickers have no sector at all | "current-state-only" | confirmed; the 3 sector-less tickers explain why C2 cells report 402 tickers, not 405 |
| tickers ending before 2021-12-01 | 0 | — | see B.4 |
| tickers starting after 2010-06-01 | 0 | — | see B.4 |
| universe tickers with `tickers.active = 0` | 0 | — | see B.4 |

**B.3 — 405 vs 408.** `cli.py`, DESIGN §12 and PREREGISTRATION.md's M4/M1/M11 entries
say the universe is a "408-ticker set"; every entry from M5 onward and REPORT §9 say
405. The cache today has 405. The three fewer tickers are most likely the same
data-coverage filter applied against a later DB snapshot; the docs never record the
change. Not result-affecting (the M4/M1/M11 numbers were computed on whatever panel
existed then and are not re-run here — M1 *is* re-run in §C.7 on today's 405-ticker
panel and matches), but the reproducibility appendix should say which it is.

**B.4 — Invariant #4 is satisfied vacuously, and that matters more than the docs
say.** The universe is "S&P 500 membership *as of 2021-12-31*, with full bars_1d
coverage 2010-06-01 → 2021-12-01" (`data.py::sp500_full_coverage_tickers`). Every
ticker in the panel is therefore (a) alive on the last day of the window, and (b) in
the index on the last day of the window. Nothing was dropped because nothing delisted
was ever eligible. This is a stronger selection than DESIGN §7.3's "delisted-history
ceiling" framing suggests: it is selection on *end-of-window index membership*, i.e.
the universe itself was chosen with information from the end of the sample. Every
beaten-down-state bucket (full bearish stack, falling-slope tail, low 52-week-range
position, below-MA states) is populated only by names that subsequently made or kept
the S&P 500 by 2021. The study caps M2 and M18 for this reason and promotes M6.3
because its rising tail shows the same effect (a good argument); the cap should also
be stated once, up front, as a property of U1 rather than per cell — and the
point-in-time universe (`db.read_index_membership`, which CLAUDE.md names as the
intended universe source) should be the first thing the modeling phase changes.

## C. Reproductions

Settings: each module's own `prepare()`/test function, `seed=0`, `n_boot=500`,
`ci=0.90`, `block_length=42` (21d cells) / 126 / 252 (M18), exactly as logged. "Δ" is
reproduced minus logged. Effective N = distinct dates (CLAUDE.md invariant #6).

### C.1 M6.3 `slope_pctile_21_sma_50` — the Tier-2 cell (`modules/slope_magnitude.py`)

| cell | logged (EXPERIMENTS.csv) | reproduced | Δ | n_events / n_dates / n_tickers |
|---|---|---|---|---|
| `humped_test_sma50`, C2 (seed 0) | −0.002480 [−0.003540, −0.001528] | −0.002480 [−0.003540, −0.001528] | 0 | 219,700 / **2,747** / 402 (match) |
| same, seed 1 | — | −0.002480 [−0.003523, −0.001490] | CI edges move ≤ 0.00004 | |
| same, seed 2 | — | −0.002480 [−0.003496, −0.001493] | | |
| same, seed 3 | — | −0.002480 [−0.003445, −0.001549] | | |
| + `rev_tercile` (reversal-robustness) | −0.002825 [−0.003886, −0.001754] | −0.002825 [−0.003886, −0.001754] | 0 | 219,700 / 2,747 |
| recent-large-move excluded | −0.002637 [−0.003759, −0.001676] | −0.002637 [−0.003759, −0.001676] | 0 | 214,081 / 2,747 |
| rising-tail-only ({4,5} vs {8,9}) | −0.002544 [−0.004290, −0.000846] | −0.002544 [−0.004290, −0.000846] | 0 | middle 219,700, tail 221,609 / 2,747 |
| falling-tail-only ({4,5} vs {0,1}) | −0.002442 [−0.004127, −0.000959] | −0.002442 [−0.004127, −0.000959] | 0 | middle 219,700, tail 221,604 / 2,747 |
| cost: `is_middle` flips/ticker-yr → hurdle | 7.691 → 0.7691 %/yr | 7.691 → 0.7691 %/yr | 0 | |
| `humped_test_sma20` | −0.001173 [−0.002286, −0.000063] | −0.001173 [−0.002286, −0.000063] | 0 | 219,654 / 2,747 |
| `humped_test_sma200` | −0.001928 [−0.003370, −0.000556] | −0.001928 [−0.003370, −0.000556] | 0 | 219,731 / 2,747 |

**Seed sensitivity** (never varied in the study): across seeds 0–3 the 90 % CI's lower
edge ranges −0.003540 … −0.003445 and its upper edge −0.001549 … −0.001490 — a spread
of about 5 % of the CI width. The Wald p-value implied by the four seeds ranges
3.5e-5 … 5.0e-5; rank 4 of 107 is unaffected. Reporting one seed is fine for this
cell; for cells that clear their BH threshold by 2–8 % (ranks 9–11) it would not be,
and a seed-varied CI should be part of the FDR record.

**Shape (descriptive, per-decile C2, SMA50):** deciles 0 → 9 = +0.265 %, +0.029 %,
−0.034 %, −0.069 %, −0.169 %, −0.136 %, −0.037 %, −0.013 %, −0.021 %, +0.198 %. A
symmetric U with the two *extreme* deciles carrying essentially all of the lift and the
middle two deciles the trough — consistent with the module's read. Deciles 1 and 8 are
already near zero: the "tails" effect is really a decile-0-and-9 effect, which matters
for how the modeling phase encodes it (a top/bottom-decile flag, not a |percentile|
ramp).

### C.2 M14 — pattern-context reclaims (`modules/pattern_context.py`)

Reproduction as logged (`analysis.sqlite` opened read-only; `load_qualifying_patterns`
returns 75,067 pooled / 3,978 VCP qualifying instances — matches the pre-registration):

| cell | logged | reproduced | Δ | effective N |
|---|---|---|---|---|
| pooled, C2 | −0.004045 [−0.007483, −0.000866] | −0.004045 [−0.007483, −0.000866] | 0 | 10,858 in-context events / 2,274 event dates / **1,097 bootstrap-contributing dates** |
| pooled, + `ext_tercile` | −0.001962 [−0.005393, +0.001721] | −0.001962 [−0.005393, +0.001721] | 0 | 981 bootstrap dates |
| pooled, + `rev_tercile` | −0.004412 [−0.007904, −0.001021] | −0.004412 [−0.007904, −0.001021] | 0 | 862 bootstrap dates |
| **VCP, C2** | +0.018298 [+0.010600, +0.027680] | +0.018298 [+0.010600, +0.027680] | 0 | **505 events / 409 dates / 227 tickers; 168 bootstrap dates** (FINDINGS.md says 131 for this reading — 131 is the ext-neutralised reading's count) |
| VCP, + `ext_tercile` | +0.019852 [+0.014334, +0.026072] | +0.019852 [+0.014334, +0.026072] | 0 | 131 bootstrap dates |
| VCP, + `rev_tercile` | InsufficientBlocksError (112 dates) | InsufficientBlocksError (112 dates) | — | |

**Look-ahead audit of the event flag.** `in_pattern_context` is True on every date in
`[formation_end, formation_end + 21 business days]` of a qualifying pattern, and a
pattern qualifies only if `breakout_bar IS NOT NULL` with a breakout-confirmed status.
In `src/signals/patterns/lifecycle.py`, `breakout_bar` is found by walking *forward*
from `formation_end_bar_index + 1`; it is therefore always after `formation_end`, and
the whole post-`formation_end` window is flagged regardless of where inside (or after)
it the breakout lands. Mapping each qualifying pattern's `breakout_bar` (a positional
index into `load_and_validate(as_of=2021-12-31)`'s bars) back to a date — verified by
`close[breakout_bar] == entry_price` on 99.94 % of the 75,067 patterns — gives:

| | pooled | VCP |
|---|---|---|
| breakout date − `formation_end`, median (calendar days) | 12 | 5 |
| 90th percentile | 44 | 21 |
| VCP patterns by status | — | 2,804 `hit_target`, 1,173 `invalidated_failed_breakout`, 1 `active`; all `bullish` |

For the 505 VCP in-context reclaim events specifically:

| subset | n events | mean `fwd_ret_21` | hit rate | breakout timing relative to reclaim |
|---|---|---|---|---|
| breakout already observed on/before the reclaim date | 336 (66.5 %) | **+1.16 %** | **61.3 %** | median 9.5 days before |
| breakout still in the future on the reclaim date | 169 (33.5 %) | **+6.56 %** | **84.0 %** | median 6 days after; 97.6 % within 30 calendar days, i.e. *inside the 21-trading-day label window* |
| out-of-context reclaims (the control population) | 38,947 | — | 61.3 % | — |

The no-look-ahead subset's hit rate (61.3 %) is indistinguishable from the control's
(61.3 %); the lift comes from events whose *label window contains the upward VCP
breakout that qualified the pattern*. The look-ahead share is stable across years
(19–50 % of each year's events), so this is structural, not a boundary artefact.

C2B_PLACEHOLDER

**Reading.** The logged VCP number is reproducible and the module's code did what the
pre-registration said; the *definition* that was pre-registered is not `as_of`-safe. A
breakout-qualified pattern is a label, not a feature, until the breakout bar has
printed. The same flaw is in the pooled cell (20 pattern types, mixed direction),
where it partly cancels because bearish and bullish breakouts pull in opposite
directions. This is a defect in `modules/pattern_context.py::add_pattern_context_flag`
(window anchored at `formation_end`, not at the breakout date) — flagged for the
code-review branch; the fix is to anchor the window at the breakout date and require
`date >= breakout_date` (and, strictly, `date >` the bar on which the status became
knowable). M15's enrichment check consumed the same flag and should be re-run after
the fix. The IDEAS.md rows citing "VCP is the strongest single event in the MA study"
(F8, and the "two independent strong signals" paragraph) should be held until then.

### C.3 M6.6 `ribbon_agreement_extreme_drawdown` (`modules/ribbon_slope_agreement.py`)

| cell | logged | reproduced | Δ | n_events / n_dates |
|---|---|---|---|---|
| drawdown, C2 | +0.006538 [+0.004379, +0.008870] | +0.006538 [+0.004379, +0.008870] | 0 | 406,663 / 2,747 |
| drawdown, + `rev_tercile` | +0.005346 [+0.002397, +0.008361] | +0.005346 [+0.002397, +0.008361] | 0 | 406,663 / 2,747 |
| return, C2 | −0.002060 [−0.006231, +0.001835] | −0.002060 [−0.006231, +0.001835] | 0 | |
| cost | 5.415 flips/ticker-yr → 0.5415 %/yr | 5.415 → 0.5415 %/yr | 0 | |

Exact. Descriptive shape for the drawdown cell (state-5 group): mean 21-day max
drawdown −4.95 %, "hit rate" (mdd ≥ 0) 3.5 %, skew −3.1 — the statistic is a bounded
non-positive quantity, so hit rate and skew are not informative for it; the study
reports them mechanically per invariant #10.

### C.4 M12 `reclaim_durability_dollar_volume_sma50` (`modules/volume_liquidity.py`)

| cell | logged | reproduced | Δ | n_events / n_dates / n_tickers |
|---|---|---|---|---|
| dollar_volume × SMA50, C2 | −0.008696 [−0.013809, −0.004019] | −0.008696 [−0.013809, −0.004019] | 0 | 13,880 / 2,468 / 361; **866 bootstrap-contributing dates** |
| + `rev_tercile` | −0.005736 [−0.011317, −0.000691] | −0.005736 [−0.011317, −0.000691] | 0 | 627 bootstrap dates |
| other 8 primary cells | all CI-span-zero | identical to the ledger, all CI-span-zero | 0 | |

Exact. Worth adding to its record: the effective N behind the CI is 866 dates (dates
on which both dollar-volume terciles have a reclaim inside the same
date×momentum×vol×sector stratum), not the 2,468 in the ledger's `n_dates` column.

### C.5 M6.4 `slope_persistence_vol_tercile_sma20_t{0,1,2}` (`modules/slope_persistence.py`, `stats/survival.py`)

| stratum | logged Δ (emp − null S(21)) | logged envelope | reproduced Δ | reproduced envelope | n_runs / n_tickers / distinct entry dates |
|---|---|---|---|---|---|
| t0 | +0.1061 | [−0.0286, +0.0243] | +0.10609 (0.7736 − 0.6675) | [−0.02864, +0.02432] | 4,869 / 350 / 1,857 |
| t1 | +0.0726 | [−0.0271, +0.0283] | +0.07262 (0.7450 − 0.6724) | [−0.02714, +0.02833] | 5,280 / 401 / 1,924 |
| t2 | +0.0666 | [−0.0277, +0.0288] | +0.06655 (0.7438 − 0.6773) | [−0.02770, +0.02881] | 5,512 / 359 / 2,018 |

Exact (σ = 0.010754 / 0.014395 / 0.020975, μ = 0.000590, as logged). Two diagnostics
the module's own "argue against" section asks for:

- **The module's stated caveat (σ biased low by positive autocorrelation) points the
  wrong way.** Median per-ticker lag-1 autocorrelation of daily log returns in this
  panel is **−0.050** (lag 2: +0.032; lag 5: 0.000), and the median per-ticker
  variance ratio Var(21d)/(21·Var(1d)) is **0.84** (IQR 0.76–0.92). Returns here are
  mildly mean-reverting at short horizons, so a daily-σ-calibrated iid null has, if
  anything, *more* multi-day variance than the data — which would make the null's runs
  shorter and understate, not inflate, the departure. The σ caveat can be retired.
- **The departure is a regime property; the effective N is years, not runs.** Fraction
  of t0 runs lasting more than 21 days, by entry year: 2010 0.82, 2011 0.65, 2012
  0.79, 2013 0.87, 2014 0.79, 2015 0.76, 2016 0.80, 2017 0.83, **2018 0.65**, 2019
  0.83, 2020 0.75, 2021 0.73, against a null of 0.67 (t1/t2 show the same pattern,
  with **2011 0.61/0.62** and **2018 0.57/0.63** *below* the null). The departure is
  present in bull years and absent-to-reversed in the two correction years; 405
  tickers' 20-day slopes turn together, so ~5,000 runs are closer to 12 regime
  observations than to 5,000 draws. That, plus the p-value construction in §D, is why
  these three cells should not anchor the FDR table.

### C.6 M18 `dist_from_52w_low` @126d (`modules/high_low_52w.py`)

| cell | logged | reproduced | Δ | n_events / n_dates |
|---|---|---|---|---|
| `dist_from_52w_low` @126d, C2 spread | +0.025042 [+0.011043, +0.040170] | +0.025042 [+0.011043, +0.040170] | 0 | 1,069,515 / 2,643 |
| same, + `rev_tercile` | +0.026426 [+0.015677, +0.037074] | +0.026426 [+0.015677, +0.037074] | 0 | (blank in ledger) 2,643 |
| `dist_from_52w_low` @63d | +0.009558 [+0.001281, +0.018429] | identical | 0 | 1,095,030 / 2,706 |
| `dist_from_52w_high` @63d / @126d | −0.003791 [−0.015137, +0.007339] / −0.006742 [−0.026319, +0.012077] | identical | 0 | |
| cost @126d | 8.336 → 0.8336 %/yr | 8.336 → 0.8336 %/yr | 0 | |

Exact. (Block length 252 on 2,643 dates ≈ 10.5 blocks — thin for a block bootstrap,
consistent with the wide CI.)

### C.7 M1 `above_sma_{20,50,200}` (`modules/baseline_state.py`) and the `n_events` discrepancy

| cell | logged (2026-09-09) | reproduced (today's 405-ticker panel) | Δ point | n_events logged / reproduced | C2-eligible rows (event + control), reproduced |
|---|---|---|---|---|---|
| `above_sma_20` | −0.002146 [−0.003495, −0.000791] | −0.002154 [−0.003482, −0.000839] | −0.000008 | 751,406 / **420,066** | **744,889** |
| `above_sma_50` | −0.001830 [−0.003406, −0.000306] | −0.001839 [−0.003378, −0.000349] | −0.000009 | 743,745 / **432,955** | **738,018** |
| `above_sma_200` | −0.002149 [−0.004234, +0.000048] | −0.002168 [−0.004271, +0.000026] | −0.000019 | 549,243 / 325,243 | 544,672 |

**Resolved:** the ledger's M1 `n_events` is the size of the C2-eligible row set (event
*and* control rows) — 751,406 / 743,745 / 549,243 on the original 408-ticker panel
correspond to 744,889 / 738,018 / 544,672 on today's 405-ticker panel — not the event
rows `_cell_row` reports today. Point estimates and CIs move in the 4th–5th decimal,
consistent with three tickers leaving the cache between 2026-09-09 and 2026-09-17
(§B.3). Nothing changes for M1's tier; the ledger rows should be relabelled (§H). The
reproduced `below` cells are exact mirrors of `above`, as M1 documented.

## D. Whole-grid FDR pass — audit

**D.1 Recomputation from the ledger.** Taking every `EXPERIMENTS.csv` row with
`counted_in_n_tests == True`, recomputing p-values with
`stats/multiple_testing.py::p_value_from_ci` and running `benjamini_hochberg`:

| | documented (STATUS/REPORT, 2026-09-25) | recomputed from the ledger |
|---|---|---|
| N | 107 | **126 flagged rows; 116 with a valid CI** (10 NaN: M1 run-length summary, M2's 8 ablation coefficients, M6.2's unresolved SMA200 cell) |
| survivors, q = 0.10 | 11 | 11 — identical set, identical order |
| survivors, q = 0.05 | 6 | 6 — identical set |
| rank-1 p | ≈0.000000 (M6.4 t0) | 4.2e-11 |
| every survivor clears its own threshold without the step-up sweep | yes | yes |

The 116-vs-107 gap is exactly the four dedup decisions STATUS.md's table records but
the CSV flag was never updated for: M4 9→5, M11 5→3, §7.5 3→1, M7 5→4. The survivor
set is the same at either N because the rank-11 cell (`above_sma_20`, p = 0.0090)
clears both 11/107 × 0.10 = 0.0103 and 11/116 × 0.10 = 0.0095. So: **the documented
result is reproducible, but the ledger's own flag does not reproduce the documented
N.** One of the two should be made authoritative (§H).

**D.2 Arguing against it.**

*(i) What `p_value_from_ci` can and cannot say.* It backs a standard error out of a
90 % percentile-bootstrap CI (500 draws) under a normal assumption, then reports a
two-sided normal p. Two consequences:
- The smallest *empirically* resolvable two-sided p from 500 draws is 2/500 = 0.004.
  Anything below that is an extrapolation of the normal tail, not an observation. The
  study's top-6 p-values (4e-11 … 4e-4) are all extrapolations. That is acceptable
  for BH ranking *if* the bootstrap distribution is roughly normal, and for the
  return-delta cells it is: the CI asymmetry ((upper half-width − lower
  half-width)/mean half-width) for M6.6, M6.3, M14, M12, M18, M7, M2, M1 is between
  −0.16 and +0.20. Replacing every p below 0.004 with 0.004 does not change the
  survivor set. **For the return-delta cells the approximation is defensible.**
- **For the three M6.4 cells it is not a p-value at all.** Their `EXPERIMENTS.csv` row
  stores `point_estimate = empirical S(21) − null S(21)` and `ci_low/ci_high` = the
  GBM null's 5th/95th-percentile *simulation envelope* re-centred on the null
  (PREREGISTRATION M6.4 result table: "the null's 90 % simulation envelope
  re-centered the same way"). The point estimate (+0.106) lies far *outside* its own
  "CI" ([−0.029, +0.024]); the asymmetry statistic is −8.2, −5.2, −4.7. So
  `p_value_from_ci` computes `point / (null envelope width / 3.29)` — "how many null
  standard deviations away is the empirical curve" — with no sampling uncertainty on
  the empirical estimate at all, and with a null whose paths are cross-sectionally
  independent while the empirical runs are not (405 tickers' 20-day slopes turn
  positive together in every rally). Whether the departure is real is a separate
  question (§C.5 adds a by-year breakdown and the return autocorrelation the
  module's own caveat asks about); what is not defensible is ranking these three
  numbers as the study's three smallest p-values alongside Wald p-values from
  bootstrap CIs.

*(ii) Independence of the 107.* Spot checks:
- M6.4's 12 vol-tercile cells: terciles partition the runs, so the strata are
  disjoint *rows*, but they are not independent *tests* of a hypothesis — all three
  terciles at one lookback sit on the same dates and the same market-wide regimes,
  and the module's own reading is "a plateau at SMA20/SMA50". Counting 12 tests and
  then reading the three SMA20 survivors as one plateau is having it both ways: either
  they are one hypothesis (count 4, one per lookback) or twelve. Counting 4 would
  *raise* the other cells' thresholds slightly, so this cuts against the survivor
  set only at the margin (rank 11 would still clear).
- M3's 16: 10 primary (5 pairs × 2 directions) are genuinely distinct populations; the
  4 quality facets and 2 spread-velocity facets are two-way partitions *of the same
  sma_50/sma_200 golden cell*, so each pair of facets is one degree of freedom, not
  two. 16 is over-counted by about 3; with every M3 cell CI-spanning zero this only
  makes the denominator slightly generous. Harmless to the survivor set.
- The M14 VCP cell is a strict subset of the M14 pooled cell's in-context events and is
  counted as an independent test. Given §C.2 this is moot, but the convention
  ("within-restriction facets count independently") is what let a post-hoc slice
  enter the grid as a fresh test.

*(iii) Are these the same kind of test?* Three families are pooled into one BH:
return deltas (most cells), a *drawdown magnitude* delta (M6.6, M7's |return|), and a
*survival-curve departure from a simulated null* (M6.4). BH does not require the
tests to be of the same kind, only that each p-value be a valid p-value under its
own null. M6.6/M7 pass that bar (bootstrap CI on a real quantity). M6.4 does not (see
(i)). **Verdict: run the pass without M6.4's three cells, or re-derive their p-values
from a bootstrap of the empirical KM estimate against the null. Without them: N = 104,
5 survivors at q = 0.10 (M6.6 drawdown, M6.3/SMA50, M14-VCP, M12, M18@126d), 3 at
q = 0.05 (M6.6, M6.3/SMA50, M14-VCP).** Restricting further to signed-return cells
only (drop the drawdown and |return| outcomes): 2 survivors at both q levels —
M6.3/SMA50 and M14-VCP — and M14-VCP is the cell §C.2 shows to be contaminated.

## E. Cost arithmetic

Recomputed from the raw `EXPERIMENTS.csv` numbers: hurdle = `signals_per_year × 10 bps`
as stored in `cost_hurdle_annual`; annualised point/near-edge = value × 252/h.

| cell | h | hurdle (10 bp) | point ann. | near-edge ann. | near/hurdle | clears @10 bp | clears @20 bp |
|---|---|---|---|---|---|---|---|
| M6.3 `slope_pctile_21_sma_50` (Tier 2) | 21 | 0.769 % | −2.98 % | −1.83 % | 2.4× | yes | **yes** |
| M6.3 `slope_pctile_21_sma_200` | 21 | 0.382 % | −2.31 % | −0.67 % | 1.7× | yes | no |
| M12 `dollar_volume`/SMA50 | 21 | 0.291 % | −10.4 % | −4.82 % | 16.6× | yes | yes |
| M6.6 `ribbon_agreement_extreme_drawdown` | 21 | 0.542 % | +7.85 % | +5.25 % | 9.7× | yes | yes (drawdown, not return) |
| M7 `ribbon_direction_magnitude` | 21 | 0.316 % | −2.97 % | −1.11 % | 3.5× | yes | yes (\|return\|, not return) |
| M14 VCP | 21 | 0.0185 % | +21.96 % | +12.72 % | 688× | yes | yes (see §C.2) |
| M18 `dist_from_52w_low` @126d | 126 | 0.834 % | +5.01 % | +2.21 % | 2.6× | yes | yes |
| M18 `dist_from_52w_low` @63d | 63 | 0.825 % | +3.82 % | +0.51 % | 0.6× | no | no |
| M2 `stack_fully_bearish` (incremental) | 21 | 0.286 % | +12.7 % | +5.03 % | 17.6× | yes | yes |
| M2 `stack_fully_bearish` (reversal-controlled, standalone) | 21 | 0.286 % | +3.83 % | +0.53 % | 1.9× | yes | **no** |
| M6.2 `extension_x_slope`/SMA50 | 21 | 0.806 % | −7.11 % | −2.10 % | 2.6× | yes | yes |
| M13 `context_vix_bottom` | 21 | 0.689 % | −3.82 % | −0.87 % | 1.3× | yes | no |
| M13 `context_breadth_top` | 21 | 0.640 % | −4.66 % | −0.88 % | 1.4× | yes | no |
| M1 `above_sma_20` / `above_sma_50` | 21 | 3.04 % / 1.80 % | −2.58 % / −2.20 % | −0.95 % / −0.37 % | 0.3× / 0.2× | no | no |
| M4 SMA20 facets (3) | 21 | 2.47–2.62 % | −4.5 … −5.6 % | −1.1 … −1.6 % | 0.4–0.7× | no | no |

Every verdict in REPORT §8 is reproduced. Notes:
- **M11 rows cannot be checked from the CSV**: their `point_estimate/ci_*` columns hold
  the rank-IC, while the cost verdict text was computed on the decile spread, which is
  not stored. Recomputing from the stored columns gives the wrong answer (e.g.
  `dist_atr_sma_20_h21` "clears"). The row schema should carry the statistic the
  verdict was evaluated on (§H).
- The ×12 (252/21) linear annualisation assumes the position is re-entered
  continuously with no overlap; the state flips 7.7 times per ticker-year for M6.3,
  so the average holding period (~33 days) is longer than the 21-day label. It is a
  fair order-of-magnitude comparison and is labelled as such everywhere. The
  comparison that would actually settle "tradeable" — a portfolio-level backtest
  with realistic fills — was never in scope, and REPORT §9 says so.
- 10 bps round trip is optimistic-to-fair for S&P 500 names at institutional size and
  optimistic for retail. The 20 bp column is the useful sensitivity: it separates the
  cells whose cost clearance is structural (M6.3/SMA50, M12, M18@126d, M6.6) from
  those that clear on a thin margin (M6.3/SMA200, M13, M2 reversal-controlled).

## F. Document consistency

**F.1 Survivor numbers across documents.** For all 11 FDR survivors and every Tier
2/3 cell, point estimate / CI / n_dates were compared across `EXPERIMENTS.csv`,
`FINDINGS.md`, `STATUS.md` and `REPORT.md`. All agree to stated precision, with these
exceptions:
- `EXPERIMENTS.csv` rows 207–209 (M14 VCP): `n_events = 39,452`, `n_dates = 2,656`,
  `n_tickers = 402` — the *whole reclaim population*, not the 505 / 409 / 227 the
  text reports, and not the 131 bootstrap-contributing dates FINDINGS.md names as the
  real effective N. Read literally, the ledger overstates this cell's effective N by
  20×.
- `EXPERIMENTS.csv` rows 59–60 (M18 reversal-robustness): `n_events/n_dates/n_tickers`
  are blank.
- M1 `above_sma_20`/`above_sma_50` `n_events` (751,406 / 743,745) vs a fresh run — see
  §C.7 for the resolution of the discrepancy M10 flagged.

**F.2 Row counts per module.** `EXPERIMENTS.csv` has 221 rows (215 module rows + 6
FDR summaries), matching REPORT §9. Per-module counts match each module's own STATUS
row except M3 (STATUS: "18 rows"; CSV: 20 — the two extra are the spread-velocity
addendum's horizon companions, correctly flagged `counted_in_n_tests=False`).

**F.3 Two-phase commit (pre-register, then run).** On `main` every module is a single
squash-merged PR, so the ordering is only visible in the PR's own commit list.
Checked via `gh pr view <n> --json commits` for the post-termination modules and the
termination PR:

| PR | module | pre-registration commit precedes result commit? |
|---|---|---|
| #76 | M5, M6.2, FDR pass | yes — "Pre-register M5" 17:02 → run 17:32; "Pre-register M6.2" 17:35 → run 20:38 |
| #79 | M18 | yes (09-20 18:04 → 09-21 06:27) |
| #82 | M6.3 | yes (08:18 → 12:56; reversal addendum 17:08) |
| #90 | M6.6 | yes (14:06 → 14:54) |
| #91 | M12 | yes (12:02 → 15:49) |
| #99 | M6.4 | yes (12:17 → 12:30) |
| #105 | M14 | yes for both the pooled cell (15:55 → 16:20) and the VCP addendum (19:31 → 19:47) |

No exception found in the sample. Two caveats the discipline cannot rule out and the
record should say so: (a) a 13-minute gap (M6.4) is consistent with the analysis
having been run before the pre-registration was *committed*; (b) the VCP addendum was
requested *after* the pooled cell's result was known ("coordinator-requested
follow-up"), which is a post-hoc slice however cleanly it was then pre-registered — its
N_tests contribution should be read in that light.

**F.4 Stale or contradictory statements still present.**
- REPORT.md §1: "landing at one, on 50 independent tests" — N has been 107 since
  2026-09-25.
- REPORT.md §5 opening: "M15 (synthesis) remains the only module not yet run — it was
  hard-blocked on M14 merging" — contradicted by the same file's header and by the M15
  paragraph two screens later.
- `docs/backlog.md`, MA-study bullet: still describes the study as "Phase 0-3 infra +
  M4 + M1 first passes landed" with "Next module: M2…". The study is complete.
- DESIGN §12 / PREREGISTRATION M4–M11 / `cli.py`: "408-ticker set"; REPORT §9 and
  everything after M5: 405 (§B.3).
- STATUS.md M2 row: "PR pending" (merged as #74).
- FINDINGS.md's M6.3 entry still carries "**Not yet run through the whole-grid FDR
  pass** (pending re-entry)" in its Tier paragraph, immediately above the addendum
  that says it survived; cosmetic but confusing.

## G. Recommendations — do they hold?

**G.1 REPORT §6 "what would move any of these forward".** Holdout check, second
universe tier, PIT market-cap control (M12), autocorrelation-aware null (M6.4), more
data. All four are correct as far as they go. Two are missing:
- **A point-in-time universe** (§B.4). This is different from "a second universe
  tier": U1 itself is end-of-sample-selected, so *every* cell here, including the
  Tier-2 one, has a survivorship component whose sign is known (it flatters
  beaten-down states). The rising-tail decomposition protects M6.3 specifically;
  nothing protects M2, M18@126d, M12 (low dollar volume ≈ small/beaten-down) or the
  falling half of anything.
- **A proper p-value for M6.4 and a decision on whether survival departures belong
  in the same BH as return deltas** (§D). Until then the "three smallest p-values in
  the study" sentence should not be repeated.

**G.2 REPORT §9 "what this study did not build".** Accurate (U2/U3, holdout, DSR,
SPA, decile-level momentum match for M18). Add: an `as_of`-safe pattern-context flag
(§C.2) and a bootstrap that archives per-cell draws (so p-values need not be backed
out of CIs).

**G.3 Tier assignments of the 11 survivors.**
- M6.3/SMA50 → Tier 2: **justified** under DESIGN §9.2 (C2 ✓, FDR ✓ at both q, cost ✓
  incl. 20 bp, reversal ✓, large-move ✓, both tails ✓; holdout/U2 are missing infra).
  The only honest addition is the U1 survivorship note.
- M14 VCP → Tier 3 "not promoted, reversal check unrun": **understated** — the cell's
  event definition uses future information (§C.2). It should not carry a Tier-3
  "real effect" label until re-run on an `as_of`-safe flag; on this audit's
  no-look-ahead re-run it is [see §C.2 for the number].
- M6.4 SMA20 t0/t1/t2 → Tier 3 "GBM null may be miscalibrated": **the stated caveat
  is the wrong one**. The bigger issues are the p-value construction (§D) and
  cross-sectional dependence of runs; the σ-autocorrelation concern the module names
  is real but second-order (§C.5 reports the panel's median lag-1 autocorrelation and
  21d/1d variance ratio).
- M12, M18@126d → Tier 3 with named open confounds (size; survivorship-by-analogy):
  **consistent** with each other and with M6.3's treatment (M6.3 was promoted only
  after a *direct* test). Both also need the §B.4 universe note.
- M6.6, M7 → Tier 3 capped by the magnitude/drawdown "actionability gap":
  **consistent**; but note that M6.6's drawdown cell has *the* cleanest bootstrap
  p-value in the study once M6.4 is set aside, and "avoided-loss" is exactly what a
  barrier/path model consumes — the cap is about the study's own return-claim
  framing, not about the evidence.
- M2, M1 → Tier 3, cost/survivorship: consistent.

**G.4 The modeling-inbox paragraph (IDEAS.md, "What the finished MA study tells the
model").**

| claim | verdict | why |
|---|---|---|
| "The MA family is close to one signal (M16: all 23 rules one cluster at cosine ≥ 0.80)" | **overstated** | Kernel-weight cosine similarity is not signal redundancy. The study's own empirical correlations say otherwise: `slope_log_21` across lookbacks 0.28–0.89 (M6.6), 0.35–0.88 (M6.1); `dist_z` vs `dist_pct` 0.69 at SMA200 (M4/Track A); at cosine ≥ 0.95 M16 itself finds 10 clusters. "A few representatives per effective-lookback cluster" is the right practical conclusion, but for the reason M16 gives at 0.95, not 0.80. |
| "Two independent strong signals: extreme-slope percentile (M6.3, Tier 2) and the VCP reclaim (M14, Tier 3)" | **overstated / partly unsupported** | M6.3 is real but *small*: −0.25 %/21d, about −3 %/yr gross before any portfolio construction. M14-VCP is contaminated by look-ahead in its event definition (§C.2); until re-run on an as_of-safe flag it is not evidence of anything. "Independent" (M15's enrichment check) is supported. |
| "Extension is the recurring confound; several cells (pooled patterns, M6.2 touch) died once `dist_pct_sma_50` was controlled for" | **partly wrong** | M14 pooled: yes (extension-neutralised). M6.2 `touch_x_slope`: died to the *reversal* control (`rev_tercile`), not extension; extension was never added to its match set. The recurring confounds in this study are short-term reversal (M6.2 touch, M6.3/SMA200, M12/SMA20) and momentum/vol/sector matching in general (the C1→C2 shrinkage). Extension appears once. |
| "Fatter downside tails on the best event (VCP) are the reason the barrier/path target beats a mean-return target" | **supported in principle, wrong exhibit** | The principle (a mean can hide an asymmetric stop-out rate; CLAUDE.md invariant #10 exists for exactly this) is right and M2's `stack_fully_bullish` shape addendum is a clean, uncontaminated exhibit (+1.2 pp hit rate, −0.35 skew, flat mean). The VCP skew (−0.77) is a descriptive statistic on a cell whose events are selected with future information. |

**G.5 Recommendations the evidence supports that the docs omit.**
1. Restate every survivor's effect in the unit the modeling phase will use: M6.3 is
   ~−0.25 %/21d ≈ 0.02 σ of a typical 21-day stock return; with ~7.7 entries per
   ticker-year, a long/short decile portfolio's gross would be low-single-digit
   percent per year before shrinkage. It is a feature, not a strategy — the docs say
   this, IDEAS.md's "strong" does not.
2. Re-run the whole-grid pass with M6.4 removed (or fixed) and publish that as the
   headline table; keep the current one as superseded per the study's own
   no-silent-edits rule.
3. Fix the M14 event flag before anything downstream (M15's enrichment check, the
   modeling inbox's F8 row) reuses it: qualify a pattern by its *breakout date*, not
   its `formation_end`, and only for reclaims on or after that date.
4. Switch the universe to point-in-time membership before the modeling phase's
   baselines are set; otherwise every bearish/beaten-down feature the model learns
   inherits U1's selection.
5. Extend `validate-synth` to plant an effect at the study's actual effect scale
   (~0.3 %) through C2 + block bootstrap + `p_value_from_ci`, so the gate covers the
   inference path, not just the lag.
6. Make `EXPERIMENTS.csv`'s `counted_in_n_tests` reflect the pass's actual grid, and
   store the statistic the cost/FDR verdict used (M11).

## H. Proposed corrections to shared docs (for the coordinator; not applied here)

Per the study's own no-silent-edits rule, each of these is a dated addendum or a
labelled correction, not a rewrite of frozen text.

| # | file | current text (exact) | proposed |
|---|---|---|---|
| 1 | `EXPERIMENTS.csv`, rows `pattern_context_reclaim_sma50_vcp_only`, `..._vcp_only_extension_neutralized`, `..._vcp_only_reversal_robustness` | `n_events=39452, n_dates=2656, n_tickers=402` | `n_events=505, n_dates=409, n_tickers=227`, and in `notes`: "bootstrap-contributing dates: 168 (default C2), 131 (ext-neutralised); event flag anchored at formation_end, not breakout date — 169 of 505 events precede the qualifying breakout (VALIDATION_2026-09-28 §C.2); not as_of-safe as logged". |
| 2 | `EXPERIMENTS.csv`, same VCP primary row | `tier=3`, `outcome=confirmed_opposite_sign_from_pooled_survives_extension` | Do not edit the frozen row; append a new dated row `pattern_context_reclaim_sma50_vcp_only_as_of_safe` once the flag is fixed and re-run, with the no-look-ahead number (§C.2). Until then, `STATUS.md`/`REPORT.md`/`FINDINGS.md` should carry a dated addendum stating the cell is under an open look-ahead finding and is not to be cited. |
| 3 | `EXPERIMENTS.csv`, `counted_in_n_tests` on: `dist_atr_sma_20_h21`, `dist_z_sma_20_h21`, `dist_atr_sma_50_h21`, `dist_atr_sma_200_h21` (M4); M11 `dist_pct_sma_20_h21`, `dist_pct_sma_50_h21`; `placebo_sma200_h21`, `placebo_sma50_h21`; M7 `ribbon_vol_expansion_c2_no_vol_match` | `True` | `False`, with `notes` += "excluded from the whole-grid pass by STATUS.md's dedup table (2026-09-17/23), flag corrected 2026-09-29" — so the ledger's flag reproduces N = 107. (Alternatively keep the flag and add a `fdr_grid_member` column; either way one source must reproduce the documented N.) |
| 4 | `EXPERIMENTS.csv`, M1 rows `above_sma_20/50/200` | `n_events=751406 / 743745 / 549243` | Leave values; `notes` += "n_events here is the C2-eligible row set (event + control) on the 408-ticker panel; event rows on today's 405-ticker panel are 420,066 / 432,955 / 325,243 (VALIDATION_2026-09-28 §C.7)". |
| 5 | `EXPERIMENTS.csv`, M18 rows `dist_from_52w_low_h63/h126_reversal_robustness` | `n_events`, `n_dates`, `n_tickers` blank | `1095030 / 2706 / 405` and `1069515 / 2643 / 405` (same population as the primary rows). |
| 6 | `EXPERIMENTS.csv`, M6.4 rows (12 primary + 12 companion) | `ci_low`/`ci_high` hold the null envelope | Add to `notes`: "ci_low/ci_high are the GBM null's 5th/95th simulation envelope re-centred on the null, NOT a CI on the estimate; `p_value_from_ci` is not valid on these rows (VALIDATION_2026-09-28 §D.2)". Set `counted_in_n_tests=False` pending a bootstrap-based p-value, or keep and mark the FDR table accordingly. |
| 7 | `EXPERIMENTS.csv`, M11 rows | `point_estimate/ci_*` = rank-IC; `cost_verdict` computed on the unstored spread | Add the spread point/CI to `notes` (they exist in PREREGISTRATION.md's M11 addendum) so the cost verdict is checkable from the row. |
| 8 | `STATUS.md`, "Whole-grid FDR pass" section, verdict paragraph | "at q = 0.10, 11 of 107 deduplicated tests survive … at q = 0.05, 6 of 107 survive" | Append a dated (2026-09-29) addendum: "Audit (VALIDATION_2026-09-28 §D): reproduces exactly from the ledger. Caveat: the three M6.4 rows' p-values are computed from the null envelope, not a CI on the estimate, and are not comparable to the other 104; without them, 5 survive at q = 0.10 (M6.6 drawdown, M6.3/SMA50, M14-VCP, M12, M18@126d) and 3 at q = 0.05 (M6.6, M6.3/SMA50, M14-VCP), and M14-VCP is under an open look-ahead finding (§C.2). The Tier-2 result is unaffected." |
| 9 | `STATUS.md`, M14 row and M15 row | "**opposite-signed, extension-robust** … Tier 3" / "additive, not redundant" | Append to each: "2026-09-29 audit: the `in_pattern_context` flag is anchored at `formation_end` and includes windows whose qualifying breakout has not yet occurred on the reclaim date; 169/505 VCP events are of this kind and carry the whole effect (VALIDATION_2026-09-28 §C.2). Cell and M15's enrichment check to be re-run on an as_of-safe flag." |
| 10 | `STATUS.md`, M6.4 row, "Argued against directly" clause | "the GBM null's own `sigma` is computed from the same potentially-autocorrelated series … could bias the null's noise level low" | Append: "2026-09-29 audit: median lag-1 autocorrelation is −0.05 and the 21d/1d variance ratio is 0.84, so this bias runs the other way; the live caveats are the p-value construction and cross-sectional/regime dependence (departure absent or reversed in 2011 and 2018) — VALIDATION_2026-09-28 §C.5/§D." |
| 11 | `STATUS.md`, M2 row | "PR pending" | "PR #74, merged 2026-09-16". |
| 12 | `REPORT.md` §1 | "landing at one, on 50 independent tests, is close to that band's floor" | "landing at one, on 107 deduplicated tests (§4), is …" |
| 13 | `REPORT.md` §5, opening paragraph | "M15 (synthesis) remains the only module not yet run — it was hard-blocked on M14 merging, and now also has a real second Tier-2-adjacent candidate …" | Delete the sentence (the header and the M15 paragraph below already state M15 ran), or replace with "M15 (synthesis) ran 2026-09-25 — see below." |
| 14 | `REPORT.md` §1/§4/§6, every instance of "the three smallest p-values this study has ever produced" (M6.4) | as quoted | Append "(see the 2026-09-29 audit note in `STATUS.md`: these are envelope-based, not CI-based, p-values and are not comparable to the rest of the grid)". |
| 15 | `REPORT.md` §2 "Universe and window (U1)" | "405 S&P 500 constituents with full coverage … (S&P 500 membership as of the 2021-12-31 holdout boundary …)" | Append: "Because membership is taken as of the *end* of the window and full coverage is required, U1 contains no ticker that delisted or left the index during 2010–2021 — invariant #4 holds vacuously, and every below-MA / falling-slope / near-52-week-low bucket is populated only by names that were still S&P 500 members at 2021-12-31. This is a universe-level survivorship selection, not only the per-cell §7.3 cap." |
| 16 | `REPORT.md` §9 | "405 tickers" vs `cli.py` / DESIGN §12 / PREREGISTRATION M4–M11 "408-ticker set" | Add one line: "The panel was 408 tickers when M4/M1/M11 ran (2026-09-08/10) and 405 from the 2026-09-17 rebuild onward; M1 reproduces on the 405-ticker panel to the 4th decimal (VALIDATION_2026-09-28 §C.7)." |
| 17 | `FINDINGS.md`, M6.3 SMA50 entry, "Tier" paragraph | "**Not yet run through the whole-grid FDR pass** (pending re-entry — see `PREREGISTRATION.md`)." | Append "(superseded by the 2026-09-23 addendum below)". |
| 18 | `FINDINGS.md`, M14 VCP entry, "Effective N (bootstrap-contributing …)" | "the default-C2 bootstrap's own stratum construction finds both group values present on 131 distinct dates" | "… 168 distinct dates (default C2); 131 (extension-neutralised)". Plus the look-ahead addendum from row 9. |
| 19 | `docs/backlog.md`, MA-study bullet | "Phase 0-3 infra + M4 + M1 first passes landed … **Next module**: …" | Replace with a two-line pointer: "Study complete 2026-09-25 (M1–M18, whole-grid FDR N=107, one Tier-2 result); scoreboard in `docs/features/moving-averages/STATUS.md`. Open items from the 2026-09-29 validation: as_of-safe pattern flag (M14/M15), M6.4 p-values, `counted_in_n_tests` flag, PIT universe for the modeling phase." |
| 20 | `docs/modeling/IDEAS.md` (untracked, user's file — not touched; noted for the owner) | "Two independent strong signals … VCP reclaim (M14, Tier 3)"; "Extension is the recurring confound … (pooled patterns, M6.2 touch)" | See §G.4: drop "strong"; hold the VCP row until the flag is fixed; M6.2 touch died to reversal, not extension. |
