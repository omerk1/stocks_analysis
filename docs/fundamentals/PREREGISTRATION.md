# Company financials: pre-registrations (plan step 4)

The three research questions of `plan.md` step 4, written and committed **before** any
of them runs. This follows the same discipline as `docs/modeling/PREREGISTRATION.md`:
once an entry has run, its text is frozen, and a result or a change of scope is a new
dated addendum below it. Every run is logged whatever it finds: the scorecard question
in `docs/modeling/TRIALS.csv`, the other two in a result addendum here.

Track: B, confirmation, for all three. The questions come from `plan.md` step 4. The
features they read were built and leakage-gated in step 3 (Done #145, #147, #149).
None of the questions has been run before: no fundamentals column has been fitted,
scored or plotted against returns.

Run order: F2 (the combined model, the main goal), then F3, then F1. Each runs in its
own PR.

## Shared rules

- **Window:** development only. Bars, labels and features end on 2021-12-31; a
  trade or forward return whose window reaches past it is dropped, never truncated.
  The holdout stays locked.
- **Universe:** the point-in-time S&P 500 of the modeling caches
  (`dataset.universe_mask`: $20M dollar-volume floor, history-break rules). Delisted
  members are read from Tiingo; their terminal returns stay in.
- **Data:** the feature cache rebuilt from `main` at 69553a7 on 2026-10-16
  (`data/models/features/sp500_fund`). It has every step-3 column, the valuation
  columns, `share_change_yoy` and the fixed `debt_to_equity`. Coverage by year is in
  Done #152. The label cache is `data/models/labels/sp500` (built 2026-10-07, after
  #184's disputes list).
- **Entry and lag:** a decision at the close of day t trades at the open of t+1 (the
  barrier labels' rule). Every feature is as known at the close of t.
- **Ties in the top-k:** broken by a hash of (ticker, date), not by ticker name
  (`metrics.tie_key`, fixed in this entry's PR). Isotonic calibration leaves ~120
  distinct probability triples among ~470 names a day. In S1's archived predictions,
  the top-20 cut fell inside a tie on 36–57% of test dates, and up to ~11 of the 20
  picks were then the alphabetically first names.
- **Three verdicts** (`LRP.md` §3, amended 2026-10-07), against a band committed here:
  - **dead:** the whole CI sits inside the relevance band. An effect big enough to
    matter is ruled out.
  - **inconclusive:** the CI spans zero and reaches past the band. That means
    underpowered, never "no effect".
  - **effect:** the CI excludes zero. The sign says which way. An effect whose point
    estimate is inside the band is reported as "real but too small to trade".
- **Relevance band: ±10 bps per trade** for all three questions. That is one realistic
  round-trip cost for an S&P 500 name: an edge smaller than the cost of the trade it
  asks for doesn't matter. It is also the stricter choice for calling a result dead,
  as in E1.
- **CIs: the date-block bootstrap's 99% interval** (`inference.bootstrap_ratio`:
  circular moving blocks of 2H trading dates, 1,000 draws). It is used as the verdict
  interval because the nominal levels under-cover at this block count.
  - **The check:** the scorecard's noise test, 24 seeds of a within-date-shuffled
    panel, 3 test years, ~18 blocks, `ev_atr` ranking, 96 readouts.
  - **How often the interval left out zero:**
    - nominal 90%: 13.5% (should be 10%);
    - nominal 95%: 11.5% (should be 5%);
    - nominal 99%: 2.1% (should be 1%).
  - So the 99% interval behaves like a ~98% one. That is slightly conservative, the
    safe direction.
  - **Block counts in these runs:** F2 and F3 at H = 21 have ~48 blocks; F2 at H = 63
    has ~16, as in the check. More blocks only make the interval more conservative.
  - The point estimates were unbiased (mean z 0, sd 1.08).
- **Effective N:** distinct dates. They are reported next to every row count.
- **Costs:** 10 bps round trip is the headline, with 0 and 25 bps beside it. Every
  readout that implies trading carries trades per year × cost.
- **Descriptive, never a verdict:** hit rate, average win over average loss, and skew
  next to every mean. Also per era (2014–17, 2018–21, or the drift study's own halves)
  and per year. No CI is put on these and nothing is killed on them.
- **Neighbouring parameters:** each entry names its neighbours. A verdict that holds
  at its primary setting but flips sign at the neighbours is reported as a lone pixel,
  not a result.
- **Known data caveats** (`docs/backlog.md`, Data):
  - **market cap:** vendor spin-off "splits" inflate it, EBAY 2.4× (2015–17) and NI
    2.5× (2015–20), YUM 2016 and HPE 2017 too;
  - **share counts:** the SEC → yfinance count hand-off steps it ~12–14% for MA and
    CMCSA.
  Both skew E/P, S/P and B/M. F2 reruns its readout without these six tickers
  (below). F1 and F3 read no market cap.

---

## F2: does the company-financials group improve the combined model's top-k after costs? (registered 2026-10-16)

- **Promoted from:** `plan.md` step 4, "Combined model". It is the main question of
  the track.
- **Why this test:** the modeling goal is one combined model judged on the trades it
  picks, after costs (`VALIDATION_HARNESS.md` §9). A feature group is judged like any
  other: does the model with it pick better trades than the same model without it?

### Hypothesis

Adding the 11 company-financials inputs to the combined model raises the realized
per-trade return of its daily top-20 picks (EV in ATR units, `rank="ev_atr"`). The
comparison is the same model without them, on the same dates.

### Models

- **Reference (the control):** the combined model as registered on `main` without
  the group. That is B4 + the MA family + the step 2b indicators and market regime:
  S1's columns plus S2's `STEP_2B_COLUMNS`, 30 columns in all.
  - It is the matched control because the only difference is the group: the same
    learner, folds, seeds, rows and ranking.
  - The level features (step 2) aren't registered on `main` yet, so neither side has
    them.
- **Model:** the reference + the group's 11 model inputs. Ranked columns enter as
  their per-date rank, the rest raw (`registry.model_input`):
  - `days_since_earnings`, `days_to_earnings_expected`, `rev_growth_accel`,
    `net_margin_ttm`, `debt_to_equity`;
  - `sue_net_income_rank`, `rev_growth_yoy_rank`, `earnings_yield_rank`,
    `sales_yield_rank`, `book_to_market_rank`, `share_change_yoy_rank`.
  - Missing values stay NaN; the boosting learner routes them, and the reference
    never sees them.
- Both column lists are written literally into the code, so a later registration
  can't change them.

### Scope

- **Cells:** all 9 v1 barrier cells (U ∈ {2, 3, 4} × D ∈ {1, 1.5, 2}, scaled by
  √(H/21)) at H = 21 and H = 63.
- **Learner:** v1 `BoostingConfig`, fixed, no tuning. Isotonic calibration on 2 inner
  folds.
- **Seed:** 0, one seed, as S1/S1b/S2. Each cell is two fits × 8 folds; three seeds
  would triple a run of several hours. Seed variance is a stated caveat. If a horizon's
  verdict is an effect, it is rerun with seeds 1 and 2 before anything enters the
  model. A rerun can confirm an effect but never rescue an inconclusive one.
- **Folds:** expanding walk-forward, test years 2014–2021, first training window
  2011–2013, label windows purged (E1's scheme).
- **Picks:** each test date's top 20 rows by EV in ATR units, per model. Top-5 is
  reported, never a verdict.

### Primary metric and kill criterion

- **Per horizon:** D_H = the date-weighted mean, over test dates, of model minus
  reference top-20 basket return, averaged over the 9 cells on each date.
  - It is gross: both sides trade 20 names a day, so the cost cancels.
  - Its CI is the date-block bootstrap of that per-date series, so the cells share
    their blocks and aren't counted as 9 independent looks.
- **Band:** ±10 bps per trade.
- **Verdict per horizon,** on the 99% interval of D_H (shared rules):
  - **dead** if it sits inside [−0.10%, +0.10%];
  - **inconclusive** if it spans zero and reaches past the band;
  - **effect** if it excludes zero.
- **The group enters the combined model only if:**
  - at least one horizon shows a positive effect, with Holm's correction over the two
    horizons (one-sided bootstrap p at 0.005, the interval's own level);
  - its point estimate is at least +10 bps;
  - its point estimate is positive in both eras (2014–17 and 2018–21);
  - it survives the seed rerun above.
- **Group verdict:**
  - **dead** if both horizons are dead;
  - **effect** (positive or negative) if either horizon shows one, per the rule above;
  - **inconclusive** otherwise.

### Readouts (descriptive, never a verdict)

- **Per cell, k ∈ {5, 20}:** each strategy's expectancy net of 0/10/25 bps, its R/R
  (average win over average loss), win rate and skew; model minus reference and minus
  the market, with 99% intervals. These are 36 uncorrected looks, labelled as such.
- **Portfolio:** non-overlapping holds net of 10 bps, with annual return, Sharpe and
  drawdown; the model vs the random-k basket and the market basket.
- **Per era and per year:** D_H.
- **Neighbours:** the 9 cells are each other's neighbours, and both horizons. D_H's
  sign at each cell is reported; a verdict carried by one or two cells is said to be.
- **Caveat sensitivity:** D_H again without EBAY, NI, YUM, HPE, MA and CMCSA. They
  are taken out of every strategy's pickable rows, and both models' picks are re-read
  from the archived predictions with no refit. If the verdict changes, the result is
  reported as hinging on the market-cap defects.
- **Diagnostic only:** how often each picked row has the group's columns filled, and
  the top-20 overlap between the two models. No ablation inside the group is run or
  reported as a verdict.

### Known confounds

- **The test years are not fresh.** S1, S1b and S2 scored the same 2014–2021 folds
  with the reference's columns, B4's and S1's. The group's columns themselves have
  never been scored.
- **Survivorship:** 101 delisted members are still missing (backlog: EODHD).
- **Sector** is current-state.
- **One bull market,** long only.
- **The reference's `days_since_earnings` stand-in:** none. The reference sees no
  earnings timing. Part of any gain could be the group dodging earnings gaps, which
  is F3's question. F3 reports how much of the model's picks differ in earnings
  exposure.

### Outcomes

- **Positive effect that meets the entry rule:** the group joins the combined model's
  column set for the later pre-registered test of the full feature set.
- **Inconclusive:** the group stays registered and isn't dropped. A null prior doesn't
  exclude a feature (`IDEAS.md` §2). It's logged as underpowered.
- **Dead:** the group is left out of the next scorecard runs. That is written up as a
  demonstrated null at this band.
- **Negative effect:** left out, and the reason is looked for (overfitting through
  NaN routing is the first suspect).

### Result (2026-10-17 addendum)

Run as registered: 18 trials, seed 0, git ce579c1, `TRIALS.csv` experiment `F2`
(`run-scorecard --preregistered F2`, then `close-scorecard F2`). 2,001 test dates
(2014–2021), none left out for a missing cell. The coverage table this entry cites as
"Done #152" is in Done #153 (#152 went to another PR first).

**Verdict: inconclusive at both horizons, so the group is inconclusive.** It stays
registered and isn't dropped. The entry rule isn't met, and no seed rerun is run
(a rerun can't rescue an inconclusive result).

| | D_H (model − reference, top-20) | 99% CI | one-sided p | verdict |
|---|---|---|---|---|
| H = 21 | +0.029% | [−0.041%, +0.102%] | 0.16 | inconclusive |
| H = 63 | −0.060% | [−0.208%, +0.080%] | 0.83 | inconclusive |

- **H = 21 is close to dead:** the upper end passes the +10 bps band by 0.2 bps. It is
  still inconclusive by the rule, not "dead" and not "nearly an effect".
- **Monte Carlo precision of the interval's ends:** at 1,000 draws a 99% end rests on
  ~5 tail draws. Rerun at 10,000 draws (`close-scorecard F2 --n-boot 10000`, a check,
  not the registered verdict): H21 [−0.047%, +0.101%], H63 [−0.214%, +0.097%]. Both
  are still inconclusive, and H21 is still just past the band. Entries registered from
  now on should state 10,000 draws for a 99% interval.
- **Caveat sensitivity:** without EBAY, NI, YUM, HPE, MA and CMCSA the numbers barely
  move (H21 +0.029% [−0.043%, +0.104%]; H63 −0.059% [−0.208%, +0.088%]). The verdict
  doesn't hinge on the market-cap defects.
- **Costs:** both sides trade 20 names a day, so D_H is the same gross or net. At
  10 bps per trade, the model's top-20 nets +0.52% per trade at H21 (reference +0.49%,
  market +0.47%) and +1.53% at H63 (reference +1.59%, market +1.58%). Means over the
  9 cells; ~5,000 signal trades a year (20 × 252), i.e. ~5.0 percentage points of
  turnover cost per year at 10 bps in the overlapping signal stream.

**Readouts (descriptive, not verdicts):**

- **Shape, top-20, net 10 bps, means over the 9 cells:**
  - H21: win rate 44.9% vs 44.5%, avg win / avg loss 1.61 vs 1.61, skew 1.89 vs 2.25
    (model vs reference);
  - H63: win rate 46.5% vs 47.0%, avg win / avg loss 1.74 vs 1.73, skew 1.98 vs 1.67.
  - The group changes which names win, not the shape of the trade.
- **Per era:** H21 +0.053% (2014–17), +0.004% (2018–21); H63 −0.175%, +0.057%.
- **Per year:** H21 positive 2014–2018, negative 2019–2021. H63's mean is carried by
  2016–2017 (−0.32%, −0.42%) and 2020 (+0.24%).
- **Neighbours:** H21, 6 of 9 cells positive (−0.07% to +0.09%); H63, 2 of 9.
  Top-5 is negative at both horizons (H21 −0.04%, H63 −0.21%; one H63 cell's
  uncorrected CI excludes zero, 1 look of 36). No sign holds across cells, k and
  horizons: no plateau.
- **Diagnostics:**
  These come from `close-scorecard`'s pick diagnostics (`trading.pick_diagnostics`),
  as means over the 9 cells.
  - The two models' top-20 overlap on 42% of names a day at H21 and 55% at H63, so
    the group really changes the picks.
  - The model's picks have all 11 group columns filled 56% of the time at H21 (55% at
    H63), about the same as the reference's picks (56%, 55%).
  - The model avoids earnings: at H21, 17% of its picks have an expected earnings
    date inside the horizon, against 27% of the reference's (H63: 84% vs 86%). The
    trades it swaps in do no better or worse on average. Whether earnings inside the
    horizon matter to the result is F3's question.

**Against this result:**

- One seed: the seed variance isn't measured here, and D_H is only a few bps. A second
  seed could move H21's upper end inside the band or further out. Neither would change
  "no effect shown".
- The group's columns are 67% (sales yield, 2014) to ~100% filled in the test years,
  and only 56% of picks have all 11; the boosting learner routes
  missing values. An effect concentrated in fully covered names would be diluted
  here. That's a reason the test is underpowered, not evidence of an effect.
- The test years were scored before (S1, S1b and S2) with the reference's columns;
  the group's columns were not. Nothing here was tuned on them.
- No framing rescues it: no cell, k, era or the caveat rerun gives a consistent sign.

---

## F3: does an expected earnings date inside the horizon change the picks' realized result? (registered 2026-10-16)

- **Promoted from:** `plan.md` step 4, "Earnings as risk", and `IDEAS.md` §3/§7
  ("Earnings dates": an earnings gap jumps both barriers).

### Hypothesis

Among the combined model's top-20 picks, those with an expected earnings date inside
the holding window have a different realized per-trade result than those without.
Dropping them and taking the next-best names instead changes the top-20 basket's
return after costs. The sign isn't predicted: a gap can hit the target as easily as
the stop.

### Setup

- **Predictions:** F2's archived reference-model predictions (the combined model
  without the group, which has no earnings information), H = 21, all 9 cells. No new
  fit.
  - The F2 model's predictions are re-read the same way as a secondary. That model can
    already see `days_to_earnings_expected`.
- **The flag:** `days_to_earnings_expected` ≤ 21 at the close of t, i.e. the
  *expected* next reaction date (the same quarter a year earlier + 52 weeks), never
  the realized one.
  - 0 (overdue) counts as inside.
  - NaN (no history) is "unknown": never excluded, and reported as its own group.
- **Excluding:** each date's top 20 among the rows not flagged inside. The next-best
  names fill the gaps, so the basket always holds 20 names on dates with enough
  candidates.
- **Horizon:** H = 21 only for the verdict. At H = 63 an expected date falls inside
  nearly every row's window, so exclusion leaves almost nothing. H = 63's flag rates
  and R/R split are reported descriptively.

### Primary metric and kill criterion

- **Metric:** D = the date-weighted mean, over test dates, of the excluding top-20
  basket's return minus the unrestricted top-20's, averaged over the 9 H = 21 cells on
  each date.
  - It is gross: both trade 20 names a day, so the cost cancels.
  - Its CI is the 99% date-block bootstrap interval (block 42), as in F2.
- **Band:** ±10 bps per trade.
- **Verdict:**
  - **dead** if the CI sits inside [−0.10%, +0.10%];
  - **inconclusive** if it spans zero and reaches past the band;
  - **effect** if it excludes zero: positive means excluding helps, negative means it
    hurts.
- **Control:** the unrestricted top 20 of the same model on the same dates. It is the
  matched control because only the flag differs: the same predictions, the same
  ranking and the same day.

### Readouts (descriptive)

- **Within the unrestricted picks,** inside vs outside vs unknown, per cell:
  - target, stop and timeout rates;
  - expectancy net of 10 bps;
  - R/R (average win over average loss), win rate and skew;
  - the share of picks flagged.
  This is the "flag" half of the question: how the R/R distribution differs, not
  only the mean.
- **The flag's accuracy:** the share of flagged rows whose realized reaction date
  falls inside the window, and of unflagged rows whose doesn't. It uses the realized
  date, as a label diagnostic only.
- **Neighbours:**
  - windows ≤ 16 and ≤ 26 business days (the flag's ±5);
  - the 9 cells' signs;
  - a sign flip across the window widths is reported as fragile.
- **Per era:** 2014–17 and 2018–21.
- **Secondary:** the F2 model's picks, the same metric.

### Known confounds

- The expected date misses moved announcements (about 1 in 10 quarters shift by more
  than a week; the flag-accuracy readout measures it here).
- A model with no earnings information may already prefer or avoid pre-earnings names
  through volatility features. The flag share among picks vs among all rows is
  reported.

### Outcomes

- **Positive effect:** an exclusion rule (or the flag as a decision filter) is
  proposed for the combined model. It's a later decision, written up as a dated
  addendum, not adopted automatically.
- **Dead:** earnings timing doesn't move the top-20 result enough to matter at H = 21.
  The flag stays a feature (F2) and nothing more.
- **Inconclusive:** logged as underpowered.

---

## F1: post-earnings drift beyond momentum (registered 2026-10-16)

- **Promoted from:** `plan.md` step 4, "Post-earnings drift" (the classic
  post-earnings-announcement drift, measured here against the company's own history
  because there is no consensus).

### Hypothesis

After a large own-history surprise (`sue_net_income`), the stock's return over the
next H trading days moves in the surprise's direction, beyond what its price
momentum predicts. Large positive surprises beat their momentum-matched controls, and
large negative ones trail theirs.

### Events

- **When:** an event is the session on which a quarter's SUE first counts, its
  `known_at` (`fundamentals.quarter_features`). That is the 10-Q/10-K's acceptance,
  usually days after the earnings reaction (median 6 calendar days).
  - The drift is measured from there, after the announcement and after the filing.
    It is what an investor could still trade on the data this repo has.
  - The reaction itself (the gap) is not part of the outcome.
- **Which rows:** an event counts only if the ticker is an eligible row that day and
  the cache's `sue_net_income` that day equals the event's value (not stale).
  - Event dates run from 2011-01-01. SUE needs three years of quarters, so earlier
    years are nearly empty.
  - The forward window must end by 2021-12-31.
- **"Large", defined before looking at any return:** SUE at or above the 90th
  percentile, or at or below the 10th, of every event's SUE over the previous 365
  calendar days.
  - It is trailing, not full-sample, and needs at least 200 such events; earlier
    events are left out.
  - It is a cross-sectional cut, the classic decile sort, without look-ahead.
- **Neighbours:** the 80th/20th and 95th/5th percentiles.

### Outcome and control

- **Outcome:** the total-return log return from the open of t+1 to the close of
  t+H, on `total_return` bars (Tiingo for delisted members).
  - A ticker that stops trading inside the window keeps its return to its last close.
    That is the terminal return, never dropped.
  - Pure forward return, not a barrier label: drift is a question about where the
    price goes, not which barrier it touches.
- **Horizons:** H = 63 primary (the classic drift window, about a quarter), H = 21
  secondary.
- **Control, momentum-matched:** on the same date, eligible rows that aren't events
  within ±5 sessions and whose current SUE isn't large.
  - They are bucketed by `mom_12_1_rank` quintile × `mom_1_0_rank` tercile. The
    one-month reversal term matters because the earnings reaction sits inside the last
    month.
  - The event's delta is its return minus its bucket's mean control return. A bucket
    with fewer than 5 controls drops the event.
- **Why this control:** the question is "beyond momentum". Medium-term momentum and
  the one-month reaction are what momentum alone would predict. Size and volatility
  are a robustness tier, not the primary:
  - the same buckets × `log_dollar_volume_20d_rank` tercile;
  - the same buckets × `realized_vol_63_rank` tercile;
  - each reported, not judged.

### Primary metric and kill criterion

- **Metric:** S_H = the date-weighted mean, over event dates, of each date's mean
  *signed* delta: + for positive surprises, − for negative ones. That is the
  long-positive / short-negative drift beyond momentum, per event.
- **CI:** the 99% date-block bootstrap interval over the event dates (block 2H event dates; event
  dates are sparser than trading dates, so the blocks span more calendar time, which
  is the conservative direction).
- **Band:** ±10 bps per event. Each event is one round trip; a drift smaller than its
  cost isn't tradable.
- **Verdict at H = 63:**
  - **dead** if the CI sits inside [−0.10%, +0.10%];
  - **inconclusive** if it spans zero and reaches past the band;
  - **effect** if it excludes zero.
  H = 21 gets the same three verdicts, reported, but the question's answer is
  H = 63's.
- **Per side,** reported: positive surprises' mean delta and negative surprises'
  mean delta, each with its CI. The literature's drift is often one-sided.

### Readouts (descriptive)

- **Raw, unmatched:** the event's return minus the same-date eligible mean. It shows
  how much the momentum match changes the number.
- **Per event:** hit rate (the signed delta > 0), win/loss magnitude ratio, and skew.
- **Per era:** 2011–2016 and 2017–2021; per year.
- **Costs:** events per year × 10 bps, next to S_H.
- **Neighbours:** the 80/20 and 95/5 cuts, and H = 21 vs 63.

### Known confounds

- **No consensus:** an own-history surprise is not what the market expected. Much of
  it is predictable from the trend in earnings, which momentum partly carries. This is
  why the control is momentum-matched.
- **Measured after the 10-Q, not the press release:** if the drift is concentrated in
  the first days after the announcement, this design misses it. That is by
  construction; the readout says so.
- **Survivorship:** the 101 missing delisted members are mostly cap drops, where a
  large negative surprise's drift would be largest. That biases the negative side
  toward zero.
- **Events cluster in earnings season.** That is why effective N is in dates and the
  CI uses date blocks.

### Outcomes

- **Effect, positive at H = 63:** the drift exists here beyond momentum. Since
  `sue_net_income_rank` is already a combined-model input, nothing is added; the
  finding explains (or not) what F2 found.
- **Dead or inconclusive:** logged as such. Not reframed (another threshold, another
  horizon, an EPS surprise) without a new dated entry.
