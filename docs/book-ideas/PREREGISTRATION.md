# Book ideas: pre-registrations

The confirmation tests from `docs/book-ideas/TASKS.md`, each written and committed
**before** it runs. Same discipline as `docs/modeling/PREREGISTRATION.md` and
`docs/fundamentals/PREREGISTRATION.md`: once an entry has run, its text is frozen. A
result, a correction or a change of scope is a new dated addendum below it, never an
edit. Every run is logged whatever it finds: scorecard runs in `docs/modeling/TRIALS.csv`,
the result in an addendum here.

---

## Drawdown compared with the market (registered 2026-11-24)

- **From:** `docs/book-ideas/TASKS.md`, "6. Drawdown compared with the market" (ideas
  11, 29, 43, 45, 50, 52, 56 in `docs/book-ideas/IDEAS.md`).
- **Why this test:** the book's leaders are the stocks that fall least while the market
  falls and are first back to new highs. Plain distance from the 52-week high was
  inconclusive in the moving-average study and largely explained by momentum
  (`docs/modeling/IDEAS.md`, "Recurring confounds"). Measuring a stock's drawdown
  against the market's over the same span is a different question, mostly about down
  markets. As everywhere in the modeling track, the inputs are judged by whether the
  combined model picks better trades with them than without them
  (`docs/modeling/VALIDATION_HARNESS.md` §9).
- **Status at registration:** nothing built, fitted or scored. The two inputs below
  don't exist in code yet. The only data read for this entry was SPY's closes and the
  universe's closes up to 2021-12-31, to count dates and rows for the power note; no
  forward return or label was looked at.

### Shared rules

- **Window:** development only. Features from 2010 (for the 252-day warmup), test years
  2014–2021. Bars, labels and features end on 2021-12-31; a trade whose window reaches
  past it is dropped, never truncated. The holdout stays locked.
- **Universe:** the point-in-time S&P 500 of the modeling caches
  (`dataset.universe_mask`: $20M dollar-volume floor, history-break rules). Delisted
  members read from Tiingo stay in, with their terminal returns.
- **Entry and lag:** a decision at the close of day t trades at the open of t+1 (the
  barrier labels' rule). Both inputs use only closes up to and including t.
- **Ties in the top-k:** broken by `metrics.tie_key` (hash of ticker and date), as in
  every scorecard since the company-financials test.
- **Three verdicts,** against the band below:
  - **dead:** the whole interval sits inside the band. An effect big enough to matter is
    ruled out.
  - **inconclusive:** the interval spans zero and reaches past the band. Underpowered,
    never "no effect".
  - **effect:** the interval excludes zero; the sign says which way. An effect whose
    point estimate is inside the band is reported as "real but too small to trade".
- **Relevance band: ±10 bps per trade,** the scorecard's usual band: one realistic
  round trip for an S&P 500 name.
- **Interval:** the date-block bootstrap's 99% interval (`inference.bootstrap_ratio`,
  circular blocks of 2H trading dates), **10,000 draws**. The noise check behind the 99%
  level is the one cited in `docs/fundamentals/PREREGISTRATION.md`, "Shared rules"
  (the 99% interval behaves like a ~98% one at this block count); the 10,000 draws follow
  that file's company-financials result addendum, which asks for them on every 99%
  interval registered after it.
- **Effective N:** distinct decision dates, next to every row count.
- **Costs:** 10 bps round trip is the headline, with 0 and 25 bps beside it. Every
  readout that implies trading carries trades per year × cost.
- **Descriptive, never a verdict:** hit rate, average win over average loss and skew
  next to every mean; per era (2014–17, 2018–21) and per year. No interval on these,
  nothing killed on them.
- **Environment:** the project venv (`/Users/omerkoren/dev/stocks_analysis/venv`),
  where every reference-model fit since 2026-10-31 was made. Both sides are fitted in
  the same run, so they share one environment by construction.

### The new inputs (defined here, built in the build PR)

Both are per-name, per-date columns on the total-return basis the other model features
use (`baseline.FEATURE_BASIS`), computed from closes up to day t. Registry group
`drawdown`, shape `dense`, prior **null** (untested here), warmup 252 bars.

