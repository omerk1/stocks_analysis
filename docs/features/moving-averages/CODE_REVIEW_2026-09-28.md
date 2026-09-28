# Moving-averages study — code review (2026-09-28)

Scope: every file under `src/signals/moving_averages/` (features, labels, stats,
modules, cli, data, synthetic, the top-level run/scan scripts) and every
`tests/test_moving_averages_*.py`, read in full. Study docs (`STATUS.md`,
`REPORT.md`, `EXPERIMENTS.csv`, `FINDINGS.md`, `PREREGISTRATION.md`, `DESIGN.md`)
were read for context only and are **not** edited by this review; where a code
defect touches an already-logged number, the affected `cell_id`s are named so the
re-run can be scheduled separately.

## Summary

| | |
|---|---|
| Baseline | `pytest tests/test_moving_averages_*.py`: **361 passed**, 34 warnings, 284 s. `validate-synth`: GATE PASS (planted +0.0309 vs +0.0300, null +0.0009, shifted +0.0151). |
| After fixes | **367 passed** (6 new regression tests), 155 s. `validate-synth`: GATE PASS, identical numbers. |
| Findings | 3 Critical, 5 Major, 12 Minor, 3 Nit. 5 fixed in this branch (each with a regression test); the rest are documented with a concrete next step. |
| Logged results touched by a fixed defect | M6.4's 24 `slope_persistence_*` rows (12 counted in `N_tests`), M17's histogram-divergence cell. Both need a re-run before the FDR pass is re-consolidated. |
| Logged results touched by an unfixed defect | M14's `pattern_context_reclaim_sma50` and `pattern_context_reclaim_sma50_vcp_only` (look-ahead in the flag definition — needs a pre-registration addendum, not just a code patch). |

The stats core (`stats/controls.py`, the block-bootstrap machinery in
`stats/inference.py`, `stats/costs.py`, `benjamini_hochberg`, `white_reality_check`)
and the central lag in `features/panel.py::apply_lag` are correct as written: dates
are resampled in contiguous circular blocks, strata are weighted as documented, the
event group is excluded from its own control, terciles/deciles are per-date
cross-sectional, the lag is applied once per ticker and never bleeds across ticker
boundaries, and every label looks forward from the row's own close. The defects
below are at the module boundary (a null built differently from its empirical
counterpart, a flag computed on the wrong bar, a flag defined with information from
after the event) and in the universe construction.

---

## Critical

### C1 — M6.4's GBM null pools rising and falling runs; the empirical grid is rising-only. **Fixed.**

`src/signals/moving_averages/stats/survival.py:96-120` (`_slope_sign_runs_single_path`)
and `modules/slope_persistence.py:189-192` (`stratum_result`).

