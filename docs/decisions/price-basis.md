# Price basis: which price series each module uses

**Decided:** 2026-10-01. **Enforced by:** `src/foundation/market_common/price_basis.py` and
`tests/test_market_common_price_basis.py`.

## The rule

`bars_1d` holds the same yfinance daily bars on two bases:

| Basis | `bars_1d.source` | Adjusted for | Use it for |
|---|---|---|---|
| `total_return` | `yfinance` | splits **and** dividends | anything that measures **returns**: the dividend is part of what a holder earned |
| `traded` | `yfinance_split_only` | splits only | anything that places a **price level**, and market caps: the prices that actually traded, on today's share basis (TradingView's default chart) |

That's the target split. **Today the level modules are still on `total_return`** (see
"Planned" below); only market caps use `traded`.

Every module computes on exactly one basis, declared in its config (`price_basis`, or
`price_source` for the older modules) and taken from one central table,
`MODULE_PRICE_BASIS`. The shared loader (`market_common.data.load_bars` /
`load_and_validate`) has no default basis, so no code can load bars without saying which
kind. Loaded bars carry `attrs["price_basis"]`, and every run records its config, basis
included, in the `runs` table.

## Module by module

| Module | Basis today | Planned | Why |
|---|---|---|---|
| gaps, avwap, volume_profile, sr_lines, fibonacci, market_structure, patterns | `total_return` | **`traded`** | They place price levels, which belong where trades happened. |
| divergences | `total_return` | **`traded`** | Chart-based price pivots compared with an indicator, as on a chart. |
| market caps (`market_cap.PRICE_SOURCE`) | `traded` | `traded` | Market cap = the price that traded × shares outstanding (Done #67). |
| moving_averages (the MA study) | `total_return` | `total_return` | Return-based study, finished on this basis. Changing it would reopen its results. |
| relative_strength, breadth | `total_return` | `total_return` | Built on returns and return-based state. |
| modeling labels (`src/models/labels`) | the caller's choice | — | Labels are returns, so `total_return` fits. LRP's level features must use the same basis as the levels they measure. |

## Why levels should move to `traded`

- **Dividend adjustment moves old levels away from where they really were**, and the error
  grows with age. KO on 2012-04-30 closed at $38.16 split-only versus $24.46 fully adjusted.
  A 10-year-old level on a ~3% yielder is off by roughly 25–30%.
- **The whole dividend-adjusted history rescales with every new dividend.** Stored levels
  silently drift: 999 of AAPL's 2,809 stored gaps no longer matched the bars one day after
  storing (2026-09-30).
- **On `traded`, history only changes when a stock splits**, which is rare and visible in
  the `splits` table. That makes it possible to append new days without recomputing
  everything (see "Updates" below).

## Rules that follow from it

- **Never mix bases within one calculation.** A level and the close or ATR it's compared
  with must come from the same basis. Ratios like `(level − close) / ATR` are the safe way
  to combine one module's levels with another module's features.
- **Stored level tables are tied to the basis and bars of their run.** `gaps.store.read_gaps`
  refuses stored gaps when the bars passed in are on another basis, or when zones no longer
  match the bars. Other level tables have no read-back path; recompute with `as_of`.
- **Changing a module's basis means:**
  1. update `MODULE_PRICE_BASIS` and this table;
  2. rerun that module's stored results;
  3. update any real-data tests that pin values.

## Updates

- **`total_return` data must be re-fetched over its full history** on every refresh.
  Appending only new days leaves a seam wherever a dividend fell in between.
- **`traded` data can be extended with new days.** Re-fetch a ticker's full history only
  when it has split since the last fetch.
- **Level modules still recompute fully on each run today.** Incremental runs are possible
  on `traded`, but not built.

## Planned: moving the level modules to `traded`

Not done yet, deliberately. The enforcement (the table, the required basis, the guards and
the tests) went in first with no change to any module's data. The switch:

1. Extend `traded` bars back to each ticker's start; they begin 2009-01-02 today.
2. Change the eight level-module rows in `MODULE_PRICE_BASIS` to `TRADED`, and update this
   table.
3. Rerun those modules' stored results, and update real-data tests that pin values.

Best done before LRP's level features are built, so they start on the right basis.

## History

Before 2026-10-01, every module read `yfinance` (`total_return`) implicitly, through a fixed
`REQUIRED_SOURCE` in the shared loader, except market caps, which moved to `traded` in
Done #67. From 2026-10-01 every module states its basis explicitly; the values didn't change.
