"""Bars + overlays + chart type -> a plain Plotly figure. No Dash in here, so it
can be tested directly and exported to HTML without the app."""

from __future__ import annotations

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


def build_figure(
    bars: pd.DataFrame,
    ticker: str,
    timeframe: Timeframe,
    chart_type: ChartType,
    mas: dict[str, pd.Series],
    ma_specs: tuple[MASpec, ...],
    show_volume: bool = True,
    span_days: int | None = None,
) -> go.Figure:
    """`mas` holds the series to draw, keyed by `MASpec.key`; `ma_specs` gives their
    labels and colour order. `span_days` sets the initial x-range to the last that
    many calendar days (None: everything)."""
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
        colours = [_UP if c >= o else _DOWN for o, c in zip(bars["open"], bars["close"])]
        fig.add_trace(go.Bar(x=bars.index, y=bars["volume"], name="Volume", marker_color=colours,
                             opacity=0.5, showlegend=False), row=2, col=1)

    fig.update_layout(
        template="plotly_white", margin=dict(l=10, r=60, t=10, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        xaxis_rangeslider_visible=False, dragmode="pan", uirevision=f"{ticker}-{timeframe.value}",
    )
    fig.update_yaxes(side="right")
    if timeframe == Timeframe.DAILY:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    if span_days is not None and not bars.empty:
        end = bars.index.max()
        start = end - pd.Timedelta(days=span_days)
        fig.update_xaxes(range=[start, end + pd.Timedelta(days=5 if timeframe == Timeframe.DAILY else 14)])
        apply_y_fit(fig, bars, mas, start, end, show_volume)
    return fig


def y_fit(bars: pd.DataFrame, mas: dict[str, pd.Series], start, end) -> tuple[list, float | None] | None:
    """Price-axis range covering the bars and moving averages between `start` and
    `end` (5% padding), and the volume axis's top. None when no bar is in range.
    Plotly doesn't refit y when x is zoomed or panned, so the app calls this."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    visible = bars.loc[(bars.index >= start) & (bars.index <= end)]
    if visible.empty:
        return None
    lows, highs = [visible["low"].min()], [visible["high"].max()]
    for series in mas.values():
        window = series.loc[(series.index >= start) & (series.index <= end)]
        lows.append(window.min())
        highs.append(window.max())
    low = min(v for v in lows if pd.notna(v))
    high = max(v for v in highs if pd.notna(v))
    pad = (high - low) * 0.05 or high * 0.01
    volume_top = float(visible["volume"].max()) * 1.1 if visible["volume"].max() > 0 else None
    return [max(low - pad, 0.0), high + pad], volume_top


def apply_y_fit(fig: go.Figure, bars, mas, start, end, show_volume: bool) -> None:
    fit = y_fit(bars, mas, start, end)
    if fit is None:
        return
    price_range, volume_top = fit
    fig.update_yaxes(range=price_range, row=1, col=1)
    if show_volume and volume_top is not None:
        fig.update_yaxes(range=[0, volume_top], row=2, col=1)
