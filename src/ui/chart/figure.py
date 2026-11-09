"""Bars + overlays + chart type -> a plain Plotly figure. No Dash in here, so it
can be tested directly and exported to HTML without the app."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.foundation.market_common.models import Timeframe
from src.ui.chart import earnings as earnings_mod
from src.ui.chart import panes as panes_mod
from src.ui.chart.config import ChartType, MASpec, PaneConfig
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
    "volume_profile": ("#ea580c", None),
    "patterns": ("#64748b", None),  # a pattern with no direction yet (a pending symmetric triangle)
}


def _overlay_trace(o: Overlay, x_end: pd.Timestamp) -> go.Scatter:
    """One overlay as a trace: a zone as a filled box, a line from its start to the
    right edge, a series as a curve. Its short tag sits at the right end; the full
    label is the trace name (and the hover, for a curve)."""
    line, fill = _OVERLAY_STYLE.get(o.family, ("#64748b", "rgba(100,116,139,0.15)"))
    line = _event_colour(o) if o.bullish is not None else line
    common = dict(name=o.label, uid=f"{o.family}:{o.item_id}", showlegend=False, legendgroup=o.family, textfont=dict(size=10, color=line))
    if o.kind == "segment":
        return _segment_trace(o.points, o, line, common)
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


def earnings_annotations(bars: pd.DataFrame, cards, expanded, price_range: list | None = None) -> list[dict]:
    """A small "E" flag per card on its bar, or the whole card for those in
    `expanded` (keys). The arrow points at the bar's high, or its low when the
    reaction day fell; clicking it (`captureevents`) toggles the card in the app.
    An open card is tall, so it goes on the side of the bar with more room in
    `price_range` (the price axis as drawn): above the high when the bar is in the
    lower half, below the low when it's in the upper half, so it never runs off the
    top of the figure or down into the panes below."""
    out = []
    middle = sum(price_range) / 2 if price_range else None
    for card in cards:
        x = earnings_bar(bars, card)
        if x is None:
            continue
        bar = bars.loc[x]
        colour = _DOWN if card.fell else _UP
        is_open = card.key in expanded
        down = card.fell
        if is_open and middle is not None:
            down = (float(bar["high"]) + float(bar["low"])) / 2 > middle
        text = earnings_mod.card_text(card) if is_open else "E"
        out.append(dict(
            x=x, y=float(bar["low"] if down else bar["high"]), xref="x", yref="y", name=card.key, text=text,
            showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=colour, ax=0,
            ay=(1 if down else -1) * (110 if is_open else 22), align="left",
            bordercolor=colour, borderwidth=1, borderpad=4 if is_open else 2, bgcolor="rgba(255,255,255,0.94)",
            font=dict(size=11 if is_open else 10, color="#0f172a" if is_open else colour),
            hovertext=earnings_mod.hover_text(card), captureevents=True))
    return out


def _segment_trace(points, o: Overlay, colour: str, common: dict) -> go.Scatter:
    """An event through its points (a divergence's two pivots, a chart pattern's
    outline), its tag at the last."""
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return go.Scatter(x=xs, y=ys, mode="lines+markers+text", text=[""] * (len(xs) - 1) + [o.tag],
                      textposition="top center" if ys[-1] >= ys[0] else "bottom center",
                      marker=dict(size=5, color=colour),
                      line=dict(color=colour, width=1.6, dash="dash" if o.dashed else "solid"),
                      hovertemplate=f"{o.label}<extra></extra>", **common)


def guide_traces(o: Overlay, x_end: pd.Timestamp) -> list[go.Scatter]:
    """A segment's extra lines (`Overlay.guides`: a pattern's trigger and target), thin,
    in its colour and legend group, no hover of their own. One with `to_edge` runs to
    `x_end`, the right edge."""
    colour = _event_colour(o)
    return [go.Scatter(x=[g.x0, x_end if g.to_edge else g.x1], y=[g.y0, g.y1], mode="lines+text",
                       text=["", g.text], textposition="top left", textfont=dict(size=10, color=colour),
                       line=dict(color=colour, width=1, dash=g.dash), uid=f"{o.family}:{o.item_id}:guide{i}",
                       name=o.label, showlegend=False, legendgroup=o.family, hoverinfo="skip")
            for i, g in enumerate(o.guides)]


def _event_colour(o: Overlay) -> str:
    if o.bullish is None:
        return _OVERLAY_STYLE.get(o.family, ("#64748b", None))[0]
    return _UP if o.bullish else _DOWN


def pane_segment_trace(o: Overlay) -> go.Scatter:
    """An event's segment on its indicator pane (`Overlay.pane_points`), in the same
    colour and legend group as its price segment."""
    colour = _event_colour(o)
    common = dict(name=o.label, uid=f"{o.family}:{o.item_id}:pane", showlegend=False, legendgroup=o.family,
                  textfont=dict(size=10, color=colour))
    return _segment_trace(o.pane_points, o, colour, common)


def _drawable(o: Overlay) -> bool:
    """A segment needs at least two points; anything else is always drawable."""
    return o.kind != "segment" or len(o.points) >= 2


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
    panes: tuple[panes_mod.Pane, ...] = (),
    pane_config: PaneConfig = PaneConfig(),
) -> go.Figure:
    """`mas` holds the series to draw, keyed by `MASpec.key`; `ma_specs` gives their
    labels and colour order. `x_range` sets the visible window, with the y-axes
    fitted to it (None: everything, autoranged). `holidays` (from `closed_weekdays`)
    are hidden on a daily chart along with weekends. `overlays` are drawn under the
    moving averages, in the order given. `earnings` get a flag each, or their card
    when their key is in `expanded`. `panes` (RSI, MACD, RS) go below the volume pane,
    in order, each labelled in its top-left corner."""
    axes = pane_axes(show_volume, panes)
    heights = [_PANE_HEIGHT["volume" if key == "volume" else "pane"] for key in axes]
    if sum(heights) > _PANES_MAX_SHARE:  # keep the price pane the biggest
        heights = [h * _PANES_MAX_SHARE / sum(heights) for h in heights]
    fig = make_subplots(rows=1 + len(axes), cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=[1.0 - sum(heights), *heights])
    if not bars.empty:
        x_end = bars.index.max() + _right_pad(timeframe)
        for o in overlays:
            if _drawable(o):
                fig.add_trace(_overlay_trace(o, x_end), row=1, col=1)
                for trace in guide_traces(o, x_end):
                    fig.add_trace(trace, row=1, col=1)
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
    for row, pane in enumerate(panes, start=2 + show_volume):
        for trace in _pane_traces(pane):
            fig.add_trace(trace, row=row, col=1)
        if pane.key == panes_mod.RSI:
            for level in pane_config.rsi_bands:
                fig.add_hline(y=level, line=dict(color="#94a3b8", width=0.8, dash="dash"), row=row, col=1)
        else:
            fig.add_hline(y=0, line=dict(color="#94a3b8", width=0.8), row=row, col=1)
        for o in overlays:
            if o.kind == "segment" and o.pane == pane.key and len(o.pane_points) == 2:
                fig.add_trace(pane_segment_trace(o), row=row, col=1)

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

    ranges = {}
    if x_range is not None and not bars.empty:
        fig.update_xaxes(range=list(x_range))
        ranges = y_axis_ranges(bars, mas, x_range, chart_type, show_volume, overlays, panes)
        for axis, axis_range in ranges.items():
            fig.update_layout({axis: {"range": axis_range}})
    annotations = figure_annotations(bars, show_volume, panes, earnings, expanded, ranges.get("yaxis"))
    if annotations:
        fig.update_layout(annotations=annotations)
    return fig


def figure_annotations(bars: pd.DataFrame, show_volume: bool, panes: tuple[panes_mod.Pane, ...],
                       earnings=(), expanded=frozenset(), price_range: list | None = None) -> list[dict]:
    """Every annotation on the figure: each pane's label (top-left of its own
    subplot), then the earnings flags and cards. The app's zoom refit rebuilds these
    with the new price range, so an open card's side keeps up with the view."""
    out = []
    for key, axis in pane_axes(show_volume, panes).items():
        if key == "volume":
            continue
        n = axis[len("yaxis"):]
        label = next(p.label for p in panes if p.key == key)
        out.append(dict(text=label, xref=f"x{n} domain", yref=f"y{n} domain", x=0.0, y=1.0, xanchor="left",
                        yanchor="top", showarrow=False, font=dict(size=11, color="#475569"),
                        bgcolor="rgba(255,255,255,0.7)"))
    if earnings and not bars.empty:
        out += earnings_annotations(bars, earnings, expanded, price_range)
    return out


