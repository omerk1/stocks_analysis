"""Plotly review chart -- a pure consumer of DetectionResult (plus the raw
bars, for candlesticks; DetectionResult deliberately doesn't carry price
data). No detection logic lives here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.sr_lines.models import DetectionResult, EventType, Line, LineState

# (symbol, color, size, outline_width) -- BREAK is deliberately the odd one
# out (solid black, bold, larger) rather than just a darker/thinner shade of
# BODY_FAKE's red: a real NVDA chart showed the two reading as near-identical
# marks at normal zoom, which made a genuinely never-reclaimed break next to
# a nearby line's density of reclaimed body-fakes easy to misread as several
# breaks on the wrong zone. BODY_FAKE is an open/hollow shape on purpose --
# it visually reads as "attempted, not solid," the opposite of BREAK.
_EVENT_MARKERS = {
    EventType.TOUCH: ("triangle-up", "#2ca02c", 9, 1),
    EventType.WICK_FAKE: ("triangle-down", "#ff7f0e", 9, 1),
    EventType.BODY_FAKE: ("circle-open", "#d62728", 9, 2),
    EventType.BREAK: ("x", "#000000", 13, 2),
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
    or the defining pivot if there were none yet). Always ends at the run's
    own reference date (the latest available bar -- which is `as_of` for a
    frozen/backtest run), regardless of state: for backtesting, a zone that
    was detected as of some date X should be shown in full as of X whether
    or not it later broke or flipped -- state is a label/color, not
    something that should shorten the box."""
    return pd.Timestamp(line.first_touch), last_bar_ts


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


def render_review_chart(
    bars: pd.DataFrame, result: DetectionResult, reference_date: pd.Timestamp | None = None
) -> go.Figure:
    """`bars` is what gets drawn as candlesticks -- it can extend past the
    detection's own cutoff (`reference_date`) so a backtest run can be
    visually checked against what actually happened afterward, even though
    the zones themselves were computed blind to that future. `reference_date`
    defaults to `bars`' last timestamp (i.e. a non-backtest, "show everything
    through today" call, where detection and display naturally end at the
    same place).
    """
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name=result.ticker, showlegend=False,
        )
    )

    last_bar_ts = pd.Timestamp(reference_date) if reference_date is not None else bars.index[-1]
    if last_bar_ts < bars.index[-1]:
        fig.add_vline(
            x=last_bar_ts, line_dash="dot", line_color="black",
            annotation_text=f"as_of {last_bar_ts.date()}", annotation_position="top left",
        )

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

        for event_type, (symbol, marker_color, size, outline_width) in _EVENT_MARKERS.items():
            matching = [e for e in line.events if e.type == event_type]
            if not matching:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[pd.Timestamp(e.end) for e in matching],
                    y=[line.center] * len(matching),
                    mode="markers",
                    marker=dict(
                        symbol=symbol, size=size, color=marker_color,
                        line=dict(width=outline_width, color="black"),
                    ),
                    name=event_type.value,
                    legendgroup=f"{line.id}-events",
                    showlegend=False,
                    hovertext=[f"{line.id} {event_type.value} {e.start}->{e.end}" for e in matching],
                    hoverinfo="text",
                )
            )

        # Line ID is in the text itself, not just the hover -- on a chart
        # where two zones' centers are only a few dollars apart (compressed
        # to a handful of pixels against the chart's full price range), a
        # bare "break"/"flip" label can visually read as belonging to
        # whichever nearby box it happens to land closest to.
        if line.broken_at is not None:
            fig.add_annotation(
                x=pd.Timestamp(line.broken_at), y=line.center, text=f"{line.id} break",
                showarrow=True, arrowhead=2, ax=0, ay=-30,
            )
        if line.flipped_at is not None:
            fig.add_annotation(
                x=pd.Timestamp(line.flipped_at), y=line.center, text=f"{line.id} flip",
                showarrow=True, arrowhead=2, ax=0, ay=30,
            )

    fig.update_layout(
        title=f"{result.ticker} S/R lines (as of {result.as_of})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    return fig
