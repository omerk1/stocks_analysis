"""Feature panel: build, lag, and cache (DESIGN.md §4.4, §7.2).

`apply_lag` is the central lag application CLAUDE.md's one-bar-lag invariant requires
-- every feature that will be used to condition on a forward outcome must
pass through it before being paired with a label, rather than an analysis
module hand-rolling its own `.shift()`.

`build_panel` is Phase 2's starting-subset feature layer: SMA/EMA at
lookbacks {20, 50, 150, 200} (features/ma.py -- 150 added for M2,
PREREGISTRATION.md 2026-09-12), dist_pct/dist_atr/dist_z and the
`above` state (features/distance.py), slope_log_k at k in {5, 21, 63}
(features/slope.py), basic SMA/EMA full-stack booleans, (added for M4's
C2 matched control, DESIGN §6.1) `mom_12_1`/`realized_vol_63`
(features/context.py), (added for M1, DESIGN §8 -- PREREGISTRATION.md)
`run_length_bucket` per SMA lookback (features/state.py), SMA only this
slice, (added for M1's short-term-reversal confound check,
PREREGISTRATION.md 2026-09-09) `mom_1_0`, and (added for M2,
PREREGISTRATION.md 2026-09-12) `dist_from_52w_high`/`dist_from_52w_low`
(features/context.py). `write_panel`/`read_panel` cache it as
partitioned parquet per §4.4's schema.

`rs_rating` (Trend Template criterion 8, IBD-style RS rank) is
deliberately *not* joined in here -- it's cross-sectional, index-
membership-scoped (`relative_strength.compute.compute_stock_vs_market`),
unlike every feature above (per-ticker time series, no DB access beyond
this ticker's own bars). M2's own `prepare()` (`modules/stack_minervini.py`)
joins it onto a panel already built by this module and re-applies this
same `apply_lag` to just that one new column, rather than this module
taking on an index-membership dependency for every caller.

Not yet built (later scope, not this phase's): WMA/HMA/KAMA/VWMA, the full
lookback grid, ribbon/regime features, and point-in-time `mktcap_decile`/
`universe_flags` -- Phase 0's hygiene audit found the market-cap data
underneath those too thin to build honestly right now (only 1,011 of 5,304
active tickers have any `shares_outstanding` history, and none of it is
point-in-time). `sector` is included as best-effort context but is
current-state-only, not point-in-time (`docs/limitations.md`), and is
labelled as such in this module rather than silently treated as PIT-safe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import indicators
from src.foundation.market_common.data import load_bars, validate_bars
from src.foundation.market_common.models import Timeframe
from src.signals.moving_averages.features import context, distance, ma, slope, state

ATR_PERIOD = 14
_NON_FEATURE_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume")


def apply_lag(
    panel: pd.DataFrame, columns: list[str], ticker_col: str = "ticker", lag: int = 1
) -> pd.DataFrame:
    """Shift `columns` forward by `lag` row(s) *within each ticker* (never
    across ticker boundaries) -- a signal computed on the close of day t is
    only available for use starting day t+1 (DESIGN.md §7.2's one-bar lag),
    so the value on day t+1's row must be what was true as of day t's
    close, not day t+1's own close.

    `panel` must already be sorted by (ticker, date) within each ticker
    group (grouped shift respects the panel's existing row order, it
    doesn't re-sort). A naive global `.shift()` without grouping by ticker
    would bleed one ticker's trailing row(s) into the next ticker's
    leading `lag` row(s) -- the specific bug this guards against.
    """
    result = panel.copy()
    result[columns] = panel.groupby(ticker_col)[columns].shift(lag)
    return result


def _build_ticker_features(clean: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Raw (un-lagged) features for one already-validated ticker frame,
    indexed by date. Every feature that touches a given day's own
    high/low/close (ATR, every MA and everything derived from it) is
    computed here as "known as of that day's close" -- the panel-level
    lag that makes it *usable* starting the next day is applied once,
    centrally, in `build_panel`, not here.
    """
    frame = clean.copy()
    frame["ticker"] = ticker
    frame["atr_14"] = indicators.atr(frame, ATR_PERIOD)

    for family in ma.FAMILIES:
        for lookback in ma.LOOKBACKS:
            frame[ma.ma_column_name(family, lookback)] = ma.compute_ma(frame["close"], family, lookback)

    for family in ma.FAMILIES:
        for lookback in ma.LOOKBACKS:
            ma_col = ma.ma_column_name(family, lookback)
            ma_series = frame[ma_col]
            dist_pct_col = distance.dist_pct(frame["close"], ma_series)
            frame[f"dist_pct_{ma_col}"] = dist_pct_col
            frame[f"dist_atr_{ma_col}"] = distance.dist_atr(frame["close"], ma_series, frame["atr_14"])
            frame[f"dist_z_{ma_col}"] = distance.dist_z(dist_pct_col)
            frame[f"above_{ma_col}"] = distance.above(frame["close"], ma_series)
            for k in slope.SLOPE_K:
                frame[f"slope_log_{k}_{ma_col}"] = slope.slope_log_k(ma_series, k)

    # Run-length (state age, M1's sub-question, DESIGN §8) -- SMA only this
    # slice: PREREGISTRATION.md's M1 entry defers EMA state-agreement to a
    # separate Track A look rather than assuming redundancy (or
    # independence) and doubling this module's N_tests on it.
    for lookback in ma.LOOKBACKS:
        ma_col = ma.ma_column_name("sma", lookback)
        above_col = frame[f"above_{ma_col}"]
        run_id = state.state_run_id(above_col)
        days = state.days_in_run(above_col, run_id=run_id)
        frame[f"run_length_bucket_{ma_col}"] = state.run_length_bucket(days, run_id)

    # Basic stack/state (DESIGN §4.3 "Pairwise"/"Ribbon", starting-subset
    # version): fully bullish alignment across the three lookbacks within
    # each family. Not the full stack_perm categorical (24 states) --
    # that's later scope.
    # `distance.above` reused here (not `>` directly) for its NA handling --
    # a bare `sma_50 > sma_200` would silently read sma_200's warmup as
    # "not stacked" (False) instead of undefined, the same defect fixed in
    # `above` itself. Nullable "boolean" `&` propagates NA correctly
    # (Kleene logic), so a pairwise comparison already known False (e.g.
    # 20-vs-50 with both defined) short-circuits the AND even if the other
    # pairwise comparison is NA -- only genuinely undetermined cases end up
    # NA, not merely everything touching an undefined MA.
    frame["stacked_sma"] = distance.above(frame["sma_20"], frame["sma_50"]) & distance.above(
        frame["sma_50"], frame["sma_200"]
    )
    frame["stacked_ema"] = distance.above(frame["ema_20"], frame["ema_50"]) & distance.above(
        frame["ema_50"], frame["ema_200"]
    )

    # Context (DESIGN §4.3): the momentum/vol controls C2 matching needs
    # (§6.1). Added alongside M4, the first module that needs C2 -- see
    # PREREGISTRATION.md.
    frame["mom_12_1"] = context.mom_12_1(frame["close"])
    frame["realized_vol_63"] = context.realized_vol_63(frame["close"])
    frame["mom_1_0"] = context.mom_1_0(frame["close"])
    # Added for M2 (PREREGISTRATION.md, 2026-09-12): Trend Template
    # criteria 6/7 (52-week low/high proximity).
    frame["dist_from_52w_high"] = context.dist_from_52w_high(frame["close"])
    frame["dist_from_52w_low"] = context.dist_from_52w_low(frame["close"])

    return frame.reset_index().rename(columns={"timestamp": "date"})


def build_panel(
    conn: sqlite3.Connection,
    tickers: list[str],
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Builds the Phase 2 starting-subset MA feature panel for `tickers` --
    one row per (ticker, date), OHLCV plus every feature column (see this
    module's docstring for exactly what's included).

    Every feature column (everything except `ticker`/`date`/OHLCV) is
    passed through `apply_lag` before being returned, so a row at date d
    already reflects only information known as of close(d-1) -- ready to
    pair directly with a forward return computed starting date d, with no
    per-analysis lag bookkeeping needed (DESIGN §7.2 / CLAUDE.md's
    one-bar-lag invariant). `atr_14` is included in that lag: it's derived from the
    day's own high/low just like the MA features are, so it's subject to
    the same same-bar-availability timing.

    `end` is the holdout boundary (CLAUDE.md's holdout-lock invariant): passed through
    to `load_bars` as `as_of`, so data past it is never even loaded, not
    just excluded from a later plot/aggregate. Callers building anything
    for the development window MUST pass `end` explicitly (the CLI's
    `build-panel` command defaults it to the current holdout boundary for
    exactly this reason) -- leaving it `None` pulls all available history,
    including the holdout.

    `sector` is joined in from `ticker_sector` as best-effort context --
    current-state-only (see module docstring), not point-in-time.
    """
    frames = []
    for ticker in tickers:
        bars = load_bars(conn, ticker, Timeframe.DAILY, as_of=end, start=start)
        if bars.empty:
            continue
        clean, _ = validate_bars(bars, ticker)
        if clean.empty:
            continue
        frames.append(_build_ticker_features(clean, ticker))

    if not frames:
        return pd.DataFrame()

    panel = pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)

    # Identify which feature columns are boolean/string *before* lagging --
    # `.shift()` introduces a NaN into the first row of each ticker group,
    # which upcasts a plain `bool` column to `object` (True/False/nan);
    # checking dtype after the lag would silently misclassify every
    # boolean feature as numeric and cast it to float32 below. Every
    # boolean feature here (`above_*`, `stacked_sma`/`stacked_ema`) is
    # already nullable "boolean" dtype pre-lag, not plain `bool` --
    # `distance.above` returns "boolean" directly (its own NA-vs-warmup
    # fix) -- but plain `bool` is still checked too in case a future
    # feature returns it. Same reasoning for `run_length_bucket`'s
    # nullable "string" columns -- cast to float32 would fail outright
    # rather than silently misclassify.
    feature_cols = [c for c in panel.columns if c not in _NON_FEATURE_COLUMNS]
    bool_cols = [c for c in feature_cols if panel[c].dtype == bool or panel[c].dtype == "boolean"]
    string_cols = [c for c in feature_cols if panel[c].dtype == "string"]
    float_cols = [c for c in feature_cols if c not in bool_cols and c not in string_cols]

    panel = apply_lag(panel, columns=feature_cols)

    sectors = db.read_ticker_sector(conn)
    panel = panel.merge(sectors[["ticker", "sector"]], on="ticker", how="left")
    # Nullable string dtype, not plain object -- an object column mixing
    # NaN (missing before the lag/merge) and None (missing sector) round-
    # trips inconsistently through parquet (NaN comes back as None either
    # way), which silently breaks equality checks on cached-then-reloaded
    # panels.
    panel["sector"] = panel["sector"].astype("string")

    panel[float_cols] = panel[float_cols].astype("float32")
    # Nullable boolean dtype, not plain bool -- plain `bool` can't hold the
    # NaN the lag introduces into each ticker's first row.
    panel[bool_cols] = panel[bool_cols].astype("boolean")
    panel[string_cols] = panel[string_cols].astype("string")

    return panel


def write_panel(panel: pd.DataFrame, output_dir: Path) -> None:
    """Writes `panel` to `output_dir` as parquet partitioned by year
    (`ma_panel/year=YYYY/part-*.parquet`) -- so a later read can filter to
    a date range without loading the whole cache ("materialise per-module
    feature subsets rather than loading the whole thing," DESIGN.md §4.4).

    §4.4's schema box shows a `date=YYYY-MM-DD` directory name, but its own
    surrounding prose says "partition by year" for the full ~32M-row
    universe this is sized for -- the box illustrates the row/column
    shape (one row per ticker×date, wide), not a literal one-file-per-day
    layout. One file per exact date was tried first here and produced a
    146MB cache for a 10-ticker/4,171-date demo (~35KB/file) that should
    have been a few MB -- parquet's fixed per-file overhead dominates when
    a partition holds only a handful of rows, which any partition finer
    than "many tickers per file" will do until the universe is much
    larger than this phase's starting subset.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    years = pd.to_datetime(panel["date"]).dt.year
    for year, group in panel.groupby(years):
        partition_dir = output_dir / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        group.to_parquet(partition_dir / "part-0.parquet", index=False)


def read_panel(
    output_dir: Path, start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None
) -> pd.DataFrame:
    """Reads back a panel written by `write_panel`, optionally restricted
    to [`start`, `end`] -- only the year-partitions overlapping the range
    are read off disk (not the whole cache), then trimmed to the exact
    day bounds within those years.
    """
    partitions = sorted(output_dir.glob("year=*"))
    start_ts = pd.Timestamp(start) if start is not None else None
    end_ts = pd.Timestamp(end) if end is not None else None

    frames = []
    for partition in partitions:
        year = int(partition.name.removeprefix("year="))
        if start_ts is not None and year < start_ts.year:
            continue
        if end_ts is not None and year > end_ts.year:
            continue
        frames.append(pd.read_parquet(partition / "part-0.parquet"))

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if start_ts is not None:
        combined = combined[combined["date"] >= start_ts]
    if end_ts is not None:
        combined = combined[combined["date"] <= end_ts]
    return combined.sort_values(["ticker", "date"]).reset_index(drop=True)