_PANE_HEIGHT = {"volume": 0.2, "pane": 0.17}  # shares of the figure's height
_PANES_MAX_SHARE = 0.5


def pane_axes(show_volume: bool, panes: tuple[panes_mod.Pane, ...] = ()) -> dict[str, str]:
    """{"volume" or pane key: its layout y-axis name}, top to bottom below the price
    pane (yaxis): the volume pane first when shown, then the indicator panes in order."""
    keys = (["volume"] if show_volume else []) + [p.key for p in panes]
    return {key: f"yaxis{row}" for row, key in enumerate(keys, start=2)}


def _pane_traces(pane: panes_mod.Pane) -> list[go.BaseTraceType]:
    f = pane.frame
    if pane.key == panes_mod.MACD:
        colours = np.where(f["hist"] >= 0, _UP, _DOWN)
        return [go.Bar(x=f.index, y=f["hist"], name="MACD hist", uid="macd-hist", marker_color=colours,
                       opacity=0.5, showlegend=False),
                go.Scatter(x=f.index, y=f["macd"], mode="lines", name="MACD", uid="macd", showlegend=False,
                           line=dict(color="#2563eb", width=1.2)),
                go.Scatter(x=f.index, y=f["signal"], mode="lines", name="Signal", uid="macd-signal",
                           showlegend=False, line=dict(color="#f59e0b", width=1.2))]
    column = {panes_mod.RSI: "rsi", panes_mod.RS: "mansfield"}[pane.key]
    return [go.Scatter(x=f.index, y=f[column], mode="lines", name=pane.label, uid=pane.key, showlegend=False,
                       line=dict(color="#7c3aed", width=1.2), hovertemplate=f"{pane.label} %{{y:.1f}}<extra></extra>")]


