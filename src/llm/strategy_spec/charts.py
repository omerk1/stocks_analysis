"""Charts for grounding instances (step 4, `docs/strategy-agent/idea.md` workflow step 2):
candlesticks, the moving average (or other spec geometry), and a marker on the trigger
bar — and, deliberately, **nothing after the trigger bar**.

The truncation is the point, not a styling choice. Examples define the idea; they must
carry zero outcome information. If the trader sees how an instance turned out, "yes,
that's my setup" quietly becomes "yes, that one worked", and the definition starts
fitting winners before any test runs (the selection risk `idea.md` names). The finders
put an instance's date on the signal bar itself, so that bar's close — the trigger — is
fully visible at the chart's edge, and even one later bar would already show the
execution open and the first day of the forward return.

Charts are also **blind to near-miss status**: a near-miss gets the same title, filename
shape and styling as a match (`ground.py` interleaves them unlabelled), otherwise the
trader knows to reject it and the threshold probe measures nothing.

Pure drawing, same separation as the signal modules' own plotting.py files: a prepared
window of bars in, a plotly figure out, no detection logic and no file naming here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

LOOKBACK_BARS = 90  # context before the trigger: the away run and some history
FORWARD_BARS = 0    # the chart ends ON the trigger bar: its close is the signal, and any later bar leaks outcome
CHART_FROM_MARGIN_BARS = 10  # context drawn before a candidate-declared window start
ZONE_BARS = 10  # a level stack's zone is drawn over this many bars up to the touch

# Same convention as patterns/gaps plotting: no weekend voids in the x axis.
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]


def chart_window(bars: pd.DataFrame, trigger_date: pd.Timestamp,
                 lookback: int = LOOKBACK_BARS, forward: int = FORWARD_BARS,
                 chart_from: pd.Timestamp | None = None) -> pd.DataFrame:
    """The rows of one ticker's date-sorted `bars` from `lookback` bars before the
    trigger to `forward` bars after it — the only bars a grounding chart may show.
    `chart_from` (a candidate's own geometry start, e.g. the first bar of a breakout's
    base) opens the window early enough to include it plus `CHART_FROM_MARGIN_BARS` of
    context; it can only widen the window, never shrink it below `lookback`."""
    positions = np.flatnonzero((bars["date"] == trigger_date).to_numpy())
    if len(positions) != 1:
        raise ValueError(f"trigger date {trigger_date.date()} appears {len(positions)} times in the window's bars")
    position = int(positions[0])
    start = position - lookback
    if chart_from is not None:
        first = int(np.searchsorted(bars["date"].to_numpy(), np.datetime64(chart_from, "ns")))
        start = min(start, first - CHART_FROM_MARGIN_BARS)
    return bars.iloc[max(0, start): position + forward + 1]


def candidate_overlay(window: pd.DataFrame, overlay_span: tuple[pd.Timestamp, pd.Timestamp, float],
                      overlay_col: str) -> pd.DataFrame:
    """A copy of `window` whose `overlay_col` is this candidate's own line: the span's
    constant value across [first bar, last bar], NaN elsewhere — never another
    episode's overlay, whatever a shared panel column holds on these rows."""
    window = window.copy()
    start, end, value = overlay_span
    window[overlay_col] = np.where(window["date"].between(start, end), value, np.nan)
    return window


def instance_chart(window: pd.DataFrame, overlay_col: str, overlay_name: str,
                   trigger_date: pd.Timestamp, title: str) -> go.Figure:
    """One instance as a figure: candles, the `overlay_col` line (the spec's geometry —
    for first touch, the MA), and a marker on the trigger bar. `window` must already be
    truncated by `chart_window`; this function draws whatever it is given."""
    figure = go.Figure()
    figure.add_trace(go.Candlestick(
        x=window["date"], open=window["open"], high=window["high"],
        low=window["low"], close=window["close"], name="price", showlegend=False))
    figure.add_trace(go.Scatter(
        x=window["date"], y=window[overlay_col], name=overlay_name,
        mode="lines", line=dict(color="rgb(31, 119, 180)", width=1.5)))
    trigger = window[window["date"] == trigger_date]
    figure.add_trace(go.Scatter(
        x=trigger["date"], y=trigger["close"], name="trigger bar", mode="markers",
        marker=dict(symbol="circle-open", size=14, color="rgb(214, 39, 40)", line=dict(width=2))))
    figure.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        xaxis=dict(rangebreaks=_WEEKEND_RANGEBREAKS), margin=dict(l=40, r=40, t=60, b=40))
    return figure


