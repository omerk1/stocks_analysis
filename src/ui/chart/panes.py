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
    return rs_pane_data(index, timeframe, ticker_weekly, market_weekly, config)[0]


def rs_pane_data(index: pd.DatetimeIndex, timeframe: Timeframe, ticker_weekly: pd.Series,
                 market_weekly: pd.Series, config: PaneConfig) -> tuple[pd.DataFrame, str | None]:
    """(`rs_frame`'s frame, a note when its prices end before the chart's bars), from
    one weekly series, so the blank and the note always agree on where it ends."""
    if ticker_weekly.empty or market_weekly.empty:
        return pd.DataFrame({"mansfield": np.nan}, index=index), None
    weekly = rs_compute._weekly_mansfield(ticker_weekly, market_weekly, config.mansfield_weeks)
    # the last week with a value; with none yet (under a year of history), the last
    # week both price series have, so the note still says where the prices end
    valued = weekly.dropna()
    last_week = valued.index.max() if not valued.empty else min(ticker_weekly.index.max(),
                                                                 market_weekly.index.max())
    # a weekly chart shows that week; a daily one also the days after it that its value
    # covers, until the next week would have completed
    shown_to = (last_week.to_period("W-SUN").end_time.normalize() + pd.Timedelta(days=7)
                if timeframe == Timeframe.DAILY else last_week)
    if timeframe == Timeframe.WEEKLY:
        values = weekly.reindex(index)
    else:
        values = rs_compute._completed_weeks_as_of_daily(weekly, index).where(index <= shown_to)
    frame = pd.DataFrame({"mansfield": values.to_numpy()}, index=index)
    note = (f"RS (Mansfield): total-return prices end the week of {last_week:%Y-%m-%d}"
            if not index.empty and index.max() > shown_to else None)
    return frame, note


def rs_line_frame(bars: pd.DataFrame, market_bars: pd.DataFrame, config: PaneConfig) -> pd.DataFrame:
    """The RS line: the ticker's close over the market's on the chart's own bars
    (traded basis, so it runs to the chart's last bar; a price ratio, as charting
    sites draw it, not total return). NaN where the market has no bar.

    `high` is the line where it's above every value of the `rs_line_high_days`
    before it (a new 52-week high, the blue dots): by date, not bar count, over the
    days that have a ratio, so a missing bar neither stretches the window nor blanks
    it. Strictly above, so a flat line isn't a new high every bar. NaN elsewhere and
    for the first `rs_line_high_days` of the line (no full year behind it)."""
    if bars.empty or market_bars.empty:
        return pd.DataFrame({"ratio": np.nan, "high": np.nan}, index=bars.index)
    # a zero close gives inf, which would be the rolling high for a year: dropped like a gap
    valued = indicators.ratio(bars["close"], market_bars["close"]).replace([np.inf, -np.inf], np.nan).dropna()
    window = pd.Timedelta(days=config.rs_line_high_days)
    prior_high = valued.rolling(window, closed="left").max()
    high = valued.where((valued > prior_high) & (valued.index >= valued.index.min() + window))
    return pd.DataFrame({"ratio": valued.reindex(bars.index), "high": high.reindex(bars.index)}, index=bars.index)


def rs_line_end(bars: pd.DataFrame, market_bars: pd.DataFrame, market: str) -> str | None:
    """A note when the market's bars end before the ticker's (the RS line stops there)."""
    if bars.empty:
        return None
    if market_bars.empty:
        return f"RS line: no {market} bars"
    if market_bars.index.max() < bars.index.max():
        return f"RS line: {market} bars end {market_bars.index.max():%Y-%m-%d}"
    return None


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
    # a flat or nearly flat window: at least a pad of the value's own size (a ratio of
    # 0.005 in a +/-1 range, or in a 1e-14-wide one, isn't readable)
    pad = max((high - low) * 0.08, abs(high) * 0.05) or 1.0
    return [low - pad, high + pad]
