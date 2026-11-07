"""Indicator panes below the chart (`docs/features/chart_ui_design.md`, step 4): RSI,
MACD and relative strength against the market. Off by default, not ranked.

RSI and MACD are computed on the bars the chart shows (traded basis, the chart's
timeframe) with the shared `market_common.indicators` wrappers, so they end on the
chart's last bar.

The RS pane is the relative-strength module's own Mansfield oscillator, computed
with that module's own functions instead of read from the stored `rs_mansfield`
(only as fresh as the last RS run): the ticker's weekly total-return close over the
market's (SPY), in % from its own 52-week average, on completed weeks. On a daily
chart each day carries the last week completed before it, the module's
point-in-time rule, so the pane steps once a week and matches the stored values.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.foundation.market_common import indicators
from src.foundation.market_common.models import Timeframe
from src.signals.relative_strength import compute as rs_compute
from src.ui.chart.config import PaneConfig

RSI, MACD, RS = "rsi", "macd", "rs"
PANES = (RSI, MACD, RS)


@dataclass(frozen=True, eq=False)
class Pane:
    key: str
    label: str
    frame: pd.DataFrame
    note: str | None = None  # why the pane is empty, shown in the header


def pane_label(key: str, config: PaneConfig) -> str:
    fast, slow, signal = config.macd
    return {RSI: f"RSI {config.rsi_period}", MACD: f"MACD {fast}/{slow}/{signal}",
            RS: f"RS vs {config.market} (Mansfield)"}[key]


def pane_frame(key: str, bars: pd.DataFrame, config: PaneConfig) -> pd.DataFrame:
    """RSI or MACD on `bars`' index; NaN through warmups."""
    close = bars["close"]
    if key == RSI:
        return pd.DataFrame({"rsi": indicators.rsi(close, config.rsi_period)}, index=bars.index)
    if key == MACD:
        line, signal, hist = indicators.macd(close, *config.macd)
        return pd.DataFrame({"macd": line, "signal": signal, "hist": hist}, index=bars.index)
    raise ValueError(f"unknown pane {key!r}")


def rs_frame(index: pd.DatetimeIndex, timeframe: Timeframe, ticker_weekly: pd.Series,
             market_weekly: pd.Series, config: PaneConfig) -> pd.DataFrame:
    """The Mansfield oscillator on the chart's `index`, from weekly total-return
    closes (Monday-labelled, completed weeks). A weekly chart takes each week's
    value; a daily chart the last week completed before each day."""
    if ticker_weekly.empty or market_weekly.empty:
        return pd.DataFrame({"mansfield": np.nan}, index=index)
    weekly = rs_compute._weekly_mansfield(ticker_weekly, market_weekly, config.mansfield_weeks)
    if timeframe == Timeframe.WEEKLY:
        values = weekly.reindex(index)
    else:
        values = rs_compute._completed_weeks_as_of_daily(weekly, index)
    return pd.DataFrame({"mansfield": values.to_numpy()}, index=index)


def pane_range(key: str, frame: pd.DataFrame, start, end) -> list[float]:
    """The pane's y-range over [start, end]: RSI is always 0-100; the others fit what's
    in the window, with 0 kept in view (both oscillate around it); [-1, 1] when the
    window holds nothing (a warmup), so a stale range from a previous view never stays."""
    if key == RSI:
        return [0.0, 100.0]
    window = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    values = window.stack().dropna() if not window.empty else window
    if len(values) == 0:
        return [-1.0, 1.0]
    low, high = min(float(values.min()), 0.0), max(float(values.max()), 0.0)
    pad = (high - low) * 0.08 or 1.0
    return [low - pad, high + pad]
