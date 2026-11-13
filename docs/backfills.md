# Backfills

Pure data refreshes of the shared databases (`data/raw/market_data.sqlite`,
`data/derived/analysis.sqlite`) with no code change, newest last. Refreshes
that came with a code change are logged in `docs/done.md` with that change.
One entry per refresh: what was fetched or recomputed, the command, the
dates the tables end on, row counts and anything that failed.

## 2026-11-10 → 11-13: bars and derived RS/breadth tables to 2026-11-06

**Before:** total-return bars (source `yfinance`) and Tiingo ended 2026-09-30;
traded bars (`yfinance_split_only`) ended 2026-11-06; `breadth`,
`relative_strength` and `sector_relative_strength` ended 2026-09-30.

1. **Total-return bars, full re-download** (it can't be appended to: every
   new dividend rescales all earlier prices, see done.md #81).
   `bulk_yfinance_ingest --start 1970-01-01 --end 2026-11-07
   --job-type yfinance_daily_refresh_20261109 --tickers <list>`, the list being
   the 514 current S&P 500 / Nasdaq-100 members with bars plus SPY and the 11
   sector ETFs (526). 524 ok, 2 failed (KVUE, WBD: no data, delisted); PSKY
   ends 2026-10-16. +19,230 rows; one ticker's first date moved. Seam check
   (total-return ÷ traded close must never step down): no drop since 2024 or
   over 3%; the older ones under 2% are Yahoo rounding on old low prices.
   ASML, PDD, ARM and EA are members with no bars (not CS tickers).
2. **Traded bars, incremental:** `bulk_yfinance_ingest --split-only --incremental`
   (job `yfinance_daily_split_only_incremental_20261110`): 5,106 appended,
   191 no new data, 1 full re-fetch, 47 failed (delistings and reused
   symbols whose Yahoo history now starts late, refused by design, plus KVUE,
   PSKY, WBD). Traded bars now end 2026-11-09, no partial bars.
3. **Tiingo:** not refreshed. Relative strength and breadth don't read it;
   only the modeling dataset does (T by choice, delisted members whose bars
   don't change).
4. **Derived tables:** the nine `refresh_derived` steps, full history, ran
   2026-11-12 20:32–23:05 UTC from a scratch script that stops before the
   sweep (the command has no dry run), so the delete count could be checked
   first: 0 rows in each table; the sweep then ran and deleted 0. A
   concurrent rebuild with done.md #191's combined S&P 500 + Nasdaq-100
   ranking ran at the same time and wrote each step after this one, so all
   stored rows are from those runs.

**After** (all three end 2026-11-06, the last total-return bar):

| table | before | after |
|---|---|---|
| `breadth` (4 slices) | 57,232 | 57,340 |
| `relative_strength` | 5,036,340 | 5,068,210 |
| `sector_relative_strength` | 67,575 | 67,978 |

Sector RS on 2026-11-06 (rating vs SPY): Healthcare 100, Energy 90.9,
Consumer Defensive 81.8, Financials 72.7, Materials 63.6, Real Estate 54.5,
Utilities 45.5, Technology 36.4, Consumer Cyclical 27.3, Industrials 18.2,
Communication Services 9.1. SPY is the benchmark, so it has no RS row of its
own. Above the 200-day average on 2026-11-06: S&P 500 58.2% of members / 59.9%
of cap; Nasdaq-100 44.8% of members / 50.3% of cap.
