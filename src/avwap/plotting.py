"""Plotly overlay: candlesticks + one AVWAP line per anchor. Pure consumer
of (bars, anchors) -- no detection logic here, matching sr_lines/
gaps.plotting's own separation. The full AVWAP series for each anchor is
computed on demand via compute.anchored_vwap, never read from the DB (see
avwap/models.py's AnchoredVwap docstring for why only the snapshot value is
ever stored).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.avwap import compute
from src.avwap.config import AvwapConfig
from src.avwap.models import AnchoredVwap, AnchorStatus, AnchorType, primary_role

# Most senior role present decides both color family and saturation --
# ath/atl most saturated, 52w_* next, cycle_* most muted (see
# models.primary_role for the seniority ranking these opacities mirror).
_ROLE_RGB = {
    AnchorType.ATH: (31, 119, 180),
    AnchorType.ATL: (31, 119, 180),
    AnchorType.WEEK_52_HIGH: (255, 127, 14),
    AnchorType.WEEK_52_LOW: (255, 127, 14),
    AnchorType.CYCLE_HIGH: (127, 127, 127),
    AnchorType.CYCLE_LOW: (127, 127, 127),
}
_ROLE_OPACITY = {
    AnchorType.ATH: 1.0, AnchorType.ATL: 1.0,
    AnchorType.WEEK_52_HIGH: 0.75, AnchorType.WEEK_52_LOW: 0.75,
    AnchorType.CYCLE_HIGH: 0.45, AnchorType.CYCLE_LOW: 0.45,
}


def _color(anchor: AnchoredVwap) -> str:
    role = primary_role(anchor.anchor_types)
    r, g, b = _ROLE_RGB[role]
    return f"rgba({r},{g},{b},{_ROLE_OPACITY[role]:.2f})"


def _label(anchor: AnchoredVwap) -> str:
    types = "+".join(sorted(t.value for t in anchor.anchor_types))
    return f"{anchor.anchor_date[:10]} [{types}]{' (stale)' if anchor.status == AnchorStatus.STALE else ''}"


def render_avwap_chart(
    bars: pd.DataFrame,
    anchors: list[AnchoredVwap],
    ticker: str,
    timeframe,
    config: AvwapConfig | None = None,
    include_stale: bool = False,
) -> go.Figure:
    """`bars` is what gets drawn as candlesticks; each anchor's AVWAP line
    is drawn from its own anchor_date to the last available bar. Stale
    anchors are skipped unless `include_stale`, in which case they're drawn
    dashed to read as "no longer current" at a glance."""
    config = config or AvwapConfig()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
        name=ticker, showlegend=False,
    ))

    for anchor in anchors:
        if anchor.status == AnchorStatus.STALE and not include_stale:
            continue

        series = compute.anchored_vwap(bars, anchor.anchor_date, config.price_source)
        anchor_ts = pd.Timestamp(anchor.anchor_date)
        visible = series.loc[series.index >= anchor_ts]
        if visible.empty:
            continue
        color = _color(anchor)
        dash = "dash" if anchor.status == AnchorStatus.STALE else "solid"

        fig.add_trace(go.Scatter(
            x=visible.index, y=visible.values, mode="lines",
            line=dict(color=color, width=1.5, dash=dash),
            name=_label(anchor),
        ))

        if anchor_ts in bars.index:
            anchor_bar = bars.loc[anchor_ts]
            fig.add_trace(go.Scatter(
                x=[anchor_ts], y=[anchor_bar["high"]], mode="markers",
                marker=dict(color=color, size=9, symbol="triangle-down"),
                showlegend=False, hovertext=_label(anchor), hoverinfo="text",
            ))

    fig.update_layout(
        title=f"{ticker} anchored VWAP ({getattr(timeframe, 'value', timeframe)})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
    )
    return fig