_LINE_COLOURS = ("rgb(31, 119, 180)", "rgb(255, 127, 14)", "rgb(44, 160, 44)", "rgb(148, 103, 189)",
                 "rgb(140, 86, 75)", "rgb(227, 119, 194)", "rgb(127, 127, 127)", "rgb(188, 189, 34)")


def stack_chart(window: pd.DataFrame, stack, trigger_date: pd.Timestamp, title: str) -> go.Figure:
    """A level stack (`level_stack.StackGeometry`) on `window` (truncated by
    `chart_window`): candles, the zone as a band from the geometry's start to the trigger
    bar, each level's line where it stood, the divergence between its two price pivots,
    and the trigger marker. Nothing past the trigger bar is drawn."""
    figure = go.Figure()
    figure.add_trace(go.Candlestick(
        x=window["date"], open=window["open"], high=window["high"],
        low=window["low"], close=window["close"], name="price", showlegend=False))
    first = max(pd.Timestamp(stack.start), pd.Timestamp(window["date"].iloc[0]))
    lo, hi = stack.zone
    # The zone is the stack as it stood at the touch (an AVWAP moves): drawn over the last
    # few bars only, so it doesn't suggest the stack stood there all along.
    band_from = max(first, pd.Timestamp(window["date"].iloc[max(len(window) - ZONE_BARS, 0)]))
    # Dates as DatetimeIndexes, not lists of Timestamps: image export can't serialise those.
    figure.add_trace(go.Scatter(
        x=pd.DatetimeIndex([band_from, trigger_date, trigger_date, band_from, band_from]), y=[lo, lo, hi, hi, lo],
        fill="toself",
        mode="lines", line=dict(width=0), fillcolor="rgba(44, 160, 44, 0.15)",
        name=f"zone {lo:.2f}–{hi:.2f}", hoverinfo="name"))
    for n, line in enumerate(stack.lines):
        keep = [i for i, d in enumerate(line.dates) if first <= d <= trigger_date]
        colour = _LINE_COLOURS[n % len(_LINE_COLOURS)]
        figure.add_trace(go.Scatter(
            x=pd.DatetimeIndex([line.dates[i] for i in keep]), y=[line.values[i] for i in keep], name=line.label,
            # A level first known on the touch bar's eve is one point: a marker, or it isn't drawn at all.
            mode="lines" if len(keep) > 1 else "markers",
            line=dict(color=colour, width=1.5), marker=dict(color=colour, symbol="line-ew-open", size=14)))
    if stack.divergence is not None:
        d1, p1, d2, p2 = stack.divergence
        figure.add_trace(go.Scatter(x=pd.DatetimeIndex([d1, d2]), y=[p1, p2],
                                    name=stack.divergence_label or "bullish divergence",
                                    mode="lines+markers",
                                    line=dict(color="rgb(44, 160, 44)", width=2, dash="dot")))
    trigger = window[window["date"] == trigger_date]
    figure.add_trace(go.Scatter(
        x=trigger["date"], y=trigger["low"], name="trigger bar", mode="markers",
        marker=dict(symbol="circle-open", size=14, color="rgb(214, 39, 40)", line=dict(width=2))))
    figure.update_layout(
        title=title, xaxis_rangeslider_visible=False,
        xaxis=dict(rangebreaks=_WEEKEND_RANGEBREAKS), margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", y=-0.08))
    return figure


def write_chart(figure: go.Figure, path) -> None:
    """Self-contained-enough HTML: plotly.js from the CDN keeps each file small."""
    figure.write_html(path, include_plotlyjs="cdn")
