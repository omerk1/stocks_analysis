# Validation harness — design

**Status:** design, 2026-09-30. Nothing built yet. This is the first modeling code, and
every model result depends on it, so it gets built and checked before any real fit.

**What it is:** one pipeline that takes a feature panel and a model, and returns
out-of-sample metrics with honest confidence intervals, logging every trial. It
*enforces* the requirements `ma_study_insights.md` already derived, and doesn't restate
them:
- **§3** — baselines B0–B5 the model has to beat.
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
upper `P0 + U·A`, lower `P0 − D·A`, horizon `H` trading days (bars t+1 … t+H):

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
  the row is flagged. Until survivorship-free data exists, this almost never fires
  (backlog).
- **Grid (v1):** H ∈ {5 (diagnostic), 10, 21, 42, 63}, U ∈ {1, 2, 3}, D ∈ {1, 1.5, 2}.
  That's 45 cells, fixed before any fit. 126-day horizons (M18's 52-week family) are a
  separate, later grid, because at H=126 the study had about 10 independent blocks
  (§4 of the insights doc).
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

- **Baselines B0–B5** as defined in `ma_study_insights.md` §3, each a model with a
  fixed column set:
  - B0 per-date base rate
  - B1 date-demeaned
  - B2 momentum × vol × sector
  - B3 + reversal
  - B4 + extension
  - B5 + the Tier-2 slope percentile

  B2 in both its matched-stratum and regression forms, once, to confirm they agree.
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
stays only on an out-of-sample gain over the step before it.

---

## 8. Gates that run before any real fit

1. **Synthetic planted-effect gate** (port of `moving_averages/synthetic.py`, per §5):
   - On a synthetic panel, plant a feature that raises P(upper first) by a known amount
     at one cell. The harness must recover it within its CI.
   - A pure-noise feature must show no gain.
   - Shifting the planted feature one extra bar must degrade recovery by the expected
     amount.
2. **Label-shuffle gate:** permuting labels *within date* must collapse every model to
   B1. Anything better means leakage through the date structure.
3. **Leakage test:** extend `tests/test_moving_averages_leakage.py`'s pattern to every
   registered feature. Perturb all bars after *t*; every feature at *t* must be
   unchanged.
4. **Purge test:** no training label window intersects any test date, for every fold
   scheme and horizon.

Any gate failing means no result from the harness is trusted. This is the same rule as
the MA study's `validate-synth`.

---

## 9. Code layout and build order

```
src/models/
  dataset.py          H1 holdout lock, H3 universe mask, panel assembly
  labels/barriers.py  §3
  splits.py           §4
  baselines.py        B0–B5
  learners.py         gradient-boosting wrapper, calibration, monotonicity check
  metrics.py          §6 metrics, n_dates gate
  inference.py        draws-returning bootstrap wrapper over moving_averages/stats
  trial_log.py        TRIALS.csv + data/models/<trial_id>/
  features/registry.py
  synthetic.py        §8 gate 1
  cli.py              run-trial, run-gates
tests/test_models_*.py
```

Build order, one PR each, each with its own tests:
1. `labels/barriers.py` + `splits.py` + purge test. **Done (#140).**
2. `dataset.py` (holdout lock, universe mask, liquidity floor) + `metrics.py`
   + `inference.py`. Notes carried from step 1:
   - **Build labels one horizon at a time** and store them on disk (e.g. a
     parquet per horizon). All 45 cells in long format for the full universe is
     roughly 65M rows (~130k per ticker), too much to hold at once.
   - **Apply `ticker_renames.apply_renames` to membership** before anything
     else. Without it, the 26 renamed members (FB→META, ABC→COR, …) look
     price-less and silently drop out of training. It applies each rename only
     inside its verified window (Done #68).
   - **Labels are computed from bars truncated at the holdout boundary**
     (`data_end=2021-12-31`), so windows crossing it come back NaN by design.
3. `baselines.py` + `learners.py` + `trial_log.py`.
4. The four gates (§8). Real data is used only after these pass.
5. First pre-registered experiment: E1 from `ma_study_insights.md` §8, run on the
   harness end to end.

---

## 10. Open questions

- **Entry at the next open vs the next close.** The open is realistic for an after-close
  notification but adds overnight gap noise. The MA study used close-to-close. v1 uses
  the open; one trial at the close checks the sensitivity.
- **Universe for v1 fits:** S&P 500 only (cleanest point-in-time membership), with
  R1000/R2000 proxies added once they're stored (PR #129 is built but not stored,
  pending survivorship-free data).
- **Sector is not point-in-time** (`ma_study_insights.md` §2.4): used in B2 as-is, with
  the leak documented, until a PIT sector table exists.
