"""Bars + overlays + chart type -> a plain Plotly figure. No Dash in here, so it
can be tested directly and exported to HTML without the app."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.foundation.market_common.models import Timeframe
from src.ui.chart.config import ChartType, MASpec

# Line colours for the moving averages, in menu order; shorter periods first.
_MA_COLOURS = ("#2563eb", "#f59e0b", "#a855f7", "#dc2626", "#0d9488", "#64748b", "#db2777", "#65a30d")
_UP, _DOWN = "#16a34a", "#dc2626"


def _price_trace(bars: pd.DataFrame, chart_type: ChartType, ticker: str) -> go.BaseTraceType:
    if chart_type == ChartType.LINE:
        return go.Scatter(x=bars.index, y=bars["close"], mode="lines", name=ticker,
                          line=dict(color="#0f172a", width=1.5))
    cls = go.Candlestick if chart_type == ChartType.CANDLES else go.Ohlc
    return cls(x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
               name=ticker, increasing_line_color=_UP, decreasing_line_color=_DOWN)


def default_x_range(bars: pd.DataFrame, timeframe: Timeframe, span_days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The last `span_days` calendar days, plus a little room after the last bar."""
    end = bars.index.max()
    return end - pd.Timedelta(days=span_days), end + pd.Timedelta(days=5 if timeframe == Timeframe.DAILY else 14)


def closed_weekdays(market_days: pd.DatetimeIndex) -> tuple[str, ...]:
    """Weekdays the market was closed (holidays), from a market-wide calendar such as
    SPY's trading days, for daily rangebreaks. Built from the market, not from the
    ticker's own bars, so a ticker's halt or missing data still shows as a gap."""
    if market_days.empty:
        return ()
    missing = pd.bdate_range(market_days.min(), market_days.max()).difference(market_days.normalize())
    return tuple(d.strftime("%Y-%m-%d") for d in missing)


def build_figure(
    bars: pd.DataFrame,
    ticker: str,
    timeframe: Timeframe,
    chart_type: ChartType,
    mas: dict[str, pd.Series],
    ma_specs: tuple[MASpec, ...],
    show_volume: bool = True,
    x_range: tuple | None = None,
    holidays: tuple[str, ...] = (),
) -> go.Figure:
    """`mas` holds the series to draw, keyed by `MASpec.key`; `ma_specs` gives their
    labels and colour order. `x_range` sets the visible window, with the y-axes
    fitted to it (None: everything, autoranged). `holidays` (from `closed_weekdays`)
    are hidden on a daily chart along with weekends."""
    rows = 2 if show_volume else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=[0.8, 0.2] if show_volume else [1.0])
    fig.add_trace(_price_trace(bars, chart_type, ticker), row=1, col=1)

    for i, spec in enumerate(ma_specs):
        if spec.key not in mas:
            continue
        fig.add_trace(go.Scatter(x=bars.index, y=mas[spec.key], mode="lines", name=spec.label,
                                 line=dict(color=_MA_COLOURS[i % len(_MA_COLOURS)], width=1.2),
                                 hovertemplate=f"{spec.label} %{{y:.2f}}<extra></extra>"),
                      row=1, col=1)

    if show_volume:
        colours = np.where(bars["close"] >= bars["open"], _UP, _DOWN)
        fig.add_trace(go.Bar(x=bars.index, y=bars["volume"], name="Volume", marker_color=colours,
                             opacity=0.5, showlegend=False), row=2, col=1)

    fig.update_layout(
        template="plotly_white", margin=dict(l=10, r=60, t=10, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        xaxis_rangeslider_visible=False, dragmode="pan",
        # Keeps the user's legend clicks and drag mode across redraws of the same chart;
        # the axis ranges are set explicitly from the stored view, so they don't drift.
        uirevision=f"{ticker}-{timeframe.value}",
    )
    fig.update_yaxes(side="right")
    if timeframe == Timeframe.DAILY:
        breaks = [dict(bounds=["sat", "mon"])]
        if holidays:
            breaks.append(dict(values=list(holidays)))
        fig.update_xaxes(rangebreaks=breaks)

    if x_range is not None and not bars.empty:
        fig.update_xaxes(range=list(x_range))
        for axis, axis_range in y_axis_ranges(bars, mas, x_range, chart_type, show_volume).items():
            fig.update_layout({axis: {"range": axis_range}})
    return fig


def y_axis_ranges(bars: pd.DataFrame, mas: dict[str, pd.Series], x_range, chart_type: ChartType,
                  show_volume: bool) -> dict[str, list]:
    """Layout axis name -> range for the window `x_range`; the one place both the first
    draw and the app's zoom refit get their y-ranges from. Empty when no bar is in range."""
    fit = y_fit(bars, mas, *x_range, closes_only=chart_type == ChartType.LINE)
    if fit is None:
        return {}
    price_range, volume_top = fit
    ranges = {"yaxis": price_range}
    if show_volume and volume_top is not None:
        ranges["yaxis2"] = [0, volume_top]
    return ranges


def y_fit(bars: pd.DataFrame, mas: dict[str, pd.Series], start, end,
          closes_only: bool = False) -> tuple[list, float | None] | None:
    """Price-axis range covering what's drawn between `start` and `end` (the bars'
    highs/lows, or only closes for a line chart, and the moving averages; 5%
    padding, never below 0), and the volume axis's top. None when no bar is in range.
    Plotly doesn't refit y when x is zoomed or panned, so the app calls this."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    visible = bars.loc[(bars.index >= start) & (bars.index <= end)]
    if visible.empty:
        return None
    low_col, high_col = ("close", "close") if closes_only else ("low", "high")
    lows, highs = [visible[low_col].min()], [visible[high_col].max()]
    for series in mas.values():
        window = series.loc[(series.index >= start) & (series.index <= end)]
        lows.append(window.min())
        highs.append(window.max())
    low = min(v for v in lows if pd.notna(v))
    high = max(v for v in highs if pd.notna(v))
    pad = (high - low) * 0.05 or abs(high) * 0.01 or 1.0
    volume_top = float(visible["volume"].max()) * 1.1 if visible["volume"].max() > 0 else None
    return [max(low - pad, 0.0), high + pad], volume_top
