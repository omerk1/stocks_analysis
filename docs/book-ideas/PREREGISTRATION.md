# Book ideas: pre-registrations

Confirmation tests that come out of `TASKS.md` in this folder, each written and committed
**before** it runs. It follows the discipline of `docs/modeling/PREREGISTRATION.md` and
`docs/fundamentals/PREREGISTRATION.md`: once an entry has run, its text is frozen, and a
result or a change of scope is a new dated addendum below it, never an edit. Every run
is logged whatever it finds: scorecard cells in `docs/modeling/TRIALS.csv`, the verdict
in a result addendum here.

---

## Earnings and margin acceleration inputs (registered 2026-11-24)

- **Promoted from:** `TASKS.md`, "5. Earnings and margin acceleration inputs", built
  from `IDEAS.md` rows 5, 10, 19, 21, 25, 27 and 38 (accelerating sales and earnings,
  several quarters in a row; earnings growth coming from revenue rather than cost
  cutting; turnarounds back near their old earnings peak; recent growth against
  longer-term growth; net margin over time).
- **Why this test:** the company-financials group has revenue acceleration but none of
  these. Like any input, they are judged by the modeling goal: does the combined model
  pick better trades with them than without them, after costs
  (`docs/modeling/VALIDATION_HARNESS.md` §9).
- **What is new here:** none of the six inputs below exists yet. Nothing has been
  fitted, scored or plotted against returns with them. This entry was written after
  counting how many quarters have the data they need (under **Power**), not after
  looking at any return.
- **Steps, each its own PR:**
  1. this entry (no code);
  2. build: the six inputs in `src/models/features/fundamentals.py`, registered, the
     leakage gate passing, the feature cache rebuilt, and this entry's executable copy
     in `src/models/trading.py` (`PREREGISTERED["earnings_accel"]`, column lists
     written literally, with a test pinning them);
  3. run, close, and a result addendum here.

  If the build changes anything written here (a definition that can't be built as
  stated, a coverage surprise), it is a dated addendum below, before the run.

### Shared rules

The shared rules of `docs/fundamentals/PREREGISTRATION.md` ("Shared rules") apply as
written there, with these settings:

- **Window:** development only. Bars, labels and features end on 2021-12-31; a trade
  whose window reaches past it is dropped, never truncated. The holdout stays locked;
  this test never reads a date after 2021-12-31.
- **Universe:** the point-in-time S&P 500 of the modeling caches
  (`dataset.universe_mask`: $20M dollar-volume floor, history-break rules). Delisted
  members and their terminal returns stay in.
- **Entry and lag:** a decision at the close of day t trades at the open of t+1. Every
  input is as known at the close of t.
- **Ties in the top-k:** broken by the (ticker, date) hash (`metrics.tie_key`).
- **Three verdicts,** against the band below:
  - **dead:** the whole interval sits inside the band, so an effect big enough to
    matter is ruled out;
  - **inconclusive:** the interval spans zero and reaches past the band. That means
    underpowered, never "no effect";
  - **effect:** the interval excludes zero, sign named. A point estimate inside the
    band is reported as "real but too small to trade".
- **Relevance band: ±10 bps per trade,** one realistic round trip for an S&P 500 name,
  as in every earlier scorecard question.
- **Interval:** the date-block bootstrap's 99% interval (circular blocks of 2H trading
  dates), **10,000 draws**. The 99% level because the noise check behind the shared
  rules found it behaves like a ~98% interval at ~18 blocks (the safe direction).
  10,000 draws because the company-financials result found 1,000 leave the 99% ends
  resting on ~5 tail draws, and said later entries should use 10,000
  (`docs/fundamentals/PREREGISTRATION.md`, "Result (2026-10-17 addendum)").
- **Effective N:** distinct test dates, next to every row count.
- **Costs:** 10 bps round trip is the headline, 0 and 25 bps beside it; trades per year
  × cost next to every number that implies trading.
- **Shape, descriptive only:** hit rate, average win over average loss and skew next to
  every mean. No interval, no verdict on them.

### Hypothesis

Adding the six inputs below to the combined model raises the realized per-trade return
of its daily top-20 picks (ranked by EV in ATR units, `rank="ev_atr"`), compared with
the same model without them, on the same dates.

### The new inputs

Every input is computed on the quarters `fundamentals.py` already uses, under the same
rules (`docs/fundamentals/plan.md`, "3. Features", "How point-in-time is enforced"):