1. **`drawdown_vs_spy`** — the stock's drawdown divided by SPY's, over the same trailing
   252 trading days.
   - `dd_stock(t) = close(t) / max(close over the stock's last 252 bars, t included) − 1`.
     This is exactly `context.dist_from_52w_high` (`src/signals/moving_averages/features/context.py`),
     so it is ≤ 0, and NaN until the stock has 252 bars.
   - `dd_spy(t)` = the same for SPY's close on date t (`market.BENCHMARK`).
   - `drawdown_vs_spy(t) = dd_stock(t) / dd_spy(t)` when `dd_spy(t) ≤ −0.02`.
   - **NaN** when SPY is within 2% of its 52-week high (`dd_spy(t) > −0.02`), where
     the ratio is meaningless, and wherever either drawdown is NaN. Missing values stay
     NaN; the boosting learner routes them.
   - Reading it: 0 = the stock is at its own 52-week high; 1 = it is as far off its
     high as the market is off its own; above 1 = it fell more than the market. Bounded
     above by 50 (a −100% stock over a −2% market); not clipped.
   - **Entered raw, not as a per-date rank.** On any one date `dd_spy` is the same for
     every name, so a per-date rank of the ratio would equal the per-date rank of plain
     distance from the 52-week high: the measure already found inconclusive. Raw, the
     model can compare names across dates ("fell less than half as much as the market").
