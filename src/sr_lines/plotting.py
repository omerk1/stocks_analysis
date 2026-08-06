"""Plotly review chart -- a pure consumer of DetectionResult (plus the raw
bars, for candlesticks; DetectionResult deliberately doesn't carry price
data). No detection logic lives here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.sr_lines.models import DetectionResult, Event, EventType, Line, LineKind, LineState

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
    or the defining pivot if there were none yet), *not* `regime_start`.

    An earlier version of this used `regime_start` instead, reasoning that a
    box spanning a line's full history (including a real multi-year dormant
    gap) would reintroduce the "looks disconnected from real price" visual
    the `in_play_gate` fix was built to exclude. That conflated two
    different jobs: `in_play_gate`/`regime_start` decide whether a line is
    good enough to make top-N *at all* -- that's the actual clutter
    filter -- while the box's job, once a line clears that bar, is just to
    show what it *is*: its full known history, exactly like every other
    line on this chart. Truncating a genuinely good, top-N line's box to its
    current regime hides the very thing that makes a multi-year diagonal
    trendline recognizable (a real PAAS descending resistance from a 2020
    high, dormant for ~3 years, then decisively broken in 2024 -- the box
    needs to visibly span from 2020, not just the last few months of the
    breakout, or the chart doesn't show the pattern that makes the line
    meaningful in the first place). `regime_start` is still used for
    scoring and shown in hover text -- only the render was wrong to key off
    it. Always ends at the run's own reference date (the latest available
    bar -- which is `as_of` for a frozen/backtest run), regardless of state:
    for backtesting, a zone that was detected as of some date X should be
    shown in full as of X whether or not it later broke or flipped -- state
    is a label/color, not something that should shorten the box."""
    return pd.Timestamp(line.first_touch), last_bar_ts


def _y_at(line: Line, bars: pd.DataFrame, ts) -> float:
    """The line's own price at a given timestamp -- flat `center` for
    horizontal, `price_at(bar_index)` for diagonal (its price genuinely
    moves with the trend, so a marker/annotation drawn at a fixed height
    would drift off the sloped band over time)."""
    if line.kind == LineKind.HORIZONTAL:
        return line.center
    return line.price_at(bars.index.get_loc(pd.Timestamp(ts)))


def _marker_ts(event: Event) -> str:
    """Where an event's marker should actually be drawn -- `event.start`
    for BREAK, `event.end` for everything else.

    A BREAK's `.end` is deliberately the bar where the `fakeout_reclaim_bars`
    window elapsed *without* a reclaim (confirming it's a real break, not a
    fakeout) -- correct for classification, but that bar can be several
    trading days after the actual crossing, by which point a real,
    continuing breakdown has often moved price well away from the level.
    Plotted there, the marker (bold black X, the most visually prominent
    marker on the chart) reads as floating in empty space, disconnected
    from the candle where the break actually happened -- confirmed on a
    real AAPL window where BREAK markers averaged 2.6% (up to 5.5%)
    deviation from real price, roughly double every other event type
    (all under ~1.7% on average, well under 3%). `.start` is the bar
    where price first closed beyond the zone -- the actual break -- and is
    already what `flip_status.broken_at` anchors the break/flip
    annotations to, so this makes the scatter marker agree with them
    instead of using a third, inconsistent position.

    Every other event type is already same-bar (TOUCH/WICK_FAKE) or
    resolves quickly enough in practice that `.end` reads fine (BODY_FAKE
    averaged ~1.1% deviation in the same real check) -- left alone rather
    than changed without a demonstrated problem.
    """
    return event.start if event.type == EventType.BREAK else event.end


def _hover_text(line: Line) -> str:
    s = line.scores
    return (
        f"{line.id} | {line.role.value} | {line.state.value}<br>"
        f"strength={line.strength:.3f} proximity={line.proximity:.3f}<br>"
        f"touch_quality={s.touch_quality:.2f} duration_density={s.duration_density:.2f} "
        f"resilience={s.resilience:.2f} role_reversal={s.role_reversal:.2f}<br>"
        f"relevance_gate={s.relevance_gate:.2f} in_play_gate={s.in_play_gate:.2f}"
        f"{f' diagonal_penalty={s.diagonal_penalty:.2f}' if line.kind == LineKind.DIAGONAL else ''}<br>"
        f"touches={line.n_touches} wick_fakes={line.n_wick_fakes} "
        f"body_fakes={line.n_body_fakes} breaks={line.n_breaks}<br>"
        f"first_touch={line.first_touch} regime_start={line.regime_start} last_event={line.last_event}"
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

        if line.kind == LineKind.DIAGONAL:
            # Sloped 4-point band, not a flat rectangle -- zone_at() at each
            # end of the box's time range, since a diagonal band's width in
            # real-price terms changes along with its own price level.
            lo0, hi0 = line.zone_at(bars.index.get_loc(x0))
            lo1, hi1 = line.zone_at(bars.index.get_loc(x1))
            poly_y = [lo0, lo1, hi1, hi0, lo0]
        else:
            y_lo, y_hi = line.center - line.half_width, line.center + line.half_width
            poly_y = [y_lo, y_lo, y_hi, y_hi, y_lo]

        fig.add_trace(
            go.Scatter(
                x=[x0, x1, x1, x0, x0], y=poly_y,
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
                    x=[pd.Timestamp(_marker_ts(e)) for e in matching],
                    y=[_y_at(line, bars, _marker_ts(e)) for e in matching],
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
                x=pd.Timestamp(line.broken_at), y=_y_at(line, bars, line.broken_at), text=f"{line.id} break",
                showarrow=True, arrowhead=2, ax=0, ay=-30,
            )
        if line.flipped_at is not None:
            fig.add_annotation(
                x=pd.Timestamp(line.flipped_at), y=_y_at(line, bars, line.flipped_at), text=f"{line.id} flip",
                showarrow=True, arrowhead=2, ax=0, ay=30,
            )

    fig.update_layout(
        title=f"{result.ticker} S/R lines (as of {result.as_of})",
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        legend=dict(groupclick="togglegroup"),
    )
    return fig
