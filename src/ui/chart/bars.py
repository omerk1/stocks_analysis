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

from src.foundation.market_common import indicators
from src.foundation.market_common.data import load_and_validate
from src.foundation.market_common.models import Timeframe
from src.foundation.market_common.price_basis import PriceBasis
from src.ui.chart.config import MAKind, MASpec

CHART_BASIS = PriceBasis.TRADED


def load_chart_bars(conn: sqlite3.Connection, ticker: str, timeframe: Timeframe) -> pd.DataFrame:
    """All stored history for `ticker`, validated (impossible bars dropped).
    Empty when the ticker has no bars."""
    bars, _ = load_and_validate(conn, ticker.upper(), timeframe, basis=CHART_BASIS)
    return bars


def moving_averages(close: pd.Series, specs: tuple[MASpec, ...]) -> dict[str, pd.Series]:
    """One series per spec, keyed by `MASpec.key`; NaN through each warmup."""
    fns = {MAKind.SMA: indicators.sma, MAKind.EMA: indicators.ema}
    return {spec.key: fns[spec.kind](close, spec.period) for spec in specs}