def y_axis_ranges(bars: pd.DataFrame, mas: dict[str, pd.Series], x_range, chart_type: ChartType,
                  show_volume: bool, overlays: tuple[Overlay, ...] = (),
                  panes: tuple[panes_mod.Pane, ...] = ()) -> dict[str, list]:
    """Layout axis name -> range for the window `x_range`; the one place both the first
    draw and the app's zoom refit get their y-ranges from. Empty when no bar is in range."""
    fit = y_fit(bars, mas, *x_range, closes_only=chart_type == ChartType.LINE, overlays=overlays)
    if fit is None:
        return {}
    price_range, volume_top = fit
    ranges = {"yaxis": price_range}
    axes = pane_axes(show_volume, panes)
    if show_volume and volume_top is not None:
        ranges[axes["volume"]] = [0, volume_top]
    for pane in panes:
        ranges[axes[pane.key]] = panes_mod.pane_range(pane.key, pane.frame, *x_range)
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
        if o.kind == "segment":  # counts only while what lo/hi cover (`Overlay.x_end`) is in the window
            if _drawable(o) and o.x0 <= end and o.x_end >= start:
                lows.append(o.lo)
                highs.append(o.hi)
        elif o.kind != "series" and o.x0 <= end:
            lows.append(o.lo)
            highs.append(o.hi)
    low = min(v for v in lows if pd.notna(v))
    high = max(v for v in highs if pd.notna(v))
    pad = (high - low) * 0.05 or abs(high) * 0.01 or 1.0
    volume_top = float(visible["volume"].max()) * 1.1 if visible["volume"].max() > 0 else None
    return [max(low - pad, 0.0), high + pad], volume_top
