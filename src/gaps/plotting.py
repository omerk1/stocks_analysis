"""Plotly overlay: candlesticks + gap zones as translucent rectangles.
Pure consumer of (bars, gaps) -- no detection logic here, matching
sr_lines/plotting.py's own separation.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.gaps.models import Direction, Gap, GapStatus, Timeframe

# Weekend-closed markets leave a blank gap between Friday and Monday
# candles on a plain datetime x-axis -- this collapses those empty slots
# so consecutive trading days render adjacent, same fix as any daily-bar
# candlestick chart needs regardless of what's overlaid on top of it.
_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]

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


def _cluster_overlapping(gaps: list[Gap]) -> list[list[Gap]]:
    """Group gaps that share a (status, direction) and whose price zones
    overlap -- e.g. a classic gap and the FVG from the same move, or two
    FVGs a few days apart on the same drop, almost always overlap almost
    entirely and stack into an indistinguishable blob when each gets its
    own translucent rectangle + legend entry. Clustering them into one
    drawn shape (still hoverable per-gap via the merged hover text) is a
    pure rendering grouping -- it never merges or drops any Gap, and
    doesn't touch detection/lifecycle at all.
    """
    by_group: dict[tuple[str, str], list[Gap]] = {}
    for gap in gaps:
        by_group.setdefault((gap.status.value, gap.direction.value), []).append(gap)

    clusters: list[list[Gap]] = []
    for group in by_group.values():
        assigned = [False] * len(group)
        for i, gap in enumerate(group):
            if assigned[i]:
                continue
            cluster = [gap]
            assigned[i] = True
            # Fixed point: keep absorbing any not-yet-assigned gap that
            # overlaps *any* gap already in the cluster, since overlap
            # isn't transitive pairwise-only (A-B and B-C overlapping
            # doesn't guarantee A-C do).
            grown = True
            while grown:
                grown = False
                for j, candidate in enumerate(group):
                    if assigned[j]:
                        continue
                    if any(
                        candidate.zone_top >= member.zone_bottom and member.zone_top >= candidate.zone_bottom
                        for member in cluster
                    ):
                        cluster.append(candidate)
                        assigned[j] = True
                        grown = True
            clusters.append(cluster)
    return clusters


def _cluster_hover_text(cluster: list[Gap]) -> str:
    if len(cluster) == 1:
        return _hover_text(cluster[0])
    header = f"{len(cluster)} overlapping {cluster[0].status.value} {cluster[0].direction.value} gaps:"
    lines = [
        f"  {gap.kind.value} created={gap.created_at[:10]} zone=[{gap.zone_bottom:.2f}, {gap.zone_top:.2f}] "
        f"size_atr={gap.size_atr:.2f} fill={gap.max_fill_pct:.0f}%"
        for gap in sorted(cluster, key=lambda g: g.created_at)
    ]
    return "<br>".join([header, *lines])


def render_gap_chart(
    bars: pd.DataFrame, gaps: list[Gap], ticker: str, timeframe: Timeframe
) -> go.Figure:
    """`bars` is what gets drawn as candlesticks; `gaps` (already run through
    lifecycle) are drawn from `created_at` to `closed_date`, or the right
    chart edge if the gap never closed. Overlapping same-status/direction
    gaps are clustered into a single drawn shape (see `_cluster_overlapping`)
    rather than one rectangle per gap."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=ticker, showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1] if not bars.empty else pd.Timestamp.now()

    for cluster in _cluster_overlapping(gaps):
        representative = cluster[0]
        x0 = min(pd.Timestamp(gap.created_at) for gap in cluster)
        x1 = max(
            pd.Timestamp(gap.closed_date) if gap.closed_date else last_bar_ts
            for gap in cluster
        )
        y0 = min(gap.zone_bottom for gap in cluster)
        y1 = max(gap.zone_top for gap in cluster)

        fig.add_trace(
            go.Scatter(
                x=[x0, x1, x1, x0, x0],
                y=[y0, y0, y1, y1, y0],
                mode="lines", fill="toself", fillcolor=_fill_color(representative),
                line=dict(color=_fill_color(representative), width=1),
                name=f"{representative.status.value} x{len(cluster)}" if len(cluster) > 1 else representative.status.value,
                legendgroup=representative.status.value,
                hovertext=_cluster_hover_text(cluster), hoverinfo="text",
            )
        )

    fig.update_layout(
        title=f"{ticker} gaps/FVGs ({timeframe.value})",
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=_WEEKEND_RANGEBREAKS,
        template="plotly_white",
        # groupclick="togglegroup" -- toggling any OPEN-status trace hides
        # every OPEN gap at once, so each status can be reviewed in
        # isolation instead of only being able to hide one gap at a time.
        legend=dict(groupclick="togglegroup"),
    )
    return fig
