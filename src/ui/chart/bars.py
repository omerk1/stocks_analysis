"""Bars and moving averages for the chart.

Prices are on the TRADED basis (split-adjusted only), what TradingView shows by
default and what the price-level modules (S/R, gaps, AVWAP) are computed on, so
their lines will sit on these bars in step 2 (`market_common.price_basis`). The
moving averages are computed here on the displayed closes, not read from the
moving-averages study's panel (that one is on total-return prices, which would
put the line below the bars on a dividend payer).

Weekly bars come from `market_common.data.load_bars`, which resamples the daily
bars and leaves out the week still in progress.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from src.foundation.market_common import indicators, price_basis
from src.foundation.market_common.data import load_and_validate
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import PriceBasis
from src.ui.chart.config import MAKind, MASpec

CHART_BASIS = PriceBasis.TRADED


def load_chart_bars(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe,
                    basis: PriceBasis = CHART_BASIS) -> pd.DataFrame:
    """All stored history for `ticker`, validated (impossible bars dropped).
    Empty when the ticker has no bars. `basis`: another price basis, for a pane
    that must match a module computed on it (the RS pane: total return).

    The bars come from `chart_source`. It's kept in `attrs["source"]`, so the level
    detectors that load their own bars read the same vendor (`overlays.py`)."""
    ticker = ticker.upper()
    source = chart_source(conn, ticker, basis)
    bars, _ = load_and_validate(conn, ticker, timeframe, basis=basis, source=source)
    bars.attrs["source"] = source
    return bars


def chart_source(conn: sqlite3.Connection, ticker: str, basis: PriceBasis) -> str:
    """The `bars_1d.source` the chart reads `ticker` from: the basis's primary one
    (yfinance) whenever it has bars, as before, so the chart shows the latest bars;
    else the fallback (Tiingo: ARM, ASML, PDD, delisted members). Unlike the modules
    that opt into the fallback (`price_basis.resolve_sources`, and the Groups page),
    there's no `PREFER_TIINGO` swap and no dropping a disputed yfinance history: the
    chart is a display and keeps showing what yfinance has. Tiingo bars under a
    whole-history dispute (another company's under a reused symbol) aren't used; the
    primary source is returned then, and the ticker has no bars.

    Like `price_basis.ticker_sources`, any bar counts: a ticker with a few yfinance rows
    is read from yfinance. Both probes are the shared ones: the primary through
    `ticker_sources` without the fallback (no swap, no dispute check), the fallback
    through `resolve_sources` (its dispute policy), reached only without yfinance bars."""
    primary = price_basis.source_for(basis)
    if ticker in price_basis.ticker_sources(conn, [ticker], basis, fallback=False):
        return primary
    try:
        return price_basis.resolve_sources(conn, [ticker], basis, fallback=True).get(ticker, primary)
    except ValueError:  # a PREFER_TIINGO ticker with no bars on either vendor
        return primary


def moving_averages(close: pd.Series, specs: tuple[MASpec, ...]) -> dict[str, pd.Series]:
    """One series per spec, keyed by `MASpec.key`; NaN through each warmup."""
    fns = {MAKind.SMA: indicators.sma, MAKind.EMA: indicators.ema}
    return {spec.key: fns[spec.kind](close, spec.period) for spec in specs}
