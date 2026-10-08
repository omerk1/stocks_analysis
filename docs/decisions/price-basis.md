# Price basis: which price series each module uses

**Decided:** 2026-10-01; level modules switched to `traded` 2026-10-02. **Enforced by:** `src/foundation/market_common/price_basis.py` and
`tests/test_market_common_price_basis.py`.

## The rule

`bars_1d` holds the same yfinance daily bars on two bases:

| Basis | `bars_1d.source` | Adjusted for | Use it for |
|---|---|---|---|
| `total_return` | `yfinance` | splits **and** dividends | anything that measures **returns**: the dividend is part of what a holder earned |
| `traded` | `yfinance_split_only` | splits only | anything that places a **price level**, and market caps: the prices that actually traded, on today's share basis (TradingView's default chart) |

Every module computes on exactly one basis, declared in its config (`price_basis`, or
`price_source` for the older modules) and taken from one central table,
`MODULE_PRICE_BASIS`. The shared loader (`market_common.data.load_bars` /
`load_and_validate`) has no default basis, so no code can load bars without saying which
kind. Loaded bars carry `attrs["price_basis"]`, and every run records its config, basis
included, in the `runs` table.

## Module by module

| Module | Basis | Why |
|---|---|---|
| gaps, avwap, volume_profile, sr_lines, fibonacci, market_structure, patterns | `traded` | They place price levels, which belong where trades happened. |
| divergences | `traded` | Chart-based price pivots compared with an indicator, as on a chart. |
| market caps (`market_cap.PRICE_SOURCE`) | `traded` | Market cap = the price that traded × shares outstanding (Done #67). |
| moving_averages (the MA study) | `total_return` | Return-based study, finished on this basis. Changing it would reopen its results. |
| relative_strength, breadth | `total_return` | Built on returns and return-based state. |
| modeling labels (`src/models/dataset.py`, `models_labels`) | `total_return` | Labels, ATR and the decision-day close are returns. LRP's level features must use the level modules' basis (`traded`) for the level, close and ATR alike. |
| modeling universe (`src/models/dataset.py`, `models_universe`) | `traded` | The liquidity floor (close × volume) and the penny/price-floor checks need the prices that traded; dividend adjustment would make the dollar-volume floor stricter in older years. |
| modeling baseline features (`src/models/features/baseline.py`, `models_features`) | `total_return` | The MA study's factor definitions (momentum, volatility, reversal, extension), on the study's basis. |

## Delisted members: Tiingo fallback (2026-10-05)

Index members yfinance can't serve (delisted before it could) have Tiingo bars on the same
two bases: `tiingo` (total return) and `tiingo_split_only` (traded), plus their splits under
`splits.source = 'tiingo'` (`bulk_tiingo_ingest.py`, Done #82). A module reads them only if
it's in `price_basis.MODULES_WITH_FALLBACK`: the three modeling modules
(`models_labels`, `models_universe`, `models_features`), so delisted members aren't missing
from the training set, and since 2026-10-08 `divergences` (its event base was survivors-only
— the backlog's Signals item; detection, context scalars and control pairs all resolve the
same per-ticker vendor, and a whole-history-disputed ticker is skipped everywhere).
Everything else, the MA study included, reads yfinance only.

- **One vendor per ticker, never spliced.** A ticker with any yfinance bars on the basis is
  read from yfinance alone; only a ticker with none is read from Tiingo
  (`price_basis.ticker_sources`). The choice doesn't depend on the dates asked for.
- **Splits come from the same vendor as the bars** (`SPLITS_SOURCE_BY_BAR_SOURCE`), since
  `history_breaks` recovers traded prices from them.
- **The sources used are recorded:** the universe's `attrs["spec"]["price_sources"]` and the
  label manifest's `price_sources` count tickers per source.
- Checked on overlapping tickers: on ordinary days the vendors agree (KO and AAPL <0.1%).
  Around corporate actions each has its own errors (Done #86), so the modeling labels also
  skip reviewed disputed days (`market_common/price_disputes.csv`), and a ticker whose
  yfinance error can't be masked (T's dividend drift) is read from Tiingo instead
  (`market_common/vendor_overrides.PREFER_TIINGO`).

## Why levels are on `traded`

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
- **Outcomes measured inside a level module are price returns, on `traded`.** The patterns
  and market-structure backtests and the gap-fill analysis check whether price reached a
  target, stop or zone, which are levels, so they use the same series as the levels.
  Switching only their returns to `total_return` would compare levels and prices from two
  series. The cost is known and small: those returns leave out dividends, about the
  dividend yield × the horizon (e.g. ~0.5% over a quarter for a 2% yielder). Anything that
  measures **total** return (the MA study, modeling labels) uses `total_return`.
- **Stored level tables are tied to the basis and bars of their run.** `gaps.store.read_gaps`
  refuses stored gaps when the bars passed in are on another basis, or when zones no longer
  match the bars. Other level tables have no read-back path; recompute with `as_of`.
- **Changing a module's basis means:**
  1. update `MODULE_PRICE_BASIS` and this table;
  2. rerun that module's stored results;
  3. run `python -m src.foundation.market_common.basis_cleanup` (dry run, then `--apply`).
     Most stores only insert or update, so rows only the old prices produced would otherwise
     stay, on the old basis;
  4. update any real-data tests that pin values.

## Updates

- **`total_return` data must be re-fetched over its full history** on every refresh.
  Appending only new days leaves a seam wherever a dividend fell in between.
- **`traded` data can be extended with new days.** Re-fetch a ticker's full history only
  when it has split since the last fetch. `bulk_yfinance_ingest --split-only --incremental`
  does this (Done #81): it re-fetches a few days of overlap, appends when the overlapping
  closes are unchanged, and re-fetches the full history when they differ.
- **Level modules still recompute fully on each run today.** Incremental runs are possible
  on `traded`, but not built.

## History

Before 2026-10-01, every module read `yfinance` (`total_return`) implicitly, through a fixed
`REQUIRED_SOURCE` in the shared loader, except market caps, which moved to `traded` in
Done #67. From 2026-10-01 every module states its basis explicitly (Done #73, no values
changed). On 2026-10-02 the eight level modules moved to `traded` (Done #74), after `traded`
history was extended back to 1970 and checked against `total_return`. The two sources cover
the same tickers; `traded` has a few extra old days for 84 of 305 sampled tickers. Their
price ratio changes only on dividends and distributions: spin-offs and special dividends show
as single steps, e.g. VLO 1997-08-01 and CCO's 2012/2016 special dividends.
