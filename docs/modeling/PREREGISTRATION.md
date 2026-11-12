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
  - Same-ticker vendor gate: pass, AUC 0.519 over 285 tickers, T included (rerun after a vendor-check fix, Done #105).
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
- **T2 vs B4 (Brier):** spans zero at every horizon.
- **Log loss difference:** spans zero in 7 of 8 trials. The exception is T2 vs T1 at
  H = 63: −0.0061 [−0.0117, −0.0012], in T2's favour.
- **Top-k excess return per test date, over the H-day hold** (the basket's H-day forward return minus that date's mean; CIs on the difference):

  | H | top-5, T1 vs B4 | top-5, T2 vs T1 | top-20, T1 vs B4 | top-20, T2 vs T1 |
  |---|---|---|---|---|
  | 10 | −0.15% (spans 0) | **+0.23%** | **−0.12%** | **+0.14%** |
  | 21 | −0.08% (spans 0) | +0.09% (spans 0) | −0.10% (spans 0) | +0.04% (spans 0) |
  | 42 | **−0.80%** | **+1.25%** | **−0.46%** | **+0.57%** |
  | 63 | −0.75% (spans 0) | **+1.32%** | **−0.65%** | **+0.73%** |

  Bold = 90% CI excludes zero.
  - The pattern: the supported pair alone (T1) makes the picks *worse* than B4's. Adding the weak group (T2)
    lifts them back above T1 at H = 10, 42 and 63. There is no CI for T2 vs B4 on top-k, and
    at H = 21 top-20, T2 is still below B4 (net table), so this is not a T2 > B4 claim.
  - All of these are descriptive readouts without a verdict or a multiple-testing
    correction (16 top-k looks plus log loss), so none is a finding.
  - A plausible mechanism to test, not a claim: the weak group includes the size rank
    (`log_dollar_volume_20d_rank`). It may push the EV ranking toward smaller, more
    volatile names, whose wider ATR inflates EV.
- **Costs** (invariant #8): the mean return per pick, held 10–63 days (by horizon), net
  of a 10 / 25 bps round trip. One basket per day, so holdings overlap.

  | H | top-5 B4 | top-5 T1 | top-5 T2 | top-20 B4 | top-20 T1 | top-20 T2 |
  |---|---|---|---|---|---|---|
  | 10 | +0.14% / −0.01% | −0.01% / −0.16% | +0.22% / +0.07% | +0.15% | +0.03% | +0.17% |
  | 21 | +0.64% / +0.49% | +0.57% / +0.42% | +0.66% / +0.51% | +0.53% | +0.43% | +0.46% |
  | 42 | +1.64% / +1.49% | +0.84% / +0.69% | +2.10% / +1.95% | +1.54% | +1.08% | +1.65% |
  | 63 | +2.88% / +2.73% | +2.13% / +1.98% | +3.44% / +3.29% | +2.46% | +1.81% | +2.54% |

  Top-5 shows net 10 / 25 bps; top-20 shows net 10 bps. These are raw returns, not
  excess: they include the market's own move over the hold. No CI is computed for
  T2 vs B4 on top-k.

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

---

## HT1: does the frozen combined model's top 20 beat the market after costs, on the holdout? (registered 2026-11-09)

Registering is not opening. This entry is committed before any data after 2021-12-31
is read, and the holdout is opened only after the prerequisites under **Before the
holdout is opened** are done. It is then opened once, by this entry, and never again
for this model.

- **Track:** B, confirmation. This is the harness's final step (`VALIDATION_HARNESS.md`
  §9: "one pre-registered trading test of the full set, and the holdout opened once at
  the end"). The full set was cut short on purpose: levels and step 3 are a later
  version, tested against this one on data that arrives after this test.
- **Promoted from:** the Track A scorecards S1 → S1b → S1v (EV-in-ATR ranking beats the
  market at every readout of the dev window, CI clearing zero at 16 of 36), step 2b's
  per-name columns (`S2_no_market`, `S2_no_market_v`: CI above zero at 9 and 6 of 36 vs
  S1), and the freeze checks (`VALIDATION_HARNESS.md` §9, "Freeze checks", Result).
- **Executable copy:** `src/models/trading.py`, `PREREGISTERED["HT1"]`. Its column
  lists are literal, and a test pins them to the registry as of this entry, like F2.

### Hypothesis

The frozen model's daily top 20 by EV in ATR units (`rank="ev_atr"`), each traded to
its barrier cell's exit (target, stop, or the H-bar limit), has a higher mean return
per trade than the market basket traded the same way from the same date, **after a
10 bps round trip**, on data the model has never seen (2022-01-01 onward). Each date's
basket counts once, whatever its size: D_H below is a mean over dates of per-date
basket means, not a mean over all trades.

### Model

**S1 + the 8 per-name step-2b columns** (`COLUMN_SETS["S2_no_market"]`, 24 columns),
chosen by the freeze rule committed before the freeze runs (`VALIDATION_HARNESS.md` §9,
"Freeze checks"): against S1 the 8's paired median is +0.08% at seed 1 and +0.07% at
seed 2, CI below zero at 0 of 36 both times; against S1 + the 3 volatility columns
alone, +0.03%, CI above zero at 6 of 36. The columns:
- **B4 (5):** `mom_12_1_rank`, `realized_vol_63_rank`, `sector`, `mom_1_0_rank`,
  `dist_pct_sma_50_rank`;
- **MA (11):** `slope_log_21_sma_50_rank`, `ribbon_agreement_state`, `dist_z_sma_20`,
  `dist_from_52w_low`, `stack_fully_bearish`, `log_dollar_volume_20d_rank`,
  `macd_hist_pct`, `ribbon_width_pctile`, `dist_z_sma_200`, `slope_log_63_sma_50`,
  `adx_14`;
- **step 2b per-name (8):** `bb_width_pctile`, `atr_ratio_5_63`, `rvol_21_pctile_252`,
  `rel_volume_20_rank`, `updown_volume_20`, `rsi_14`, `sector_rel_mom_63`,
  `sector_rank_mom_63`.

The reference model is B4 (its 5 columns, same folds and seeds), a control here, not
the verdict.

Everything else is fixed as on the dev scorecards: v1 `BoostingConfig`, no tuning;
isotonic calibration on 2 inner folds; ties broken by the (ticker, date) hash.
**Seeds 0, 1, 2, averaged** before ranking (the probability average, as E1): no
single-seed caveat on the result.

### Scope

- **Test window:** every decision date from 2022-01-03 to the last date whose H-day
  label is complete on the refreshed bars. Nothing after that date exists for this test.
- **Folds:** expanding walk-forward continued from the dev scheme: yearly test folds
  2022, 2023, 2024, 2025, 2026 (partial). Each fold's model is trained on everything
  before it (2011 → the year before), label windows purged at the boundary. This is the
  model as it would be run: refitted once a year.
- **Universe:** the point-in-time S&P 500 with the $20M floor and history-break rules
  (`dataset.universe_mask`), delisted members and their terminal returns kept.
- **Horizons and cells:** H = 21 and H = 63, the 9 v1 barrier cells each (U ∈ {2, 3, 4}
  × D ∈ {1, 1.5, 2}, scaled by √(H/21)), pooled per horizon as in F2.
- **Picks:** each test date's top 20 by EV in ATR units. Top-5 is reported, never a
  verdict.
- **Entry and lag:** decision at the close of t, trade at the open of t+1.

### Primary metric and kill criterion

- **Per horizon:** D_H = the date-weighted mean over test dates of (model top-20 basket
  return − 10 bps) − (market basket return), averaged over the 9 cells on each date.
  Every basket's return is the cell's label return: entry at the open of t+1, exit at
  the target, the stop or the H-th bar, whichever comes first.
  - **Pooled dates:** a date enters D_H only if all 9 cells have it; dates missing a
    cell are left out and their count is printed (`dates_missing_a_cell`). The years
    rule below counts these pooled dates.
  - **Market basket:** the equal-weight mean label return of every row the model could
    pick that date (in the universe, scored by the model, with a resolved label and an
    ATR / close at the decision), with the same barrier exits as the picks. The model's
    picks need only a score and a resolved label; the ATR and decision close are label
    columns the barriers are computed from, so a resolved label carries both and the
    two pools are the same rows. It is charged no cost: it stands in
    for owning the equal-weight universe, which an index fund does at ~0.2% a year, not
    per trade. That stand-in is approximate: the basket exits each name at its
    barriers, which a fund doesn't. So D_H is the model's edge net of its own trading
    cost against the universe traded by the same exit rule at no cost.
  - **CI:** the date-block bootstrap (blocks of 2H dates, **10,000 draws**), 99%
    interval, the cells sharing their blocks. 10,000, not the dev runs' 1,000, because
    of the Holm cut below: the one-sided p is (draws ≤ 0 + 1) / (draws + 1), so at
    1,000 draws p ≤ 0.0025 would allow at most 1 draw ≤ 0, and the verdict would turn
    on one draw of Monte Carlo noise. At 10,000 it allows 24. The per-cell trial
    bootstraps use the same 10,000 (the close accepts only trials run at the
    registered count).
- **A missing cell:** a horizon with a cell that has no usable trial (not run, failed,
  or its first `ok` row logged from a dirty checkout, which voids it; a later row never
  replaces it) is **inconclusive**, with p = 1, and stays so. The holdout is not
  reopened to fill it.
- **Band:** ±10 bps per trade (the shared band of F1–F3 and E1's choice).
- **Verdict per horizon** on the 99% interval:
  - **dead** if it sits inside [−0.10%, +0.10%];
  - **inconclusive** if it spans zero and reaches past the band;
  - **effect** if it excludes zero, sign named.
- **The model passes ("works") only if**, at at least one horizon:
  - the effect is positive under Holm over the two horizons, at a family-wise one-sided
    level of 0.005 (the 99% interval's): the smaller one-sided bootstrap p must be at
    most 0.0025, and the other horizon then passes at p ≤ 0.005;
  - the point estimate is at least +10 bps;
  - the point estimate is positive in at least 3 of the test years. A year counts only
    with at least 126 pooled decision dates (`trading.MIN_YEAR_DATES`). With bars to
    November 2026, the partial 2026 has about 190 labelled dates at H = 21 and about
    150 at H = 63, so it most likely counts at both: 3 of 5 years. If it falls under
    126 at a horizon, that horizon's rule is 3 of 4 full years. Either way the count
    is whatever `trading.years_positive` returns on the refreshed bars.
- **One era, 2022–2026.** The code's "positive in every era" rule is given a single era
  holding every test year, so it adds nothing past a positive point estimate; the
  years rule above is what checks that the result isn't one stretch of time.
- **Overall result:** the model **passes** if the pass rule holds at either horizon
  (`entry_rule_met`). The seeds are averaged inside the run, so there is no seed rerun
  after it: `entry_rule_met` on the registered close (10,000 draws, no tickers
  excluded) is the pass. A precision check or an excluded-tickers rerun is not.
  Otherwise it doesn't pass, and the group verdict over the two
  horizons (`trading.group_verdict`) is reported: dead if both horizons are dead; a
  positive or negative effect if one or both show one of that sign; mixed if they show
  effects of opposite signs; inconclusive otherwise. A positive effect that fails the
  pass rule (under +10 bps, too few positive years, or not Holm-significant) is
  reported as "positive effect, pass rule not met", never as a pass.

### Named controls (reported, not part of the pass rule)

Each answers "is the edge just X?", and the outcome text below says how a pass reads
next to each.
- **vs B4** (the reference model, same folds and seeds), 99% CI: does the combined
  model add anything to plain momentum, volatility, sector, reversal and extension?
- **vs a low-volatility basket**, 99% CI: each date's 20 rows with the lowest
  ATR(14) / close, from the same rows the market basket uses (a zero ATR, a stale or
  halted price, left out), with the same barrier exits, net of the same 10 bps. Part of the dev gain
  came with calmer picks; low volatility is a known effect on its own.
- **The random-k basket** (20 random universe names a day, net 10 bps), descriptive
  only: its portfolio Sharpe per cell next to the model's, no CI.

### Readouts (descriptive, never a verdict)

- Per cell, k ∈ {5, 20}: expectancy net of 0/10/25 bps, hit rate, average win / average
  loss, skew; trades per year × cost next to every gross number.
- Portfolio of non-overlapping holds, net 10 bps: annual return, Sharpe, max drawdown;
  same for B4 and the random-k basket (median over 20 draws), and for the market,
  which in this readout *is* charged 10 bps (unlike the verdict): its annual return
  there carries a cost drag of (252 / H) × 10 bps a year that the verdict's market
  doesn't. The verdict's comparison is D_H, not this table. The low-vol basket enters through its
  pooled control above.
- D_H per test year and per cell (a pass carried by one or two cells is said to be).
- Picks' mean ATR / close, per side; the model's and B4's daily overlap; and, if the
  feature cache read at closing carries `days_to_earnings_expected`, the share of
  picks with an expected earnings date inside H (none of the 24 columns needs it).
- Effective N: the pooled D_H reports its distinct decision dates (its unit is one
  value per date); date blocks are those dates over 2H. The per-cell readouts give
  trade counts next to their dates.

Sector mix was in the draft but isn't computed by the closing code; it is left out
rather than added after the look.

### Known confounds

- **Few blocks at H = 63.** About 4.7 years at 126-date blocks is ~9 blocks; the 99%
  interval's coverage was checked at ~16–18 blocks (F1–F3 shared rules), not 9. See the
  prerequisite below. H = 21 has ~28 blocks.
- **One regime sequence:** the 2022 bear market, the 2023–24 rally led by a few large
  names. An equal-weight market basket lagged the cap-weighted index in that rally;
  D_H is against equal-weight, by design (same universe, same weights as the picks).
- **Survivorship after 2021:** delistings in 2022+ must be in the bars with terminal
  returns (prerequisite below).
- **Sector** is current-state, as in every dev run.
- **The dev window was searched.** The column set was chosen from ~10 scorecard looks
  on 2014–2021; this test is the first that isn't on those years.

### Before the holdout is opened (prerequisites, each its own step)

1. **Freeze checks:** done (Done #183), Model filled in above.
2. **Holdout scorecard code:** done (Done #179): test years past 2021 behind
   `open_holdout=True` (logged), the market-net-of-cost D_H verdict, the low-volatility
   basket, the years rule, seeds averaged.
3. **Cache builders' `--open-holdout`**, so features and labels can be built past 2021
   only by an explicit flag recorded in their manifests.
4. **Noise check at the holdout's block count:** the within-date-shuffle check of the
   shared rules rerun with 5 dev test years, so the 99% interval's coverage at ~9 blocks
   is known before the verdict leans on it. If it under-covers badly, the interval
   level for H = 63 is fixed in a dated addendum here, before opening.
5. **Data refresh** (writes to the shared DB, with the user's go-ahead): `total_return`
   bars re-fetched in full; `traded` bars incremental (done 2026-11-07, 37 tickers
   refused and unextended: those must be resolved or listed as missing).
6. **Holdout coverage, checked without reading returns:** point-in-time S&P 500
   membership through the test window; every 2022+ delisted member has bars to its last
   day.
7. **Caches rebuilt through the test window** (features, labels), `open_holdout=True`
   recorded in their manifests; `vendor-check` same-ticker gate on the frozen columns.

### Outcomes

- **Pass:** the model is a candidate to trade, starting with paper trading on new
  dates. Read next to the controls: if it also beats the low-vol basket and B4, the
  combined model is the edge; if not, the simpler rule that matches it is what gets
  paper-traded, and the model is the explanation.
- **Inconclusive:** underpowered, not "no edge". No retest on the same holdout. The
  model is paper-traded forward and judged on the new dates by this same rule, with the
  date fixed in an addendum before it starts.
- **Dead:** the model's edge doesn't cover its cost out of sample. Written up as a
  demonstrated null at this band; the dev-window results stay exploration.
- **Negative effect:** as dead, and the dev-window gain is looked into as overfitting
  to 2014–2021 first.
- **Logging:** every cell's `TRIALS.csv` row; the result as a dated addendum below;
  done.md.
