# Book ideas: tasks

Scoped tasks built from `IDEAS.md`. Each is one PR, about one session. The order is the
suggested order; dependencies are listed. Each task's "Ideas" line gives the `IDEAS.md`
rows it came from.

**How this file is kept.** Each pass reads only what changed in the notes, adds the new
ideas to `IDEAS.md`, then reconciles here: merge overlaps, split anything that got too big,
drop what the repo has since built or tested, reorder. The section below is replaced each
pass, not appended to. A finished task moves out (to `docs/done.md`, as usual) and leaves a
one-line pointer under "Finished" here.

**Analysis tasks** follow the repo's usual test rules: data up to 2021-12-31 only, delisted
tickers kept, one-bar lag, a matched control (momentum at least, since that is what killed
the 52-week-high and pattern looks before), effective N (distinct dates), costs, and a
three-way verdict against a band fixed before running: dead (the whole interval inside the
band), inconclusive (spans zero and reaches past the band), or an effect. A task marked
*exploration* is a cheap look whose numbers are never stated as findings; a task marked
*confirmation* is written into a pre-registration and committed before it runs.

## This pass (pass 1, 2026-11-23)

First pass over the notes from *Trade Like a Stock Market Wizard*: 70 ideas; 31 of
them feed 11 tasks. Of the rest, 8 are already covered by the repo, 18 parked (mostly no
data: analyst estimates, guidance, intraday bars, sentiment), 6 are principles and 7 were
dropped (page references or no data). Several ideas the book treats as strong have been tested here
already and came out inconclusive, not dead: VCP-only patterns, distance from the 52-week
high, post-earnings drift by surprise size. Tasks touching those (1, 6, 7, 11) are framed
to add something new (a stricter definition, a different measure, more events), not to
rerun the same test.

## Tasks

### 1. Check the VCP detector against the book's rules (audit, docs only)

- **Goal:** know exactly which of the book's VCP rules our detector enforces, and which
  it doesn't, before testing VCP again.
- **Why:** the last test of VCP-only setups was inconclusive on 402 events
  (`docs/modeling/IDEAS.md`, "Feature families", chart patterns row). The book's version
  is stricter than "contractions getting shallower".
- **Ideas:** 54, 55, 56, 57, 59, 62, 63.
- **Done when:** a short table in `docs/features/chart_pattern_detection_design_notes.md`
  (VCP section): each book rule (2-6 contractions, each shallower; total correction
  10-35%; base 3-65 weeks; final contraction volume below the 50-day average with a
  very-low-volume day; breakout on volume above average; shakeouts; tight closes)
  against what `src/signals/patterns/detectors/vcp.py` checks, its config value, and
  whether it's a hard rule, a score component, or missing.
- **Out of scope:** changing the detector.
- **Size:** small.

### 2. New 52-week highs and lows in the breadth table (build)

- **Goal:** daily counts of stocks making new 52-week highs and lows, for the market and
  for each sector.
- **Why:** the breadth table has percent above moving averages and advance/decline, but
  no new-highs/new-lows count, which the book leans on for spotting market turns and
  leading groups.
- **Ideas:** 39, 40, 50, 51.
- **Done when:** `src/signals/breadth/` writes `pct_new_high_52w`, `pct_new_low_52w` and
  their difference, market-wide and per sector, on the point-in-time membership; NaN
  during each stock's first 252 bars (not counted as "not a new high"), with a test for
  that; the stored table recomputed (one step at a time, checked between steps).
