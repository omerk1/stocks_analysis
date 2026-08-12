"""Two-pane Plotly divergence chart -- top candlesticks, bottom the
selected indicator's line, with a connecting line drawn between each
divergence's two price pivots (top pane) and its two paired indicator
pivots (bottom pane). Pure consumer of already-detected `Divergence` rows
plus the bars/indicator series that produced them -- no detection logic
lives here (mirrors sr_lines.plotting's own separation).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.divergences.models import Direction, Divergence

# Green/red for bullish/bearish -- same pair sr_lines.plotting already uses
# for its TOUCH (#2ca02c) / BODY_FAKE (#d62728) markers, kept consistent
# rather than introducing a third palette into the same codebase.
_DIRECTION_COLORS = {
    Direction.BULLISH: "#2ca02c",
    Direction.BEARISH: "#d62728",
}

# Weekend-closed markets leave a blank gap between Friday and Monday
# candles on a plain datetime x-axis -- collapse those empty slots so
# consecutive trading days render adjacent.
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]


def render_divergence_chart(
    bars: pd.DataFrame,
    indicator_series: pd.Series,
    divergences: list[Divergence],
    indicator_name: str,
    ticker: str | None = None,
) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
        vertical_spacing=0.04,
        subplot_titles=(ticker or "price", indicator_name),
    )

    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=ticker or "price", showlegend=False,
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=indicator_series.index, y=indicator_series, mode="lines", name=indicator_name,
            line=dict(color="#7f7f7f", width=1.5), showlegend=False,
        ),
        row=2, col=1,
    )

    relevant = [d for d in divergences if d.indicator.value == indicator_name]
    for d in relevant:
        color = _DIRECTION_COLORS[d.direction]
        p1_ts, p2_ts = pd.Timestamp(d.p1_date), pd.Timestamp(d.p2_date)
        hover = f"{d.direction.value} {indicator_name} strength={d.strength:.2f} confirmed_at={d.confirmed_at}"

        fig.add_trace(
            go.Scatter(
                x=[p1_ts, p2_ts], y=[d.p1_price, d.p2_price], mode="lines+markers",
                line=dict(color=color, width=2), marker=dict(size=6, color=color),
                name=f"{d.direction.value} {d.strength:.2f}", legendgroup=d.id,
                hovertext=hover, hoverinfo="text",
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=[p1_ts, p2_ts], y=[d.i1_value, d.i2_value], mode="lines+markers",
                line=dict(color=color, width=2, dash="dot"), marker=dict(size=6, color=color),
                showlegend=False, legendgroup=d.id,
                hovertext=hover, hoverinfo="text",
            ),
            row=2, col=1,
        )
        # Marker at confirmed_at, not appeared_at (p2's own timestamp) --
        # confirmed_at is when the divergence actually became knowable
        # (see detect.py), which is the point that matters for as_of
        # lookahead correctness and is usually a few bars after p2 itself.
        fig.add_trace(
            go.Scatter(
                x=[pd.Timestamp(d.confirmed_at)], y=[d.p2_price], mode="markers",
                marker=dict(symbol="star", size=11, color=color, line=dict(width=1, color="black")),
                showlegend=False, legendgroup=d.id,
                hovertext=f"confirmed {d.confirmed_at}", hoverinfo="text",
            ),
            row=1, col=1,
        )

    fig.update_layout(
        title=f"{(ticker + ' ') if ticker else ''}divergences ({indicator_name})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    fig.update_xaxes(rangebreaks=_WEEKEND_RANGEBREAKS)
    return fig
