"""Plotly overlay: candlesticks + gap zones as translucent rectangles.
Pure consumer of (bars, gaps) -- no detection logic here, matching
sr_lines/plotting.py's own separation.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.gaps.models import Direction, Gap, GapStatus, Timeframe

# Green family for bullish, red for bearish -- opacity keyed by status below
# (OPEN most saturated, CLOSED faintest), same reasoning as sr_lines'
# strength-based fade: a fully closed gap is "resolved" and should recede,
# an OPEN one is still a live, actionable zone and should stay prominent.
_DIRECTION_RGB = {
    Direction.BULLISH: (44, 160, 44),
    Direction.BEARISH: (214, 39, 40),
}

_STATUS_OPACITY = {
    GapStatus.OPEN: 0.55,
    GapStatus.PARTIAL: 0.40,
    GapStatus.SOFT_CLOSED: 0.25,
    GapStatus.CLOSED: 0.12,
}


def _fill_color(gap: Gap) -> str:
    r, g, b = _DIRECTION_RGB[gap.direction]
    return f"rgba({r},{g},{b},{_STATUS_OPACITY[gap.status]:.3f})"


def _hover_text(gap: Gap) -> str:
    return (
        f"{gap.kind.value} | {gap.direction.value} | {gap.status.value}<br>"
        f"zone=[{gap.zone_bottom:.2f}, {gap.zone_top:.2f}] size_atr={gap.size_atr:.2f}<br>"
        f"max_fill_pct={gap.max_fill_pct:.1f}%<br>"
        f"created_at={gap.created_at} closed_date={gap.closed_date}"
    )


def render_gap_chart(
    bars: pd.DataFrame, gaps: list[Gap], ticker: str, timeframe: Timeframe
) -> go.Figure:
    """`bars` is what gets drawn as candlesticks; `gaps` (already run through
    lifecycle) are drawn from `created_at` to `closed_date`, or the right
    chart edge if the gap never closed."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=ticker, showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1] if not bars.empty else pd.Timestamp.now()

    for gap in gaps:
        x0 = pd.Timestamp(gap.created_at)
        x1 = pd.Timestamp(gap.closed_date) if gap.closed_date else last_bar_ts

        fig.add_trace(
            go.Scatter(
                x=[x0, x1, x1, x0, x0],
                y=[gap.zone_bottom, gap.zone_bottom, gap.zone_top, gap.zone_top, gap.zone_bottom],
                mode="lines", fill="toself", fillcolor=_fill_color(gap),
                line=dict(color=_fill_color(gap), width=1),
                name=gap.status.value,
                legendgroup=gap.status.value,
                hovertext=_hover_text(gap), hoverinfo="text",
            )
        )

    fig.update_layout(
        title=f"{ticker} gaps/FVGs ({timeframe.value})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        # groupclick="togglegroup" -- toggling any OPEN-status trace hides
        # every OPEN gap at once, so each status can be reviewed in
        # isolation instead of only being able to hide one gap at a time.
        legend=dict(groupclick="togglegroup"),
    )
    return fig
