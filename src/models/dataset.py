"""Dataset assembly for the modeling harness (`docs/modeling/VALIDATION_HARNESS.md`
§1 H1/H3, §2, §9 step 2): the holdout lock, the point-in-time universe, and the
on-disk label cache.

- **H1, holdout lock.** Nothing dated after `HOLDOUT_END` is read unless the
  caller passes `open_holdout=True`, which is logged and recorded with what it
  produced (the universe frame's `attrs`, the label cache's manifest).
- **H3, point-in-time universe.** A (ticker, date) row exists if the ticker was
  an index member on that date. Membership intervals get
  `ticker_renames.apply_renames` *first*, so a renamed member (FB -> META) keeps
  the prices that live under its new symbol. `eligible` = member AND passes the
  trailing liquidity floor AND `history_breaks.training_eligibility`. Each part
  is its own column, so a fold can say which filter removed which rows.
- **Labels, one horizon at a time** (`build_labels`), stored as one parquet file
  per side and horizon holding that horizon's 9 (U, D) cells. Only member rows
  are stored, liquidity and eligibility unapplied, so changing a floor never
  means relabeling.

Two price bases, on purpose and never mixed within one calculation
(`docs/decisions/price-basis.md`): labels, ATR and the decision close are
returns-based (`LABEL_BASIS`, total return); dollar volume and the
traded-price checks use the prices that actually traded (`UNIVERSE_BASIS`).
On each basis a ticker is read from yfinance, or from Tiingo if yfinance has
no bars for it at all (delisted members, `bulk_tiingo_ingest.py`) -- one
vendor per ticker, never spliced. The sources used are recorded in the
universe `attrs["spec"]` and the label manifest.

Everything here only reads the databases.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.foundation.data_processing import db
from src.foundation.data_processing.ticker_renames import apply_renames
from src.foundation.market_common.history_breaks import HistoryBreakConfig, training_eligibility
from src.foundation.market_common.price_basis import (
    MODULE_PRICE_BASIS, MODULES_WITH_FALLBACK, SPLITS_SOURCE_BY_BAR_SOURCE, PriceBasis, source_for, ticker_sources,
)
from src.foundation.market_common.price_disputes import DISPUTED_DAYS, DisputedDay, vendor_of
from src.models.labels.barriers import ATR_PERIOD, LONG, barrier_labels, v1_grid

logger = logging.getLogger(__name__)

HOLDOUT_END = pd.Timestamp("2021-12-31")

LABEL_BASIS = MODULE_PRICE_BASIS["models_labels"]
UNIVERSE_BASIS = MODULE_PRICE_BASIS["models_universe"]
# Delisted members yfinance can't serve are read from Tiingo, per ticker
# (`price_basis.MODULES_WITH_FALLBACK`).
LABEL_FALLBACK = "models_labels" in MODULES_WITH_FALLBACK
UNIVERSE_FALLBACK = "models_universe" in MODULES_WITH_FALLBACK

# index_membership.index_name -> per-row flag column
INDEX_FLAGS = {"sp500": "in_sp500", "nasdaq100": "in_ndx100"}
# Built but not stored yet (PR #129; needs a rerun on traded prices; delisted
# prices exist only for former S&P 500 / Nasdaq-100 members, Done #82). Asking
# for one is an error, not an empty set.
UNSTORED_INDICES = ("r1000_proxy", "r2000_proxy")

DOLLAR_VOLUME_WINDOW = 20
# Bars read before the requested start, for the liquidity window, ATR and the
# history-break tests (63-bar dormancy window). The traded series starts 2009-01-02.
BAR_WARMUP_DAYS = 400


@dataclass(frozen=True)
class LiquidityFloor:
    min_dollar_volume: float  # trailing DOLLAR_VOLUME_WINDOW-day median, $
    min_price: float | None = None  # actually traded close, $


# VALIDATION_HARNESS.md §2 defaults; each trial logs the ones it used.
LIQUIDITY_FLOORS = {
    "sp500": LiquidityFloor(20e6),
    "nasdaq100": LiquidityFloor(20e6),
    "r1000_proxy": LiquidityFloor(20e6),
    "r2000_proxy": LiquidityFloor(5e6, min_price=5.0),
}


class HoldoutError(ValueError):
    """A read would reach past `HOLDOUT_END` without `open_holdout=True`."""


def check_holdout(end: str | pd.Timestamp, open_holdout: bool = False) -> None:
    """H1. Raises unless `end` is inside the development window or the caller
    explicitly opened the holdout (which is logged)."""
    end = pd.Timestamp(end)
    if end <= HOLDOUT_END:
        return
    if not open_holdout:
        raise HoldoutError(
            f"end {end.date()} is past the holdout boundary {HOLDOUT_END.date()}; "
            "pass open_holdout=True only for a task that explicitly opens the holdout"
        )
    logger.warning("HOLDOUT OPEN: reading data through %s (boundary %s)", end.date(), HOLDOUT_END.date())


# ---------------------------------------------------------------- bars

def resolve_sources(
    conn: sqlite3.Connection, tickers: list[str], basis: PriceBasis | str, fallback: bool,
) -> dict[str, str]:
    """ticker -> the `bars_1d.source` its `basis` bars come from. Without
    `fallback`, every ticker maps to the basis's primary source (no lookup).
    With it (the modeling modules), a ticker whose vendor has a whole-history
    dispute (`price_disputes`, no date: e.g. a reused symbol whose bars are
    another company's) is left out, so it has no bars at all -- not in the
    universe, the per-date ranks or the labels."""
    if not fallback:
        return dict.fromkeys(tickers, source_for(basis))
    sources = ticker_sources(conn, tickers, basis, fallback=True)
    return {t: s for t, s in sources.items() if (t, vendor_of(s)) not in _whole_history_disputes()}


def _whole_history_disputes() -> set[tuple[str, str]]:
    return {(d.ticker, d.vendor) for d in DISPUTED_DAYS if d.date is None}


def _source_groups(sources: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for ticker, source in sources.items():
        groups.setdefault(source, []).append(ticker)
    return groups


def read_bars_bulk(
    conn: sqlite3.Connection, tickers: list[str], basis: PriceBasis | str,
    start: str | pd.Timestamp, end: str | pd.Timestamp, fallback: bool = False,
) -> pd.DataFrame:
    """Daily bars for many tickers on one price basis, long format (ticker,
    date, open, high, low, close, volume), partial rows dropped. One query per
    batch of tickers instead of one per ticker. With `fallback`, a ticker
    with no yfinance bars is read from Tiingo (`resolve_sources`);
    `attrs["price_sources"]` counts tickers per source."""
    basis = PriceBasis(basis)
    columns = ["ticker", "date", "open", "high", "low", "close", "volume"]
    sources = resolve_sources(conn, list(tickers), basis, fallback)
    frames = []
    for source, group in _source_groups(sources).items():
        for i in range(0, len(group), 500):  # SQLite's bound-parameter limit
            batch = group[i:i + 500]
            frames.append(pd.read_sql_query(
                "SELECT ticker, timestamp, open, high, low, close, volume FROM bars_1d "
                f"WHERE source = ? AND is_partial = 0 AND ticker IN ({','.join('?' * len(batch))}) "
                "AND timestamp >= ? AND timestamp <= ?",
                conn,
                params=[source, *batch,
                        pd.Timestamp(start).isoformat(),
                        (pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)).isoformat()],
            ))
    if not frames:
        bars = pd.DataFrame(columns=columns)
    else:
        bars = pd.concat(frames, ignore_index=True)
        bars["date"] = pd.to_datetime(bars.pop("timestamp")).dt.normalize()
        bars = bars.drop_duplicates(["ticker", "date"], keep="last").sort_values(["ticker", "date"])
        bars = bars[columns].reset_index(drop=True)
    bars.attrs["price_basis"] = basis.value
    bars.attrs["price_sources"] = {s: len(g) for s, g in _source_groups(sources).items()}
    bars.attrs["ticker_sources"] = sources
    return bars


def trading_calendar(
    conn: sqlite3.Connection, tickers: list[str], basis: PriceBasis | str,
    start: str | pd.Timestamp, end: str | pd.Timestamp, fallback: bool = False,
) -> pd.DatetimeIndex:
    """Every date on which any of `tickers` has a bar on `basis` in [start, end]."""
    dates = set()
    for source, group in _source_groups(resolve_sources(conn, list(tickers), basis, fallback)).items():
        for i in range(0, len(group), 500):
            batch = group[i:i + 500]
            dates.update(pd.read_sql_query(
                "SELECT DISTINCT timestamp FROM bars_1d "
                f"WHERE source = ? AND is_partial = 0 AND ticker IN ({','.join('?' * len(batch))}) "
                "AND timestamp >= ? AND timestamp <= ?",
                conn, params=[source, *batch, pd.Timestamp(start).isoformat(),
                              (pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59)).isoformat()],
            )["timestamp"])
    return pd.DatetimeIndex(pd.to_datetime(sorted(dates))).normalize().unique()


def _all_index_tickers(conn: sqlite3.Connection) -> list[str]:
    """Every symbol ever in a stored index, renamed to its price symbol."""
    members = pd.concat([apply_renames(conn, db.read_index_membership(conn, n)) for n in INDEX_FLAGS],
                        ignore_index=True)
    return sorted(members["ticker"].unique())


def _read_splits_bulk(conn: sqlite3.Connection, bar_sources: dict[str, str]) -> dict[str, pd.DataFrame]:
    """Per ticker, the splits from the vendor its bars came from (the
    adjustment those bars carry): yfinance's or Tiingo's."""
    out = {}
    for bar_source, group in _source_groups(bar_sources).items():
        splits = pd.read_sql_query(
            "SELECT ticker, execution_date, ratio FROM splits WHERE source = ?", conn,
            params=[SPLITS_SOURCE_BY_BAR_SOURCE[bar_source]], parse_dates=["execution_date"],
        )
        splits = splits[splits["ticker"].isin(group)]
        out.update({t: g.drop(columns="ticker") for t, g in splits.groupby("ticker")})
    return out


# ---------------------------------------------------------------- membership

def _check_indices(indices: tuple[str, ...]) -> None:
    if not indices:
        raise ValueError("at least one index is needed")
    for name in indices:
        if name in UNSTORED_INDICES:
            raise NotImplementedError(f"{name} membership is not stored yet (VALIDATION_HARNESS.md §10)")
        if name not in INDEX_FLAGS:
            raise ValueError(f"unknown index {name!r}; known: {sorted(INDEX_FLAGS)}")


def membership_rows(
    conn: sqlite3.Connection, indices: tuple[str, ...], calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """One row per (ticker, date in `calendar`) where the ticker was a member of
    any of `indices` -- the same answer as `db.read_index_membership(as_of=date)`
    for every date, computed once from the intervals. Renames are applied to the
    intervals first. Columns: ticker, date, one `INDEX_FLAGS` column per index."""
    _check_indices(indices)
    cal = np.asarray(pd.DatetimeIndex(calendar).sort_values().unique(), dtype="datetime64[ns]")
    parts = []
    for name in indices:
        intervals = apply_renames(conn, db.read_index_membership(conn, name))
        if intervals.empty:
            continue
        start = pd.to_datetime(intervals["start_date"]).to_numpy(dtype="datetime64[ns]")
        end = pd.to_datetime(intervals["end_date"]).fillna(pd.Timestamp.max).to_numpy(dtype="datetime64[ns]")
        lo = np.searchsorted(cal, start, side="left")
        hi = np.searchsorted(cal, end, side="right")  # end_date inclusive, as `read_index_membership`
        counts = np.maximum(hi - lo, 0)
        pos = np.concatenate([np.arange(a, b) for a, b in zip(lo, hi) if b > a]) if counts.sum() else np.array([], int)
        parts.append(pd.DataFrame({
            "ticker": np.repeat(intervals["ticker"].to_numpy(), counts),
            "date": cal[pos],
            "index": name,
        }))
    flags = [INDEX_FLAGS[n] for n in indices]
    if not parts:
        return pd.DataFrame({"ticker": pd.Series(dtype=object), "date": pd.Series(dtype="datetime64[ns]"),
                             **{f: pd.Series(dtype=bool) for f in flags}})
    long = pd.concat(parts, ignore_index=True)
    for name in indices:
        long[INDEX_FLAGS[name]] = long["index"].eq(name)
    # A renamed member can hold two overlapping intervals under one symbol.
    return long.groupby(["ticker", "date"], as_index=False)[flags].max().sort_values(["ticker", "date"],
                                                                                      ignore_index=True)


# ---------------------------------------------------------------- liquidity

def trailing_dollar_volume(traded_bars: pd.DataFrame, window: int = DOLLAR_VOLUME_WINDOW) -> pd.Series:
    """Median of close x volume over the `window` bars ending at each date
    (inclusive: known at that date's close, when the decision is made). NaN
    until a full window exists. Bars must be on the traded basis -- split
    adjustment cancels in close x volume, dividend adjustment doesn't."""
    if traded_bars.attrs.get("price_basis", UNIVERSE_BASIS.value) != UNIVERSE_BASIS.value:
        raise ValueError("dollar volume needs traded-basis bars")
    frame = traded_bars.sort_values(["ticker", "date"])
    dv = frame["close"] * frame["volume"]
    return dv.groupby(frame["ticker"]).transform(lambda s: s.rolling(window, min_periods=window).median())


# ---------------------------------------------------------------- universe

def universe_mask(
    conn: sqlite3.Connection,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    indices: tuple[str, ...] = ("sp500",),
    floors: dict[str, LiquidityFloor] | None = None,
    history_config: HistoryBreakConfig | None = None,
    open_holdout: bool = False,
) -> pd.DataFrame:
    """H3: the point-in-time universe for [start, end], one row per member
    (ticker, date). The same function serves training and prediction.

    Columns: ticker, date, the `INDEX_FLAGS` columns, `has_bars` (a traded bar
    exists that day -- False marks a member with no prices, e.g. a delisting
    without data), `dollar_volume_20d`, `unadjusted_close`, `liquid`,
    `history_eligible`, `eligible`.

    `liquid`: passes the floor of at least one index the row is a member of;
    False while the trailing window is incomplete. `eligible` = has_bars AND
    liquid AND history_eligible. The settings used are in `attrs["spec"]`.
    """
    check_holdout(end, open_holdout)
    _check_indices(indices)
    floors = {**LIQUIDITY_FLOORS, **(floors or {})}
    history_config = history_config or HistoryBreakConfig()
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    intervals = pd.concat([apply_renames(conn, db.read_index_membership(conn, n)) for n in indices],
                          ignore_index=True)
    tickers = sorted(intervals["ticker"].unique())
    bar_sources = resolve_sources(conn, tickers, UNIVERSE_BASIS, UNIVERSE_FALLBACK)
    bars = read_bars_bulk(conn, tickers, UNIVERSE_BASIS, start - pd.Timedelta(days=BAR_WARMUP_DAYS), end,
                          fallback=UNIVERSE_FALLBACK)
    calendar = pd.DatetimeIndex(bars.loc[bars["date"].between(start, end), "date"].unique()).sort_values()

    members = membership_rows(conn, indices, calendar)
    flags = [INDEX_FLAGS[n] for n in indices]

    bars["dollar_volume_20d"] = trailing_dollar_volume(bars)
    splits = _read_splits_bulk(conn, bar_sources)
    elig = []
    for ticker, g in bars.groupby("ticker", sort=False):
        flags_t = training_eligibility(g.set_index("date"), splits.get(ticker), history_config)
        elig.append(pd.DataFrame({
            "ticker": ticker, "date": flags_t.index,
            "unadjusted_close": flags_t["unadjusted_close"].to_numpy(),
            "history_eligible": flags_t["eligible"].to_numpy(),
        }))
    per_bar = bars[["ticker", "date", "dollar_volume_20d"]]
    if elig:
        per_bar = per_bar.merge(pd.concat(elig, ignore_index=True), on=["ticker", "date"], how="left")
    else:
        per_bar = per_bar.assign(unadjusted_close=np.nan, history_eligible=False)

    out = members.merge(per_bar, on=["ticker", "date"], how="left", indicator=True)
    out["has_bars"] = out.pop("_merge").eq("both")
    out["history_eligible"] = out["history_eligible"].fillna(False).astype(bool)

    dv = out["dollar_volume_20d"]
    liquid = pd.Series(False, index=out.index)
    for name, flag in zip(indices, flags):
        floor = floors[name]
        ok = dv >= floor.min_dollar_volume  # NaN (warm-up, no bars) -> False: not known to be liquid
        if floor.min_price is not None:
            ok &= out["unadjusted_close"] >= floor.min_price
        liquid |= out[flag] & ok
    out["liquid"] = liquid
    out["eligible"] = out["has_bars"] & out["liquid"] & out["history_eligible"]
    for col in ("dollar_volume_20d", "unadjusted_close"):
        out[col] = out[col].astype("float32")

    out = out[["ticker", "date", *flags, "has_bars", "dollar_volume_20d", "unadjusted_close",
               "liquid", "history_eligible", "eligible"]].reset_index(drop=True)
    out.attrs["spec"] = {
        "indices": list(indices), "start": str(start.date()), "end": str(end.date()),
        "floors": {n: asdict(floors[n]) for n in indices},
        "dollar_volume_window": DOLLAR_VOLUME_WINDOW,
        "history_config": asdict(history_config),
        "universe_basis": UNIVERSE_BASIS.value,
        "price_sources": bars.attrs["price_sources"],
        "open_holdout": bool(open_holdout),
    }
    return out


# ---------------------------------------------------------------- disputed days

# A fake one-day move distorts ATR(14) for weeks: Wilder smoothing keeps
# (13/14)^k of it after k bars, so a +45% day (DHR) still inflates ATR ~25%
# after 28 bars and ~10% after 42.
DISPUTE_ATR_TAIL = 3 * ATR_PERIOD


def drop_disputed(
    labels: pd.DataFrame, ticker_sources: dict[str, str], bars: pd.DataFrame, horizon: int,
    disputes: tuple[DisputedDay, ...] | None = None,
) -> tuple[pd.DataFrame, int]:
    """`labels` without the rows a disputed day reaches (`price_disputes`).

    Positions are counted on each ticker's own bars (`bars`: ticker, date),
    as the labels are: decision day t is dropped if a disputed day D of the
    vendor its bars came from is within its next `horizon` bars (the label
    window) or at most DISPUTE_ATR_TAIL bars before it (the ATR its barriers
    are sized with) -- D in [t - DISPUTE_ATR_TAIL, t + horizon] in bars. A
    disputed date the ticker has no bar on counts from the next bar. A
    dispute with no date drops the ticker. Returns (kept rows, number
    dropped)."""
    disputes = DISPUTED_DAYS if disputes is None else disputes
    if labels.empty or not disputes:
        return labels, 0
    drop = pd.Series(False, index=labels.index)
    for d in disputes:
        source = ticker_sources.get(d.ticker)
        if source is None or vendor_of(source) != d.vendor:
            continue
        mine = labels["ticker"] == d.ticker
        if not mine.any():
            continue
        if d.date is None:
            drop |= mine
            continue
        own = np.sort(bars.loc[bars["ticker"] == d.ticker, "date"].to_numpy(dtype="datetime64[ns]"))
        pos = pd.Series(np.searchsorted(own, labels.loc[mine, "date"].to_numpy(dtype="datetime64[ns]")),
                        index=labels.index[mine])
        p = int(np.searchsorted(own, np.datetime64(pd.Timestamp(d.date))))
        hit = pos.between(p - horizon, p + DISPUTE_ATR_TAIL)
        drop.loc[hit[hit].index] = True
    return labels[~drop], int(drop.sum())


# ---------------------------------------------------------------- label cache

def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class StaleLabelCacheError(ValueError):
    """A label cache was built for a different barrier grid than the current `v1_grid`."""


def _grid_cells(horizon: int) -> list[dict]:
    return [{"upper": c.upper, "lower": c.lower, "upper_atr": c.upper_atr, "lower_atr": c.lower_atr}
            for c in v1_grid() if c.horizon == horizon]


def label_path(out_dir: Path, horizon: int, side: str = LONG) -> Path:
    return Path(out_dir) / side / f"h={horizon}.parquet"


def build_labels(
    conn: sqlite3.Connection,
    rows: pd.DataFrame,
    horizon: int,
    out_dir: Path,
    side: str = LONG,
    open_holdout: bool = False,
    chunk_size: int = 50,
) -> Path:
    """Barrier labels for one horizon (all its v1 (U, D) cells) on the
    (ticker, date) rows of `rows` (normally `universe_mask(...)` restricted to
    `has_bars`), written to `label_path(out_dir, horizon, side)` with a JSON
    manifest beside it. Bars are read on `LABEL_BASIS` and cut at
    `HOLDOUT_END` (or at the rows' last date with `open_holdout`), so a window
    crossing the boundary is NaN. Adds `close_t`, the decision-day close the
    EV ranking uses (the entry price is the next open, not known at decision time).
    """
    cells = [c for c in v1_grid() if c.horizon == horizon]
    if not cells:
        raise ValueError(f"horizon {horizon} is not in the v1 grid")
    rows = rows[["ticker", "date"]].drop_duplicates()
    if rows.empty:
        raise ValueError("no rows to label")
    last_row = rows["date"].max()
    check_holdout(last_row, open_holdout)
    data_end = last_row if open_holdout else HOLDOUT_END

    tickers = sorted(rows["ticker"].unique())
    first = rows["date"].min() - pd.Timedelta(days=BAR_WARMUP_DAYS)
    # One calendar for every chunk and every call, so "delisted" means the same
    # thing whichever rows are passed: built from every ticker ever in a stored
    # index, not just these (a slice of early-ended names would otherwise set
    # its own end and never count as delisted).
    reference = sorted(set(tickers) | set(_all_index_tickers(conn)))
    calendar = trading_calendar(conn, reference, LABEL_BASIS, first, data_end, fallback=LABEL_FALLBACK)
    price_sources: dict[str, int] = {}
    n_disputed = 0

    path = label_path(out_dir, horizon, side)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    n_rows = 0
    try:
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            bars = read_bars_bulk(conn, chunk, LABEL_BASIS, first, data_end, fallback=LABEL_FALLBACK)
            for source, n in bars.attrs["price_sources"].items():
                price_sources[source] = price_sources.get(source, 0) + n
            if bars.empty:
                continue
            labels = barrier_labels(bars, cells, data_end=data_end, side=side, calendar=calendar)
            labels = labels.merge(bars[["ticker", "date", "close"]].rename(columns={"close": "close_t"}),
                                  on=["ticker", "date"], how="left")
            labels = labels.merge(rows[rows["ticker"].isin(chunk)], on=["ticker", "date"], how="inner")
            labels, dropped = drop_disputed(labels, bars.attrs["ticker_sources"], bars, horizon)
            n_disputed += dropped
            for col in labels.columns:
                if labels[col].dtype == "float64":
                    labels[col] = labels[col].astype("float32")
            table = pa.Table.from_pandas(labels, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema)
            writer.write_table(table.cast(writer.schema))
            n_rows += len(labels)
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise ValueError("no bars for any requested ticker")

    manifest = {
        "horizon": horizon, "side": side,
        "cells": _grid_cells(horizon),
        "data_end": str(pd.Timestamp(data_end).date()),
        "first_row": str(rows["date"].min().date()), "last_row": str(last_row.date()),
        "label_basis": LABEL_BASIS.value, "price_sources": price_sources, "open_holdout": bool(open_holdout),
        "n_rows": n_rows, "n_tickers": len(tickers), "n_disputed_dropped": n_disputed,
        "git_sha": _git_sha(), "created": pd.Timestamp.now("UTC").isoformat(),
    }
    path.with_suffix(".json").write_text(json.dumps(manifest, indent=2))
    return path


def _same_cells(stored: list[dict], current: list[dict]) -> bool:
    keys = ("upper", "lower", "upper_atr", "lower_atr")
    if len(stored) != len(current):
        return False
    return all(all(k in s and abs(s[k] - c[k]) < 1e-9 for k in keys) for s, c in zip(stored, current))


def read_labels(
    out_dir: Path, horizon: int, side: str = LONG,
    start: str | pd.Timestamp | None = None, end: str | pd.Timestamp | None = None,
    open_holdout: bool = False,
) -> pd.DataFrame:
    """A cached horizon's labels, optionally limited to [start, end]. Refuses a
    cache built with the holdout open unless the reader opens it too, and one
    built for a different barrier grid (e.g. before the 2026-10-06 rescale)."""
    path = label_path(out_dir, horizon, side)
    manifest = json.loads(path.with_suffix(".json").read_text())
    if not _same_cells(manifest.get("cells", []), _grid_cells(horizon)):
        raise StaleLabelCacheError(f"{path} was built for another barrier grid; rebuild it with build_labels")
    if manifest["open_holdout"] and not open_holdout:
        raise HoldoutError(f"{path} was built with the holdout open; pass open_holdout=True to read it")
    end = pd.Timestamp(end) if end is not None else pd.Timestamp(manifest["last_row"])
    check_holdout(end, open_holdout)
    filters = [("date", "<=", end)]
    if start is not None:
        filters.append(("date", ">=", pd.Timestamp(start)))
    labels = pq.read_table(path, filters=filters).to_pandas()
    labels.attrs["manifest"] = manifest
    return labels.sort_values(["ticker", "date", "upper", "lower"], ignore_index=True)
