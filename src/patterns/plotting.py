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
from plotly.subplots import make_subplots

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
    # Resolved (broke out, ran its full §7.3 horizon, never reached target),
    # so it recedes with the other terminal statuses rather than staying
    # prominent the way an unresolved ACTIVE one does.
    PatternStatus.EXPIRED_UNRESOLVED: 0.15,
}

# This lookup is exhaustive by design (a missing status raises KeyError
# mid-render rather than silently drawing wrong), so adding a PatternStatus
# without adding it here breaks every chart containing one -- see
# tests/test_patterns_plotting.py's coverage assertion.
assert set(_STATUS_OPACITY) == set(PatternStatus), "every PatternStatus needs a plotting opacity"


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
    detected against -- `match.breakout_bar` is a positional index into it.

    Two rows sharing an x-axis: price (candlesticks + pattern overlays) on
    top, volume bars below. Volume isn't just decoration -- every
    detector's breakout confirmation (`config.breakout_volume_mult`,
    `match.volume_confirmed`) depends on it, and per design doc §4.5 it's
    "core to the pattern, not just confirmatory" for VCP specifically, so
    a chart with no volume at all made that half of the judgment
    impossible to eyeball (surfaced by `backtest/labeler.py`'s own first
    real label, whose notes flagged exactly this gap)."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25],
    )
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=ticker, showlegend=False,
        ),
        row=1, col=1,
    )

    up_r, up_g, up_b = _DIRECTION_RGB[Direction.BULLISH]
    down_r, down_g, down_b = _DIRECTION_RGB[Direction.BEARISH]
    volume_colors = [
        f"rgba({up_r},{up_g},{up_b},0.5)" if c >= o else f"rgba({down_r},{down_g},{down_b},0.5)"
        for o, c in zip(bars["open"], bars["close"])
    ]
    fig.add_trace(
        go.Bar(x=bars.index, y=bars["volume"], marker=dict(color=volume_colors), name="volume", showlegend=False),
        row=2, col=1,
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
            ),
            row=1, col=1,
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
                    ),
                    row=1, col=1,
                )
        else:
            neckline = match.key_levels.get("neckline")
            if neckline is not None:
                # No fixed index is a reliable invariant here: double
                # top/bottom's trough sits at index -2 of its fixed
                # 3-pivot list, cup & handle's right rim also lands at -2
                # (a handle pivot always follows it) -- but Rounding
                # (Phase 6, cup & handle "without the handle") ends its
                # own window *at* the right rim, landing it at -1 instead,
                # which a fixed -2 assumption drew from the wrong pivot
                # (caught in code review; the same class of bug the -2
                # fix itself replaced, see docs/done.md #51/#53). Locate
                # the actual neckline pivot by price instead of position
                # -- every detector sets `key_levels["neckline"]` from a
                # pivot object that's also literally in `match.pivots`,
                # so this is an exact float match, not a fragile
                # recomputed-value comparison. Searched from the *end*:
                # the neckline pivot is always at or near the tail of the
                # list, and an earlier pivot can legitimately share its
                # exact price (e.g. a cup/rounding's rim1 and rim2, gated
                # to be close and sometimes exactly equal) -- a forward
                # search would silently prefer that earlier, wrong pivot.
                neckline_bar = match.key_levels.get("neckline_bar")
                if neckline_bar is not None and 0 <= int(neckline_bar) < len(bars):
                    x_start = bars.index[int(neckline_bar)]
                else:
                    # Pre-`neckline_bar` matches (older rows in
                    # `pattern_matches`, hand-built test fixtures) still fall
                    # back to locating the pivot by price. Kept only for
                    # those: it cannot work for cup/rounding any more, whose
                    # neckline is now the rim bar's *close* while
                    # `pivot.price` stays the intraday high/low, so the
                    # equality never holds -- which is exactly why the bar
                    # index is now stored explicitly rather than recovered
                    # by matching floats.
                    neckline_idx = next(
                        (idx for idx in range(len(match.pivots) - 1, -1, -1) if match.pivots[idx].price == neckline),
                        len(pivot_x) - 2 if len(pivot_x) > 1 else 0,
                    )
                    x_start = pivot_x[neckline_idx]
                fig.add_trace(
                    go.Scatter(
                        x=[x_start, x_end], y=[neckline, neckline],
                        mode="lines", line=dict(color=color, width=1, dash="dot"),
                        showlegend=False, hoverinfo="skip",
                    ),
                    row=1, col=1,
                )

        if match.breakout_bar is not None and match.target_price is not None:
            fig.add_trace(
                go.Scatter(
                    x=[x_end, last_bar_ts], y=[match.target_price, match.target_price],
                    mode="lines", line=dict(color=color, width=1, dash="dash"),
                    showlegend=False, hoverinfo="skip",
                ),
                row=1, col=1,
            )

    fig.update_layout(
        title=f"{ticker} chart patterns ({timeframe.value})",
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    fig.update_xaxes(rangebreaks=_WEEKEND_RANGEBREAKS)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_yaxes(title_text="volume", row=2, col=1)
    return fig
