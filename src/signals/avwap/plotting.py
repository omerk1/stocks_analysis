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

from src.signals.avwap import compute
from src.signals.avwap.config import AvwapConfig
from src.signals.avwap.models import AnchoredVwap, AnchorStatus, SENIORITY, primary_role

# Categorical palette (dataviz skill's validated default, light-mode column --
# this chart is a static plotly_white export, not a theme-aware artifact).
# Assigned per drawn line (one per cluster, see `_cluster_close_anchors`) by
# position, not by role: the previous scheme colored every cycle_high/
# cycle_low anchor the same flat gray, which made 3-4 simultaneous cycle
# anchors indistinguishable from each other. Seniority still comes through
# via opacity (below), so ath/atl still visually lead even though every line
# now has its own hue.
_LINE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_ROLE_OPACITY = {
    0: 1.0,   # ath/atl
    1: 0.80,  # 52w_high/52w_low
    2: 0.60,  # cycle_high/cycle_low
}

# Weekend-closed markets leave a blank gap between Friday and Monday
# candles on a plain datetime x-axis -- collapse those empty slots so
# consecutive trading days render adjacent.
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]

# Two anchors this close together (regardless of which roles they carry)
# mark practically the same market event -- e.g. a cycle_high pivot
# confirmed the day before the very bar that also happens to be the
# all-time high. Drawing both as separate near-identical AVWAP lines from
# almost the same start date is visual noise, not two distinct signals, so
# they're clustered into one drawn line (see `_cluster_close_anchors`).
_CLUSTER_TOLERANCE_DAYS = 5


def _label(anchor: AnchoredVwap) -> str:
    types = "+".join(sorted(t.value for t in anchor.anchor_types))
    return f"{anchor.anchor_date[:10]} [{types}]{' (stale)' if anchor.status == AnchorStatus.STALE else ''}"


def _cluster_close_anchors(anchors: list[AnchoredVwap]) -> list[list[AnchoredVwap]]:
    """Chain-merge anchors whose dates land within `_CLUSTER_TOLERANCE_DAYS`
    of their cluster's most recent member -- a simple interval-style merge
    (not gaps.plotting's zone-overlap union-find) since anchors are single
    dates, not price ranges."""
    ordered = sorted(anchors, key=lambda a: a.anchor_date)
    clusters: list[list[AnchoredVwap]] = []
    for anchor in ordered:
        if clusters:
            last = clusters[-1][-1]
            gap_days = (pd.Timestamp(anchor.anchor_date) - pd.Timestamp(last.anchor_date)).days
            if gap_days <= _CLUSTER_TOLERANCE_DAYS:
                clusters[-1].append(anchor)
                continue
        clusters.append([anchor])
    return clusters


def _representative(cluster: list[AnchoredVwap]) -> AnchoredVwap:
    """The most senior-role anchor in the cluster is the one whose AVWAP
    actually gets drawn -- e.g. an ath beats a cycle_high pivot confirmed
    the day before, since the ath is almost certainly the more meaningful
    of the two nearly-simultaneous events. Ties broken by earliest date."""
    return min(cluster, key=lambda a: (SENIORITY[primary_role(a.anchor_types)], a.anchor_date))


def render_avwap_chart(
    bars: pd.DataFrame,
    anchors: list[AnchoredVwap],
    ticker: str,
    timeframe,
    config: AvwapConfig | None = None,
    include_stale: bool = False,
) -> go.Figure:
    """`bars` is what gets drawn as candlesticks. Anchors within
    `_CLUSTER_TOLERANCE_DAYS` of each other are merged into one drawn line
    (from the cluster's most senior anchor) rather than one line per anchor.
    Stale anchors are skipped unless `include_stale`, in which case they're
    drawn dashed to read as "no longer current" at a glance."""
    config = config or AvwapConfig()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
        name=ticker, showlegend=False,
    ))

    drawable = [a for a in anchors if include_stale or a.status == AnchorStatus.ACTIVE]

    for i, cluster in enumerate(_cluster_close_anchors(drawable)):
        rep = _representative(cluster)
        color = _LINE_COLORS[i % len(_LINE_COLORS)]
        opacity = _ROLE_OPACITY[SENIORITY[primary_role(rep.anchor_types)]]

        series = compute.anchored_vwap(bars, rep.anchor_date, config.price_source)
        anchor_ts = pd.Timestamp(rep.anchor_date)
        visible = series.loc[series.index >= anchor_ts]
        if visible.empty:
            continue
        dash = "dash" if any(a.status == AnchorStatus.STALE for a in cluster) else "solid"
        label = " + ".join(_label(a) for a in cluster)

        fig.add_trace(go.Scatter(
            x=visible.index, y=visible.values, mode="lines",
            line=dict(color=color, width=1.5, dash=dash),
            opacity=opacity,
            name=label,
            legendgroup=rep.id,
        ))

        if anchor_ts in bars.index:
            anchor_bar = bars.loc[anchor_ts]
            fig.add_trace(go.Scatter(
                x=[anchor_ts], y=[anchor_bar["high"]], mode="markers",
                marker=dict(color=color, size=9, symbol="triangle-down"),
                opacity=opacity,
                showlegend=False, legendgroup=rep.id,
                hovertext=label, hoverinfo="text",
            ))

    fig.update_layout(
        title=f"{ticker} anchored VWAP ({getattr(timeframe, 'value', timeframe)})",
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=_WEEKEND_RANGEBREAKS,
        template="plotly_white",
    )
    return fig
