"""Relative strength: how a stock/sector is performing against a benchmark,
on three axes -- stock-vs-market, stock-vs-sector, sector-vs-market. Each
axis is the same underlying primitive (an RS ratio line + Mansfield
oscillator against one benchmark, plus an IBD-style 1-99 percentile Rating
against a peer group) applied to a different pairing:

- stock-vs-market: every stock in an index vs `config.market_benchmark`
  (e.g. SPY), rs_rating ranked against every other stock in that index.
- stock-vs-sector: every stock vs its own GICS-style sector's SPDR ETF
  (`db.read_ticker_sector` -> `config.SECTOR_ETF_MAP`), rs_rating ranked
  only against same-sector peers.
- sector-vs-market: the 11 sector ETFs themselves vs `config
  .market_benchmark`, rs_rating ranked among just the 11 sectors.

Cross-sectional like `src/breadth/`, but with a second, different ticker's
price series joined in -- the first place in this codebase two different
tickers' price series are compared directly (see `indicators.ratio`).
Point-in-time correct for the stock-level axes via the same
`index_membership` interval join `breadth/compute.py` uses -- a ticker only
counts for dates it was actually a member.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.data_processing import db
from src.market_common import indicators
from src.market_common.data import load_bars
from src.market_common.models import Timeframe
from src.relative_strength.config import SECTOR_ETF_MAP, RelativeStrengthConfig

_RESULT_COLUMNS = ["ticker", "date", "benchmark", "rs_ratio", "rs_mansfield", "rs_rating"]
_SECTOR_RESULT_COLUMNS = ["sector", "date", "benchmark", "rs_ratio", "rs_mansfield", "rs_rating"]


def _load_closes(conn: sqlite3.Connection, tickers: list[str], source: str) -> pd.DataFrame:
    """Bulk-load `bars_1d` close prices for every ticker in `tickers` (one
    query, not one per ticker) -- long format: ticker, date, close. Same
    query shape as `breadth/compute.py:_load_closes`; not shared cross-
    module, matching how every existing detector module keeps its own
    private loader.
    """
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    placeholders = ",".join("?" for _ in tickers)
    query = (
        f"SELECT ticker, timestamp AS date, close FROM bars_1d "
        f"WHERE source = ? AND ticker IN ({placeholders}) ORDER BY ticker, timestamp"
    )
    return pd.read_sql_query(query, conn, params=[source, *tickers], parse_dates=["date"])


def _closes_by_ticker(prices: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        ticker: group.set_index("date")["close"].sort_index()
        for ticker, group in prices.groupby("ticker")
    }


def _weekly_close(conn: sqlite3.Connection, ticker: str) -> pd.Series:
    """Weekly close series for `ticker`, resampled live from `bars_1d` --
    reuses `market_common.data.load_bars(..., Timeframe.WEEKLY)` directly
    rather than reading the separately-ingested `bars_1w` table (known
    incomplete for several tickers, e.g. T and GEVO both have zero rows
    despite a fully backfilled `bars_1d`) or duplicating its resample
    logic here.

    `load_bars` hardcodes source=yfinance (every weekly consumer in this
    codebase does -- mixing Polygon/yfinance adjustment conventions
    produces phantom levels, per `market_common/data.py`'s docstring), so
    this is yfinance-only regardless of `RelativeStrengthConfig
    .price_source` -- consistent with the rest of the codebase's weekly
    handling, not a new inconsistency.
    """
    weekly = load_bars(conn, ticker, Timeframe.WEEKLY)
    return weekly["close"] if not weekly.empty else pd.Series(dtype="float64", name="close")


def _weekly_mansfield(
    target_weekly_close: pd.Series, benchmark_weekly_close: pd.Series, period: int
) -> pd.Series:
    """Mansfield oscillator on WEEKLY closes -- the textbook definition (a
    52-*week* SMA of a weekly RS ratio line, ~1 year), unlike rs_ratio/
    rs_rating below which stay on daily bars. Indexed by each week's start
    date; callers reindex/forward-fill this onto their own daily date
    index in `_rs_frame` -- each trading day carries the most recently
    *completed* week's value, updating once a week, standard for a
    weekly-computed oscillator plotted against a daily timeline.
    """
    weekly_ratio = indicators.ratio(target_weekly_close, benchmark_weekly_close)
    if weekly_ratio.empty:
        return pd.Series(dtype="float64")
    return indicators.mansfield_rs(weekly_ratio, period)


def _ibd_weighted_return(
    close: pd.Series, windows: tuple[int, ...], weights: tuple[float, ...]
) -> pd.Series:
    """IBD-style trailing return: a weighted sum of pct-change over each of
    `windows` (heavier weight on the most recent, per `weights`). NaN until
    every window has real history to look back on -- never a partial score
    computed from only the windows that happen to be available yet.
    """
    total = pd.Series(0.0, index=close.index)
    for window, weight in zip(windows, weights):
        total = total + weight * (close / close.shift(window) - 1)
    return total


def _rs_frame(
    key: str, key_value: str, close: pd.Series, benchmark_ticker: str, benchmark_close: pd.Series,
    weekly_mansfield: pd.Series, config: RelativeStrengthConfig,
) -> pd.DataFrame | None:
    """Ratio + Mansfield + IBD-weighted-return for one (target, benchmark)
    pair -- `rs_rating` itself isn't filled in here since it's a cross-
    sectional percentile computed once across the whole result set by the
    caller, not per-pair. `weekly_mansfield` is `_weekly_mansfield`'s
    output (weekly-dated); forward-filled here onto `rs_ratio`'s daily
    dates, so a week with no new bar yet still carries last week's value
    rather than going NaN.
    """
    rs_ratio = indicators.ratio(close, benchmark_close)
    if rs_ratio.empty:
        return None
    rs_mansfield = weekly_mansfield.reindex(rs_ratio.index, method="ffill")
    weighted_return = _ibd_weighted_return(
        close, config.rs_rating_windows, config.rs_rating_weights
    ).reindex(rs_ratio.index)
    return pd.DataFrame(
        {
            key: key_value,
            "date": rs_ratio.index,
            "benchmark": benchmark_ticker,
            "rs_ratio": rs_ratio.to_numpy(),
            "rs_mansfield": rs_mansfield.to_numpy(),
            "weighted_return": weighted_return.to_numpy(),
        }
    )


def _restrict_to_membership(frame: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    """Survivorship-safe interval join -- same pattern as
    `breadth/compute.py`'s membership merge: a ticker only counts for
    dates within its own point-in-time membership interval(s).
    """
    merged = frame.merge(membership[["ticker", "start_date", "end_date"]], on="ticker", how="inner")
    in_interval = (merged["date"] >= merged["start_date"]) & (
        merged["end_date"].isna() | (merged["date"] <= merged["end_date"])
    )
    return merged[in_interval].copy()


def compute_stock_vs_market(
    conn: sqlite3.Connection, index_name: str, config: RelativeStrengthConfig
) -> pd.DataFrame:
    """Per (ticker, date): RS ratio/Mansfield oscillator against
    `config.market_benchmark`, and an rs_rating percentile-ranked against
    every other ticker in `index_name`'s point-in-time membership that
    date. Empty if the index has no membership rows or the benchmark has
    no local price data.
    """
    membership = db.read_index_membership(conn, index_name)
    if membership.empty:
        return pd.DataFrame()
    membership = membership.copy()
    membership["start_date"] = pd.to_datetime(membership["start_date"])
    membership["end_date"] = pd.to_datetime(membership["end_date"])

    tickers = sorted(membership["ticker"].unique())
    prices = _load_closes(conn, tickers, config.price_source)
    if prices.empty:
        return pd.DataFrame()

    benchmark_prices = _load_closes(conn, [config.market_benchmark], config.price_source)
    if benchmark_prices.empty:
        return pd.DataFrame()
    benchmark_close = benchmark_prices.set_index("date")["close"].sort_index()
    benchmark_weekly_close = _weekly_close(conn, config.market_benchmark)

    frames = []
    for ticker, close in _closes_by_ticker(prices).items():
        weekly_mansfield = _weekly_mansfield(
            _weekly_close(conn, ticker), benchmark_weekly_close, config.mansfield_period
        )
        frame = _rs_frame(
            "ticker", ticker, close, config.market_benchmark, benchmark_close,
            weekly_mansfield, config,
        )
        if frame is not None:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    result = _restrict_to_membership(combined, membership)
    if result.empty:
        return pd.DataFrame()

    result["rs_rating"] = result.groupby("date")["weighted_return"].transform(
        indicators.percentile_rank
    )

    return result[_RESULT_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def compute_stock_vs_sector(
    conn: sqlite3.Connection, index_name: str, config: RelativeStrengthConfig
) -> pd.DataFrame:
    """Per (ticker, date): RS ratio/Mansfield oscillator against the
    ticker's own sector's SPDR ETF (via `db.read_ticker_sector` ->
    `SECTOR_ETF_MAP`), and an rs_rating percentile-ranked only against
    same-sector peers that date -- deliberately *not* the whole index (see
    `compute_stock_vs_market` for that). A ticker with no sector on file,
    or a sector this codebase has no ETF mapping for, is skipped -- no
    data to compare it against, not a wrong 0.
    """
    membership = db.read_index_membership(conn, index_name)
    if membership.empty:
        return pd.DataFrame()
    membership = membership.copy()
    membership["start_date"] = pd.to_datetime(membership["start_date"])
    membership["end_date"] = pd.to_datetime(membership["end_date"])

    tickers = sorted(membership["ticker"].unique())
    prices = _load_closes(conn, tickers, config.price_source)
    if prices.empty:
        return pd.DataFrame()

    sectors = db.read_ticker_sector(conn)
    sector_by_ticker = dict(zip(sectors["ticker"], sectors["sector"]))

    etf_tickers = sorted(set(SECTOR_ETF_MAP.values()))
    etf_close = _closes_by_ticker(_load_closes(conn, etf_tickers, config.price_source))
    etf_weekly_close = {etf: _weekly_close(conn, etf) for etf in etf_tickers}

    frames = []
    sector_by_row_ticker = {}
    for ticker, close in _closes_by_ticker(prices).items():
        sector = sector_by_ticker.get(ticker)
        benchmark_ticker = SECTOR_ETF_MAP.get(sector) if sector else None
        if benchmark_ticker is None or benchmark_ticker not in etf_close:
            continue
        weekly_mansfield = _weekly_mansfield(
            _weekly_close(conn, ticker), etf_weekly_close[benchmark_ticker], config.mansfield_period
        )
        frame = _rs_frame(
            "ticker", ticker, close, benchmark_ticker, etf_close[benchmark_ticker],
            weekly_mansfield, config,
        )
        if frame is not None:
            frames.append(frame)
            sector_by_row_ticker[ticker] = sector
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["sector"] = combined["ticker"].map(sector_by_row_ticker)
    result = _restrict_to_membership(combined, membership)
    if result.empty:
        return pd.DataFrame()

    result["rs_rating"] = result.groupby(["date", "sector"])["weighted_return"].transform(
        indicators.percentile_rank
    )

    return result[_RESULT_COLUMNS].sort_values(["date", "ticker"]).reset_index(drop=True)


def compute_sector_vs_market(
    conn: sqlite3.Connection, config: RelativeStrengthConfig
) -> pd.DataFrame:
    """Per (sector, date): the sector's SPDR ETF itself as the target,
    RS ratio/Mansfield oscillator against `config.market_benchmark`, and
    an rs_rating percentile-ranked among just the 11 sectors that date --
    necessarily coarse with only 11 points, the standard limitation of any
    sector-rotation view, not a bug. Not index_membership-scoped -- sector
    ETFs trade continuously once ingested, no point-in-time roster concept.
    """
    etf_tickers = sorted(set(SECTOR_ETF_MAP.values()))
    etf_prices = _load_closes(conn, etf_tickers, config.price_source)
    if etf_prices.empty:
        return pd.DataFrame()

    benchmark_prices = _load_closes(conn, [config.market_benchmark], config.price_source)
    if benchmark_prices.empty:
        return pd.DataFrame()
    benchmark_close = benchmark_prices.set_index("date")["close"].sort_index()
    benchmark_weekly_close = _weekly_close(conn, config.market_benchmark)

    sector_by_etf = {etf: sector for sector, etf in SECTOR_ETF_MAP.items()}

    frames = []
    for etf_ticker, close in _closes_by_ticker(etf_prices).items():
        sector = sector_by_etf.get(etf_ticker, etf_ticker)
        weekly_mansfield = _weekly_mansfield(
            _weekly_close(conn, etf_ticker), benchmark_weekly_close, config.mansfield_period
        )
        frame = _rs_frame(
            "sector", sector, close, config.market_benchmark, benchmark_close,
            weekly_mansfield, config,
        )
        if frame is not None:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined["rs_rating"] = combined.groupby("date")["weighted_return"].transform(
        indicators.percentile_rank
    )

    return combined[_SECTOR_RESULT_COLUMNS].sort_values(["date", "sector"]).reset_index(drop=True)
