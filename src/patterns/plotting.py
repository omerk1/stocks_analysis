"""Plotly overlay: candlesticks + detected pattern geometry (defining
pivots connected as a polyline, neckline/trigger level, target). Pure
consumer of (bars, matches) -- no detection logic here, matching
gaps/sr_lines' own plotting.py separation.

Drawing `match.pivots` as a connected polyline (rather than anything
double-top-specific) is deliberately pattern-agnostic -- it works
unchanged for H&S's 5 pivots, a triangle's 6 pivots, etc. without this
module needing to change. Every entry in `match.trendlines` (slope,
intercept in bar-index space) is drawn as its own line -- one for H&S's
"neckline", two ("upper"/"lower") for a triangle/wedge -- since each is
linear by construction, two endpoints computed off the fit are enough to
draw it exactly. Falls back to a flat line at `key_levels["neckline"]` for
double top/bottom, which has no `trendlines` entry at all. Both looked up
defensively (`.get`), since not every pattern type populates either.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.market_common.models import Direction
from src.patterns.models import PatternMatch, PatternStatus, Timeframe

_WEEKEND_RANGEBREAKS = [dict(bounds=["sat", "mon"])]

# Green family for bullish, red for bearish -- opacity keyed by status
# below, same reasoning as gaps.plotting's _DIRECTION_RGB/_STATUS_OPACITY:
# a resolved (terminal, non-ACTIVE) pattern recedes, a live one stays
# prominent.
_DIRECTION_RGB = {
    Direction.BULLISH: (44, 160, 44),
    Direction.BEARISH: (214, 39, 40),
    # A still-PENDING symmetric triangle has no breakout-resolved
    # direction yet (Direction.NEUTRAL, Phase 3) -- neutral gray until it
    # actually breaks one way or the other.
    Direction.NEUTRAL: (127, 127, 127),
}

_STATUS_OPACITY = {
    PatternStatus.PENDING: 0.35,
    PatternStatus.CONFIRMED: 0.55,
    PatternStatus.ACTIVE: 0.75,
    PatternStatus.HIT_TARGET: 0.90,
    PatternStatus.INVALIDATED: 0.15,
    PatternStatus.INVALIDATED_FAILED_BREAKOUT: 0.15,
    PatternStatus.EXPIRED: 0.15,
}


def _color(match: PatternMatch) -> str:
    r, g, b = _DIRECTION_RGB[match.direction]
    return f"rgba({r},{g},{b},{_STATUS_OPACITY[match.status]:.3f})"


def _hover_text(match: PatternMatch) -> str:
    levels = ", ".join(f"{k}={v:.2f}" for k, v in match.key_levels.items())
    target = f"{match.target_price:.2f}" if match.target_price is not None else "n/a"
    stop = f"{match.stop_price:.2f}" if match.stop_price is not None else "n/a"
    notes = "<br>".join(match.notes)
    return (
        f"{match.pattern_type.value} | {match.direction.value} | {match.status.value}<br>"
        f"{levels}<br>"
        f"target={target} stop={stop}<br>"
        f"confidence={match.confidence:.2f}<br>"
        f"{notes}"
    )


def render_pattern_chart(
    bars: pd.DataFrame, matches: list[PatternMatch], ticker: str, timeframe: Timeframe
) -> go.Figure:
    """`bars` must be the same frame (same index/length) `matches` was
    detected against -- `match.breakout_bar` is a positional index into it."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=ticker, showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1] if not bars.empty else pd.Timestamp.now()

    for match in matches:
        color = _color(match)
        pivot_x = [pd.Timestamp(p.timestamp) for p in match.pivots]
        pivot_y = [p.price for p in match.pivots]

        fig.add_trace(
            go.Scatter(
                x=pivot_x, y=pivot_y, mode="lines+markers",
                line=dict(color=color, width=2), marker=dict(size=7, color=color),
                name=f"{match.pattern_type.value} {match.status.value}",
                legendgroup=match.status.value,
                hovertext=_hover_text(match), hoverinfo="text",
            )
        )

        x_end = bars.index[match.breakout_bar] if match.breakout_bar is not None else last_bar_ts
        x_end_idx = match.breakout_bar if match.breakout_bar is not None else len(bars) - 1

        if match.trendlines:
            for name, (slope, intercept) in match.trendlines.items():
                # H&S's neckline is only defined by its own two trough/
                # peak pivots (index 1), not the whole pivot list -- a
                # triangle/wedge's upper/lower lines are fit through the
                # entire window, so they're drawn from its first pivot.
                x_start_idx = match.pivots[1].bar_index if name == "neckline" and len(match.pivots) > 1 else match.pivots[0].bar_index
                x_start = bars.index[x_start_idx]
                fig.add_trace(
                    go.Scatter(
                        x=[x_start, x_end],
                        y=[slope * x_start_idx + intercept, slope * x_end_idx + intercept],
                        mode="lines", line=dict(color=color, width=1, dash="dot"),
                        showlegend=False, hoverinfo="skip",
                    )
                )
        else:
            neckline = match.key_levels.get("neckline")
            if neckline is not None:
                # The trigger-level pivot is always second-to-last in
                # match.pivots -- double top/bottom's trough (3-pivot
                # list: [p1, trough, p2]) and cup & handle's right rim
                # (variable-length list: [rim1, ..., rim2, handle]) both
                # land there. Index 1 only coincides with that for a
                # fixed 3-pivot list; -2 is the actual invariant.
                x_start = pivot_x[-2] if len(pivot_x) > 1 else pivot_x[0]
                fig.add_trace(
                    go.Scatter(
                        x=[x_start, x_end], y=[neckline, neckline],
                        mode="lines", line=dict(color=color, width=1, dash="dot"),
                        showlegend=False, hoverinfo="skip",
                    )
                )

        if match.breakout_bar is not None and match.target_price is not None:
            fig.add_trace(
                go.Scatter(
                    x=[x_end, last_bar_ts], y=[match.target_price, match.target_price],
                    mode="lines", line=dict(color=color, width=1, dash="dash"),
                    showlegend=False, hoverinfo="skip",
                )
            )

    fig.update_layout(
        title=f"{ticker} chart patterns ({timeframe.value})",
        xaxis_rangeslider_visible=False,
        xaxis_rangebreaks=_WEEKEND_RANGEBREAKS,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    return fig
