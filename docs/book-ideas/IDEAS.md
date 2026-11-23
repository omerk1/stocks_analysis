# Book ideas: raw register

Every idea taken from the book notes in `notes/`, one row each, with what happened to it.
Nothing is deleted. A row only changes status, with the reason in the row. The scoped tasks
built from these rows are in `TASKS.md`.

**Status values:** **task**: feeds a task in `TASKS.md`. **covered**: the repo already has
it (where is given). **parked**: worth doing, but blocked (by what is given). **principle**:
a way of working, not a buildable thing. **dropped**: not usable as written (why is given).

**Processed so far:** `notes/trade-like-a-stock-market-wizard.md`, whole file, as of
commit `54f149b` (pass 1, 2026-11-23). On the next pass, read only what changed in the
notes since that commit (`git diff 54f149b -- docs/book-ideas/notes/`).

## Trade Like a Stock Market Wizard

### Finding the big winners (chapters 3, 5, 6)

| # | Idea | Status |
|---|---|---|
| 1 | Study past big winners (over 100% in a year) and find what they had in common before the run ("reverse factor modeling") | task 3 |
| 2 | Build an "optimal leadership profile" and score new stocks against it | task 3 (a score only if the profile turns out to differ from ordinary stocks) |
| 3 | Relative strength as a forecaster (Robert A. Levy) | covered: `rs_rating`, `mom_12_1` and its rank are model inputs (`src/signals/relative_strength/`) |
| 4 | Enter only when fundamentals, price action, volume and the market agree | covered: this is what the combined model does (`docs/modeling/IDEAS.md`) |
| 5 | Accelerating sales and earnings | task 5 (revenue acceleration exists as `rev_growth_accel`; earnings and margin acceleration don't) |
| 6 | Examine profitability | covered: `net_margin_ttm` (`docs/fundamentals/plan.md`, "3. Features") |
| 7 | Small caps can run further; take profits on large caps sooner | parked: the model universe is mostly S&P 500, so there are few small caps to measure |
| 8 | A few simple screens rather than one complicated screener | principle: matches the model's "many simple features" design |
| 9 | Trend template (p. 79) | task 9 |
| 10 | EPS trend and its rate of change | task 5 |
| 11 | Strongest stocks: best earnings and sales, closest to a new high, strong relative strength | covered by the combined model's inputs; the "closest to a new high" part is task 6 |

### Valuation (chapter 4)

| # | Idea | Status |
|---|---|---|
| 12 | P/E reflects the past, not the future | principle |
| 13 | Valuation methods work in some markets and fail in others | principle (earnings yield, sales yield, book-to-market are already inputs; `src/models/features/valuation.py`) |
| 14 | PEG (P/E over growth) over time as a signal | parked: low priority; ill-defined when growth is near zero or negative. Revisit after task 5 |
| 15 | Buy at P/E X, get cautious at 2-3X | parked: an exit rule; needs real positions (paper trading) first |

### Company quality (chapters 6, 7, 8)

| # | Idea | Status |
|---|---|---|
| 16 | Earnings growth expectations relative to the industry | dropped: no analyst-estimate data |
| 17 | Market size vs company size | dropped: no data |
| 18 | Sales per square foot, per dollar of capital, vs peers | dropped: no data, and industry-specific |
| 19 | Turnarounds: 2-3 strong quarters, or trailing 12-month earnings near the old peak | task 5 |
| 20 | Debt source and cash runway while losing money | task 8 |
| 21 | Last 2-3 quarters' growth vs 3- and 5-year growth | task 5 |
| 22 | Cyclical stocks (p. 107) | dropped: just a page reference |
| 23 | Estimates revised up 5% or more do better | parked: needs an analyst-estimates source (paid) |
| 24 | Current and next-year estimates trending up | parked: same as 23 |
| 25 | Earnings growth should come from revenue, not cost cutting or one product | task 5 (earnings growth vs revenue growth) |
| 26 | Lowered guidance followed by a beat is a red flag; also one-time charges, write-downs | parked: needs the guidance extraction (`docs/fundamentals/guidance_probe.md`, full fetch not decided) |
| 27 | Net margin over time, maybe vs the industry | task 5 |
| 28 | After a report: first reaction, whether gains hold, how fast it recovers | task 7 |
| 29 | A real leader shouldn't have a sell-off that breaks the whole leg up | task 6 (depth of drawdown) |
| 30 | Companies use guidance to sway investors | parked: same as 26 |
| 31 | Beat plus raised guidance | parked: same as 26 |
| 32 | The reaction to guidance can beat the reaction to the earnings | parked: same as 26 |
| 33 | "Spin" after bad news (buybacks etc.) | parked: same as 26; buybacks partly covered by the share-count change input |
| 34 | Distrust forecasts beyond the next quarter or fiscal year | principle |
| 35 | Inventory growing faster than sales is a warning (finished goods most) | task 8 |
| 36 | Receivables growing faster than sales is a warning; both at once is worse | task 8 |
| 37 | "Differential disclosures" (p. 158) | dropped: just a page reference |
| 38 | Acceleration in earnings, sales and margins for 3 quarters in a row | task 5 |

### The market and its leaders (chapters 6, 9)

| # | Idea | Status |
|---|---|---|
| 39 | Industry groups with many new 52-week highs early in a bull market lead | tasks 2 and 4 |
| 40 | New highs outpacing new lows, and expanding | tasks 2 and 4 |
| 41 | Market ignoring an overbought reading after a bear market, leaders list growing | dropped: too vague to define as written; the "leaders growing" part is task 4 |
| 42 | Raise risk when the market turns, but use stops; repeated stop-outs mean you're early | principle (for paper trading) |
| 43 | Stocks that hold up best and make new highs in the first 4-8 weeks off a low become leaders | task 6 |
| 44 | AMZN chart (p. 167), EMEX story (p. 170, 177) | dropped: references only |
| 45 | Stocks with strong news and earnings that hold up during declines become the next leaders | task 6 |
| 46 | Bottoming market: first leaders build bases, setups multiply, leaders hold their gains | task 4 (as far as it can be counted) |
| 47 | Index volume: more volume on down days than up days means it's too early | parked: index-level up/down volume isn't stored (per-stock `updown_volume_20` is); add if task 4 shows breadth matters |
| 48 | Key reversals, advisory sentiment, put/call, Nasdaq up/down volume | parked: no sentiment or options data |
| 49 | Leaders topping while indexes still rise means the bull is ending | parked: hard to define, and there are few bull-market ends in 2010-2021 |
| 50 | Keep a 52-week-high list in bear markets; stocks only 5-15% off their high are strong | tasks 2 and 6 |
| 51 | Keep a 52-week-low list to avoid | task 2 |
| 52 | A 25-30% fall in a bear market is normal; much more leaves too much overhead supply | task 6 |
| 53 | Past bull-market leaders rarely lead the next one | parked: only a handful of market cycles in the data; too few to test |

### Bases and entries (chapter 10)

| # | Idea | Status |
|---|---|---|
| 54 | Volatility contraction pattern: 2-6 contractions, each tighter, volume drying up | covered: VCP detector (`src/signals/patterns/`); how closely it matches the book is task 1 |
| 55 | Tight closes, day to day and week to week, with volume drying up near the lows | task 1 |
| 56 | Avoid stocks down 60% or more; good setups correct 10-35%, and less than 2-3x the market's fall | tasks 1 and 6 |
| 57 | A base lasts 3 to 65 weeks | task 1 |
| 58 | What's obvious to you is obvious to everyone: stops under obvious levels get run | parked: interesting but needs a stop-placement study; after task 10 |
| 59 | One or more shakeouts (undercuts of support that recover) during the base | task 1 |
| 60 | Big-volume up spikes and gaps show institutional buying | covered: gaps module (`src/signals/gaps/`), `rel_volume_20`, `updown_volume_20` |
| 61 | Big up days bigger and more frequent than big down days, on volume | covered: `updown_volume_20` |
| 62 | A big spike (e.g. raised guidance) then a VCP is very strong | task 1 (as a variant to check) |
| 63 | Final contraction's volume below the 50-day average, with one or two very low days | task 1 |
| 64 | Extrapolate intraday volume to judge the breakout early | parked: no intraday data |
| 65 | Squats: breakout closes back in the range; wait up to ~10 days for a recovery | task 10 |
| 66 | A close below the 20-day average after a breakout lowers the odds | task 10 |
| 67 | Early-day reversal on the breakout day | parked: needs intraday data |
| 68 | The base sequence: downtrend, rally, pause, breakout | covered: base-breakout and retest finder (`src/signals/base_breakout/`, Done #163) |

### Working habits (chapter 1)

| # | Idea | Status |
|---|---|---|
| 69 | Learn from your successes and failures | parked: a review of paper trades (what worked, what didn't, why), once paper trading has some |
| 70 | Focus on real experience | principle |
