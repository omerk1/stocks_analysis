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
- **Data:** the runner refuses a feature cache built for another universe, window or
  disputes list,
  and a label cache missing more than 2% of the feature rows in the folds' window
  (disputed days drop 0.4–0.6%).
  The feature and label caches are rebuilt from `main` after the reused-symbol
  disputes PR (#184, merged 2026-10-07), before the run. A cache built with any other
  disputes list is refused. `vendor-check`'s same-ticker gate must pass
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
- **Which row counts:** each trial is its first `ok` row with the registered design
  (columns, cell, folds, seeds, hyperparameters) at 1,000 draws. If that row was run
  from a dirty checkout, the trial is void (p = 1). A later rerun is counted but never
  replaces it. `run-experiment` refuses to start on a dirty checkout.
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

### Result (2026-10-08 addendum)

**Verdict: both groups inconclusive.** No trial is BH-significant, and every CI spans
zero while reaching far past the band. Per the outcomes above, both groups are dropped
from v1. This is underpowered, not evidence of no effect.

- **Run:** `run-experiment E1` from commit 44a52de (clean), 2026-10-07 22:34 to
  2026-10-08 09:39. 8 of 8 trials `ok`, none rerun. `close-experiment E1` gave the
  table below.
- **Data:** caches rebuilt from `main` after #184.
  - Features: 1,368,478 eligible rows, 641 tickers (113 read from Tiingo).
  - Labels: disputes list `62b330fb12d4dd7c`. 23,751 rows dropped for disputed days at
    H = 10, and 47,601 at H = 63.
  - Rows without a label in the folds' window: 0.19–0.37%.
  - Same-ticker vendor gate: pass, AUC 0.519 over 285 tickers, T included (rerun after a vendor-check fix, Done #102).
  - All four gates pass on the run's code (main at e08fc82, before the run).
- **Effective N:** 2,001–2,005 test dates per trial (2014–2021).

| step | H | Brier diff (90% CI) | p | years better | 2014–17 / 2018–21 | band | verdict | trial |
|---|---|---|---|---|---|---|---|---|
| T1 vs B4 | 10 | +0.00006 [−0.00045, +0.00054] | 0.57 | 4/8 | +0.00085 / −0.00069 | 9.7e-5 | inconclusive | 20261007-193359-44a52de-ca22ac |
| T1 vs B4 | 21 | −0.00006 [−0.00071, +0.00063] | 0.45 | 5/8 | +0.00076 / −0.00084 | 4.6e-5 | inconclusive | 20261007-203109-44a52de-eb2fff |
| T1 vs B4 | 42 | −0.00055 [−0.00156, +0.00044] | 0.19 | 6/8 | +0.00038 / −0.00146 | 2.3e-5 | inconclusive | 20261007-215239-44a52de-ec9946 |
| T1 vs B4 | 63 | −0.00049 [−0.00219, +0.00128] | 0.32 | 4/8 | +0.00058 / −0.00156 | 1.5e-5 | inconclusive | 20261008-042715-44a52de-e55333 |
| T2 vs T1 | 10 | −0.00001 [−0.00097, +0.00088] | 0.52 | 5/8 | +0.00036 / −0.00036 | 9.7e-5 | inconclusive | 20261007-200447-44a52de-448e8f |
| T2 vs T1 | 21 | +0.00059 [−0.00054, +0.00180] | 0.79 | 3/8 | +0.00124 / −0.00003 | 4.6e-5 | inconclusive | 20261007-210044-44a52de-3c03d2 |
| T2 vs T1 | 42 | +0.00005 [−0.00237, +0.00218] | 0.54 | 4/8 | +0.00132 / −0.00120 | 2.3e-5 | inconclusive | 20261008-002905-44a52de-551caf |
| T2 vs T1 | 63 | −0.00085 [−0.00434, +0.00218] | 0.39 | 4/8 | +0.00150 / −0.00317 | 1.5e-5 | inconclusive | 20261008-060100-44a52de-e21998 |

Negative = better than the reference. B4's own three-class Brier score runs from 0.602
at H = 10 to 0.577 at H = 63. Every difference above is under 0.15% of that.

**Secondary readouts** (descriptive, no verdict):
- **Uncalibrated Brier:** worse than the reference in all 8 trials (+0.0003 to +0.0039,
  every CI spanning zero). Calibration isn't hiding a gain.
- **Seeds:** the three seeds agree in sign in every trial except T2 at H = 10 and 42,
  both near zero.
- **IC difference:** spans zero everywhere.
- **T2 vs B4:** spans zero at every horizon.
- **Top-5 excess return per day:**
  - T1 vs B4 is lower at H = 42 (−0.80%, CI excludes zero).
  - T2 vs T1 is higher at H = 10 (+0.23%), 42 (+1.25%) and 63 (+1.32%), with CIs
    excluding zero.
  - These are 8 unregistered looks, and top-k was registered as a readout only, so this
    is not a finding. A plausible mechanism to test, not a claim: the weak group
    includes the size rank (`log_dollar_volume_20d_rank`). It may push the EV ranking
    toward smaller, more volatile names, whose wider ATR inflates EV.
- **Costs** (invariant #8): one top-5 basket per day, over 21–63 days, at 10 bps round
  trip. The net returns are in each trial's `metrics.top_k`.

**Against the result:**
- **The era pattern is universal.** All 8 trials are worse in 2014–17 and better in
  2018–21. Two readings fit:
  - *More training data.* With expanding folds, the later years train on 7–10 years,
    against 3–6 for the early ones. Models with more columns may need that much.
  - *A regime change.* The low-volatility 2014–17 market differs from the 2018–21
    years, which include 2018 Q4 and 2020.

  The sliding (3-year) scheme would separate the two readings. That is a candidate
  addendum, not part of this verdict.
- **Plateau:** no horizon passes, and the neighbouring horizons agree. There is no lone
  bright cell.
- **Power:** the CIs are 10–100 times wider than the band. At this band a null is out
  of reach for any experiment of this size. The band (Brier gain needed to cover 10 bps
  on the top-5 picks) is generous to the signal, so it is small. The pre-registered
  rule is applied as written. A future experiment that wants a reachable null needs a
  larger band or a more powerful metric, set in its own entry before it runs.

**Consequence:** v1 is B4's columns. The MA family is not in the v1 feature set.
`IDEAS.md` §2's priors are unchanged: an inconclusive result revises nothing. E1b
(null- and inconclusive-prior features) and a sliding-window look at the era pattern
are both open, and each needs its own entry before it runs.