- **Quarters:** one row per (ticker, quarter end), net income and revenue as first
  reported (`_quarters`). A late report of an old quarter is dropped before anything is
  computed (`_in_order`), so it can't change, after the fact, which quarter counted as
  "a year earlier" or which quarters filled a window.
- **A year earlier:** the quarter whose end is 365 ± 15 days before (`_year_ago`).
  **The previous quarter:** the one ending 80–100 days before (`QUARTER_GAP`). A
  missing quarter in between makes the value NaN, never a longer gap.
- **When a value counts:** from the latest `available_date` of *every* value it reads
  (this quarter, the year-ago ones, every quarter of a window), and only once the
  quarter's own value is known. That date is the value's `known_at`.
- **Stale:** NaN once the quarter ended more than 200 days before t (`MAX_AGE_DAYS`).
- **Undefined stays NaN:** a value whose inputs are missing, or fail a condition below,
  is NaN, never 0 or False. The build adds a test that each input is NaN across its
  inputs' undefined region, not only correct elsewhere (`CLAUDE.md`, invariant 9).

Two intermediate values, not model inputs themselves:

- **net income growth,** `g_ni(q)` = NI(q) / NI(q−4) − 1, only when both net incomes
  are positive. A ratio with a loss in either quarter has no meaning (a loss shrinking
  from −10 to −1 would read as −90%), so those quarters are NaN here; the turnaround
  input below covers them.
- **revenue growth,** `g_rev(q)`: the existing `rev_growth_yoy` (same revenue tag or
  two total-revenue tags, both positive).

The six inputs. "Ranked" ones enter the model as their per-date rank across the
universe (`registry.model_input`, column `<name>_rank`); the count enters raw.

| Column | Formula | Model input |
|---|---|---|
| `ni_growth_accel` | g_ni(q) − g_ni(q−1): whether earnings growth is speeding up, the net-income twin of `rev_growth_accel`. Both growths defined, q−1 the previous quarter | ranked |
| `net_margin_change_yoy` | NI(q)/REV(q) − NI(q−4)/REV(q−4): this quarter's net margin against the same quarter a year earlier. Both revenues positive and of the same tag family (`rev_growth_yoy`'s rule). Single quarters, not trailing four, so the change shows the quarter it happens in; comparing the same quarter a year apart takes out seasonality | ranked |
| `rev_accel_streak` | how many of the last 3 quarters (q, q−1, q−2) have `rev_growth_accel` > 0: 0–3. The three must be consecutive quarters and all three accelerations defined, else NaN (a partial count would read "not accelerating" where it means "unknown") | raw, 0–3 |
| `ni_minus_rev_growth` | g_ni(q) − g_rev(q), both defined. High means earnings grew faster than sales: margin expansion, often cost cutting; near zero or negative means the earnings growth is carried by sales | ranked |
| `ni_ttm_vs_peak` | (NI_ttm(q) − P(q)) / REV_ttm(q), where NI_ttm and REV_ttm are the trailing four quarters as in `net_margin_ttm` (four consecutive quarters, first-to-fourth span 250–300 days, both concepts present) and P(q) is the highest NI_ttm among the earlier quarters ending in the 1,100 days before q (about 3 years), at least 8 of them defined. REV_ttm(q) > 0. Positive: trailing earnings at a new 3-year high, by that many points of revenue; negative: how far below its old peak. Scaling by revenue, not by the peak, keeps it defined when the old peak was a loss | ranked |
| `ni_growth_recent_vs_3y` | mean(g_ni(q), g_ni(q−1)) − [(NI_ttm(q) / NI_ttm(q−12))^(1/3) − 1]: the last two quarters' growth against the annual growth rate over three years. q−1 the previous quarter; q−12 the quarter ending 1,095 ± 15 days before q; both trailing net incomes positive | ranked |

- **Group and prior:** registered in group `fundamentals`, prior null (untested here),
  as the existing eleven.
- **Not built:** analyst estimates, guidance (out of scope in `TASKS.md`); EPS (net
  income instead, for the reasons in `plan.md`, "3. Features": as-filed EPS needs split
  and scale cleaning); five-year growth (the XBRL quarters start in 2009, so it would
  exist only from 2014–15).
