"""Plotly review chart -- a pure consumer of DetectionResult (plus the raw
bars, for candlesticks; DetectionResult deliberately doesn't carry price
data). No detection logic lives here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.sr_lines.models import DetectionResult, EventType, Line, LineState

_EVENT_MARKERS = {
    EventType.TOUCH: ("triangle-up", "#2ca02c"),
    EventType.WICK_FAKE: ("triangle-down", "#ff7f0e"),
    EventType.BODY_FAKE: ("x", "#d62728"),
    EventType.BREAK: ("x-thin", "#8c1414"),
}


def _strength_colors(strength: float) -> tuple[str, str]:
    """Returns (fill_rgba, border_rgb) -- blue, saturating with strength:
    weak lines fade toward pale/transparent, strong lines toward a solid,
    saturated blue border with a more opaque fill."""
    t = max(0.0, min(strength, 1.0))
    r = int(200 - 120 * t)
    g = int(210 - 100 * t)
    b = 255
    fill = f"rgba({r},{g},{b},{0.15 + 0.45 * t:.3f})"
    border = f"rgb({r},{g},{b})"
    return fill, border


def _relevant_range(line: Line, last_bar_ts: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The time span the engine actually determined this zone was relevant
    for -- not the whole chart. Starts at `first_touch` (the earliest event,
    or the defining pivot if there were none yet). Ends at `broken_at` for a
    BROKEN line (it stopped mattering once it broke and was never reclaimed);
    otherwise extends to the last available bar, since ACTIVE/FLIPPED lines
    are still relevant now."""
    start = pd.Timestamp(line.first_touch)
    if line.state == LineState.BROKEN and line.broken_at is not None:
        end = pd.Timestamp(line.broken_at)
    else:
        end = last_bar_ts
    return start, end


def _hover_text(line: Line) -> str:
    s = line.scores
    return (
        f"{line.id} | {line.role.value} | {line.state.value}<br>"
        f"strength={line.strength:.3f} proximity={line.proximity:.3f}<br>"
        f"touch_quality={s.touch_quality:.2f} duration_density={s.duration_density:.2f} "
        f"resilience={s.resilience:.2f} role_reversal={s.role_reversal:.2f}<br>"
        f"touches={line.n_touches} wick_fakes={line.n_wick_fakes} "
        f"body_fakes={line.n_body_fakes} breaks={line.n_breaks}<br>"
        f"first_touch={line.first_touch} last_event={line.last_event}"
    )


def render_review_chart(bars: pd.DataFrame, result: DetectionResult) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=result.ticker, showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1]

    for line in result.lines:
        fill_color, border_color = _strength_colors(line.strength)
        dash = "solid" if line.state == LineState.ACTIVE else "dash"
        x0, x1 = _relevant_range(line, last_bar_ts)

        y_lo, y_hi = line.center - line.half_width, line.center + line.half_width
        fig.add_trace(
            go.Scatter(
                x=[x0, x1, x1, x0, x0], y=[y_lo, y_lo, y_hi, y_hi, y_lo],
                mode="lines", fill="toself", fillcolor=fill_color,
                line=dict(color=border_color, dash=dash, width=1 + 2 * line.strength),
                name=f"{line.id} [{line.role.value}] {line.strength:.2f}",
                legendgroup=line.id,
                hovertext=_hover_text(line), hoverinfo="text",
            )
        )

        for event_type, (symbol, marker_color) in _EVENT_MARKERS.items():
            matching = [e for e in line.events if e.type == event_type]
            if not matching:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[pd.Timestamp(e.end) for e in matching],
                    y=[line.center] * len(matching),
                    mode="markers",
                    marker=dict(symbol=symbol, size=9, color=marker_color, line=dict(width=1, color="black")),
                    name=event_type.value,
                    legendgroup=f"{line.id}-events",
                    showlegend=False,
                    hovertext=[f"{line.id} {event_type.value} {e.start}->{e.end}" for e in matching],
                    hoverinfo="text",
                )
            )

        if line.broken_at is not None:
            fig.add_annotation(
                x=pd.Timestamp(line.broken_at), y=line.center, text="break",
                showarrow=True, arrowhead=2, ax=0, ay=-30,
            )

    fig.update_layout(
        title=f"{result.ticker} S/R lines (as of {result.as_of})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    return fig
