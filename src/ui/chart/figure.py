"""Bars + overlays + chart type -> a plain Plotly figure. No Dash in here, so it
can be tested directly and exported to HTML without the app."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.foundation.market_common.models import Timeframe
from src.ui.chart import earnings as earnings_mod
from src.ui.chart.config import ChartType, MASpec
from src.ui.chart.earnings import EarningsCard
from src.ui.chart.overlays import Overlay

# Line colours for the moving averages, in menu order; shorter periods first.
_MA_COLOURS = ("#2563eb", "#f59e0b", "#a855f7", "#dc2626", "#0d9488", "#64748b", "#db2777", "#65a30d")
_UP, _DOWN = "#16a34a", "#dc2626"


def _price_trace(bars: pd.DataFrame, chart_type: ChartType, ticker: str) -> go.BaseTraceType:
    if chart_type == ChartType.LINE:
        return go.Scatter(x=bars.index, y=bars["close"], mode="lines", name=ticker, uid="price",
                          line=dict(color="#0f172a", width=1.5))
    cls = go.Candlestick if chart_type == ChartType.CANDLES else go.Ohlc
    return cls(x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
               name=ticker, uid="price", increasing_line_color=_UP, decreasing_line_color=_DOWN)


def _right_pad(timeframe: Timeframe) -> pd.Timedelta:
    return pd.Timedelta(days=5 if timeframe == Timeframe.DAILY else 14)


def default_x_range(bars: pd.DataFrame, timeframe: Timeframe, span_days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The last `span_days` calendar days, plus a little room after the last bar."""
    end = bars.index.max()
    return end - pd.Timedelta(days=span_days), end + _right_pad(timeframe)


# Per family: (line colour, fill colour). Zones are translucent so the bars stay readable.
_OVERLAY_STYLE = {
    "sr_lines": ("#0284c7", "rgba(2,132,199,0.13)"),
    "gaps": ("#ca8a04", "rgba(234,179,8,0.20)"),
    "avwap": ("#0d9488", None),
    "fibonacci": ("#c026d3", None),
}


def _overlay_trace(o: Overlay, x_end: pd.Timestamp) -> go.Scatter:
    """One overlay as a trace: a zone as a filled box, a line from its start to the
    right edge, a series as a curve. Its short tag sits at the right end; the full
    label is the trace name (and the hover, for a curve)."""
    line, fill = _OVERLAY_STYLE.get(o.family, ("#64748b", "rgba(100,116,139,0.15)"))
    common = dict(name=o.label, uid=f"{o.family}:{o.item_id}", showlegend=False, legendgroup=o.family, textfont=dict(size=10, color=line))
    if o.kind == "series" and o.series is not None:
        s = o.series.dropna()
        text = [""] * len(s)
        if text:
            text[-1] = o.tag
        return go.Scatter(x=s.index, y=s.to_numpy(), mode="lines+text", text=text, textposition="top left",
                          line=dict(color=line, width=1.2, dash="dot"),
                          hovertemplate=f"{o.label} %{{y:.2f}}<extra></extra>", **common)
    if o.kind == "zone":
        return go.Scatter(x=[o.x0, x_end, x_end, o.x0, o.x0], y=[o.lo, o.lo, o.hi, o.hi, o.lo],
                          mode="lines+text", fill="toself", fillcolor=fill, line=dict(color=line, width=0.6),
                          text=["", "", o.tag, "", ""], textposition="bottom left", hoverinfo="skip", **common)
    return go.Scatter(x=[o.x0, x_end], y=[o.lo, o.lo], mode="lines+text", text=["", o.tag], textposition="top left",
                      line=dict(color=line, width=1, dash="dash"), hoverinfo="skip", **common)


def earnings_bar(bars: pd.DataFrame, card: EarningsCard) -> pd.Timestamp | None:
    """The chart bar a card points at: its reaction day's bar (a weekly chart's bar is
    labelled by its week's Monday, so the last one on or before the day, if it's that
    week). None off the chart, e.g. in the weekly chart's week still in progress."""
    at = bars.index.searchsorted(card.reaction_date, side="right") - 1
    if at < 0 or card.reaction_date - bars.index[at] >= pd.Timedelta(days=7):
        return None
    return bars.index[at]


