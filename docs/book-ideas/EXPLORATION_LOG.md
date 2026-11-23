Cheap looks from the book-ideas tasks (`docs/book-ideas/TASKS.md`): descriptive numbers only, never findings; anything worth keeping still needs a proper test.

## 2026-11-24

**What did big winners look like before their run?** (`docs/book-ideas/TASKS.md`, task 3;
`scripts/book_ideas_big_winners.py`, outputs in `output/book_ideas_big_winners/`.)
A big winner start date is an S&P 500 stock-date from the model's eligible rows whose
return over the next 252 trading days is +100% or more. Entry is the next day's open,
exit is the close 252 days later, and delisted names keep their last close. Start dates
run 2010-01-04 to 2020-12-31, so no exit is later than 2021-12-31. The model inputs come
from the cached feature files `data/models/features/sp500_fund` and `sp500_levels`: 97
inputs (sector left out). For each input, every row gets its percentile within its date.
The gap is the winners' percentile minus that of the non-winners on the same date,
averaged over winner rows, in SDs of the input's percentile within the sub-period. The
momentum-adjusted gap compares winners only with non-winners in the same 12-1 month
momentum decile on the same date. Winners are rare and bunched together. 2010-13:
4,278 winner rows of 417,173 rows, on 763 dates, from 77 stocks. 2014-17: 2,637 of
459,133, on 818 dates, from 66 stocks. 2018-20: 11,634 of 367,706, on 579 dates, from
254 stocks, and 10,848 of those rows start in 2020, the rebound after the crash. Only
5 inputs pass 0.3 SD with the same sign in all three sub-periods, and only one of them,
63-day volatility, still passes after the momentum adjustment. Before their run, winners
had lower 12-1 month momentum than everyone else (−0.44, −0.11, −0.74 SD), not higher:
in this universe a double usually followed a fall, not a leader breaking out. The six
market-wide inputs (index trend, breadth) show 0 by construction, because every stock
has the same value on a date.

| input | raw 2010-13 / 2014-17 / 2018-20 (SD) | momentum-adjusted (SD) | big losers, raw (SD) |
|---|---|---|---|
| 63-day realized volatility | +1.13 / +1.17 / +1.12 | +0.70 / +0.68 / +0.60 | +1.34 / +1.12 / +0.97 |
| moving averages fully stacked bearish | +0.52 / +0.46 / +0.49 | +0.21 / +0.24 / +0.21 | +0.24 / +0.61 / +0.50 |
| distance up to nearest support/resistance line (ATRs) | +0.31 / +0.52 / +0.60 | +0.18 / +0.20 / +0.19 | +0.24 / +0.18 / +0.29 |
| trailing net margin | −0.82 / −0.41 / −0.43 | −0.65 / −0.24 / −0.16 | −0.20 / −0.20 / −0.38 |
| distance down to the 52-week low (ATRs) | −0.54 / −0.36 / −0.56 | −0.10 / −0.23 / −0.23 | −0.59 / −0.85 / −0.71 |

Effective N per sub-period is the number of distinct winner stocks (77 / 66 / 254), not
the 763 / 818 / 579 distinct dates. Each stock is a winner on many days in a row
(NFLX alone gives 435 rows), so the row counts overstate the evidence many times over.
"Big losers" are rows that fell 50% or more over the same 252 days (36 / 70 / 115
stocks).

*Against it.* The volatility gap is mostly the arithmetic of a 252-day window: a +100%
move needs a volatile stock. The big-loser column shows nearly the same gap, so
volatility marks big moves in either direction, not winners. The other four inputs look
like "beaten-down and volatile": far from resistance and close to the 52-week low in ATR
terms, bearish moving averages, thin margins. Losers look the same on the two distance
inputs, and the 2018-20 period is mostly one event, the stocks that bounced after the
2020 crash. Nothing here suggests a "leadership profile" score built from these inputs
would pick winners rather than volatility, so this look stops here.
