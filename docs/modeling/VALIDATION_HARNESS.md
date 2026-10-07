# Validation harness — design

**Status:** design, 2026-09-30. Steps 1–4 built (§9). This is the first modeling code, and
every model result depends on it, so it gets built and checked before any real fit.

**What it is:** one pipeline that takes a feature panel and a model, and returns
out-of-sample metrics with honest confidence intervals, logging every trial. It
*enforces* the requirements `ma_study_insights.md` already derived, and doesn't restate
them:
- **§3** — the baselines the model has to beat (the harness uses B0, B2–B4; §5).
- **§4** — the barrier target and horizons.
- **§5** — the requirements table: purge, embargo, effective N, seeds, plateau,
  synthetic gate, costs.

Where this doc says "per §5", that table is the source.

---

## 1. Invariants the harness enforces in code (not by convention)

| # | invariant | enforced by |
|---|---|---|
| H1 | **Holdout locked.** No row dated after 2021-12-31 is loaded unless `open_holdout=True` is passed explicitly, and that flag is recorded in the trial log. | `dataset.load(...)` raises; test asserts it. |
| H2 | **One-bar lag.** Features are known at the close of *t*; the position is entered at the **open of t+1**. | Barrier labels start at t+1 (§3); features come through `apply_lag` or the level-snapshot roll-forward (`LRP.md` §4); leakage test (§8). |
| H3 | **Point-in-time universe.** A row exists only if the ticker was a member on *t* (`db.read_index_membership(as_of=t)`, with `ticker_renames.apply_renames` so renamed members keep their prices), passes the liquidity floor on trailing data, and passes `history_breaks.training_eligibility`. | `dataset.universe_mask(...)`; the same function is used at training and prediction time (backlog, history-breaks follow-up (b)). |
| H4 | **No full-sample statistics.** Every normalisation and rank is trailing or per-date. | Feature registry declares each feature's construction; leakage test perturbs the future (§8). |
| H5 | **No overlap leakage.** Training rows whose label window reaches into a test fold are purged; an embargo follows each test fold. | `splits.py` (§4), with a test that no train label window intersects a test date. |
| H6 | **Effective N.** Every metric row carries `n_rows` and `n_dates`; a fold or subgroup under `MIN_BLOCKS × block_length` dates is reported as "not computable", never silently pooled. | `metrics.py` + the existing `InsufficientBlocksError`. |
| H7 | **Every trial logged**, including failed and abandoned ones. | `trial_log.py` appends before returning results (§6). |

---

## 2. Data contract

The harness consumes one long table, one row per (ticker, date) in the universe:

```
ticker, date                      keys
universe flags                    in_sp500, in_ndx100, in_r1000_proxy, ... (PIT, per row)
eligible                          H3 mask (membership ∧ liquidity ∧ training_eligibility)
features ...                      float32, already lagged; each registered (§7)
label columns ...                 one per barrier cell (§3), plus label_end_date
```

- **Assembly:** from the cached MA panel (`features/panel.py::read_panel`, extended per
  `ma_study_insights.md` §7) plus new feature families, joined on (ticker, date).
  Families never recompute each other's inputs (CLAUDE.md style: "every module reads
  from cache").