def earnings_annotations(bars: pd.DataFrame, cards, expanded) -> list[dict]:
    """A small "E" flag per card on its bar, or the whole card for those in
    `expanded` (keys). The arrow points at the bar's high, or its low when the
    reaction day fell; clicking it (`captureevents`) toggles the card in the app."""
    out = []
    for card in cards:
        x = earnings_bar(bars, card)
        if x is None:
            continue
        bar = bars.loc[x]
        down = card.fell
        colour = _DOWN if down else _UP
        is_open = card.key in expanded
        text = earnings_mod.card_text(card) if is_open else "E"
        out.append(dict(
            x=x, y=float(bar["low"] if down else bar["high"]), xref="x", yref="y", name=card.key, text=text,
            showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=colour, ax=0,
            ay=(1 if down else -1) * (110 if is_open else 22), align="left",
            bordercolor=colour, borderwidth=1, borderpad=4 if is_open else 2, bgcolor="rgba(255,255,255,0.94)",
            font=dict(size=11 if is_open else 10, color="#0f172a" if is_open else colour),
            hovertext=earnings_mod.hover_text(card), captureevents=True))
    return out


def closed_weekdays(market_days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Weekdays inside a market-wide calendar's span (e.g. SPY's trading days) with no
    bar: the market's holidays, plus any hole in that calendar's own data."""
    if market_days.empty:
        return pd.DatetimeIndex([])
    return pd.bdate_range(market_days.min(), market_days.max()).difference(market_days.normalize())


def hidden_weekdays(closed: pd.DatetimeIndex, ticker_days: pd.DatetimeIndex) -> tuple[str, ...]:
    """Weekdays to hide on a ticker's daily chart: closed for the market *and* no bar for
    the ticker. A bar the ticker has is never hidden (a hole in the calendar's data
    can't swallow it), and a ticker's own halt or data gap still shows as a gap.
    Outside the calendar's span nothing is hidden, so holidays there show as gaps."""
    return tuple(d.strftime("%Y-%m-%d") for d in closed.difference(ticker_days.normalize()))


def padded_full_range(bars: pd.DataFrame, timeframe: Timeframe) -> tuple[str, str]:
    """The whole history with a little room on both sides (1% of the span before the
    first bar, the default view's few days after the last), as plain date strings."""
    start, end = bars.index.min(), bars.index.max()
    before = max((end - start) * 0.01, pd.Timedelta(days=1))
    return (start - before).strftime("%Y-%m-%d"), (end + _right_pad(timeframe)).strftime("%Y-%m-%d")


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
    overlays: tuple[Overlay, ...] = (),
    earnings: tuple[EarningsCard, ...] = (),
    expanded: frozenset[str] = frozenset(),
) -> go.Figure:
    """`mas` holds the series to draw, keyed by `MASpec.key`; `ma_specs` gives their
    labels and colour order. `x_range` sets the visible window, with the y-axes
    fitted to it (None: everything, autoranged). `holidays` (from `closed_weekdays`)
    are hidden on a daily chart along with weekends. `overlays` are drawn under the
    moving averages, in the order given. `earnings` get a flag each, or their card
    when their key is in `expanded`."""
    rows = 2 if show_volume else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=[0.8, 0.2] if show_volume else [1.0])
    if not bars.empty:
        x_end = bars.index.max() + _right_pad(timeframe)
        for o in overlays:
            fig.add_trace(_overlay_trace(o, x_end), row=1, col=1)
    fig.add_trace(_price_trace(bars, chart_type, ticker), row=1, col=1)

    for i, spec in enumerate(ma_specs):
        if spec.key not in mas:
            continue
        fig.add_trace(go.Scatter(x=bars.index, y=mas[spec.key], mode="lines", name=spec.label, uid=spec.key,
                                 line=dict(color=_MA_COLOURS[i % len(_MA_COLOURS)], width=1.2),
                                 hovertemplate=f"{spec.label} %{{y:.2f}}<extra></extra>"),
                      row=1, col=1)

    if show_volume:
        colours = np.where(bars["close"] >= bars["open"], _UP, _DOWN)
        fig.add_trace(go.Bar(x=bars.index, y=bars["volume"], name="Volume", uid="volume", marker_color=colours,
                             opacity=0.5, showlegend=False), row=2, col=1)

    fig.update_layout(
        template="plotly_white", margin=dict(l=10, r=60, t=10, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        xaxis_rangeslider_visible=False, dragmode="pan",
        # Keeps the user's legend clicks and drag mode across redraws of the same chart;
        # the axis ranges are set explicitly from the stored view, so they don't drift.
        # Every trace has a stable `uid`, so a legend click stays with its trace when
        # overlays are added or removed in front of it (plotly matches by uid, else index).
        uirevision=f"{ticker}-{timeframe.value}",
    )
    # y is always fitted by the server (here and on every zoom/pan), so panning moves
    # time only and a GUI-set y-range can never outlive a redraw that refits it.
    fig.update_yaxes(side="right", fixedrange=True)
    if timeframe == Timeframe.DAILY:
        breaks = [dict(bounds=["sat", "mon"])]
        if holidays:
            breaks.append(dict(values=list(holidays)))
        fig.update_xaxes(rangebreaks=breaks)

    if earnings and not bars.empty:
        fig.update_layout(annotations=earnings_annotations(bars, earnings, expanded))
    if x_range is not None and not bars.empty:
        fig.update_xaxes(range=list(x_range))
        for axis, axis_range in y_axis_ranges(bars, mas, x_range, chart_type, show_volume, overlays).items():
            fig.update_layout({axis: {"range": axis_range}})
    return fig


def y_axis_ranges(bars: pd.DataFrame, mas: dict[str, pd.Series], x_range, chart_type: ChartType,
                  show_volume: bool, overlays: tuple[Overlay, ...] = ()) -> dict[str, list]:
    """Layout axis name -> range for the window `x_range`; the one place both the first
    draw and the app's zoom refit get their y-ranges from. Empty when no bar is in range."""
    fit = y_fit(bars, mas, *x_range, closes_only=chart_type == ChartType.LINE, overlays=overlays)
    if fit is None:
        return {}
    price_range, volume_top = fit
    ranges = {"yaxis": price_range}
    if show_volume and volume_top is not None:
        ranges["yaxis2"] = [0, volume_top]
    return ranges


def y_fit(bars: pd.DataFrame, mas: dict[str, pd.Series], start, end,
          closes_only: bool = False, overlays: tuple[Overlay, ...] = ()) -> tuple[list, float | None] | None:
    """Price-axis range covering what's drawn between `start` and `end` (the bars'
    highs/lows, or only closes for a line chart, the moving averages and the
    overlays; 5% padding, never below 0), and the volume axis's top. None when no
    bar is in range. Plotly doesn't refit y when x is zoomed or panned, so the app
    calls this. A zone or line counts once it has started (it runs to the right
    edge); a series by its values in the window."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    visible = bars.loc[(bars.index >= start) & (bars.index <= end)]
    if visible.empty:
        return None
    low_col, high_col = ("close", "close") if closes_only else ("low", "high")
    lows, highs = [visible[low_col].min()], [visible[high_col].max()]
    curves = list(mas.values()) + [o.series for o in overlays if o.kind == "series" and o.series is not None]
    for series in curves:
        window = series.loc[(series.index >= start) & (series.index <= end)]
        lows.append(window.min())
        highs.append(window.max())
    for o in overlays:
        if o.kind != "series" and o.x0 <= end:
            lows.append(o.lo)
            highs.append(o.hi)
    low = min(v for v in lows if pd.notna(v))
    high = max(v for v in highs if pd.notna(v))
    pad = (high - low) * 0.05 or abs(high) * 0.01 or 1.0
    volume_top = float(visible["volume"].max()) * 1.1 if visible["volume"].max() > 0 else None
    return [max(low - pad, 0.0), high + pad], volume_top
