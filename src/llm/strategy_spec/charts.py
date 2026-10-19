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


def write_chart(figure: go.Figure, path) -> None:
    """Self-contained-enough HTML: plotly.js from the CDN keeps each file small."""
    figure.write_html(path, include_plotlyjs="cdn")