- **Two inputs overlap by construction:** (1 + g_ni) / (1 + g_rev) is this quarter's
  margin over the year-ago one, so `ni_minus_rev_growth` and `net_margin_change_yoy`
  move together, and both relate to the existing `net_margin_ttm`. Both are kept because
  the task names both; the learner gets all of them, and no ablation inside the six is
  run (see **Readouts**).

**Leakage gate (build step, before the run):** the registry's gate with the
`future_filings` perturbation passes on synthetic data (3 seeds) and on the 20 real
tickers, as for the existing columns. The build also plants one leak specific to the
new multi-quarter windows and checks the gate catches it: a late report of a quarter
inside the 3-year peak window, or inside the streak's three quarters, changing the value
on a date before that report.

### Models

- **Reference (the control):** the frozen combined model's 24 columns
  (`docs/modeling/PREREGISTRATION.md`, the holdout trading test's "Model": the 5
  baseline columns, 11 moving-average columns and 8 per-name indicator columns) plus
  the 11 existing company-financials inputs (`trading.FUNDAMENTALS_COLUMNS`): 35
  columns.
  - The frozen model is the current combined model. The company-financials group came
    out inconclusive and stays registered, not dropped
    (`docs/fundamentals/PREREGISTRATION.md`, "Result (2026-10-17 addendum)"), so the
    six new inputs are judged as additions to it.
  - It is the matched control because the six inputs are the only difference: the same
    learner, folds, seeds, rows and ranking, refitted in the same run. Momentum
    (`mom_12_1_rank`, `mom_1_0_rank`) and the existing revenue acceleration, margin and
    earnings surprise are on both sides, so a gain has to come from what the six add.
- **Model:** the reference + `ni_growth_accel_rank`, `net_margin_change_yoy_rank`,
  `rev_accel_streak`, `ni_minus_rev_growth_rank`, `ni_ttm_vs_peak_rank`,
  `ni_growth_recent_vs_3y_rank`: 41 columns. Missing values stay NaN; the boosting
  learner routes them.
- Both lists are written literally into the code at the build step.

### Scope

- **Cells:** the 9 v1 barrier cells (U ∈ {2, 3, 4} × D ∈ {1, 1.5, 2}, scaled by
  √(H/21)) at H = 21 and H = 63.
- **Learner:** v1 `BoostingConfig`, fixed, no tuning. Isotonic calibration on 2 inner
  folds.