`stratum_result` filters the real-data run table to `direction == True` (rising runs,
per PREREGISTRATION.md's M6.4 entry: "positive (rising) runs only"), then calls
`gbm_null_survival`, which collected **every** run on every simulated path regardless
of sign. The null is simulated with `mu` = the panel's pooled daily log-return mean
(measured directly from the cached panel: **+0.00059/day**), so under the null itself
rising runs are systematically longer than falling ones and the pooled curve sits
between them. A rising-only empirical curve was therefore being compared against a
null whose centre is too low by construction.

Quantified with the module's own simulator (2,000 paths × 1,500 days, `mu=0.00059`,
sigma at roughly each vol-tercile's median entry `realized_vol_63`), survival at 21
days:

| lookback | sigma | pooled null | rising-only null | gap | pooled envelope ±half-width | logged empirical − pooled null (`EXPERIMENTS.csv`) |
|---|---|---|---|---|---|---|
| SMA20 | 0.010 | 0.666 | 0.756 | **+0.090** | 0.027 | t0: +0.106 |
| SMA20 | 0.0146 | 0.668 | 0.729 | **+0.061** | 0.025 | t1: +0.073 |
| SMA20 | 0.021 | 0.671 | 0.715 | **+0.044** | 0.026 | t2: +0.067 |
| SMA50 | 0.010 | 0.802 | 0.864 | **+0.062** | 0.035 | t0: +0.051 |
| SMA50 | 0.0146 | 0.802 | 0.843 | **+0.041** | 0.036 | t1: +0.044 |
| SMA50 | 0.021 | 0.806 | 0.833 | **+0.027** | 0.042 | t2: +0.049 |

The drift asymmetry alone is larger than the pooled envelope's half-width at every
SMA20/SMA50 stratum and accounts for most (SMA20) or all (SMA50 t0/t1) of the logged
"departure toward more persistence". A pure random walk, sampled rising-only and
compared against the pooled null, would have been reported as departing from the
null in exactly the direction M6.4 reports.

Failure scenario: any positive-drift series → "empirical persistence exceeds the
null" regardless of whether returns are autocorrelated.

Affects: `slope_persistence_vol_tercile_sma{20,50,150,200}_t{0,1,2}` (12 counted
cells, FDR ranks 1/3/5 at N=107 for the three SMA20 cells) and the 12
`slope_persistence_er_tercile_*` companions. `FINDINGS.md`'s two M6.4 entries and the
"clean plateau" reading in `STATUS.md`/`REPORT.md` rest on these numbers.

Fix in this branch: `gbm_null_survival(..., direction=)` keeps only runs of the
requested sign (`None` reproduces the old pooled behaviour); `stratum_result` passes
its own `direction` through and reports `null_direction`. Regression tests:
`test_slope_sign_runs_single_path_direction_filter_keeps_only_that_sign`,
`test_gbm_null_survival_rising_and_falling_runs_differ_under_positive_drift`
(asserts the rising-vs-pooled gap exceeds the envelope half-width at the study's
drift), `test_stratum_result_requests_a_direction_matched_null`. **The module must
be re-run** and the 24 rows, the FDR pass, and the M6.4 narrative updated; that is
out of this review's lane.

### C2 — M14's "in pattern context" flag is defined with information from after the event. **Not fixed** (needs a pre-registration addendum and a breakout *date*).

`src/signals/moving_averages/modules/pattern_context.py:55-113`
(`load_qualifying_patterns`, `add_pattern_context_flag`).

The flag is True on every trading day in `[formation_end, formation_end + 21 BDays]`
for a pattern with `status IN (confirmed, active, hit_target,
invalidated_failed_breakout)`, `breakout_bar IS NOT NULL`, `confidence >= 0.7`.
Checked against `src/signals/patterns/lifecycle.py` and the real
`data/derived/analysis.sqlite`:

- Every qualifying status is assigned **after** a breakout has occurred (75,067
  qualifying rows: `hit_target` 37,611, `invalidated_failed_breakout` 36,913, `active`
  543). Patterns that never broke out (`pending`, `invalidated`, `expired`) are
  excluded. The breakout is searched for **forward from `formation_end`**
  (`lifecycle.py::apply_lifecycle`), so on a day *d* in the flag window the
  breakout may not have happened yet — the flag encodes "this pattern will break
  out", which is not knowable at *d*.
- `breakout_bar` is a positional index into the scanner's own bar array
  (`patterns/plotting.py:86`), not a date; the table cannot tell which flagged days
  precede the breakout. `confidence` is the score as of the scan (`models.py:100-103`:
  "not a historical record of what confidence was on some earlier run").
- The holdout bound (`as_of=2021-12-31`, `formation_end <= as_of`) is correctly
  applied and is a separate question: it keeps the study out of 2022+, it does not
  make the flag point-in-time within 2010–2021.

Failure scenario: an `above_sma_50` reclaim on day *d* inside a bullish pattern's
window is labelled in-context only if the pattern later breaks out. For a bullish
pattern a breakout and a reclaim are positively related events, so the in-context
group is enriched for names that are about to break out — a positive forward return
by construction. This is the sign M14's VCP cell reports.

Affects: `pattern_context_reclaim_sma50` (pooled, Tier 4) and
`pattern_context_reclaim_sma50_vcp_only` (FDR rank 6 at N=107, the only other cell
besides M6.3 to clear q=0.05, "largest point estimate in the study"). M15's overlap
check reuses the same population.

Recommended fix (coordinator's call — it changes the pre-registered definition):
(a) recover the breakout *date* by re-running `patterns.scanner.detect(as_of=...)`
per ticker with the same `load_and_validate` bar array and mapping `breakout_bar`
through `bars.index`, or persist it in `pattern_matches`; (b) start the flag window
at the breakout date, not `formation_end`; (c) drop `hit_target`/
`invalidated_failed_breakout` from the status filter (both are post-breakout
outcomes) or, equivalently, require only "a breakout bar exists and is ≤ *d*".
Log as a dated addendum to M14, re-run, re-consolidate FDR.

### C3 — The universe is survivorship-selected twice over, and the DB cannot support CLAUDE.md invariant #4. **Not fixed** (design-level).

`src/signals/moving_averages/data.py:61-92` (`sp500_full_coverage_tickers`),
`cli.py:53-59`.

The universe is "S&P 500 member **as of 2021-12-31**" (`im.start_date <= as_of AND
(end_date IS NULL OR end_date >= as_of)`) **and** "has bars from 2010-06-01 to
2021-12-01". Measured against the real DB:

| | count |
|---|---|
| S&P 500 members as of 2021-12-31 | 505 |
| Distinct tickers that were members at any point 2010–2021 | 759 |
| Of those, `tickers.active = 0` (delisted) | 179 |
| Delisted tickers with **any** `bars_1d` row dated 2010–2021 | **0** |
| Delisted tickers with bars, by year (`delisted_coverage_by_year`) | 2024: 1,097 · 2025: 981 · 2026: 418 · nothing earlier |

So every name in the panel is known to have survived to, and be large enough to be in
the index at, the end of the development window. This is not the ordinary
"delisting returns are missing" survivorship (§7.3); it is a look-ahead selection on
the outcome. It biases every weak-state bucket upward — precisely the direction of
`stack_fully_bearish` (M2, +), `dist_from_52w_low` (M18, +), the falling tail of
`slope_pctile_21_sma_50` (M6.3), bottom-dollar-volume reclaims (M12, +) and VCP
reclaims (M14, +). `REPORT.md` §2 states the construction accurately but the
downstream reading treats it as a Tier cap, not as a directional bias.

`tests/test_moving_averages_hygiene.py::test_smoke_delisted_tickers_have_price_history`
asserts only that *some* delisted ticker has *some* bar in *any* year; it passes on
the 2024–2026 rows and is silent about the window the study actually uses. A
window-scoped assertion would fail today — which is the honest state
(`docs/limitations.md` already records that delisted price history is not
reachable on the current data plan). Tightening the test is a one-line change but
turns the suite red, so it is left to the coordinator.

`db.read_index_membership` (point-in-time membership) exists and is unused here; a
PIT universe would still lack delisted bars but would at least remove the
end-of-window membership condition.

---

## Major

### M1 — M17 `is_new_high` was computed on the row's own close and never lagged. **Fixed.**

`src/signals/moving_averages/modules/nonlinearity_probe.py:109-111` (before the fix).

`is_new_high = close >= rolling_max(close, 21)` used the same bar's close and was
paired with `fwd_ret_21` starting at that close — a same-bar execution, the exact
thing CLAUDE.md invariant #2 forbids and the only feature in the study that bypassed
`apply_lag`. It also read the rolling warmup as `False` (invariant #9). `divergence`
was built from this unlagged flag mixed with the lagged `macd_histogram`.

Fix: `is_new_high_raw` is built NA-preserving and passed through the same `apply_lag`
call as the oscillators; `_divergence_for_ticker` and `histogram_divergence_delta`
use `.fillna(False)` for their population restriction. Regression test:
`test_is_new_high_is_lagged_one_bar_and_na_during_warmup`. Affects M17's
histogram-divergence event cell (Tier 4, CI spanned zero; re-run to confirm the
outcome is unchanged). The incremental-IC cells (MACD/RSI/stochastics) do not use
this flag and are unaffected.

### M2 — M6.4's p-values in the whole-grid FDR pass are not the same quantity as every other cell's. **Not fixed** (lives in the consolidation, not in code).

`EXPERIMENTS.csv` rows 181–204 store `ci_low/ci_high` as the null's re-centred
**simulation envelope** (5th/95th percentile across 100 groups of 20 paths) and
`point_estimate` as empirical − null. `p_value_from_ci` then reads that envelope as
if it were a 90% CI of the empirical estimate. It is neither: it is the null's own
sampling spread at n≈1,000 runs per group, it ignores the empirical curve's own
sampling error (n_runs 839–6,451), and — with C1 — its centre is wrong. The ranks
1/3/5 at N=107 (p≈0.000000 / 0.000016 / 0.000105) are not comparable with the
bootstrap-derived p-values of the other 95 cells. After the C1 re-run, these cells
need a p-value construction of their own (e.g. a bootstrap of the empirical KM over
tickers or date blocks, differenced against the direction-matched null) before they
go back into BH.

### M3 — `p_value_from_ci` extrapolates far below what 500 bootstrap draws can resolve. **Not fixed** (design; would need archived draws).

`src/signals/moving_averages/stats/multiple_testing.py:34-58`.

A Wald p-value from a 90% percentile CI is a labelled approximation (the docstring
says so), but with `n_boot=500` the empirical two-sided resolution is ~0.004, and
the ranked table reports 0.000002, 0.00005, 0.000105. The *membership* of the
q=0.10 survivor set is fairly robust to this (survivors 7–11 sit at p≈0.003–0.009,
inside the resolvable range), but the ordering of ranks 1–6 and the "clears q=0.05"
statements are below resolution. Archiving each cell's raw draws (a `draws` key on
the bootstrap result dicts) would let the FDR pass use empirical p-values; a
percentile-CI-to-normal conversion also assumes a symmetric bootstrap distribution,
which the skewed cells (`FINDINGS.md`'s shape fields) do not satisfy.

### M4 — `block_bootstrap_spread` counted rows with an undefined decile as controls. **Fixed.**

`src/signals/moving_averages/stats/inference.py:164-165` (before the fix) and the
same construction in `block_bootstrap_spread_diff`.

`panel[decile_col] == decile_low` is `False` on NaN, so a row whose decile could not
be assigned (feature NaN, or a thin date where `qcut(duplicates="drop")` returned
fewer buckets) entered the "not decile k" control leg. Every current caller
(`distance_from_ma`, `cross_sectional`, `high_low_52w`, `placebo_levels`,
`ribbon_compression`) drops NaN deciles before calling, so **no logged result is
affected**; the function was unsafe on its own. Fix: `dropna(subset=[decile_col])`
inside both functions. Regression test:
`test_block_bootstrap_spread_ignores_rows_with_an_undefined_decile`.

### M5 — The "decile spread" statistic is (top − rest) − (bottom − rest), not top − bottom. **Not fixed** (definition; consistent across cells).

`src/signals/moving_averages/stats/inference.py::block_bootstrap_spread`.

Each leg is a C2 delta of one decile against *all other rows in the stratum*,
including the opposite decile. With ten equal deciles that is algebraically
`(10/9) × (top − bottom)`: every spread in M4, M11, M18, M7 and §7.5 is ~11% larger
than the literal long-short spread the docs describe and annualise for the cost
hurdle. Signs and CI-excludes-zero verdicts are unaffected; cost margins are
slightly optimistic, which matters only where the near edge is close to the hurdle
(`dist_from_52w_low_h63`, M11's 21d cell). Worth one line in DESIGN §6.1 or a
`spread_kind` parameter, not a silent change to logged numbers.

---

## Minor

- **m1 — `stats/shape.py::hit_rate_deltas` read a NaN return as a miss.** `(value > 0)`
  is `False` on NaN (invariant #9). Every caller passes a frame already restricted
  on `value_col`, so no logged shape field is affected. **Fixed** with
  `.where(value.notna())`; test
  `test_hit_rate_deltas_treats_a_nan_return_as_undefined_not_a_miss`.
- **m2 — M6.4's envelope width is not matched to the empirical sample size.** Groups
  of 20 paths × 1,500 days give ~1,000 runs per replicate; empirical strata range
  839–6,451 runs. The "departs" rule compares a point to a band whose width has
  nothing to do with the point's own uncertainty. Folded into M2's recommendation.
- **m3 — `features/kernels.py::kama` uses `er.fillna(0.0)`** (invariant #9). Unreachable
  in practice (the recursion starts at `er_period`, after ER is defined) but the
  shared `regime.efficiency_ratio` already does this correctly; `kama` should import
  it (the M9/M6.4 reconciliation note in `regime.py` says as much).
- **m4 — Duplicated helpers.** `per_date_median_corr` exists in `feature_sweep.py`
  (with the `MIN_TICKERS` guard) and again in `high_low_52w_run.py` (without it);
  VWMA is implemented twice (`kernels.py`, `liquidity.py`); six near-identical
  `_cell`/`_cell_row`/`_delta_cell` functions (baseline_state, context_conditioning,
  slope_conditioner, volume_liquidity, crossover_state, timeframe_sampling) differ
  only in labels. Not refactored here (no behaviour difference found), but the next
  module should reuse one.
- **m5 — `kernel_space_scan.py` runs at import time** (no `main()` guard, writes to
  `output/` on import). The other top-level scripts have guards. All six top-level
  scripts (`feature_sweep`, `distance_slope_surface`, `high_low_52w_run`,
  `high_low_52w_gate_check`, `ribbon_slope_agreement_run`, `kernel_space_scan`) sit
  at the package root rather than under a `scripts/` or `track_a/` dir the layout
  section of CLAUDE.md implies.
- **m6 — `modules/slope_magnitude.py::prepare`**: `_recent_large_move_raw` reads the
  first row's NaN daily return as `False` before lagging (invariant #9). One row per
  ticker, 40+ days before the slope warmup ends — no effect.
- **m7 — `stats/controls.py::cross_sectional_bucket`** with `duplicates="drop"` can
  return fewer than `n_buckets` labels on a thin or tied date without signalling it;
  "decile 9" then does not exist on that date and the top decile is silently label 8.
  Verified: all-NaN dates return NaN (fine), a constant date returns NaN, a 4-row
  date with a tie returns 2 buckets. Not reachable on this 405-name panel; would be
  on a broader universe with many NaN features.
- **m8 — `sp500_full_coverage_tickers`** hardcodes `source = 'yfinance'` and requires
  `MIN(timestamp) <= coverage_start` — a ticker whose history starts one day after
  2010-06-01 is dropped without a message. Fine for reproducibility, brittle for a
  U2/U3 universe.
- **m9 — `features/state.py::state_run_id`** uses `changed.loc[valid.idxmax()]`, which
  needs a unique index; every caller `reset_index`es first, but the function does
  not check.
- **m10 — `features/panel.py::build_panel`** merges `ticker_sector` with `how="left"`
  and no duplicate guard; the table has no duplicates today (checked), but a second
  source row per ticker would fan out the whole panel silently.
- **m11 — `modules/timeframe_sampling.py`** decomposition gaps are differences of two
  independently bootstrapped point estimates (documented in the module docstring);
  `evaluate_kill_criterion`'s "CIs don't contain each other's point" is a heuristic,
  not a test. Consistent with how it is logged; noted so nobody upgrades it.
- **m12 — `features/context.py::mom_12_1`** uses `close.shift(21)/close.shift(252)`, i.e.
  a 231-day window, not 11 months of a 12-month lookback. Standard enough; the name
  is slightly off from the formula, and M6.1's `raw_return_k` uses a different
  convention (log, no skip) — both documented.

## Nits

- `synthetic.py:77` `fillna(False)` on an object column raises a pandas
  `FutureWarning` on every run (5 warnings per suite).
- `modules/high_low_52w.py` and `cross_sectional.py` both compute `n_events` as the
  row count after decile assignment, which is the panel size, not an event count —
  correct per the docs' "rows" convention but misleading next to event-based modules.
- `docs`-facing cost annotations use `×12` for 21-day returns and `×50.4` for 5-day;
  `stats/costs.py::annualize` defaults to `horizon=21`, and `ribbon_slope_agreement_run.py`
  passes `horizon=21` explicitly — the M11 5-day mistake the docs record is a caller
  error the API invites. A required `horizon` argument would have prevented it.

---

## Design-level observations (not bugs, but they bound what the numbers mean)

1. **Universe selection is a look-ahead on survival and index membership** (C3). Every
   positive weak-state result should be read with this first, before momentum or
   reversal confounds.
2. **`sector` is current-state, not point-in-time** (documented in `panel.py`). A name
   reclassified during 2010–2021 is matched against the wrong sector for part of the
   window; C2's sector stratum is therefore slightly noisier than described.
3. **C2 matches on terciles, not deciles**, of `mom_12_1`/`realized_vol_63`. A tercile
   match leaves ~1/3-of-the-distribution residual momentum inside each stratum; for
   features that are themselves functions of the trailing year's path
   (`dist_from_52w_low`, `slope_pctile_21`) that residual is not small. The docs name
   this gap for M18; it applies to every cell.
4. **p-value resolution and comparability** (M2, M3): the FDR ranked table mixes three
   kinds of p-value — bootstrap-CI Wald (most cells), simulation-envelope Wald (M6.4),
   and Reality-Check empirical (M8, correctly excluded). Only the first kind is a
   p-value of the cell's own estimate.
5. **`InsufficientBlocksError` is caught and turned into NaN in 19 places**, always
   flagged via `below_threshold`. Correct, but the pattern is copy-pasted; a shared
   `bootstrap_or_nan` (as `sma_dropoff.py` already has) would make it one place.
6. **Two of the study's headline mechanisms are conditioned on outcomes of the same
   window**: M6.4 (a null that is not the pre-registered construction) and M14 (a flag
   that requires a future breakout). After C1's re-run and C2's redefinition, the
   FDR survivor set will change; `STATUS.md`/`REPORT.md`'s "first survivors in the
   study's history" framing should wait for that.

---

## Test suite assessment

- **Baseline 361 → 367 tests, all passing; wall time 284 s → 155 s (cache-warm
  second run, not a speedup from this branch).** `validate-synth` passes before and
  after with identical numbers.
- **The synthetic gate is real but narrow.** It exercises `apply_lag`,
  `forward_return` and `c1_delta` on a 5-day SMA with a planted +3% effect and a
  one-extra-day shift, and asserts recovery within ±0.5%, null within ±0.5%, and
  shifted recovery below 70% of planted. It does not exercise any module's
  `prepare()`, so a module-local feature that skips `apply_lag` (M1 here) passes the
  gate untouched. A generic leakage test — perturb every bar after *t*, assert every
  feature at *t* is unchanged — run over each module's `prepare()` would have caught
  M17 and would guard the modeling phase's feature registry too (the modeling ideas
  inbox proposes exactly this).
- **The delisted-coverage smoke test passes vacuously** (C3): it should be scoped to
  the development window, at which point it fails honestly.
- **Regression tests exist** for the bugs the docs say were caught: the `above`
  warmup-NA fix (`test_above_is_na_during_ma_warmup_not_false`), `skipna=False` in
  `ribbon_width`/`forward_realized_vol`/`forward_max_drawdown`, the `merge_asof`
  sort and `sector` collision (`test_moving_averages_timeframe_sampling.py`),
  `best_lookback_per_regime` sign-agnostic selection, `c1_delta` dilution,
  `c0 = (1-p)·pooled`, `state_run_id` internal-gap rejection.
- **Presence-only tests**: every module has a `test_prepare_adds_expected_columns`
  that asserts column names exist and nothing about values; `test_gbm_null_survival_smoke_and_sanity`
  asserted only monotonicity and `[0,1]` bounds (now complemented by the direction
  test). `test_divergence_flag_is_boolean_or_na_and_only_set_on_new_high_rows`
  computes a variable it never uses.
- **No test relates `p_value_from_ci` to an empirical bootstrap p**; a single test with
  archived draws would show how far the Wald approximation drifts on a skewed cell.
- **Stats tests are good where they exist**: bootstrap CIs cover planted effects and
  straddle zero on nulls; `block_bootstrap_group_diff` and `spread_diff` are checked
  against manual computations; BH step-up, NaN handling, and the Reality Check's
  null/alternative behaviour are all asserted directly.

## Files changed in this branch

| file | change |
|---|---|
| `src/signals/moving_averages/stats/survival.py` | `direction` filter on `_slope_sign_runs_single_path`/`gbm_null_survival`; result carries `direction` |
| `src/signals/moving_averages/modules/slope_persistence.py` | `stratum_result` requests a direction-matched null, reports `null_direction` |
| `src/signals/moving_averages/modules/nonlinearity_probe.py` | `is_new_high` built NA-preserving and lagged through `apply_lag`; population restrictions use `.fillna(False)` |
| `src/signals/moving_averages/stats/shape.py` | `hit_rate_deltas` keeps NaN returns undefined |
| `src/signals/moving_averages/stats/inference.py` | `block_bootstrap_spread`/`_spread_diff` drop undefined-decile rows |
| `tests/test_moving_averages_stats_survival.py` | +2 tests (direction filter; rising vs pooled under drift) |
| `tests/test_moving_averages_slope_persistence.py` | +1 test (direction-matched null requested) |
| `tests/test_moving_averages_nonlinearity_probe.py` | +1 test (lagged, NA-on-warmup new-high flag); one existing test adapted to the nullable flag |
| `tests/test_moving_averages_stats_shape.py` | +1 test (NaN return is undefined, not a miss) |
| `tests/test_moving_averages_stats_inference.py` | +1 test (undefined decile rows excluded) |

No study doc other than this file is touched.