2. **`drawdown_over_60`** — 1.0 when `dd_stock(t) < −0.60`, 0.0 when
   `dd_stock(t) ≥ −0.60`, **NaN where `dd_stock` is NaN** (the 252-bar warmup). A
   comparison returns False on NaN, so the build masks it explicitly and a test asserts
   NaN across the warmup (repo rule: derived features keep their inputs' missingness).
   It does not depend on SPY.

The build PR adds both to `src/models/features/registry.py`, computes them in the
`market` panel source (it already reads SPY's bars), and passes the leakage gate
(`run-gates --smoke-db`) and the vendor check (`vendor-check --scorecard rel_drawdown`).
A test pins both definitions on a hand-made series: the 2% floor at exactly −0.02, the
60% edge at exactly −0.60, and NaN in both warmups.

### Hypothesis

Adding `drawdown_vs_spy` and `drawdown_over_60` to the frozen combined model raises the
realized per-trade return of its daily top-20 picks, ranked by EV in ATR units
(`rank="ev_atr"`), against the same model without them, on the same dates.

### Models

- **Reference (the control):** the frozen combined model's 24 columns
  (`COLUMN_SETS["S2_no_market"]`: the moving-average family, B4's momentum and
  volatility columns, and the 8 per-name indicator columns; see
  `docs/modeling/VALIDATION_HARNESS.md` §9, "Freeze checks"). It is the matched control
  because the only difference is the two inputs: same learner, folds, seed, rows and
  ranking. It already carries 12-1 and 1-0 momentum, realized volatility, distance from
  the 50-day average and from the 52-week low, so the momentum control the task's rules
  ask for is inside the reference.
- **Model:** the reference + `drawdown_vs_spy` + `drawdown_over_60`, 26 columns.
- Both column lists are written literally into the scorecard's registration, as HT1's
  are, so a later registry change can't move the test.

### Scope

- **Cells:** all 9 barrier cells (U ∈ {2, 3, 4} × D ∈ {1, 1.5, 2}, scaled by √(H/21))
  at H = 21 and H = 63: 18 trials.
- **Learner:** v1 `BoostingConfig`, fixed, no tuning; isotonic calibration on 2 inner
  folds.
- **Seed:** 0. If a horizon's verdict is an effect, it is rerun on seeds 1 and 2 before
  anything enters the model. A rerun can confirm an effect, never rescue an
  inconclusive one.
- **Folds:** expanding walk-forward, test years 2014–2021, first training window
  2011–2013, label windows purged.
- **Picks:** each test date's top 20 by EV in ATR units, per model. Top 5 is reported,
  never a verdict.

### How it runs

The build PR registers the scorecard in `src/models/trading.py`:

```python
"rel_drawdown": Scorecard(experiment_id="rel_drawdown",
                          model_columns=<the 24 frozen columns, literal> + ("drawdown_vs_spy", "drawdown_over_60"),
                          reference="S2_no_market", reference_columns=<the 24, literal>,
                          horizons=(21, 63), rank="ev_atr", ci=0.99, n_boot=10_000, track="B",
                          band=0.001, verdict_k=20),
```

Then, from a clean worktree, in the venv, with the shared caches read-only:

```bash
python -m src.models.cli build-features --db data/raw/market_data.sqlite \
    --out data/models/features/sp500_rel_drawdown --scorecard rel_drawdown
python -m src.models.cli vendor-check --db data/raw/market_data.sqlite \
    --features data/models/features/sp500_rel_drawdown --scorecard rel_drawdown
python -m src.models.cli run-scorecard --preregistered rel_drawdown \
    --features data/models/features/sp500_rel_drawdown --labels data/models/labels/sp500
python -m src.models.cli close-scorecard rel_drawdown \
    --features data/models/features/sp500_rel_drawdown --labels data/models/labels/sp500
```

- **Trial ids:** `run-scorecard` writes one `TRIALS.csv` row per cell under experiment
  id `rel_drawdown`; each row's `trial_id` is made by `trial_log.Trial`
  (`<UTC time>-<git sha>-<6 hex>`), not chosen by hand. The id is new, so
  `trial_log.check_environment` has no earlier rows to clash with. No row is added
  before the run.
- The feature cache is a new directory; nothing under `data/models/features/sp500*`
  that exists today is rebuilt or written. The label cache is the one the frozen model's
  dev runs used (`data/models/labels/sp500`, built 2026-10-07).
- **Reference check (reported, not a verdict):** the reference's predictions should
  match the archived `S2_no_market_v` predictions (seed 0, same venv) cell by cell. If
  they don't, the result still stands (both sides are fitted here), but the gap is
  reported, as the B4-equality checks were.

### Primary metric and kill criterion

- **Per horizon:** D_H = the date-weighted mean, over test dates, of model minus
  reference top-20 basket return, averaged over the 9 cells on each date. Gross: both
  sides trade 20 names a day, so the cost cancels. Its interval is the date-block
  bootstrap of that per-date series, so the cells share blocks and aren't 9
  independent looks.
- **Verdict per horizon** on D_H's 99% interval: **dead** inside [−0.10%, +0.10%];
  **inconclusive** if it spans zero and reaches past the band; **effect** if it excludes
  zero.
- **The inputs enter the combined model only if:**
  - at least one horizon shows a positive effect, with Holm's correction over the two
    horizons (one-sided bootstrap p at 0.005, the interval's own level);
  - its point estimate is at least +10 bps;
  - it is positive in both eras (2014–17 and 2018–21);
  - it survives the seed rerun.
- **Overall verdict:** dead if both horizons are dead; an effect (either sign) if either
  horizon shows one, per the rule above; inconclusive otherwise.

### Secondary readout: when the market is down (reported, never a verdict)

The idea should show up, if it's real, when the market is well off its high. So D_H is
also reported on the subset of test dates where **SPY's close is more than 10% below its
252-day high close at the decision date's close** (`dd_spy(t) < −0.10`), read from the
same archived predictions with no refit.

- **What it reports:** D_H on those dates with its number of dates and separate
  declines; D_H per decline (a decline = a run of such dates with no more than 10
  trading days between them); the same at top 5; hit rate, win/loss ratio, skew.
- **Also:** D_H on all dates where the ratio is defined (`dd_spy ≤ −0.02`) and on the
  dates where it is NaN (SPY within 2% of its high). On the NaN dates the two models
  differ only by the 60% flag and by how the learner routes the NaN, so a gain there
  isn't the market-relative idea.
- **No verdict on any of these.** The interval for the down-market subset is printed
  with a note that it rests on a handful of blocks (see Power) and is not interpretable
  as a test. A positive down-market number with an inconclusive or dead primary is
  reported as that, not as a finding.
- The readout's code (a date filter on `close-scorecard`'s per-date series, by the
  rule above) goes in the run PR and is committed before `close-scorecard` is run.

### Other readouts (descriptive)

- **Per cell, k ∈ {5, 20}:** each side's expectancy net of 0/10/25 bps, R/R, win rate,
  skew; model minus reference and minus the market. 36 uncorrected looks, labelled as
  such.
- **Per era and per year:** D_H.
- **Diagnostics:** the two models' top-20 overlap; the share of each side's picks with
  `drawdown_vs_spy` defined and with the 60% flag set.

### Neighbours checked

- The 9 cells are each other's neighbours, and the two horizons. D_H's sign is reported
  at every cell; a verdict carried by one or two cells is said to be.
- k = 5 against k = 20.
- **Not refit:** the 2% floor and the 60% threshold have no neighbouring settings in
  this run (each would be another 18 trials). If the primary comes out an effect, the
  seed rerun comes first; neighbouring thresholds (1% and 5%; 50% and 70%) would be a
  new dated addendum, not part of this verdict.

### Effective N

- **Primary:** 2,015 decision dates in 2014–2021 (SPY's trading days; the
  company-financials test scored 2,001 after its label-end drops), ~950,000 universe
  rows before the label-end drops.
- **Ratio defined:** SPY was at least 2% off its high on **746 of 2,015 test dates
  (37%)**; the ratio is NaN on the other 63%. About 353,000 rows have it defined.
- **Down-market subset:** SPY more than 10% off its high on **103 dates**, in 14 runs
  that are really four declines: Aug 2015–Feb 2016 (20 dates), Feb 2018 (1), Dec 2018–Jan
  2019 (22), Feb–Jun 2020 (62, the Covid crash, 60% of the subset). By year: 2015 4,
  2016 14, 2018 12, 2019 11, 2020 62; none in 2014, 2017, 2021. About 50,000 rows.
- **The 60% flag** is set on ~5,800 rows (0.6% of rows with a drawdown defined), 909
  dates, 113 names; 3,368 of the rows are in 2020.
- These counts read closes only (yfinance total-return bars, Tiingo for names yfinance
  lacks), not the universe mask, so the run's own counts will be slightly lower.

### Costs

Both sides trade 20 names a day, so D_H is the same gross or net. The headline readout
gives each side's top-20 net of 10 bps; ~5,000 signal trades a year (20 × 252), about
5.0 percentage points a year of turnover cost at 10 bps in the overlapping signal
stream, for both sides alike.

### Power

The closest earlier run is the company-financials scorecard (same design: one group
added to a reference, 9 cells, 2,001 dates, 99% interval;
`docs/fundamentals/PREREGISTRATION.md`, "Result (2026-10-17 addendum)"). At 10,000
draws its D_H intervals were 0.148 pp wide at H = 21 and 0.311 pp at H = 63.

| | expected half-width | band | what's possible |
|---|---|---|---|
| H = 21, all dates | ~±7 bps | ±10 bps | dead only if the point estimate is within ~±3 bps; an effect needs |D| above ~7 bps |
| H = 63, all dates | ~±15 bps | ±10 bps | **dead is impossible** (the interval is wider than the band); effect or inconclusive only |
| ratio-defined dates (746) | ~×1.6: ~±12 / ~±25 bps | | likely inconclusive at both |
| down-market dates (103) | ~×4.4: ~±30 / ~±65 bps, before the extra volatility of those dates | | 2–3 blocks at H = 21, under one at H = 63: no usable interval |

The half-widths scale the earlier run's by √(2,001 / dates), assuming the same per-date
spread, which down markets don't have (they're more volatile), so the subset rows are
optimistic. **Expect the primary at H = 63 to come out inconclusive unless the inputs
move the picks by more than ~15 bps a trade, and the down-market readout to be a
description only.** The inputs touch 37% of dates at most, so an effect concentrated
in down markets is diluted about threefold in the all-dates D_H.

### Known confounds

- **On any one date, the ratio orders names exactly as their plain drawdown does.**
  What's new against plain distance from the 52-week high is only the cross-date
  scaling by the market's drawdown. The reference has no 52-week-high column, so part of
  any gain could be plain drawdown, the measure already found inconclusive and
  momentum-explained. This test can't separate the two (see "For the owner" in the PR).
- **The NaN pattern is a market-wide signal.** The ratio is missing exactly when SPY is
  within 2% of its high, so the model also learns "the market is near its high" through
  the missingness. The market-wide columns made the picks worse in the indicators run
  (`docs/modeling/VALIDATION_HARNESS.md` §9, step 2b). The NaN-dates readout above
  shows how much of D_H comes from there.
- **Few declines.** Four, one of which (2020) is 60% of the down-market dates. One bull
  market otherwise, long only.
- **Survivorship:** 101 delisted members are still missing (backlog, EODHD). They are
  over-represented among the deepest drawdowns, so the 60% flag's rows are the most
  biased.
- **The test years are not fresh:** the frozen model's columns were scored on the same
  2014–2021 folds many times. The two new inputs never were.
- **Sector** is current-state (the reference's `sector` column).

### Outcomes

- **Positive effect that meets the entry rule:** the inputs join the combined model's
  column set for the next pre-registered test of the full feature set.
- **Inconclusive:** the inputs stay registered with a null prior and aren't dropped
  (`docs/modeling/IDEAS.md` §2); logged as underpowered.
- **Dead:** left out of the next scorecard runs; written up as a demonstrated null at
  this band.
- **Negative effect:** left out, and the reason looked for (the NaN routing's
  market-wide signal first).
