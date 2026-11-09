"""Indicator panes below the chart (`docs/features/chart_ui_design.md`, step 4): RSI,
MACD and relative strength against the market. Off by default, not ranked.

RSI and MACD are computed on the bars the chart shows (traded basis, the chart's
timeframe) with the shared `market_common.indicators` wrappers, so they end on the
chart's last bar.

The RS line pane is the ticker's close over the market's on the chart's own bars,
with dots where it makes a new high (`rs_line_frame`): it moves day to day, like
the RS line charting sites draw under price.

The RS (Mansfield) pane is the relative-strength module's own Mansfield oscillator, computed
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

RSI, MACD, RS, RS_LINE = "rsi", "macd", "rs", "rs_line"
PANES = (RSI, MACD, RS_LINE, RS)


@dataclass(frozen=True, eq=False)
class Pane:
    key: str
    label: str
    frame: pd.DataFrame
    note: str | None = None  # why the pane is empty, shown in the header


def pane_label(key: str, config: PaneConfig) -> str:
    fast, slow, signal = config.macd
    return {RSI: f"RSI {config.rsi_period}", MACD: f"MACD {fast}/{slow}/{signal}",
            RS: f"RS vs {config.market} (Mansfield)", RS_LINE: f"RS line vs {config.market}"}[key]


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
    value; a daily chart the last week completed before each day, but only through
    the week after it: past that the next week would have completed, so a day with
    no newer week means the total-return prices have ended, and it's left blank
    rather than carrying a stale value forward."""
    if ticker_weekly.empty or market_weekly.empty:
        return pd.DataFrame({"mansfield": np.nan}, index=index)
    weekly = rs_compute._weekly_mansfield(ticker_weekly, market_weekly, config.mansfield_weeks)
    if timeframe == Timeframe.WEEKLY:
        values = weekly.reindex(index)
    else:
        values = rs_compute._completed_weeks_as_of_daily(weekly, index)
        last_week_end = weekly.dropna().index.max().to_period("W-SUN").end_time if weekly.notna().any() else None
        if last_week_end is not None:
            values = values.where(index <= last_week_end + pd.Timedelta(days=7))
    return pd.DataFrame({"mansfield": values.to_numpy()}, index=index)


def rs_data_end(ticker_weekly: pd.Series, market_weekly: pd.Series, index: pd.DatetimeIndex,
                timeframe: Timeframe) -> str | None:
    """A note when the Mansfield pane's total-return prices end before the chart's
    bars (the pane goes blank there), else None."""
    if ticker_weekly.empty or market_weekly.empty or index.empty:
        return None
    last = min(ticker_weekly.index.max(), market_weekly.index.max()).to_period("W-SUN").end_time
    shown_to = last + pd.Timedelta(days=7) if timeframe == Timeframe.DAILY else last
    if index.max() <= shown_to:
        return None
    return f"RS (Mansfield): total-return prices end the week of {last - pd.Timedelta(days=6):%Y-%m-%d}"


def rs_line_frame(bars: pd.DataFrame, market_bars: pd.DataFrame, timeframe: Timeframe,
                  config: PaneConfig) -> pd.DataFrame:
    """The RS line: the ticker's close over the market's on the chart's own bars
    (traded basis, so it runs to the chart's last bar; a price ratio, as charting
    sites draw it, not total return). `high` is the line where it makes a new high
    over the last 52 weeks (`rs_line_high_daily` / `_weekly` bars), the blue dots; NaN elsewhere and through
    the warmup, and wherever the market has no bar."""
    if bars.empty or market_bars.empty:
        return pd.DataFrame({"ratio": np.nan, "high": np.nan}, index=bars.index)
    ratio = bars["close"] / market_bars["close"].reindex(bars.index)
    window = config.rs_line_high_daily if timeframe == Timeframe.DAILY else config.rs_line_high_weekly
    # min_periods: a new high needs a full window behind it (a comparison isn't NaN-safe)
    rolling_high = ratio.rolling(window, min_periods=window).max()
    high = ratio.where((ratio >= rolling_high) & rolling_high.notna())
    return pd.DataFrame({"ratio": ratio, "high": high}, index=bars.index)


def pane_range(key: str, frame: pd.DataFrame, start, end) -> list[float]:
    """The pane's y-range over [start, end]: RSI is always 0-100; the others fit what's
    in the window, with 0 kept in view for the oscillators (MACD, Mansfield) but not
    the RS line (a ratio: 0 would squash it flat); [-1, 1] when the window holds
    nothing (a warmup), so a stale range from a previous view never stays."""
    if key == RSI:
        return [0.0, 100.0]
    window = frame.loc[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
    values = window.stack().dropna() if not window.empty else window
    if len(values) == 0:
        return [-1.0, 1.0]
    low, high = float(values.min()), float(values.max())
    if key != RS_LINE:
        low, high = min(low, 0.0), max(high, 0.0)
    pad = (high - low) * 0.08 or 1.0
    return [low - pad, high + pad]
