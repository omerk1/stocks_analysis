# Modeling pre-registrations

Each experiment run on the harness (`VALIDATION_HARNESS.md`) is written here and
committed **before** it runs, the same two-phase discipline as the MA study:
pre-register and commit, then run and log. Once an entry has run, its text is frozen.
A result, or any change of scope, is a new dated addendum below it, never an edit.
Every trial gets a row in `TRIALS.csv`, whatever it found.

Verdicts follow the three-verdict rule (`LRP.md` §3, amended 2026-10-07):
- **pass**;
- **null**: an improvement as large as the pre-committed relevance band is ruled out;
- **inconclusive**: the CI spans zero but reaches past the band. That means
  underpowered, never "no effect".

---

## E1: do the MA features add information over B4? (registered 2026-10-07)

- **Track:** B, confirmation. It is the harness's first experiment (`VALIDATION_HARNESS.md`
  §9 step 5).
- **Promoted from:** `ma_study_insights.md` §8 E1 (draft). It is revised as listed under
  "Changes from the draft" below. The priors come from `IDEAS.md` §2; the registry
  holds the feature list (`features/registry.py`, group `ma`).
- **Executable copy:** `src/models/ablation.py`, `PREREGISTERED["E1"]`. Its column
  lists are literal, and a test pins them to the registry as of this entry.

### Hypothesis

Adding the MA family to the v1 learner lowers the out-of-sample three-class Brier score
of the calibrated barrier probabilities, on the same rows, compared with the B4
baseline. B4 is momentum, volatility, sector, reversal and extension.

The family enters in two groups, in prior order:

| step | adds | columns | compared with |
|---|---|---|---|
| T1 | supported (2) | `slope_log_21_sma_50_rank`, `ribbon_agreement_state` | B4 |
| T2 | weak (9) | `dist_z_sma_20`, `dist_from_52w_low`, `stack_fully_bearish`, `log_dollar_volume_20d_rank`, `macd_hist_pct`, `ribbon_width_pctile`, `dist_z_sma_200`, `slope_log_63_sma_50`, `adx_14` | T1 |

Each group is judged against the step before it, as `VALIDATION_HARNESS.md` §7
requires. T2 vs B4 is reported next to it.

### Scope

