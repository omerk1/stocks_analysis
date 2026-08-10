"""Plotly overlay for detected fib sets -- pure consumer of FibSet/
FibSwing (plus the raw bars, for candlesticks), same separation as
sr_lines.plotting: no detection logic lives here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.fibonacci.models import FibLevelKind, FibSet, FibSetStatus

_RETRACEMENT_COLOR = "#1f77b4"
_EXTENSION_COLOR = "#d62728"
_SWING_COLOR = "#7f7f7f"

# Floored well above zero (unlike a bare weight-proportional value, which
# could fade a low-weight set toward fully invisible) -- even the weakest
# selected set (already top-max_sets by weight) should stay perceptible and
# hoverable on the chart, mirroring sr_lines.plotting's own marker-opacity
# floor for the same reason.
_MIN_OPACITY = 0.25


def _opacity_for_weight(weight: float) -> float:
    t = max(0.0, min(weight, 1.0))
    return _MIN_OPACITY + (1.0 - _MIN_OPACITY) * t


def _segment_end(fib_set: FibSet, last_bar_ts: pd.Timestamp) -> pd.Timestamp:
    if fib_set.status == FibSetStatus.INVALIDATED and fib_set.invalidated_date:
        return pd.Timestamp(fib_set.invalidated_date)
    return last_bar_ts


def render_fib_chart(bars: pd.DataFrame, fib_sets: list[FibSet]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=bars.index, open=bars["open"], high=bars["high"], low=bars["low"], close=bars["close"],
            name="price", showlegend=False,
        )
    )

    last_bar_ts = bars.index[-1] if not bars.empty else pd.Timestamp.now()

    for fib_set in fib_sets:
        swing = fib_set.swing
        opacity = _opacity_for_weight(fib_set.weight)
        start_ts = pd.Timestamp(swing.end_date)
        end_ts = max(_segment_end(fib_set, last_bar_ts), start_ts)

        for level in fib_set.levels:
            is_retracement = level.kind == FibLevelKind.RETRACEMENT
            fig.add_trace(
                go.Scatter(
                    x=[start_ts, end_ts], y=[level.price, level.price],
                    mode="lines",
                    line=dict(
                        color=_RETRACEMENT_COLOR if is_retracement else _EXTENSION_COLOR,
                        dash="solid" if is_retracement else "dash",
                        width=1.5,
                    ),
                    opacity=opacity,
                    name=f"{fib_set.id[:8]} {level.kind.value} {level.ratio}",
                    hovertemplate=f"{level.kind.value} {level.ratio}: {level.price:.2f}<extra></extra>",
                    showlegend=False,
                )
            )

        fig.add_trace(
            go.Scatter(
                x=[pd.Timestamp(swing.origin_date), pd.Timestamp(swing.end_date)],
                y=[swing.origin_price, swing.end_price],
                mode="lines+markers",
                line=dict(color=_SWING_COLOR, width=2, dash="dot"),
                marker=dict(size=6, color=_SWING_COLOR),
                opacity=opacity,
                name=f"{fib_set.id[:8]} swing",
                hovertemplate=(
                    f"{swing.direction.value} swing x{swing.scale_mult:g}<br>"
                    f"{swing.origin_date} @ {swing.origin_price:.2f} -&gt; "
                    f"{swing.end_date} @ {swing.end_price:.2f}<extra></extra>"
                ),
                showlegend=False,
            )
        )

        status_suffix = " [invalidated]" if fib_set.status == FibSetStatus.INVALIDATED else ""
        fig.add_annotation(
            x=pd.Timestamp(swing.end_date), y=swing.end_price,
            text=f"{swing.direction.value} x{swing.scale_mult:g}{status_suffix}",
            showarrow=True, arrowhead=1, opacity=opacity, font=dict(size=10),
        )

    fig.update_layout(xaxis_rangeslider_visible=False, template="plotly_white")
    return fig