- **Seeds 0, 1, 2, averaged** before ranking (the probability average, as in the
  holdout test). That replaces the single seed and seed rerun of the company-financials
  test: there, the effect was a few bps and seed variance was an unmeasured caveat.
  The cost is three fits per side per fold; expect roughly 15–20 hours for the 18
  cells (the holdout test's 18 averaged ~1 hour each), runnable one horizon per night.
- **Folds:** expanding walk-forward, test years 2014–2021, first training window from
  2011-01-01, label windows purged.
- **Picks:** each test date's top 20 by EV in ATR units, per model. Top-5 is reported,
  never a verdict.
- **Data:** the label cache `data/models/labels/sp500`; a feature cache rebuilt at the
  build step from the commit that adds the inputs (its path and commit written in the
  build PR and in a dated addendum here, before the run).

### Primary metric and kill criterion

- **Per horizon:** D_H = the date-weighted mean over test dates of model minus reference
  top-20 basket return, averaged over the 9 cells on each date. A date enters only if
  all 9 cells have it; the count left out is printed.
  - It is gross and net at once: both sides trade 20 names a day, so the cost cancels.
  - Its interval is the date-block bootstrap of that per-date series, so the 9 cells
    share their blocks and aren't 9 independent looks.
- **Band:** ±10 bps per trade.
- **Verdict per horizon** on the 99% interval of D_H:
  - **dead** if it sits inside [−0.10%, +0.10%];
  - **inconclusive** if it spans zero and reaches past the band;
  - **effect** if it excludes zero, sign named.
- **A missing cell:** a horizon with a cell that has no usable trial (not run, failed,
  or its first `ok` row from a dirty checkout, which voids it) is inconclusive.
- **The six inputs join the combined model only if,** at at least one horizon:
  - the effect is positive under Holm over the two horizons, one-sided at 0.005 (the
    99% interval's level): the smaller one-sided bootstrap p at most 0.0025, the other
    horizon then at most 0.005;
  - the point estimate is at least +10 bps;
  - the point estimate is positive in both eras (2014–17 and 2018–21).

  Seeds are averaged inside the run, so there is no seed rerun after it.
- **Overall verdict:** dead if both horizons are dead; a positive or negative effect if
  one or both show one of that sign; mixed if they show effects of opposite signs;
  inconclusive otherwise (`trading.group_verdict`). A positive effect that fails the
  entry rule is reported as "positive effect, entry rule not met".

### Power

What the interval is likely to look like, from the nearest earlier run: the
company-financials scorecard, same universe, cells, folds and dates
(`docs/fundamentals/PREREGISTRATION.md`, "Result (2026-10-17 addendum)").

- **Effective N:** 2,001 test dates (2014–2021). At blocks of 2H dates that is ~48
  blocks at H = 21 and ~16 at H = 63.
- **That run's 99% interval half-widths:** about ±7 bps at H = 21 ([−0.041%, +0.102%])
  and about ±14 bps at H = 63 ([−0.208%, +0.080%]). The implied standard errors are
  ~2.8 and ~5.6 bps.
- **This run should be a little narrower:** three seeds instead of one take out some
  fit noise, and six added inputs should change fewer picks than eleven did (that run's
  models shared 42% of their top-20 at H = 21, 55% at H = 63; the more picks the two
  sides share, the smaller the per-date difference's spread). How much narrower isn't
  known before the run; the estimates below take that run's widths as the upper end.
- **Against the ±10 bps band:**
  - **H = 21:** a half-width of ~5–7 bps fits inside the band, so a **dead** verdict is
    reachable: it needs a point estimate within roughly ±3–5 bps of zero. To show an
    effect, the point estimate needs to be ~6–7 bps or more; to meet the entry rule,
    +10 bps. The smallest effect found 80% of the time at this level is about
    (2.58 + 0.84) × 2.8 ≈ 10 bps: a true +10 bps gain would show as an effect about
    80% of the time, a little less under Holm's first cut (p ≤ 0.0025).
  - **H = 63:** a half-width of ~11–14 bps is about the band itself, so **dead is
    nearly out of reach** (it would need both a near-zero estimate and a narrower
    interval than expected). The smallest effect found 80% of the time is ~19 bps.
    Anything smaller most likely comes out **inconclusive** here.
- **So, up front:** the likely outcomes are dead or inconclusive at H = 21 and
  inconclusive at H = 63, unless the gain is at least ~10 bps (H = 21) or ~19 bps
  (H = 63). An inconclusive H = 63 is expected, and says nothing either way.

**Coverage the inputs can reach** (counted from the `fundamentals` table, quarters
ending and filed by 2021-12-31, every ticker in it, ~690 a year; no returns read):

- a year-ago net-income pair exists for 95–99% of quarters from 2012;
- both net incomes are positive, so g_ni is defined, for 81–84% of quarters in
  2012–2015, 76–81% in 2016–2019, 71–72% in 2020–2021 (pandemic losses). The two
  growth-based inputs that need two such quarters will be a little lower;
- 15 earlier quarters, needed by the 3-year inputs, exist for 10% of quarters in 2012,
  57% in 2013 and 86–93% from 2014. So `ni_ttm_vs_peak` and `ni_growth_recent_vs_3y`
  are thin in the first training years (2011–2013) and near full in the test years.

These are quarter counts, not S&P member rows per day; the build reports coverage on
member rows by year, as the existing columns did.

### Readouts (descriptive, never a verdict)

- **Per cell, k ∈ {5, 20}:** each strategy's expectancy net of 0/10/25 bps, R/R
  (average win over average loss), win rate and skew; model minus reference and minus
  the market, with 99% intervals. These are 36 uncorrected looks, labelled as such.
- **Portfolio:** non-overlapping holds net of 10 bps: annual return, Sharpe, drawdown;
  the model against the random-k and market baskets.
- **Per era and per year:** D_H.
- **Controls `close-scorecard` reports beside the verdict:** the model against the
  market basket and against the low-volatility basket, same pooled readout, no verdict.
- **Costs:** ~5,000 signal trades a year per side (20 × 252), so ~5.0 percentage points
  a year of turnover cost at 10 bps in the overlapping signal stream, the same for both
  sides.
- **Without the six market-cap-defect tickers** (EBAY, NI, YUM, HPE, MA, CMCSA): D_H
  re-read from the archived predictions, no refit. The new inputs read no market cap,
  but the reference's valuation columns do; if the verdict changes, it is said to hinge
  on them.
- **Diagnostics:** the two models' daily top-20 overlap; how often each side's picks
  have each new input filled; the share of picks with an expected earnings date inside
  the horizon, per side.
- **No ablation inside the six** is run or reported as a verdict.

### Neighbours checked

- The 9 cells are each other's neighbours, and the two horizons and top-5 are reported
  beside them. D_H's sign per cell is reported; a verdict carried by one or two cells,
  or a sign that flips across cells, k or horizons, is reported as a lone pixel, not a
  result.
- **Definition variants are not run:** trailing-four-quarter margin change instead of
  single quarters, a 4-quarter streak, a revenue version of recent-vs-3-year growth, a
  5-year peak window. A look at any of them later is its own entry, counted as a new
  test, not a rescue of this one.

### Known confounds

- **The test years are not fresh.** 2014–2021 has been scored many times (the
  scorecards before the freeze, the company-financials test). The six inputs have
  never been scored.
- **Missingness carries information.** Four of the six are NaN when a year-ago or
  current quarter is a loss, so "is NaN" partly means "had a loss". That is known at t,
  so it isn't leakage, but a gain could come from the learner routing NaN rather than
  from the values. The fill-rate diagnostic shows how much of each side's picks this
  touches.
- **The inputs arrive late.** The XBRL values count from the 10-Q/10-K, a median of
  6 calendar days after the earnings reaction (90th percentile 26), so the price may
  already have moved.
- **Overlap with existing columns:** margin change, earnings-vs-sales growth and the
  existing margin, revenue acceleration and earnings surprise are related. The test
  asks what the six add to all of those, so overlap makes a gain harder to show, not
  easier.
- **Survivorship:** 101 delisted members are still missing (backlog: EODHD).
- **Sector** is current-state. **One bull market,** long only.

### Outcomes

- **Positive effect that meets the entry rule:** the six join the combined model's
  column set for the next version's pre-registered test.
- **Inconclusive:** they stay registered and aren't dropped; logged as underpowered. A
  null prior doesn't exclude a feature (`docs/modeling/IDEAS.md` §2).
- **Dead:** left out of the next scorecard runs, written up as a demonstrated null at
  this band.
- **Negative effect:** left out; overfitting through NaN routing is the first suspect.
- **Logging:** the 18 cells' rows in `docs/modeling/TRIALS.csv`, a result addendum
  here, a `docs/done.md` entry.

### How it runs

- **Registration in code (build step):** `trading.PREREGISTERED["earnings_accel"]`, a
  `Scorecard` with `experiment_id="earnings_accel"`, the 41 model and 35 reference
  columns literal, `horizons=(21, 63)`, `seeds=(0, 1, 2)`, `rank="ev_atr"`, `ci=0.99`,
  `n_boot=10_000`, `track="B"`, `band=0.001`, `verdict_k=20`, verdict against the
  reference at 0 bps (the defaults), eras 2014–17 and 2018–21 (the default),
  `open_holdout` False. The id `earnings_accel` has no rows in `TRIALS.csv` today;
  `trading.check_run` refuses to log under it with any other columns, seeds or
  settings.
- **Run** (the project venv, from the repo root):

  ```bash
  /Users/omerkoren/dev/stocks_analysis/venv/bin/python -m src.models.cli run-scorecard \
      --preregistered earnings_accel --features <the rebuilt cache> --labels data/models/labels/sp500
  ```

  optionally split as `--horizons 21` one night and `--horizons 63` the next.
- **Trial ids:** `trial_log` assigns each cell's id itself when its row is written,
  `<UTC date>-<time>-<git sha>-<6 random hex>` (e.g. `20261117-194920-e985e71-84dafa`),
  one row per cell, 18 in all, under experiment id `earnings_accel`. The registered
  trial for a cell is its first `ok` row with this design (`trading.registered_trial`);
  a first row from a dirty checkout voids that cell, and a later row never replaces it.
  So the run is made from a clean checkout of the build commit. No rows are added now.
- **Close:**

  ```bash
  /Users/omerkoren/dev/stocks_analysis/venv/bin/python -m src.models.cli close-scorecard \
      earnings_accel --features <the rebuilt cache> --labels data/models/labels/sp500
  ```

  and once more with `--exclude-tickers EBAY NI YUM HPE MA CMCSA` for the readout above.
  The verdict is the first close, at the registered 10,000 draws.