- **Target:** the long barrier cell U = 2, D = 2. The distances are in ATRs, scaled by
  √(H/21), so at H = 10/21/42/63 they are 1.38/2.00/2.83/3.46 ATR on each side. Ties
  count as stops (the labeler's rule).
- **Horizons:** H ∈ {10, 21, 42, 63}. H = 5 stays a diagnostic.
- **Universe:** the point-in-time S&P 500 with the $20M trailing-median dollar-volume
  floor and the history-break eligibility rules (`dataset.universe_mask`). Delisted
  members are read from Tiingo.
- **Window:** 2010–2021. The holdout stays locked.
- **Data:** the runner refuses a feature cache built for another universe or window.
  The feature and label caches are rebuilt from `main` once the pending
  reused-symbol disputes PR lands, before the run. A label cache built with any other
  disputes list is refused (`read_labels`). `vendor-check`'s same-ticker gate must pass
  on the registered columns. It passed on 2026-10-07 with AUC 0.524.
- **Learner:** v1 `BoostingConfig`, fixed, with no tuning: learning rate 0.05,
  200 iterations, 15 leaves, min leaf 1000, L2 1.0, 0.8 of the features per split.
- **Calibration:** isotonic, fitted on 2 inner walk-forward folds.
- **Seeds:** 0, 1 and 2. The probabilities are averaged over the seeds before scoring;
  the per-seed differences are reported.
- **Folds:**
  - expanding walk-forward;
  - yearly test folds 2014–2021, with the first training window 2011–2013;
  - training rows whose label window reaches the test year are purged;
  - no embargo is needed, because training always precedes the test.

### Trials and inference

- **8 trials:** 2 steps × 4 horizons. BH at q = 0.10 across all 8 runs once, at close
  (`close-experiment E1`). A failed or missing trial counts with p = 1.
- **Which row counts:** each trial is its first `ok` row run from a clean checkout at
  1,000 draws. A later rerun is counted but never replaces it.
- **Primary metric:** the pooled Brier difference (step − reference, negative = better)
  on the same rows. It comes with a 90% CI from the date-block bootstrap (block 2H,
  1,000 draws). The bootstrap p is the share of draws ≥ 0, one-sided.
- **Pass:** a trial passes when all four of these hold:
  1. it is BH-significant;
  2. its point estimate is at least the relevance band (an improvement too small to
     matter doesn't pass, however significant);
  3. it is better in at least 5 of the 8 test years;
  4. it is better in both eras, 2014–17 and 2018–21. The eras split the test years;
     the harness's 2010–15 / 2016–21 halves would include training-only years.
- **Not passing:** a trial that doesn't pass is **null** if its CI's improving end
  (the lower edge) stays above −band. Otherwise it is **inconclusive**.
- **Group verdict:** a group passes if any horizon passes. It is null only if every
  horizon is null. Otherwise it is inconclusive.
- **Relevance band:** the smallest Brier improvement whose top-5 pick EV would cover a
  10 bps round trip.
  - A calibrated signal that moves P(+1) up and P(−1) down by s (its sd across names)
    gains 2s² in Brier. It lifts the top 5 picks' EV by about 2.6 · s · (U+D) · ATR/close.
  - The calculation assumes ATR/close ≈ 2% (the median daily return sd in 2011–13 was
    1.46%).
  - 10 bps rather than 25 bps because it is the realistic cost for S&P 500 names. It is
    also the stricter choice for calling a null, since it gives the smaller band.

  | H | 10 | 21 | 42 | 63 |
  |---|---|---|---|---|
  | band (Brier) | 9.7e-5 | 4.6e-5 | 2.3e-5 | 1.5e-5 |

### Secondary readouts (reported, never a verdict)

- **Uncalibrated Brier difference.** Isotonic calibration shrank a weak, smooth planted
  signal in the gates (`VALIDATION_HARNESS.md` §9 step 4), so a weak group could look
  worse calibrated than it is. If calibrated and uncalibrated disagree, that is reported
  as such.
- **Log loss and per-date IC difference.**
- **Top-5 / top-20 per day by EV:**
  - hit rate;
  - excess over the day's mean return, with a CI on the difference;
  - return net of 10 and 25 bps round trip (invariant #8).

  These are descriptive. Top-k is not used to kill.
- **Per year, per era and per seed:** the Brier differences, and T2 vs B4.

### Known confounds

- **Sector** is current-state, not point-in-time. It is in every model, B4 included.
- **Survivorship:** 101 delisted members are still missing (backlog: EODHD). Their
  absence lifts the weak-trend and bearish rows the most, which is where
  `stack_fully_bearish` and `dist_from_52w_low` live.
- **Disputed days in features:** they are dropped from labels but still read by
  features (backlog: vendor disagreements (c)). A false one-day move can sit in a
  252-day window.
- **Sizes and volatilities:** the Tiingo-read delisted members differ in size and
  volatility. This is real economics, and the same-ticker vendor gate passes.

### Outcomes

- **T1 passes:** the supported pair enters the v1 feature set.
- **T2 passes:** the weak group stays with it.
- **Null or inconclusive:** the group is dropped from v1. The logged verdict says
  which. An inconclusive group may get a dated power addendum, for example a broader
  universe once R1000 is stored. A null group gets none.
- **Later:** the null-prior and inconclusive-prior features (`IDEAS.md` §2) are E1b, a
  separate entry.
- **Logging:** the result goes below as a dated addendum, with every trial's
  `TRIALS.csv` id.

### Changes from the `ma_study_insights.md` §8 draft

- **Baseline B4, not B3 → B5.** B5 was dropped on 2026-10-03 as one fragile cell. B4
  adds extension.
- **Barriers and horizons:** cell 2/2 on scaled barriers at four horizons, instead of
  1/1 ATR at H = 21. The 2026-10-06 grid revision removed U = 1, and fixed-ATR barriers
  made every horizon ≥ 21 ask the same few-day question.
- **Trial count:** 8 trials, not 12, because the fixed v1 learner is not tuned.
- **Top-k:** reported, not a kill condition.
- **Verdicts:** the three-verdict rule, with a pre-committed band.
