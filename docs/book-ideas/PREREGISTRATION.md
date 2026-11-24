# Book ideas: pre-registrations

The confirmation tests from `docs/book-ideas/TASKS.md`, each written and committed
**before** it runs. Same discipline as `docs/modeling/PREREGISTRATION.md` and
`docs/fundamentals/PREREGISTRATION.md`: once an entry has run, its text is frozen. A
result, a correction or a change of scope is a new dated addendum below it, never an
edit. Every run is logged whatever it finds: scorecard runs in `docs/modeling/TRIALS.csv`,
the result in an addendum here.

---

## The trend template as a filter on the model's picks (registered 2026-11-24)

- **From:** `docs/book-ideas/TASKS.md`, "9. The trend template as a filter on the
  model's picks" (idea 9 in `docs/book-ideas/IDEAS.md`; the book's p. 79).
- **Why this test:** the template is the book's main entry gate. The frozen combined
  model already sees most of its parts one by one (distance from the 52-week low, the
  50-day slope, the 200-day distance, 12-month momentum, a bearish moving-average
  stack), so the question is whether the hard combined rule, applied on top of the
  model's ranking, adds anything.
- **Not a rerun:** the moving-average study looked at the eight rules on every row of
  the universe, as an uncontrolled descriptive ablation
  (`docs/features/moving-averages/PREREGISTRATION.md`, "M2 — Stack states and
  Minervini ablation (2026-09-12)", part (b)). It never applied the template to a
  model's picks, which is the question here. That study also found no single
  moving-average lookback special, the 200-day included: a result here is about the
  combined rule, not about any one average.
- **Status at registration:** nothing built or run. No template flag has been put next
  to a pick or a return. The only data read for this entry is the pass-rate count in
  **Power** below (prices only, no forward returns).

### The template, exactly

All eight rules are read at the **close of day t**, from information up to that close,
like every model feature. The decision is at the close of t and the trade is at the open
of t + 1 (the barrier labels' rule), so the one-bar lag is the labels' own, as for the
model's columns. Prices are the model features' basis, total-return closes
(`price_basis.MODULE_PRICE_BASIS["models_features"]`), loaded as the feature cache
loads them (`baseline.read_bars_bulk`). "Day" means a trading day (a bar).

| # | Book's rule | Here |
|---|---|---|
| 1 | Price above the 150- and 200-day averages | close_t > SMA150_t and close_t > SMA200_t |
| 2 | The 150-day above the 200-day | SMA150_t > SMA200_t |
| 3 | The 200-day rising for at least a month | ln(SMA200_t) − ln(SMA200_{t−21}) > 0, i.e. `slope_log_k(SMA200, 21)`: the 200-day today above its value 21 bars ago |
| 4 | The 50-day above the 150- and 200-day | SMA50_t > SMA150_t and SMA50_t > SMA200_t |
| 5 | Price above the 50-day | close_t > SMA50_t |
| 6 | At least 30% above the 52-week low | close_t / min(close over the last 252 bars, t included) − 1 ≥ 0.30 (`context.dist_from_52w_low`, the model's own `dist_from_52w_low` column) |
| 7 | Within 25% of the 52-week high | close_t / max(close over the last 252 bars, t included) − 1 ≥ −0.25 (`context.dist_from_52w_high`) |
| 8 | High relative strength | `rs_rating` ≥ 70 |

- **Averages:** simple moving averages of the close (`ma.compute_ma(close, "sma", k)`),
  k = 50, 150, 200, each undefined until it has k bars.
- **The 52-week high and low** are of closes, not intraday highs and lows, as the
  model's `dist_from_52w_low` is. Undefined until 252 bars.
- **"Above" and "rising"** are strict, with the model features' float tolerance: a
  comparison or slope counts only when it clears `ma_family.TIE_TOLERANCE` × close
  (a slope, `TIE_TOLERANCE` itself), so a later split or dividend rescaling can't flip a
  tie (`ma_family.adx`'s docstring says why).
- **"High relative strength"** is this repo's IBD-style rating,
  `relative_strength.compute.compute_stock_vs_market(conn, "sp500",
  RelativeStrengthConfig())`'s `rs_rating`: the weighted return 0.4 × 63-day + 0.2 ×
  126-day + 0.2 × 189-day + 0.2 × 252-day (total-return closes), as a 0–100 percentile
  among that day's point-in-time S&P 500 members (`indicators.percentile_rank`). The
  book asks for 70 at least, preferably 80–90; 70 is the floor the book states and the
  one the moving-average study used (`stack_minervini.RS_RANK_FLOOR`). It is used as of
  the close of t, with no extra lag (the moving-average study lagged it because its
  whole panel is lagged by one bar; the model's features aren't).
- **Passing** means all eight hold. A row where any input is undefined (a name with
  fewer than 252 bars, no rating that day) **doesn't pass**: the book's gate can't be
  checked, and a gate that can't be checked doesn't let a name through. These rows are
  counted as their own group ("undefined") in every readout, and the neighbour below
  lets them through.
- **Reuse:** the rule columns come from the existing functions named above
  (`ma.compute_ma`, `slope.slope_log_k`, `context.dist_from_52w_*`,
  `compute_stock_vs_market`), not new copies. The moving-average study's own flags
  (`stack_minervini._add_trend_template_criteria`) can't be reused as they are: they
  read that study's lagged panel.

### Hypothesis

Taking the frozen model's daily top 20 from the names that pass the template only, with
the next-best passing names filling the places of those that fail, changes the realized
per-trade return of the top-20 basket. The sign isn't predicted: the template may keep
the model away from broken charts, or throw away the pullbacks the model ranks well.

### Setup

- **Predictions:** the frozen combined model (`trading.PREREGISTERED["HT1"]`'s 24
  columns, `COLUMN_SETS["S2_no_market"]`) on the development window, from its three
  archived runs: experiments `S2_no_market_v` (seed 0), `S2_no_market_v_seed1` and
  `S2_no_market_v_seed2` in `docs/modeling/TRIALS.csv`, 18 trials each (9 barrier
  cells × H = 21 and 63), all `ok` from clean checkouts. The three seeds' calibrated
  probabilities are averaged per row (`ablation.seed_mean`), as the model is run in
  the holdout test. **No new fit and no new `TRIALS.csv` rows:** like the earnings
  exclusion test (`docs/fundamentals/PREREGISTRATION.md`, F3), it re-reads archived
  predictions, and its result is logged as a dated addendum below.
  - **Why this model:** it is the model being paper-traded, so a filter on it is the
    filter that would be used. Its 2014–2021 predictions were scored before (the
    freeze checks), but never with the template.
  - **Trial ids, per cell** (the first `ok` row of each experiment, the rule
    `trading.registered_trial` applies):

    | H | U/D | seed 0 (`S2_no_market_v`) | seed 1 | seed 2 |
    |---|---|---|---|---|
    | 21 | 2/1 | `20261106-083215-683d224-9db4f4` | `20261107-123921-b315cad-805812` | `20261108-110852-b315cad-c87bd9` |
    | 21 | 2/1.5 | `20261106-084828-683d224-1cf78e` | `20261107-125253-b315cad-320b05` | `20261108-112227-b315cad-99d7df` |
    | 21 | 2/2 | `20261106-090437-683d224-096ee9` | `20261107-130635-b315cad-cb499b` | `20261108-113626-b315cad-5cc5e7` |
    | 21 | 3/1 | `20261106-091916-683d224-58e995` | `20261107-132031-b315cad-2b5d8a` | `20261108-115029-b315cad-ebac55` |
    | 21 | 3/1.5 | `20261106-093355-683d224-f6a20c` | `20261107-133419-b315cad-54dcfb` | `20261108-120429-b315cad-af1083` |
    | 21 | 3/2 | `20261106-094840-683d224-2ca0f2` | `20261107-134810-b315cad-15b748` | `20261108-121836-b315cad-45f02b` |
    | 21 | 4/1 | `20261106-100315-683d224-4c4648` | `20261107-140224-b315cad-022254` | `20261108-123246-b315cad-803956` |
    | 21 | 4/1.5 | `20261106-101736-683d224-899ad6` | `20261107-141808-b315cad-06ea8e` | `20261108-124653-b315cad-32f9e5` |
    | 21 | 4/2 | `20261106-103148-683d224-c72177` | `20261107-143156-b315cad-7ed90d` | `20261108-130102-b315cad-ce80ce` |
    | 63 | 2/1 | `20261106-104557-683d224-3ed369` | `20261107-144539-b315cad-4d218d` | `20261108-131519-b315cad-27b185` |
    | 63 | 2/1.5 | `20261106-105911-683d224-c4ba75` | `20261107-145828-b315cad-873053` | `20261108-132840-b315cad-056a72` |
    | 63 | 2/2 | `20261106-111238-683d224-5dc2a9` | `20261107-151128-b315cad-b00b24` | `20261108-134213-b315cad-4e5a2c` |
    | 63 | 3/1 | `20261106-112609-683d224-0e7e4b` | `20261107-152428-b315cad-2b6798` | `20261108-135556-b315cad-120283` |
    | 63 | 3/1.5 | `20261106-113938-683d224-34ec71` | `20261107-153730-b315cad-3a6932` | `20261108-141149-b315cad-e8eddf` |
    | 63 | 3/2 | `20261106-115314-683d224-42520a` | `20261107-155051-b315cad-c61435` | `20261108-142532-b315cad-ae0b90` |
    | 63 | 4/1 | `20261106-120651-683d224-efb4f4` | `20261107-160427-b315cad-965e18` | `20261108-143926-b315cad-7f123e` |
    | 63 | 4/1.5 | `20261106-122019-683d224-b07c51` | `20261107-161759-b315cad-70f49d` | `20261108-145306-b315cad-edc0a0` |
    | 63 | 4/2 | `20261106-123409-683d224-90412f` | `20261107-163133-b315cad-77c641` | `20261108-150653-b315cad-842386` |

  - **Caches:** the ones the trials were fitted on, the feature cache
    `data/models/features/sp500_levels` (built 2026-10-16T17:23) and the label cache
    `data/models/labels/sp500` (built 2026-10-07T19:20). The run checks both against
    the trials' logged build times and refuses on a mismatch, as `registered_trial`
    does.
- **Command:** a new script, `python -m src.analysis.trend_template_filter --db
  data/raw/market_data.sqlite --features data/models/features/sp500_levels`, built in
  the run's PR on the earnings exclusion test's pattern (`src/analysis/earnings_risk.py`):
  per cell, `trading.cell_picks(..., k=20)` unrestricted and again with
  `keep=` the template's pass mask, then `trading.pooled_readout`. It opens the
  market-data DB read-only and writes nothing but its report (and a JSON copy under
  `output/`). Before it runs on real data, it has tests: each rule on a small planted
  price series (including the undefined warmup and the tie tolerance), and a pick test
  showing failing names replaced by the next-best passing ones.
- **Window:** test years 2014–2021 (the dev scheme's expanding folds, first training
  window 2011–2013, label windows purged). Nothing after 2021-12-31 is read; the
  script refuses a cache that runs past it. The holdout stays locked.
- **Universe:** the point-in-time S&P 500 of the modeling caches
  (`dataset.universe_mask`: $20M dollar-volume floor, history-break rules), delisted
  members and their terminal returns kept. The rating is ranked among all that day's
  index members, before the dollar-volume floor.
- **Picks:** each test date's top 20 by EV in ATR units (`rank="ev_atr"`), ties broken
  by the (ticker, date) hash (`metrics.tie_key`).
  - **Filtered:** the top 20 among the rows that pass the template. If fewer than 20
    pass, the basket holds those that do (its mean is over fewer names). If none pass,
    the date has no filtered basket at that cell and drops out of D (below); the count
    is reported.
  - **Control (unrestricted):** the top 20 of every row, the same predictions, ranking
    and day. It is the matched control because only the filter differs.

### Primary metric and kill criterion

- **Per horizon:** D_H = the date-weighted mean, over test dates, of the filtered
  top-20 basket's return minus the unrestricted top-20's, averaged over the 9 cells on
  each date (`trading.pooled_difference`: a date counts only if every cell has it).
  Every return is the cell's label return: entry at the open of t + 1, exit at the
  target, the stop or the H-th bar.
  - **Gross equals net:** both sides are per-trade means and pay the same cost per
    trade, so the cost cancels in D. The baskets' own net returns are reported (below).
  - **CI:** the date-block bootstrap, blocks of 2H dates, **10,000 draws**, 99%
    interval, the cells sharing their blocks (the shared rules of
    `docs/fundamentals/PREREGISTRATION.md`, with its F2 addendum's 10,000 draws).
- **Band:** ±10 bps per trade, one realistic round trip for an S&P 500 name.
- **Verdict per horizon** (`trading.three_verdict`):
  - **dead** if the interval sits inside [−0.10%, +0.10%]: a gain or loss big enough
    to matter is ruled out;
  - **inconclusive** if it spans zero and reaches past the band: underpowered, never
    "no effect";
  - **effect** if it excludes zero: positive means filtering helps, negative means it
    hurts.
- **The template is proposed as a filter only if,** at at least one horizon:
  - the effect is positive under Holm over the two horizons (the smaller one-sided
    bootstrap p ≤ 0.0025, the other then at p ≤ 0.005);
  - its point estimate is at least +10 bps;
  - its point estimate is positive in both eras (2014–17 and 2018–21).
  The seeds are averaged inside the run, so there is no seed rerun after it.
- **Overall verdict** (`trading.group_verdict` over the two horizons): dead if both are
  dead; a positive or negative effect if one or both show one of that sign; mixed if
  they disagree; inconclusive otherwise.

### Named control: is it just momentum?

The template is largely a momentum screen: rules 6–8 are trailing returns, and rules
1–5 hold mostly in stocks that have gone up. The momentum and pattern looks before this
one were explained by momentum. So the same D is computed for a **momentum gate that
passes as many names as the template does**: on each date, of the rows the model could
pick, keep those whose `mom_12_1_rank` (the model's own 12-1 momentum rank) is in the top
p_t share, where p_t is the template's pass share among those rows that date. Fill the
top 20 the same way.

- Reported with its own 99% interval: D_H for the momentum gate, and **the template
  minus the momentum gate** (per date, filtered template basket minus filtered momentum
  basket, the same bootstrap).
- **Not part of the pass rule,** but it decides how a pass reads: if the template
  passes and template minus momentum gate excludes zero above it, the template adds
  something momentum doesn't. If template minus momentum gate spans zero, what passed is
  "a momentum gate", and the simpler rule is what gets proposed.

### Readouts (descriptive, never a verdict)

- **The share of picks the template removes** (the task's "done when" readout): per
  horizon, per cell, per year, as the share of the unrestricted top 20 that fail, and
  the number of names a date that pass among all pickable rows. Also the dates with
  fewer than 20 passing names and with none.
- **Which rules remove them:** among the unrestricted picks that fail, the share failing
  each rule, and the share failing only that rule. The undefined group's share.
- **The unrestricted picks split by pass / fail / undefined,** per horizon, pooled and
  per cell: share, expectancy net of 0, 10 and 25 bps, win rate, average win over
  average loss, skew, and target / stop / timeout rates.
- **The baskets' own results,** filtered, unrestricted and momentum gate: expectancy
  net of 10 bps, win rate, average win / average loss, skew; trades per year × cost
  next to every number that implies trading (20 names a day per cell, ~5,000 signal
  trades a year, ~5 percentage points a year of turnover cost at 10 bps in the
  overlapping signal stream, the same on both sides).
- **Per era and per year:** D_H.
- **Top-5:** the same D at k = 5, never a verdict.

### Neighbours

Each is D_H with its 99% interval, reported, not a verdict. A primary verdict whose sign
flips at the neighbours is reported as a lone pixel, not a result.
- **The rating floor:** `rs_rating` ≥ 60 and ≥ 80 (the book's "preferably 80s").
- **"Rising":** the 200-day rising over 105 bars instead of 21 (the book's "preferably
  4–5 months").
- **Undefined rows let through** instead of failing.
- **The 9 cells:** D_H's sign at each; a verdict carried by one or two cells is said to be.
- **Seed 0 alone** (`S2_no_market_v`'s predictions without averaging): a check that
  the seed average isn't what makes the result.

### Effective N

The unit is one value per decision date. D_H reports its distinct dates (about 2,000
over 2014–2021 at each horizon, minus dates with no passing name), and the bootstrap's
blocks are those dates over 2H: about 48 blocks at H = 21 and about 16 at H = 63. The
per-cell readouts give trade counts next to their dates.

### Power

The interval width is set by how many picks are swapped and how different the swapped
names' returns are, so the earlier swap tests give the scale:
- **Earnings exclusion** (`docs/fundamentals/PREREGISTRATION.md`, F3 result): about 5
  of 20 picks swapped a day, H = 21, 99% interval 0.178 percentage points wide
  (half-width ~9 bps).
- **Company-financials group** (F2 result): about 12 of 20 picks different a day at
  H = 21 (42% overlap), width 0.143 (half-width ~7 bps); about 9 at H = 63, width 0.288
  (half-width ~14 bps).

**How many picks the template would swap.** Counted for this entry from closes only
(no forward returns), on the moving-average study's panel (405 S&P 500 tickers,
2014–2021, ~350 names a day) with the rating from `compute_stock_vs_market`:
- rules 1–7 hold on 29% of rows; all eight on **20%** (RS ≥ 60: 24%; RS ≥ 80: 15%).
  72% of the rows passing rules 1–7 also have RS ≥ 70, so the rating is mostly
  redundant with the rest;
- a median of 77 names a day pass; 107 of 2,015 dates have fewer than 20, none has
  zero (the model's universe is wider, ~470 names, so it should have more).

If the model's picks passed at the universe's rate, about 16 of 20 would be swapped a
day. The model's picks may pass more often than that (EV in ATRs leans to calm,
trending names) or less (it likes pullbacks); the run reports the real share.

**Expected interval.** Scaling the widths above by the square root of the number of
names swapped, 16 swaps a day gives a 99% half-width of roughly **8–16 bps at H = 21**
and **~19 bps or more at H = 63**, against a ±10 bps band. So:
- **H = 63 can't come out dead**: its half-width alone is past the band. It is
  inconclusive unless the effect is larger than about 20 bps either way.
- **H = 21 can be dead** only at the low end of that range and with a point estimate
  within a few bps of zero. An effect needs ~10–15 bps or more to show. The most likely
  outcome, if the template does little, is **inconclusive at both horizons**.
- That isn't a reason not to run it: the filter swaps most of the basket, so a large
  effect (the book's claim) would be visible, and the momentum gate has the same width.

The count is a stand-in for power only: it is on the study's panel, not the model's
rows, and says nothing about returns.

### Known confounds

- **Momentum:** the template is mostly a momentum screen. The named control above is
  there for it.
- **The model already sees the parts:** `dist_from_52w_low`, `dist_z_sma_200`,
  `stack_fully_bearish`, `slope_log_21_sma_50`, `mom_12_1_rank`. A null here may just mean
  the model has priced them in; that would be the answer, not a flaw.
- **The test years are not fresh:** the model's column set was chosen on 2014–2021.
  The template wasn't, and this filter has never been scored.
- **The rating's peers:** `rs_rating` ranks among all index members, the model's universe
  is those that pass the dollar-volume floor; a small difference in who counts as a peer.
- **Survivorship:** delisted members missing from the bars (101 at the company-financials
  test, `docs/backlog.md`: EODHD; the run prints the current count). They would
  mostly fail the template (falling names), so their absence makes the unrestricted
  basket look better than it was, which pushes D toward "filtering hurts".
- **One bull market, long only.** In declines few names pass (107 dates under 20), so
  the template partly works as "trade less in bad markets". This per-trade test
  doesn't measure that: a smaller basket still counts as one date's mean.
- **Sector** is current-state.

### Outcomes

- **Positive effect that meets the rule:** the template (or the momentum gate, if it
  does the same) is proposed as a filter on the paper-traded picks. That is a later
  decision, written up as a dated addendum to the paper-trading rule
  (`docs/modeling/PREREGISTRATION.md`, HT1, "Paper trading after the test"), not adopted
  automatically.
- **Dead:** the hard template doesn't move the model's top-20 enough to matter. Written
  up as a demonstrated null at this band.
- **Inconclusive:** logged as underpowered. Not retested on the same years.
- **Negative effect:** filtering hurts; the model's picks that fail the template are
  better than the passing names that replace them. Reported, and the readouts say which
  rules remove them.
- **Logging:** the result as a dated addendum below; `docs/done.md`. No `TRIALS.csv`
  rows (no fit).