- **Liquidity floor:** trailing 20-day median dollar volume, per universe. Defaults:
  - S&P 500, Nasdaq-100, R1000 proxy: $20M.
  - R2000 proxy: $5M, plus a $5 price floor.

  Measured on the 2021 rank day: $20M removes 8% of R1000-proxy members but 86% of
  R2000-proxy members (PR #129). Both levels are config values, and each trial logs the
  ones it used.
- **Survivorship tag:** each row carries `capped_bucket` (the weak/bearish states the MA
  study caps). Every metric table reports the fraction of evaluated rows in it (per §5).

---

## 3. Labels: the barrier surface

New `src/models/labels/barriers.py`. It's the triple-barrier labeler `ma_study_insights.md`
§4 found missing; the MA layout's `labels/barriers.py` was never built.

For entry at the **open of t+1**, price `P0`, ATR `A = atr_14(t)` (already lagged),
upper `P0 + U·s·A`, lower `P0 − D·s·A` with `s = √(H/21)` (the grid's barriers are quoted
at H = 21 and widen with the horizon; see Grid below), horizon `H` trading days
(bars t+1 … t+H):

| output | meaning |
|---|---|
| `hit(H,U,D)` | +1 upper first, −1 lower first, 0 neither by t+H |
| `hit_day` | bars until the first hit (NaN if none) |
| `terminal_ret` | close(t+H) / P0 − 1, used for "neither" rows and for EV |
| `mfe`, `mae` | max favourable / adverse excursion in ATR over the horizon (extends `path_metrics.py`) |
| `label_end_date` | date of bar t+H, used for purging |

Rules:
- **Same-bar tie** (one bar's high ≥ upper and low ≤ lower): counted as **the stop
  first** (−1), the conservative reading of daily bars. `tie_count` is logged per cell.
  The share of ties is reported per horizon; it's the reason H=5 is diagnostic only.
- **Gap through a barrier** at the open: the fill is the open price, not the barrier.
  EV uses the actual fill, so a gap down through the stop costs more than D.
- **Delisting inside the horizon:** the label resolves on the last available bar, and
  the row is flagged. This fires for the 132 delisted members read from Tiingo
  (Done #83); the 101 still missing never reach it (backlog).
- **Disputed price days:** a label is dropped, not resolved, when its ticker's vendor
  has a reviewed disputed day (`market_common/price_disputes.csv`: a corporate action
  one vendor gets wrong, or the vendors disagree and it's unknown which is right) in
  its window or in the 42 bars before it (the ATR its barriers are sized with), counted
  on the ticker's own bars. The label manifest records how many (`n_disputed_dropped`);
  0.41–0.61% of eligible S&P 500 rows, 2010–2021 (Done #86). A ticker whose yfinance
  error masking can't fix (T's dividend drift) is read from Tiingo instead
  (`market_common/vendor_overrides.PREFER_TIINGO`).
- **Grid (v1):** H ∈ {5 (diagnostic), 10, 21, 42, 63}, U ∈ {2, 3, 4}, D ∈ {1, 1.5, 2},
  every distance × √(H/21). That's 45 cells, fixed before any fit. 126-day horizons (M18's
  52-week family) are a separate, later grid, because at H=126 the study had about 10
  independent blocks (§4 of the insights doc).

  **Revised 2026-10-06, before any fit.** The original grid used U ∈ {1, 2, 3} ATR at
  every horizon. A label check on eligible S&P 500 point-in-time rows (2010–2021, 1.37M
  rows, 642 tickers) showed that made the horizon nominal:
  - The time to reach a barrier grows with the square of its distance, so a fixed 1–3 ATR
    barrier is reached in days, whatever H is.
  - 1/1 resolved in 3.4 days on average at H = 21, 42 and 63 alike, 85% within 5 days.
  - Even 3/1.5 resolved in its first third 85% of the time at H = 63, with 1% "neither".

  Scaled by √(H/21), a cell keeps its shape across horizons. 2/2 is 48/40/12% (target /
  stop / neither) at H = 10 and 55/36/8% at H = 63, and resolves in about the first third
  at every H.

  U = 1 is dropped: it's decided by a few days of noise, costs eat a 1-ATR target, and
  tight 1:1 targets aren't how positions are managed. U = 4 is added, so R/R runs 1:1 to
  4:1.

  A random-walk check confirmed the labeler itself. On an intraday-simulated walk it named
  the true first barrier on every row except two same-bar ties, and P(target first)
  matched D/(U+D) (`test_labels_match_first_passage_on_a_random_walk`).

  `BarrierCell` keeps the nominal U, D (`upper`, `lower`) and the actual distances
  (`upper_atr`, `lower_atr`); labels and EV use the actual ones. At H = 5 the scaled
  barriers are ~0.5 ATR and ties reach ~5%, so H = 5 stays diagnostic.
- **Short side:** the same labeler with the barriers mirrored. It's computed from day
  one as a diagnostic (`IDEAS.md` §6).

---

## 4. Splits

New `src/models/splits.py`. Dates are the unit, never rows.

- **Outer folds:** walk-forward with **yearly test folds 2014–2021**. Features need
  about a year of warmup from 2010, and 2011–2013 is the first training window.
  - **Expanding** (train on everything before the fold) is the primary scheme.
  - **Sliding** (train on the last 3 years) is secondary.

  A large gap between the two is reported as a regime-drift signal.
- **Purge:** drop training rows with `label_end_date ≥ test_start`.
- **Embargo:** 21 trading days (≥ H for H ≤ 21; H for longer horizons), applied on both
  sides for any scheme where training data follows test data. That's only the nested
  inner folds here.
- **Nested inner folds** (inside each outer training window, same walk-forward shape)
  for hyperparameters and for stacking family scores (`IDEAS.md` §2b option 2). The
  outer fold never sees a model or score tuned on it.
- **Reporting splits:** per calendar year, and 2010–2015 vs 2016–2021 (per §5). A
  feature group whose sign flips between the halves does not ship.

---

## 5. Models and baselines

One interface: `fit(X, y, sample_weight) → self`, `predict_proba(X) → P(+1), P(−1), P(0)`.

- **Baselines B0, B2–B4** (`baselines.py`), from `ma_study_insights.md` §3. Each is a
  model with a fixed column set (`features/baseline.py`, the study's own definitions,
  as per-date ranks):
  - B0: the training class frequencies, the same for every row
  - B2: momentum (`mom_12_1`), volatility (`realized_vol_63`), sector
  - B3: B2 + reversal (`mom_1_0`)
  - B4: B3 + extension (`dist_pct_sma_50`)

  B2–B4 are the v1 learner itself on those columns, so beating B4 means the extra
  columns carry information. B2 is also run once in its matched-stratum form, to
  confirm the two agree.

  Dropped 2026-10-03:
  - **B1 (the date's own outcome rate).** Within-day skill is measured directly by the
    IC and the top-k excess over that day's mean return (`metrics.py`).
  - **B5 (the Tier-2 slope percentile).** One fragile cell out of 107 is too weak to be
    a rung.
- **v1 learner:** gradient-boosted trees (scikit-learn's `HistGradientBoostingClassifier`, already
  installed; LightGBM-style histogram boosting without a new dependency), one three-class model (+1 / −1 / 0)
  per (H, U, D) cell. That's option (a) of `IDEAS.md` §1,
  chosen for v1 because it's simplest to calibrate and check. Option (b), the path
  distribution, comes later and is judged against (a) on the same folds.
- **Monotonicity check after prediction:** for fixed H and U, P(stop first) must not
  fall as D shrinks. Violations are counted and reported, not silently fixed.
- **Calibration:** isotonic, fitted on the inner folds only.
- **Seeds:** every trial runs at 3 seeds; the across-seed spread is reported next to the
  across-fold spread (per §5).

---

## 6. Metrics, inference, and the trial log

**Per fold, per cell:**
- Brier score and log loss.
- Reliability curve (10 bins).
- Per-date Spearman IC of P(+1) vs realised outcome.
- `n_rows`, `n_dates`, `tie_share`, `capped_bucket` share.

**The notification metric (`IDEAS.md` §11):** each day, take the top k (k ∈ {5, 20}) rows
by expected value, where
`EV = P(+1)·U·A − P(−1)·D·A + P(0)·E[terminal_ret | 0]`, net of cost. Report their
realised hit rate and realised EV after cost at 10 and 25 bps round trip. The
best-cell-per-ticker choice happens *before* evaluation, so the winner's curse (`IDEAS.md`
§1) is inside the measured number, not outside it.

**Model vs baseline:** every comparison is a difference on the same rows, with a
date-block bootstrap CI.
- Block = 2H.
- Draws are **archived**, not just the CI (per §5), via a draws-returning variant of
  `stats/inference.py::block_bootstrap_series`.
- Models are ranked by the near CI edge, not by an extrapolated p-value.

**Multiple testing:** each experiment pre-registers its trial count. BH at q = 0.10 runs
once at the experiment's close. "Best of K models" claims use White's Reality Check
(`stats/multiple_testing.py`). A finished experiment is never re-ranked against a later
experiment's denominator.

**Plateau:** for every tuned hyperparameter or threshold, the ±20% neighbours' metric is
reported next to the chosen value. A lone best is noise.

**Trial log:** `docs/modeling/TRIALS.csv`, append-only like the study's
`EXPERIMENTS.csv`. One row per trial, including failed ones:
- `trial_id`, date, `experiment_id`
- git SHA; feature groups and their priors
- universe and liquidity floor; label cell(s); fold scheme; seeds; hyperparameters
- the metric summary with CIs, `n_dates`
- `open_holdout`
- an outcome line

Draws and per-fold detail go to `data/models/<trial_id>/` (untracked). The pre-registration
text per experiment goes in `docs/modeling/PREREGISTRATION.md`, the same two-phase commit
as the MA study: pre-register, commit, run, log.

---

## 7. Feature registry

New `src/models/features/registry.py`. Every feature column declares:
- **family and shape:** dense / event / level-set / static / market-wide
  (`IDEAS.md` §2b);
- **prior:** supported / weak / null (`IDEAS.md` §2);
- **source function, warmup in bars, and whether it's per-date ranked.**

Ablations run by *group*, in prior order: supported, then weak, then null. A null group
stays only on an out-of-sample gain over the step before it. Dropping a group is an
operational decision; the trial's recorded outcome distinguishes a **demonstrated null**
(the whole CI sits inside the pre-committed minimum-relevant-improvement band) from
**inconclusive** (the CI spans zero but extends beyond the band — underpowered, not
evidence of no effect). Rule and dating: `LRP.md` §3 kill criterion, amended 2026-10-07.

**Built (step 4), minimal.** `registry.py` declares every column decided at the close of
*t*, not just model inputs: each entry has a `role` (`model`, `universe` for the H3
filters, `decision` for the EV ranking's ATR %). The leakage gate (§8) runs every
registered source, so a feature registered later is covered automatically.
`BoostedModel` refuses a column that isn't registered (`check_columns`); only the
synthetic gates and unit tests opt out. The baseline columns, the
universe filters and `atr_pct` are registered today. `sector` is registered as static
(not bar-derived, so the leakage gate can't cover it).

**MA family (E1 step 1, 2026-10-06).** `features/ma_family.py` registers the
`ma_study_insights.md` §2.2 v1 list as group `ma`, computed on the harness's timing (row t =
close of t) with the study's own functions, all scale-free:
- **supported:** `slope_log_21_sma_50` (rank) and `ribbon_agreement_state`;
- **weak:** `dist_z_sma_20`, `dist_from_52w_low`, `stack_fully_bearish`,
  `log_dollar_volume_20d` (rank), `macd_hist_pct`, `ribbon_width_pctile`, `dist_z_sma_200`,
  `slope_log_63_sma_50` and `adx_14`. The last three priors were assigned when E1 was
  planned.

Changes from §2.2:
- the absolute-slope column is dropped (it's for linear models; the learner is a tree);
- MACD is its histogram over the close (price units fail the leakage gate);
- dollar volume is a per-date rank, not a tercile;
- ADX is the level, not the regime bucket.

**Ties.** Comparisons between price moves or levels use a tie tolerance (1e-9 × close):
ADX's "which move is larger", the ribbon's "slope > 0" and the stack's ordering. Quoted
(cent-rounded) prices tie exactly, and a later split or dividend breaks such ties in
floating point. A strict comparison would then make the value at *t* depend on corporate
actions after *t*. The real-bar smoke run caught it on ADX (Tiingo's cent prices; up to 3.9
ADX points). The gate's synthetic bars are now cent-rounded, so the synthetic gate catches
this class too.

`features/cache.py` builds one cache of every registered model column for a universe's
eligible rows, ranked per date over those rows (`python -m src.models.cli build-features`).
S&P 500 2010–2021: 1,371,246 rows, 642 tickers (112 from Tiingo), no column more than 1.0%
missing.

---

## 8. Gates that run before any real fit

`python -m src.models.cli run-gates` (`gates.py`, data from `synthetic.py`; the tests in
`tests/test_models_gates.py` call the same pass/fail functions at a smaller size). Gate
CIs are 99%, not the 90% used for reporting, so that a gate fails on a bug, not on one
draw in ten.

1. **Synthetic planted-effect gate** (port of `moving_averages/synthetic.py`, per §5):
   - Labels are drawn straight from known probabilities, not from simulated prices, so
     the size of the effect is exact. A per-ticker AR(1) feature `x` raises P(+1) by
     δ = 0.10 when it's above 0, taking it from P(−1). A market-wide regime moves every
     ticker's base rates together; no feature sees it. Tickers join late and delist
     early, as in the point-in-time universe.
   - Run through the real `fit_predict` (with calibration) on walk-forward folds, and the
     real paired bootstrap against B0. The Brier gain's CI must contain the exact oracle
     gain, −δ²/2.
   - A pure-noise feature with the same persistence must show no gain (its CI's near edge
     doesn't clear 0).
   - The feature one bar late must lose the expected share of the gain. With persistence
     ρ = 0.7, the oracle gain is −2δ²·arcsin(c²/(1+c²))/2π, where c = ρ/√(1−ρ²); that's
     about a third of the unshifted gain. Its CI must contain that value and lie entirely
     above the unshifted CI.
   - The recovered uplift in P(+1) is reported too: δ, and 2δ·arcsin(ρ)/π one bar late.
2. **Label-shuffle gate:** outcomes are permuted among each date's rows. Each date keeps
   its outcome mix, but which ticker got which outcome is lost. Within-day skill must
   vanish: the mean daily IC and the top-5 and top-20 excess over the day's mean have CIs
   containing 0. The Brier gain over B0 must vanish too. That last check is valid only
   because no synthetic feature knows the date's regime; on real data a market-wide
   feature could keep a legitimate gain. The same within-day measures on the unshuffled
   panel must detect the planted skill, so a pass isn't vacuous. (Replaces "collapse to
   B1", dropped 2026-10-03.)
3. **Leakage gate:** every registered source (§7) is recomputed after perturbing
   everything after *t*:
   - the future price path;
   - a future split: earlier adjusted prices and volumes are rescaled, and the split is
     added to that vendor's splits;
   - a future dividend: earlier total-return prices are rescaled;
   - a delisting right after *t*: later bars are removed (catches a column that reads
     whether a next bar exists).

   Every value dated ≤ *t* must be unchanged. A split or dividend after *t* rescales every
   earlier adjusted price, so a column may use price *ratios* from the past, never
   adjusted price *levels*. Two planted canaries (tomorrow's close, an adjusted price
   level) must be caught, the labels across *t* must move, and each column's first value
   must sit at its declared warmup. It runs on synthetic bars; a read-only smoke run
   (`--smoke-db`) repeats it on real bars from both vendors.
4. **Purge gate:** labels come from the real `barrier_labels` on synthetic bars (with
   holidays and delistings, so some windows are truncated). For every v1 horizon, both
   fold schemes and their inner folds, with and without the embargo: no training label
   window touches its test period. Then `fit_predict` is traced with a recording model.
   No row it fits on reaches the period it's evaluated on, or the outer test year, and
   the calibration rows are exactly the inner test years. A canary (the training window
   without the purge) must touch the test period in every fold.

Any gate failing means no result from the harness is trusted. This is the same rule as
the MA study's `validate-synth`.

**Not covered by any gate:** a column that is constant over time but differs by data
vendor. A ticker is read from Tiingo only when yfinance has no bars for it at all, which
in practice means it was later delisted. Delisted members' sectors also come from SEC SIC
codes, everyone else's from Yahoo. If Tiingo's bars differ systematically (volume scale,
gaps), a model could learn "Tiingo-looking" = "will delist". Perturbing the future can't
show that, so `python -m src.models.cli vendor-check` covers it: a same-ticker gate (live
tickers stored on both vendors, every model input, and the raw value behind each ranked one,
computed from each; passes when a vendor classifier stays at AUC <= 0.55 and, per column,
the median gap is < 0.05 SD, <= 5% of rows are off by > 0.1 SD and <= 1% are missing on one
vendor only; non-zero exit otherwise), plus, with `--features`, the delisted-vs-live
read-outs. Rerun it whenever a model feature is registered. First full run (2026-10-07,
345 tickers, 21 columns): pass, AUC 0.524, largest median gap 0.011 SD (Done #87, #89).

---

## 9. Code layout and build order

```
src/models/
  dataset.py          H1 holdout lock, H3 universe mask, panel assembly
  labels/barriers.py  §3
  splits.py           §4
  baselines.py        B0, B2–B4 (+ B2's stratum form)
  learners.py         gradient-boosting wrapper, calibration, monotonicity check
  metrics.py          §6 metrics, n_dates gate
  inference.py        draws-returning bootstrap wrapper over moving_averages/stats
  trial_log.py        TRIALS.csv + data/models/<trial_id>/
  features/baseline.py  the baselines' factor columns
  features/registry.py
  synthetic.py        §8 synthetic data
  gates.py            §8 gates and their pass/fail checks
  cli.py              run-gates (run-trial with step 5)
tests/test_models_*.py
```

Build order, one PR each, each with its own tests:
1. `labels/barriers.py` + `splits.py` + purge test. **Done (#140).**
2. `dataset.py` (holdout lock, universe mask, liquidity floor) + `metrics.py`
   + `inference.py`. **Done (#152).** Choices made there:
   - **Two price bases** (`docs/decisions/price-basis.md`): labels, ATR and
     the decision close on `total_return`; dollar volume and the traded-price
     checks on `traded`.
   - **Labels are cached one horizon at a time**, one parquet per side and
     horizon (`data/models/labels/<universe>/<side>/h=<H>.parquet` + a JSON
     manifest). Only member rows are stored, with liquidity and eligibility not
     applied, so changing a floor doesn't mean relabeling. Bars are cut at
     2021-12-31, so windows crossing it are NaN.
   - **Metrics:** three-class Brier and log loss; IC against the ordinal `hit`.
     EV ranks on ATR / decision close, never the next open. `neither_ret` comes
     from the training folds.
   - **Inference:** the bootstrap is row-weighted for losses (the point equals
     the pooled metric) and date-weighted for per-date statistics. Draws are
     archived as `.npz` files.

   Notes for step 3, from the 2019–2021 S&P 500 smoke run:
   - ~10% of member-rows have no bars: 74 names that left by 2026 (AVB, EA,
     ATVI, SIVB, …) were never ingested. They're flagged `has_bars=False`, not
     dropped, so the delisted-price fetch fills them in place (Tiingo, Done #83:
     S&P 500 member-days with prices 2019–2021 88–92% → 97–98%).
   - **BBT carries another company's prices.** The symbol was reused after BB&T
     became TFC (same CIK), and `ticker_renames` only considers price-less
     symbols, so BBT was never checked (`docs/backlog.md`, survivorship research).
   - The reverse-split cooldown flags DD (2019) and GE (2021) for a year each.
     Both were large-cap reverse splits around spin-offs, not distress. This
     feeds the with/without sensitivity in history-breaks follow-up (b).
3. `baselines.py` + `learners.py` + `trial_log.py`. **Done (#157).** Choices made
   there:
   - **Baseline features** come from `features/baseline.py`: the study's definitions,
     computed on bars up to t for the point-in-time universe, and cached as parquet.
     The MA panel isn't reused: it is lagged one row, and it only covers the 405
     tickers that survived to 2021.
   - **The learner** is three-class `HistGradientBoostingClassifier` with fixed v1
     defaults (`BoostingConfig`). Isotonic calibration (one class against the rest,
     renormalised) is fitted on inner-fold out-of-sample predictions. Inner test rows
     whose label window reaches the outer test year are purged as well.
   - **Seeds:** `max_features=0.8` makes seeds matter only with 5 or more columns. B2
     and B3 are deterministic, so their seed spread is a true 0.
   - **Trial log:** `trial(...)` writes a `TRIALS.csv` row on exit, whether the trial
     ends `ok`, `abandoned` or `failed`. A spec missing a design field (e.g.
     `open_holdout`) is refused before the trial runs.

   Smoke run (S&P 500 2010–2021, no fit): the B2–B4 columns are complete on 99.3% of
   eligible rows. 187 rows have a split-only bar but no total-return bar (and so no
   label), and FISV has no sector.
4. The four gates (§8). Real data is used only after these pass. **Done.** Choices
   made there:
   - **Planted labels, not planted prices.** Labels drawn from known probabilities make
     the gate's target an exact number. The labeler's own timing is covered by its tests
     and by gate 3, which includes the labeler's decision-day ATR.
   - **Gate runs are not trials.** They write nothing to `TRIALS.csv`, so they don't
     count toward any experiment's multiple-testing count.
   - **Full run** (v1 folds, 200 tickers, 341k test rows, 1,985 dates):
     - planted Brier gain −0.00507 (oracle −0.00500);
     - one bar late −0.00148 (oracle −0.00163);
     - noise −0.00026, CI [−0.00061, +0.00005];
     - planted uplift 0.0997 (δ = 0.10);
     - after the shuffle: IC +0.0002, top-20 excess −0.0001, both CIs spanning 0. The
       shuffled Brier gain is −0.00031, CI [−0.00068, +0.00001]: a pass, but only just
       (with noise's −0.00026, it's the same small, not significant edge for a calibrated
       boosted model over B0).

     All gates pass, including the read-only smoke run on 20 real S&P 500 tickers (4 of
     them delisted and read from Tiingo, with real splits from both vendors). About 10
     minutes.
   - **Isotonic calibration shrinks a weak, smooth signal.** The one-bar-late feature's
     expected uplift is 0.049.
     - Uncalibrated, the boosted model recovers it in full (0.048 at the tests' size).
     - Calibrated, it's cut to 0.036 at the tests' size (2–4 training years) and 0.043 at
       the full size. At the tests' size its Brier gain then misses the oracle, so the
       quick tests skip only that one amount check. At the full size the Brier gain still
       matches.
     - The likely cause: the isotonic maps are fitted on inner-fold models trained on
       fewer years, whose noisier predictions get flattened more, and the map is then
       applied to the better final model.

     Worth a look before the sliding (3-year) scheme or a weak feature group is judged on
     real data (e.g. compare uncalibrated, isotonic, and a 1-parameter scaling).
5. First pre-registered experiment: E1 from `ma_study_insights.md` §8, run on the
   harness end to end.

---

## 10. Open questions

- **Entry at the next open vs the next close.** The open is realistic for an after-close
  notification but adds overnight gap noise. The MA study used close-to-close. v1 uses
  the open; one trial at the close checks the sensitivity.
- **Universe for v1 fits:** S&P 500 only (cleanest point-in-time membership), with
  R1000/R2000 proxies added once they're stored (PR #129 is built but not stored;
  delisted prices exist only for former S&P 500 / Nasdaq-100 members, Done #82).
- **Sector is not point-in-time** (`ma_study_insights.md` §2.4): used in B2 as-is, with
  the leak documented, until a PIT sector table exists.