- **Out of scope:** using it in the model or testing it (that's task 4).
- **Size:** small to medium.

### 3. What did big winners look like before their run? (analysis, exploration)

- **Goal:** compare stocks just before a 100%+ 12-month run with all other stocks on the
  same dates, using the model inputs we already have.
- **Why:** the book's core method. It tells us which of our existing inputs separate
  future big winners, and whether a "leadership profile" score is worth building.
- **Ideas:** 1, 2.
- **Done when:** for each existing model input, the winners' average percentile minus
  everyone else's on the same dates, with effective N (distinct start dates), in three
  sub-periods (2010-13, 2014-17, 2018-21). A short note says which inputs differ by
  more than 0.3 SD in all three sub-periods, and logs the look in the exploration log.
- **Caution:** this picks stocks by their future. It describes, it doesn't predict. Any
  input it flags still needs a proper test (as part of the model's scorecard) before it
  counts.
- **Out of scope:** building a profile score.
- **Size:** medium.

### 4. Do new-highs counts point to the next leaders? (analysis, confirmation)

- **Depends on:** task 2.
- **Goal:** test whether sectors with a rising share of new 52-week highs see their
  stocks beat the market over the next 21 and 63 days.
- **Why:** the book's "industry groups with many new highs early in a bull market lead".
  The sector level gives many more data points than market timing, which has only a few
  turns in 2010-2021.
- **Ideas:** 39, 40, 46.
- **Hypothesis:** stocks in sectors whose new-high share rose most over the past 20 days
  outperform, beyond what their sector's 63-day momentum (`sector_rank_mom_63`)
  predicts.
- **Done when:** a pre-registered test with a matched control (same sector momentum
  bucket), effective N, costs and a verdict against a ±10 bps band.
- **Kill:** the whole interval inside ±10 bps.
- **Out of scope:** market-timing rules.
- **Size:** medium.

### 5. Earnings and margin acceleration inputs (build, then scorecard)

- **Goal:** add the book's earnings-quality inputs to the company-financials group.
- **Why:** we have revenue acceleration but not earnings or margin acceleration, the
  multi-quarter streak the book asks for, or a check that earnings growth comes from
  revenue rather than cost cutting.
- **Ideas:** 5, 10, 19, 21, 25, 27, 38.
- **New inputs:** net income growth acceleration; net margin change vs a year ago;
  number of the last 3 quarters with accelerating revenue growth (0-3); net income growth
  minus revenue growth (high = cost cutting); trailing 12-month net income vs its previous
  peak (turnarounds); last-2-quarter growth vs 3-year growth.
- **Done when:** the inputs are in `src/models/features/fundamentals.py` with the same
  point-in-time rules as the existing ones (`docs/fundamentals/plan.md`, "3. Features"),
  the leakage gate passes, and one scorecard run of the model with vs without them is
  logged with its verdict.
- **Out of scope:** analyst estimates, guidance.
- **Size:** medium. If the build alone fills a session, split it: build in one PR, the
  scorecard run in the next.

### 6. Drawdown compared with the market (build, then scorecard)

- **Goal:** an input measuring how far a stock has fallen from its 52-week high compared
  with how far the market (SPY) has fallen over the same span.
- **Why:** the book's leaders are the stocks that fall least during a decline and are
  first back to new highs. Plain distance from the 52-week high was inconclusive and
  largely explained by momentum (`docs/modeling/IDEAS.md`, "Recurring confounds"); a
  version measured against the market is a different question, mostly about down
  markets.
- **Ideas:** 11, 29, 43, 45, 50, 52, 56.
- **New inputs:** stock drawdown over SPY drawdown (NaN when SPY is within 2% of its
  high, where the ratio is meaningless); a flag for a drawdown deeper than 60%.
- **Done when:** the inputs are registered with a null prior, the leakage gate passes,
  and a scorecard run with vs without is logged. The report also gives the result on
  dates when SPY is more than 10% off its high, since that's where the idea should
  show up if it's real.
- **Kill:** the scorecard's usual ±10 bps band.
- **Size:** small to medium.

### 7. Earnings-day reaction and whether it holds (analysis, confirmation)

- **Goal:** test whether the price reaction to an earnings report, and whether it holds
  over the next 10 days, predicts the following 63 days.
- **Why:** drift after a big earnings surprise was inconclusive (`docs/fundamentals/plan.md`,
  "4. Research questions"). The book judges the market's reaction instead of the
  numbers: first move, whether it holds, how fast it recovers. That needs only prices
  and the earnings dates we already have.
- **Ideas:** 28, 29.
- **Hypothesis:** stocks whose reaction-day return is in the top 10% and that are still
  above the reaction day's close 10 days later outperform over the next 63 days, beyond
  momentum-matched controls. The bottom 10% mirrored as the short side.
- **Done when:** pre-registered; matched control, effective N, costs and a verdict
  against ±10 bps; neighbouring cuts (80/20, 95/5) and hold windows (5, 20 days) checked
  for agreement.
- **Kill:** the whole interval inside ±10 bps.
- **Size:** medium.

### 8. Inventory, receivables and cash runway warnings (build, after a data check)

- **Goal:** inputs for inventory and receivables growing faster than sales, and how long
  a loss-making company's cash lasts.
- **Why:** the book's main balance-sheet warnings. None are inputs today.
- **Ideas:** 20, 35, 36.
- **First step (stop if it fails):** count how often the needed filing tags (inventory,
  receivables, cash) are present for S&P 500 member-quarters in 2010-2021. Under 60%
  outside banks and insurers means stop and report, not build.
- **Done when:** inventory growth minus sales growth, receivables growth minus sales
  growth (both year over year), and cash over the trailing quarterly loss (NaN when
  profitable) are registered with a null prior, pass the leakage gate, and get one
  scorecard run.
- **Size:** medium.

### 9. The trend template as a filter on the model's picks (analysis, confirmation)

- **Goal:** test whether dropping the model's top picks that fail the book's trend
  template (p. 79: price above the 150- and 200-day averages, 150 above 200, 200 rising
  for a month, 50 above both, at least 30% above the 52-week low, within 25% of the
  52-week high, high relative strength) improves the picks after costs.
- **Why:** it's the book's main entry gate. The model already sees most of the parts
  separately, so the question is whether the hard combined rule adds anything.
- **Ideas:** 9.
- **Done when:** the template is written down exactly before running; pre-registered
  against the current reference model (top-20, next-best names swapped in, the same way
  as the earnings-as-risk test, `docs/fundamentals/PREREGISTRATION.md`); verdict against
  ±10 bps; the share of picks the template removes is reported.
- **Kill:** the whole interval inside ±10 bps.
- **Caution:** the moving-average study found no single lookback special, including the
  200-day. A result here would be about the combined rule, not any one average.
- **Size:** small to medium.

### 10. After a breakout: squats and closes below the 20-day average (analysis, exploration)

- **Goal:** for base breakouts, measure what happens after (a) a squat (the breakout day
  closes back inside the base) and (b) a close below the 20-day average within 10 days,
  vs breakouts with neither.
- **Why:** these are the book's hold-or-sell rules. Paper trading will need exit rules,
  and this is the cheapest evidence for one.
- **Ideas:** 65, 66.
- **Done when:** on the base-breakout finder's events (`src/signals/base_breakout/`),
  the 21- and 63-day result, the share of squats that recover to a new high within 10
  days, and stop-hit rates, each against breakouts with neither event, with effective N.
  Logged in the exploration log.
- **Out of scope:** intraday rules (no intraday data).
- **Size:** small to medium.

### 11. The stricter VCP, with more events (analysis, confirmation)

- **Depends on:** task 1.
- **Goal:** retest VCP setups using the book's stricter rules (whatever task 1 finds
  missing), on enough events to reach a verdict.
- **Why:** the earlier test was inconclusive, not dead: its interval was too wide to
  decide either way. That allows a new, more powerful look; it doesn't allow rerunning
  the same one.
- **Ideas:** 54-57, 59, 62, 63.
- **Done when:** a power check first (how many events are needed for the interval to fit
  inside ±10 bps if there's no effect, and whether the data has them); then the
  detector change, a pre-registration, and the test against an extension-aware matched
  control.
- **Stop:** if the power check says the events aren't there, report that and stop.
- **Size:** medium. Likely two PRs (detector + power check, then the test).

## Parked: what would unblock them

- **Analyst estimates** (ideas 16, 23, 24): a paid estimates source.
- **Guidance** (26, 30-33): the full guidance fetch and extraction
  (`docs/fundamentals/guidance_probe.md`, the owner's call).
- **Intraday data** (64, 67): intraday bars.
- **Sentiment, put/call** (48): an options or sentiment source.
- **Exit and position rules** (15, 58): paper trading running, then task 10's results.
- **Small caps** (7): a wider universe than the S&P 500.
- **Index up/down volume** (47): add if task 4 shows breadth matters.
- **Market cycles** (49, 53): more cycles than 2010-2021 holds, so probably never testable here.
- **PEG** (14): after task 5.
- **Reviewing paper trades** (69): once paper trading has trades.

## Finished

(none yet)
